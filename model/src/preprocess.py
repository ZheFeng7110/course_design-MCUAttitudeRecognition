"""统一预处理：公开数据集 + 自采集 → 100Hz、6 通道、200×6 切窗、训练/验证/测试集。

输入（公开数据集已随仓库提交，来源见 data/external/data_link.md）:
    data/external/MobiAct_Dataset_v2.0-MobiFall_Dataset_v2.0/
        sub<N>/{ADL,FALLS}/<CODE>/<CODE>_{acc,gyro,ori}_<subj>_<trial>.txt
        头部为 `#` 注释 + `@DATA` 标记；时间戳单位为 ns（实测陀螺中位 200.1Hz，与文档一致），
        加速度约 94Hz、陀螺 200Hz，逐试验插值对齐到公共时间轴
    data/external/SisFall/SisFall_dataset/<受试者>/<CODE>_<受试者>_R<NN>.txt
        200Hz，每行 9 个整数（ADXL345 xyz、ITG3200 xyz、MMA8451Q xyz），行尾带 `;`
    data/self/session_*.csv
        自采集（label,t_us,ax,ay,az,gx,gy,gz，100Hz，设备原始 LSB）

标签映射（通道序 ax,ay,az,gx,gy,gz；其余 ADL 一律丢弃，不引入第 4 类）:
    MobiAct  WAL→walk  JOG→run  FOL/FKL/BSC/SDL→fall      （STD/JUM/STU/STN/SCH/CSI/CSO 丢弃）
    SisFall  D01/D02→walk  D03/D04→run  F01..F15→fall      （D05..D19 丢弃）
    自采集   walk/run/fall 原样

量纲统一为 g / dps：
    MobiAct  DataDescribe.txt：acc m/s²、gyro rad/s → ÷9.80665、×180/π
    SisFall  Readme.txt 的 (2·Range)/2^Resolution：ADXL345 13bit ±16g → 32/8192 g/LSB，
             ITG3200 16bit ±2000dps → 4000/65536 dps/LSB
    自采集   设备 LSB 系数（ACC_LSB_PER_G / GYR_LSB_PER_DPS）

划分：按受试者/会话（group）分组划分；窗口步长 50 意味着同一试验内相邻窗口重叠 75%，
窗口级随机划分会把它们拆到训练与测试两侧，指标虚高。见 split_by_group()。

输出（model/data/processed/）:
    train.npy / val.npy / test.npy   形状 (N, 200, 6) float32
    <split>_labels.npy               形状 (N,) int64
    norm.json                        每通道均值/标准差（训练集统计，供 int8 量化）
"""

from __future__ import annotations

import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "data"
EXTERNAL = DATA / "external"
SELF = DATA / "self"
OUT = DATA / "processed"

MOBIACT_ROOT = EXTERNAL / "MobiAct_Dataset_v2.0-MobiFall_Dataset_v2.0"
SISFALL_ROOT = EXTERNAL / "SisFall" / "SisFall_dataset"

SR = 100
WIN = 200
STRIDE = 50
CLASS_MAP = {"walk": 0, "run": 1, "fall": 2}
N_CLASSES = len(CLASS_MAP)

# 传感器量程与 LSB 系数：必须与 OfflineDevice/App/modules/attitude.config.cppm 的
# kAccelLsbPerG / kGyroLsbPerDps（全项目参数源）一致，gen_c_array.py 生成端会校验。
# 训练/导出/端侧统一用物理量（g / dps）做归一化，端侧负责 LSB→物理量换算。
ACC_LSB_PER_G = 1365.0      # ±24g：32768/24
GYR_LSB_PER_DPS = 16.384    # ±2000dps：32768/2000

# 公开集量纲换算（各自数据集文档给出的口径）
MPS2_PER_G = 9.80665
DPS_PER_RADPS = 180.0 / math.pi
SISFALL_ACC_G_PER_BIT = 32.0 / 2 ** 13       # ADXL345：13bit、±16g
SISFALL_GYR_DPS_PER_BIT = 4000.0 / 2 ** 16   # ITG3200：16bit、±2000dps
SISFALL_RATE = 200.0                         # Readme.txt：等间隔 200Hz

MOBIACT_LABEL = {"WAL": "walk", "JOG": "run",
                 "FOL": "fall", "FKL": "fall", "BSC": "fall", "SDL": "fall"}
MOBIACT_FILE = re.compile(
    r"^(?P<code>[A-Z]+)_(?P<sensor>acc|gyro|ori)_(?P<subj>\d+)_(?P<trial>\d+)\.txt$")
SISFALL_LABEL = {"D01": "walk", "D02": "walk", "D03": "run", "D04": "run"}
SISFALL_LABEL.update({f"F{i:02d}": "fall" for i in range(1, 16)})
SISFALL_FILE = re.compile(r"^(?P<code>[DF]\d{2})_(?P<subj>S[AE]\d{2})_R\d{2}\.txt$")


@dataclass(frozen=True)
class Trial:
    """单次试验：series (N,6) 单位 g/dps；group 为划分离散单元（受试者或采集会话）。"""

    series: np.ndarray
    label: int
    group: str


def resample(ts: np.ndarray, values: np.ndarray, sr: int,
             t_start: float | None = None, t_end: float | None = None) -> np.ndarray:
    """线性插值重采样到等间隔时间轴（列=通道）。

    时间轴自 `t_start` 起、步长 1/sr，默认覆盖 [ts[0], ts[-1]]。
    """
    if len(ts) < 2:
        return np.empty((0, values.shape[1]), dtype=np.float32)
    order = np.argsort(ts, kind="stable")       # 时间戳理论单调，防御乱序
    ts = ts[order]
    values = values[order]
    t0 = ts[0] if t_start is None else t_start
    t1 = ts[-1] if t_end is None else t_end
    if t1 <= t0:
        return np.empty((0, values.shape[1]), dtype=np.float32)
    n = int((t1 - t0) * sr) + 1
    grid = t0 + np.arange(n, dtype=np.float64) / sr
    out = np.empty((n, values.shape[1]), dtype=np.float32)
    for c in range(values.shape[1]):
        out[:, c] = np.interp(grid, ts, values[:, c])
    return out


def align_imu(ts_acc: np.ndarray, acc: np.ndarray,
              ts_gyr: np.ndarray, gyr: np.ndarray, sr: int = SR) -> np.ndarray:
    """两路传感器重采样到公共时间轴（取时间交集），返回 (N, 6) 的 acc|gyr 拼接。"""
    t0 = max(ts_acc[0], ts_gyr[0])
    t1 = min(ts_acc[-1], ts_gyr[-1])
    a = resample(ts_acc, acc, sr, t0, t1)
    g = resample(ts_gyr, gyr, sr, t0, t1)
    n = min(len(a), len(g))
    return np.concatenate([a[:n], g[:n]], axis=1)


def windows(series: np.ndarray, label: int) -> tuple[np.ndarray, np.ndarray]:
    """切窗 (N, WIN, 6)，步长 STRIDE（不跨试验拼接）。"""
    if len(series) < WIN:
        return np.empty((0, WIN, 6), np.float32), np.empty((0,), np.int64)
    idx = range(0, len(series) - WIN + 1, STRIDE)
    xs = np.stack([series[i:i + WIN] for i in idx]).astype(np.float32)
    ys = np.full(len(idx), label, np.int64)
    return xs, ys


def read_mobiact(path: Path) -> np.ndarray:
    """MobiAct 文本：`#` 注释头 + `@DATA` 标记 + `timestamp(ns),x,y,z` 行。"""
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line[0] in "#@":
            continue
        rows.append([float(v) for v in line.split(",")])
    return np.asarray(rows, dtype=np.float64)


def read_sisfall(path: Path) -> np.ndarray:
    """SisFall 文本：每行 9 个逗号分隔整数、行尾带 `;`。

    np.loadtxt 会把行尾 `;` 带进最后一个字段（且列数报错），这里统一去掉分隔符再解析。
    """
    flat = path.read_text(encoding="utf-8", errors="replace").replace(";", " ").replace(",", " ").split()
    values = np.asarray(flat, dtype=np.float64)
    if values.size % 9:
        raise ValueError(f"{path.name}: 数值个数 {values.size} 不是 9 的倍数")
    return values.reshape(-1, 9)


def load_mobiact(root: Path = MOBIACT_ROOT) -> list[Trial]:
    """MobiAct v2 / MobiFall v2：sub<N>/{ADL,FALLS}/<CODE>/<CODE>_<sensor>_<subj>_<trial>.txt。

    同一试验的 acc 与 gyro 起止时间、采样率都不同，按时间交集对齐；
    单位按 DataDescribe.txt 换算（acc m/s² → g，gyro rad/s → dps）。
    """
    out: list[Trial] = []
    if not root.exists():
        print(f"[警告] MobiAct 不存在: {root}")
        return out
    trials: dict[tuple[str, str, str], dict[str, Path]] = {}
    for f in root.rglob("*.txt"):
        m = MOBIACT_FILE.match(f.name)
        if m is not None:                       # DataDescribe.txt / README 等跳过
            trials.setdefault((m["code"], m["subj"], m["trial"]), {})[m["sensor"]] = f
    unmapped = broken = 0
    for (code, subj, _trial), sensors in trials.items():
        name = MOBIACT_LABEL.get(code)
        if name is None:                        # STD/JUM/STU/STN/SCH/CSI/CSO：非三类目标
            unmapped += 1
            continue
        if "acc" not in sensors or "gyro" not in sensors:
            broken += 1
            continue
        a = read_mobiact(sensors["acc"])
        g = read_mobiact(sensors["gyro"])
        if len(a) < 2 or len(g) < 2:
            broken += 1
            continue
        series = align_imu(a[:, 0] * 1e-9, a[:, 1:] / MPS2_PER_G,
                           g[:, 0] * 1e-9, g[:, 1:] * DPS_PER_RADPS)
        if len(series) < WIN:
            broken += 1
            continue
        out.append(Trial(series, CLASS_MAP[name], f"mobiact/sub{subj}"))
    print(f"MobiAct: {len(out)} 个试验入集；跳过 {unmapped} 个非三类试验、{broken} 个数据不完整试验")
    return out


def load_sisfall(root: Path = SISFALL_ROOT) -> list[Trial]:
    """SisFall：<root>/<受试者>/<CODE>_<受试者>_R<NN>.txt，200Hz。

    取 ADXL345（前 3 列，±16g 与设备量程最接近）与 ITG3200（4~6 列）；
    末 3 列是 MMA8451Q（±8g），通道重复度高，不用。
    """
    out: list[Trial] = []
    if not root.exists():
        print(f"[警告] SisFall 不存在: {root}")
        return out
    unmapped = 0
    for f in sorted(root.rglob("*.txt")):
        m = SISFALL_FILE.match(f.name)
        if m is None:                           # Readme.txt / desktop.ini 等
            continue
        name = SISFALL_LABEL.get(m["code"])
        if name is None:                        # D05..D19：上下楼/坐立/弯腰/绊一下等
            unmapped += 1
            continue
        raw = read_sisfall(f)
        ts = np.arange(len(raw), dtype=np.float64) / SISFALL_RATE
        series = align_imu(ts, raw[:, 0:3] * SISFALL_ACC_G_PER_BIT,
                           ts, raw[:, 3:6] * SISFALL_GYR_DPS_PER_BIT)
        if len(series) < WIN:
            continue
        out.append(Trial(series, CLASS_MAP[name], f"sisfall/{m['subj']}"))
    print(f"SisFall: {len(out)} 个文件入集；跳过 {unmapped} 个非三类 ADL")
    return out


def load_self(root: Path = SELF) -> list[Trial]:
    """自采集 CSV：已是 100Hz、±24g LSB / ±2000dps LSB，直接转 g/dps 后切窗。

    一个会话可含多段不同活动（label 逐行标注），按连续同标签区段分别切分，
    不能整段会话取首行标签。
    """
    out: list[Trial] = []
    for f in sorted(root.glob("session_*.csv")):
        if f.stat().st_size == 0:   # 录制刚创建/中断留下的空文件
            continue
        df = pd.read_csv(f)
        df = df[df["label"].isin(CLASS_MAP)]
        if df.empty:
            continue
        for _, seg in df.groupby((df["label"] != df["label"].shift()).cumsum(), sort=False):
            acc = seg[["ax", "ay", "az"]].to_numpy(float) / ACC_LSB_PER_G
            gyr = seg[["gx", "gy", "gz"]].to_numpy(float) / GYR_LSB_PER_DPS
            series = np.concatenate([acc, gyr], axis=1).astype(np.float32)
            out.append(Trial(series, CLASS_MAP[seg.iloc[0]["label"]], f"self/{f.stem}"))
    if out:
        print(f"自采集: {len(out)} 个连续区段入集")
    return out


def split_by_group(x: np.ndarray, y: np.ndarray, groups: np.ndarray, seed: int = 42,
                   ratios: tuple[float, float, float] = (0.7, 0.15, 0.15)
                   ) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """按 group 划分 train/val/test，组规模按 ratios 贪心分配（大组优先）。

    组内三类数据同时存在（受试者既有 ADL 也有跌倒试验），所以按窗口总数分配后
    各类别占比也随之接近 ratios；MobiAct 中只有跌倒试验的受试者会在三个划分里
    等比例分摊。
    """
    names = ("train", "val", "test")
    uniq = np.unique(groups)
    sizes = {g: int((groups == g).sum()) for g in uniq}
    total = sum(sizes.values())
    need = {n: r * total for n, r in zip(names, ratios)}
    cur = {n: 0.0 for n in names}
    by_split: dict[str, list[str]] = {n: [] for n in names}

    rng = np.random.default_rng(seed)
    order = rng.permutation(uniq)                       # 同规模组的归属随机化
    for g in sorted(order, key=lambda g: -sizes[g]):
        pick = max(names, key=lambda n: need[n] - cur[n])
        by_split[pick].append(str(g))
        cur[pick] += sizes[g]
    for n in names:
        print(f"  {n}: {len(by_split[n])} 组 / {int(cur[n])} 窗口（目标 {need[n]:.0f}）")

    out = {}
    for n in names:
        mask = np.isin(groups, by_split[n])
        out[n] = (x[mask], y[mask])
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    trials = load_mobiact() + load_sisfall() + load_self()
    if not trials:
        sys.exit(f"没有可用数据：检查 {EXTERNAL}（来源见 data_link.md）与 {SELF}")

    xs, ys, gs = [], [], []
    for t in trials:
        w, l = windows(t.series, t.label)
        if len(w):
            xs.append(w)
            ys.append(l)
            gs.append(np.full(len(l), t.group))
    X = np.concatenate(xs)
    Y = np.concatenate(ys)
    G = np.concatenate(gs)
    print(f"窗口总数 {len(X)}；类别分布 walk/run/fall = {np.bincount(Y, minlength=N_CLASSES).tolist()}；"
          f"分组 {len(np.unique(G))} 个")

    splits = split_by_group(X, Y, G)
    train_x = splits["train"][0]
    for name in ("train", "val", "test"):
        x, y = splits[name]
        np.save(OUT / f"{name}.npy", x)
        np.save(OUT / f"{name}_labels.npy", y)
        print(f"{name}: {len(x)} 窗口 walk/run/fall = {np.bincount(y, minlength=N_CLASSES).tolist()}")

    # 归一化参数（训练集统计；int8 量化输入用，不单独做归一化层）
    mean = train_x.reshape(-1, 6).mean(axis=0)
    std = train_x.reshape(-1, 6).std(axis=0) + 1e-8
    (OUT / "norm.json").write_text(json.dumps({
        "mean": mean.tolist(), "std": std.tolist(),
        "note": "统计量为 g/dps 口径：端侧先 LSB→物理量，再 x_norm = (x - mean) / std，"
                "量化 int8 = round(x_norm / input_scale + zero_point)",
    }, indent=2), encoding="utf-8")
    print(f"输出 -> {OUT}")


if __name__ == "__main__":
    main()
