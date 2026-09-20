"""端到端验收（Phase 8）：录入 UART 的 ACT 行，输出混淆矩阵与延迟报告。

MCU 输出格式: ACT,WALK|RUN|FALL,p0,p1,p2,<耗时>ms
操作员每轮试验前按键打真值（1=walk 2=run 3=fall），轮次时长 --trial-sec（默认 10s）。

用法: uv run field_test.py [串口]
    串口缺省：Windows COM5 / Linux /dev/ttyUSB0（同 record.py）
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
from console_input import PORT_DEFAULT, key_input, keys_available, read_key

try:
    import serial  # type: ignore
except ImportError:
    sys.exit("缺少 pyserial")

BAUD = 921600
TRIAL_SEC = 10.0
LABELS = ["walk", "run", "fall"]
KEY2LABEL = {"1": 0, "2": 1, "3": 2}
OUT = Path(__file__).resolve().parent.parent / "data" / "field"


def main() -> None:
    port = sys.argv[1] if len(sys.argv) > 1 else PORT_DEFAULT
    OUT.mkdir(parents=True, exist_ok=True)

    conf = np.zeros((3, 3), dtype=int)  # [真实][预测]
    latencies = []
    per_class_lat = {c: [] for c in LABELS}
    trials = 0

    print("每轮试验：按键选真值标签开始（1/2/3），q=结束（Ctrl-C 同效）")
    if not keys_available():
        print("[提示] 当前环境无法读按键（stdin 非 TTY）")
    with key_input(), serial.Serial(port, BAUD, timeout=0.1) as ser:
        try:
            while True:
                key = read_key()
                if key == "q":
                    break
                if key not in KEY2LABEL:
                    time.sleep(0.02)
                    continue
                truth = KEY2LABEL[key]
                trials += 1
                print(f"试验 {trials}: {LABELS[truth]}，采集 {TRIAL_SEC}s ...")
                deadline = time.perf_counter() + TRIAL_SEC
                preds = []
                while time.perf_counter() < deadline:
                    line = ser.readline().decode("ascii", errors="ignore").strip()
                    if not line.startswith("ACT,"):
                        continue
                    parts = line.split(",")
                    if len(parts) < 6:
                        continue
                    pred_name = parts[1].lower()
                    if pred_name not in LABELS:
                        continue
                    preds.append(pred_name)
                    try:
                        latencies.append(float(parts[5].removesuffix("ms")))
                        per_class_lat[pred_name].append(latencies[-1])
                    except (ValueError, IndexError):
                        pass
                if preds:
                    counts = {p: preds.count(p) for p in set(preds)}
                    majority = max(counts, key=counts.get)
                    conf[truth, LABELS.index(majority)] += 1
        except KeyboardInterrupt:
            print("\n中断，输出已完成的试验 ...")

    if trials == 0:
        sys.exit("无试验记录")

    print("\n混淆矩阵 [行=真实, 列=预测]（walk/run/fall）:")
    print(conf)
    acc = conf.diagonal().sum() / conf.sum()
    recall_fall = conf[2, 2] / conf[2].sum() if conf[2].sum() else 0.0
    if latencies:
        arr = np.array(latencies)
        print(f"\n推理耗时: mean={arr.mean():.2f}ms p95={np.percentile(arr, 95):.2f}ms max={arr.max():.2f}ms")
    for c in LABELS:
        if per_class_lat[c]:
            a = np.array(per_class_lat[c])
            print(f"  {c}: mean={a.mean():.2f}ms n={len(a)}")
    print(f"\n整体准确率: {acc:.3f}（达标 ≥0.85）；摔倒召回: {recall_fall:.3f}（达标 ≥0.90）")

    out_file = OUT / f"field_report_{time.strftime('%Y%m%d_%H%M%S')}.txt"
    out_file.write_text(f"confusion=\n{conf}\naccuracy={acc}\nrecall_fall={recall_fall}\n", encoding="utf-8")
    print(f"报告 -> {out_file}")


if __name__ == "__main__":
    main()
