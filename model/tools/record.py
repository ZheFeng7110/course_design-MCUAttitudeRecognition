"""端侧数据采集：读取设备 CSV 原始流并按键实时打标。

设备侧（kStreamRaw = true）每帧输出一行:
    t_us,ax,ay,az,gx,gy,gz

按键（无需回车；跨平台实现见 console_input.py）:
    1 = walk   2 = run   3 = fall   0 = 无标注（继续采集但丢弃过渡段）
    q = 结束并保存（Ctrl-C 同样保存后退出）

标注切换瞬间前后 1s 的过渡数据被丢弃（"none" 段不写入文件）。
保存至 model/data/self/session_YYYYmmdd_HHMMSS.csv，
列为: label,t_us,ax,ay,az,gx,gy,gz

用法:
    uv run tools/record.py [串口]
    串口缺省：Windows COM5；Linux/macOS /dev/ttyUSB0（实际多为 /dev/ttyUSB*、
    /dev/ttyACM*、macOS /dev/tty.usbserial-*，用 `ls /dev/tty*` 确认）
    Linux 串口权限：sudo usermod -aG dialout "$USER" 后重新登录
"""

from __future__ import annotations

import collections
import csv
import sys
import time
from datetime import datetime
from pathlib import Path

from console_input import PORT_DEFAULT, key_input, keys_available, read_key

try:
    import serial  # type: ignore
except ImportError:
    sys.exit("缺少 pyserial: uv add pyserial 或 uv run --with pyserial record.py")

BAUD = 921600
TRANSITION_SEC = 1.0  # 切换前后丢弃时长
LABELS = {"1": "walk", "2": "run", "3": "fall", "0": "none"}
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "self"


def flush_settled(
    writer,  # noqa: ANN001
    pending: collections.deque,
    last_switch: float,
    drain: bool,
) -> int:
    """提交可判定的行，返回提交数。

    行 (arrival, label, values) 在 now - arrival >= 1s 后即可判定：任何会影响它的
    标注切换（落在 arrival ±1s 内）此刻都已发生。判定时丢弃落在某次切换 ±1s 内的
    行（过渡段）与 label == "none" 的行。
    drain=True（会话结束、不会再有新切换）时不看时间，立即判定全部剩余行。
    """
    n = 0
    now = time.perf_counter()
    while pending:
        arrival, lab, values = pending[0]
        if not drain and now - arrival < TRANSITION_SEC:
            break
        pending.popleft()
        if lab != "none" and abs(arrival - last_switch) >= TRANSITION_SEC:
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
    with key_input(), serial.Serial(port, BAUD, timeout=0.1) as ser, \
            open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["label", "t_us", "ax", "ay", "az", "gx", "gy", "gz"])
        print(f"记录到 {out_path}（{port} @ {BAUD}）")
        if not keys_available():
            print("[提示] 当前环境无法读按键（stdin 非 TTY），全部记为 none")
        print("按键: 1=walk 2=run 3=fall 0=none q=保存退出（Ctrl-C 同效）")

        try:
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
                committed += flush_settled(writer, pending, last_switch, drain=False)
        except KeyboardInterrupt:
            print("\n中断，保存已采集数据 ...")

        # 会话结束：不再有新切换，剩余行全部判定（切换 ±1s 内的过渡行仍丢弃）
        committed += flush_settled(writer, pending, last_switch, drain=True)

    print(f"已保存 {committed} 行 -> {out_path}")

if __name__ == "__main__":
    main()
