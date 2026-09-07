"""PC–MCU 一致性验证（Phase 7 验证门）。

从自采集会话抽取 ≥50 个窗口：
  - PC 端用 tf.lite.Interpreter 算参考概率
  - 同一窗口以二进制帧经调试 UART 发到 MCU（复用 attitude.config 的 kStreamRaw=false 通道，
    MCU 侧临时命令 'W'：随后 200 帧×12 字节 int16 原始 LSB → 返回 3×float 概率）
  - 比对 argmax 一致率（要求 100%）与概率偏差（要求 < 0.01）

用法: uv run parity_check.py <COM口> [窗口数=50]
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
try:
    import serial  # type: ignore
except ImportError:
    sys.exit("缺少 pyserial")

try:
    import tensorflow as tf
except ImportError:
    sys.exit("缺少 tensorflow（在 model/ 目录用 uv run 执行）")

ART = ROOT / "model" / "artifacts"
META = json.loads((ART / "model_meta.json").read_text())
NORM = META["input"]["normalization"]


def windows_from_sessions(min_windows: int) -> list[np.ndarray]:
    """从自采集 CSV 生成 (200,6) 窗口（按 200 帧滑窗、步长 200 抽取）。"""
    self_dir = ROOT / "model" / "data" / "self"
    wins = []
    for f in sorted(self_dir.glob("session_*.csv")):
        df = np.loadtxt(f, delimiter=",", skiprows=1, usecols=range(1, 7), dtype=np.int16)
        for i in range(0, len(df) - 200 + 1, 200):
            wins.append(df[i:i + 200].astype(np.float32))
            if len(wins) >= min_windows:
                return wins
    return wins


def pc_reference(interp: tf.lite.Interpreter, win_lsb: np.ndarray) -> tuple[np.ndarray, int, float]:
    inp = interp.get_input_details()[0]
    out_d = interp.get_output_details()[0]
    mean = np.array(NORM["mean"], np.float32)
    std = np.array(NORM["std"], np.float32)
    x = (win_lsb - mean) / std
    q = np.round(x / inp["quantization"][0] + inp["quantization"][1]).astype(np.int8)
    interp.set_tensor(inp["index"], q[np.newaxis])
    interp.invoke()
    out = interp.get_tensor(out_d["index"])[0].astype(np.float32)
    probs = (out.astype(np.float32) - out_d["quantization"][1]) * out_d["quantization"][0]
    probs = np.clip(probs, 0, 1)
    return probs, int(np.argmax(probs)), float(probs.sum() or 1.0)


def main() -> None:
    port = sys.argv[1] if len(sys.argv) > 1 else "COM5"
    n_windows = int(sys.argv[2]) if len(sys.argv) > 2 else 50

    wins = windows_from_sessions(n_windows)
    if len(wins) < n_windows:
        sys.exit(f"自采数据不足: 仅 {len(wins)} 个窗口（需 ≥{n_windows}，先采集）")

    interp = tf.lite.Interpreter(model_path=str(ART / "model.tflite"))
    interp.allocate_tensors()

    agree = 0
    max_dev = 0.0
    with serial.Serial(port, 921600, timeout=2.0) as ser:
        for win in wins:
            ser.write(b"W")  # MCU 进入 parity 模式
            ser.write(win.astype("<i2").tobytes())
            resp = ser.read(3 * 4)
            if len(resp) < 12:
                sys.exit("MCU 响应超时/过短（确认端侧临时命令已启用）")
            mcu_probs = np.array(struct.unpack("<3f", resp))
            _, mcu_argmax = int(np.argmax(mcu_probs)), int(np.argmax(mcu_probs))
            probs, pc_argmax, _ = pc_reference(interp, win)
            if mcu_argmax == pc_argmax:
                agree += 1
            max_dev = max(max_dev, float(np.abs(mcu_probs - probs).max()))

    print(f"argmax 一致率: {agree}/{len(wins)}（要求 100%）")
    print(f"最大概率偏差: {max_dev:.5f}（要求 < 0.01）")
    if agree != len(wins) or max_dev >= 0.01:
        print("[未达标]")


if __name__ == "__main__":
    main()
