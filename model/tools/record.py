"""端侧数据采集：读取设备 CSV 原始流并按键实时打标。

设备侧（kStreamRaw = true）每帧输出一行:
    t_us,ax,ay,az,gx,gy,gz

按键（Windows 终端，无需回车）:
    1 = walk   2 = run   3 = fall   0 = 无标注（继续采集但丢弃过渡段）
    q = 结束并保存

标注切换瞬间前后 1s 的过渡数据被丢弃（"none" 段不写入文件）。
保存至 model/data/self/session_YYYYmmdd_HHMMSS.csv，
列为: label,t_us,ax,ay,az,gx,gy,gz
"""

from __future__ import annotations

import collections
import csv
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import serial  # type: ignore
except ImportError:
    sys.exit("缺少 pyserial: uv add pyserial 或 uv run --with pyserial record.py")

try:
    import msvcrt

    HAS_MSVCRT = True
except ImportError:
    HAS_MSVCRT = False

PORT_DEFAULT = "COM5"
BAUD = 921600
TRANSITION_SEC = 1.0  # 切换前后丢弃时长
LABELS = {"1": "walk", "2": "run", "3": "fall", "0": "none"}
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "self"


def read_key() -> str | None:
    if HAS_MSVCRT and msvcrt.kbhit():
        return msvcrt.getwch()
    return None


def flush_settled(
    writer,  # noqa: ANN001
    pending: collections.deque,
    last_switch: float,
    commit_all: bool,
) -> int:
    """提交已越过过渡期的行，返回提交数。

    行 (arrival, label, values) 可提交当且仅当：
      - commit_all（会话结束，多余缓冲也落盘），或
      - arrival <= last_switch - 1s（切换前 1s 以外的旧行），或
      - arrival >= last_switch + 1s 且已再缓冲 1s 且期间无新切换。
    label == "none" 的行被丢弃。
    """
    n = 0
    now = time.perf_counter()
    while pending:
        arrival, lab, values = pending[0]
        settled = commit_all or (
            arrival <= last_switch - TRANSITION_SEC
            or (arrival >= last_switch + TRANSITION_SEC and now - arrival >= TRANSITION_SEC)
        )
        if not settled:
            break
        pending.popleft()
        if lab != "none":
            writer.writerow([lab, *values])
            n += 1
    return n


def main() -> None:
    port = sys.argv[1] if len(sys.argv) > 1 else PORT_DEFAULT
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    pending: collections.deque[tuple[float, str, tuple[int, ...]]] = collections.deque()
    label = "none"
    last_switch = float("-inf")
    committed = 0

    out_path = DATA_DIR / f"session_{datetime.now():%Y%m%d_%H%M%S}.csv"
    with serial.Serial(port, BAUD, timeout=0.1) as ser, \
            open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["label", "t_us", "ax", "ay", "az", "gx", "gy", "gz"])
        print(f"记录到 {out_path}（{port} @ {BAUD}）")
        print("按键: 1=walk 2=run 3=fall 0=none q=保存退出")

        while True:
            key = read_key()
            if key == "q":
                break
            if key in LABELS and LABELS[key] != label:
                label = LABELS[key]
                last_switch = time.perf_counter()
                print(f"标注 -> {label}")

            raw = ser.readline().decode("ascii", errors="ignore").strip()
            if not raw:
                continue  # 读超时
            parts = raw.split(",")
            if len(parts) != 7:
                continue  # 非数据行（init 日志/ACT 行）
            try:
                values = tuple(int(p) for p in parts)
            except ValueError:
                continue
            pending.append((time.perf_counter(), label, values))
            committed += flush_settled(writer, pending, last_switch, commit_all=False)

        # 会话结束：剩余未越过过渡期的行丢弃（过渡段不入库）
        committed += flush_settled(writer, pending, last_switch, commit_all=False)

    print(f"已保存 {committed} 行 -> {out_path}")

if __name__ == "__main__":
    main()
