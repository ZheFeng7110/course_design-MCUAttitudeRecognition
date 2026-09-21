"""统一预处理：公开数据集 + 自采集 → 100Hz、6 通道、200×6 切窗、训练/验证/测试集。

输入:
    data/external/mobiact/   MobiAct v2（试验目录内 accelerometer/gyroscope 文本文件）
    data/external/sisfall/   SisFall（S{subj}{trial}_{act}_{n}.txt，200Hz，9 列）
    data/self/session_*.csv  自采集（label,t_us,ax,ay,az,gx,gy,gz，100Hz）

标签映射（其余 ADL 丢弃）:
    MobiAct:  WAL→walk  JOG/RUN→run  FOL/FKL/BSC/SDL/FSY→fall
    SisFall:  WA/WU/WN→walk  WJ→run  S*（SA..SF 跌倒试验）→fall
    自采集:   walk/run/fall 原样

输出（model/data/processed/）:
    train.npy / val.npy / test.npy   形状 (N, 200, 6) float32 + labels.npy
    norm.json                        每通道均值/标准差（训练集统计，供 int8 量化）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "data"
EXTERNAL = DATA / "external"
SELF = DATA / "self"
OUT = DATA / "processed"

SR = 100
WIN = 200
STRIDE = 50
CHANNELS = ["ax", "ay", "az", "gx", "gy", "gz"]
CLASS_MAP = {"walk": 0, "run": 1, "fall": 2}

# 传感器量程与 LSB 系数：必须与 OfflineDevice/App/modules/attitude.config.cppm 的
# kAccelLsbPerG / kGyroLsbPerDps（全项目参数源）一致，gen_c_array.py 生成端会校验。
# 训练/导出/端侧统一用物理量（g / dps）做归一化，端侧负责 LSB→物理量换算。
ACC_LSB_PER_G = 1365.0      # ±24g：32768/24
GYR_LSB_PER_DPS = 16.384    # ±2000dps：32768/2000

MOBIACT_LABEL = {"WAL": "walk", "JOG": "run", "RUN": "run",
                 "FOL": "fall", "FKL": "fall", "BSC": "fall", "SDL": "fall", "FSY": "fall"}


def resample(ts: np.ndarray, values: np.ndarray, sr: int) -> np.ndarray:
    """线性插值重采样到固定采样率（列=通道）。"""
    if len(ts) < 2:
        return np.empty((0, values.shape[1]), dtype=np.float32)
    t0, t1 = ts[0], ts[-1]
    if t1 <= t0:
        return np.empty((0, values.shape[1]), dtype=np.float32)
    n = int((t1 - t0) * sr) + 1
    grid = np.linspace(t0, t0 + (n - 1) / sr, n)
    out = np.empty((n, values.shape[1]), dtype=np.float32)
    for c in range(values.shape[1]):
        out[:, c] = np.interp(grid, ts, values[:, c])
    return out


def windows(series: np.ndarray, label: int) -> tuple[np.ndarray, np.ndarray]:
    """切窗 (N, WIN, 6)，步长 STRIDE。"""
    if len(series) < WIN:
        return np.empty((0, WIN, 6), np.float32), np.empty((0,), np.int64)
    idx = range(0, len(series) - WIN + 1, STRIDE)
    xs = np.stack([series[i:i + WIN] for i in idx]).astype(np.float32)
    ys = np.full(len(idx), label, np.int64)
    return xs, ys


def load_mobiact(root: Path) -> list[tuple[np.ndarray, int]]:
    """MobiAct v2: <root>/<活动代码>_<试验>/accelerometer.txt + gyroscope.txt。

    传感器文件为表头 + 数据行，列含 x y z（秒级 timestamp 或 sampleNo）。
    不同版本列序有差异，这里按表头名定位。
    """
    out = []
    if not root.exists():
        print(f"[警告] MobiAct 不存在: {root}")
        return out
    for trial in sorted(p for p in root.iterdir() if p.is_dir()):
        act_code = trial.name.split("_")[0].upper()
        label = MOBIACT_LABEL.get(act_code)
        if label is None:
            continue
        acc_f = next((f for f in trial.rglob("*ccelerometer*.txt")), None)
        gyr_f = next((f for f in trial.rglob("*yroscope*.txt")), None)
        if not (acc_f and gyr_f):
            continue
        acc = pd.read_csv(acc_f, comment="#")
        gyr = pd.read_csv(gyr_f, comment="#")
        acc.columns = [c.strip().lower() for c in acc.columns]
        gyr.columns = [c.strip().lower() for c in gyr.columns]
        tcol = next((c for c in ("time_s", "timestamp", "seconds", "samplenumber", "sampleno") if c in acc.columns), None)
        ts = acc[tcol].to_numpy(float) if tcol else np.arange(len(acc), dtype=float) / 200.0
        if tcol and "seconds" not in tcol and ts.max() > 1e9:  # epoch 毫秒/纳秒归一到秒
            ts = (ts - ts[0]) / 1000.0
        a = acc[["x", "y", "z"]].to_numpy(float)
        t_g = np.arange(len(gyr), dtype=float) / 200.0 if tcol is None else gyr[tcol].to_numpy(float)
        if t_g.max() > 1e9:
            t_g = (t_g - t_g[0]) / 1000.0
        g = gyr[["x", "y", "z"]].to_numpy(float)
        a_rs = resample(ts, a, SR)
        g_rs = resample(t_g, g, SR)
        n = min(len(a_rs), len(g_rs))
        if n < WIN:
            continue
        series = np.concatenate([a_rs[:n], g_rs[:n]], axis=1)
        out.append((series, CLASS_MAP[label]))
    return out


def load_sisfall(root: Path) -> list[tuple[np.ndarray, int]]:
    """SisFall: 单文件 200Hz，9 列（ADXL345×2 + ITG3200 取第一组/末三列）。"""
    out = []
    if not root.exists():
        print(f"[警告] SisFall 不存在: {root}")
        return out
    for f in sorted(root.glob("S*.txt")):
        code = f.stem.split("_")[1] if "_" in f.stem else ""
        if code.startswith("S"):
            label = "fall"          # SA..SF 跌倒试验
        elif code == "WJ":
            label = "run"           # jogging
        elif code in ("WA", "WU", "WN"):
            label = "walk"          # walking / fast walking / slow walking
        else:
            continue
        raw = np.loadtxt(f)
        if raw.ndim != 2 or raw.shape[1] < 9:
            continue
        acc = raw[:, 0:3]           # ADXL345 (13-bit, 4mg/digit → g)
        gyr = raw[:, 6:9]           # ITG3200 (14.375 LSB/dps → dps)
        acc_g = acc * 0.004
        gyr_dps = gyr / 14.375
        ts = np.arange(len(raw), dtype=float) / 200.0
        a_rs = resample(ts, acc_g, SR)
        g_rs = resample(ts, gyr_dps, SR)
        n = min(len(a_rs), len(g_rs))
        if n < WIN:
            continue
        series = np.concatenate([a_rs[:n], g_rs[:n]], axis=1)
        out.append((series, CLASS_MAP[label]))
    return out


def load_self(root: Path) -> list[tuple[np.ndarray, int]]:
    """自采集 CSV：已是 100Hz、±24g LSB / ±2000dps LSB，直接转 g/dps 后切窗。

    一个会话可含多段不同活动（label 逐行标注），按连续同标签区段分别切分，
    不能整段会话取首行标签。
    """
    out = []
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
            out.append((series, CLASS_MAP[seg.iloc[0]["label"]]))
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    trials = []
    trials += load_mobiact(EXTERNAL / "mobiact")
    trials += load_sisfall(EXTERNAL / "sisfall")
    trials += load_self(SELF)
    if not trials:
        sys.exit("没有可用数据：先运行 download_data.py / 自采集（见 Assumption #5）")

    xs, ys = [], []
    for series, label in trials:
        w, l = windows(series, label)
        if len(w):
            xs.append(w)
            ys.append(l)
    X = np.concatenate(xs)
    Y = np.concatenate(ys)
    print(f"窗口总数 {len(X)}；类别分布 walk/run/fall = "
          f"{np.sum(Y == 0)}/{np.sum(Y == 1)}/{np.sum(Y == 2)}")

    # 按试验级划分近似：这里按窗口随机划分（小模型可接受），固定种子
    rng = np.random.default_rng(42)
    perm = rng.permutation(len(X))
    X, Y = X[perm], Y[perm]
    n = len(X)
    n_val, n_test = int(n * 0.15), int(n * 0.15)
    splits = {
        "test": (X[:n_test], Y[:n_test]),
        "val": (X[n_test:n_test + n_val], Y[n_test:n_test + n_val]),
        "train": (X[n_test + n_val:], Y[n_test + n_val:]),
    }
    for name, (x, y) in splits.items():
        np.save(OUT / f"{name}.npy", x)
        np.save(OUT / f"{name}_labels.npy", y)

    # 归一化参数（训练集统计；int8 量化输入用，不单独做归一化层）
    mean = splits["train"][0].reshape(-1, 6).mean(axis=0)
    std = splits["train"][0].reshape(-1, 6).std(axis=0) + 1e-8
    (OUT / "norm.json").write_text(json.dumps({
        "mean": mean.tolist(), "std": std.tolist(),
        "note": "x_norm = (x_lsb - mean) / std；端侧量化: int8 = round(x_norm / input_scale + zero_point)",
    }, indent=2), encoding="utf-8")
    print(f"输出 -> {OUT}")


if __name__ == "__main__":
    main()
