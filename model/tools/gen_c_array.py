"""生成端侧模型数组与量化元数据常量:
model.tflite + model_meta.json → App/src/model_data.cc + App/inc/model_data.h

模型数据是生成物，保持普通 TU（不进模块）。
生成后以 -DATTITUDE_ENABLE_TFLM=ON 重新配置，并把 attitude.config 的
kUseMockInference 置 false。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent  # 仓库根
TFLITE = ROOT / "model" / "artifacts" / "model.tflite"
META = ROOT / "model" / "artifacts" / "model_meta.json"
OUT_CC = ROOT / "OfflineDevice" / "App" / "src" / "model_data.cc"
OUT_H = ROOT / "OfflineDevice" / "App" / "inc" / "model_data.h"

HEADER = """\
// 生成文件：由 model/tools/gen_c_array.py 产生，请勿手改
#ifndef ATTITUDE_MODEL_DATA_H
#define ATTITUDE_MODEL_DATA_H

#include <cstddef>
#include <cstdint>

#ifdef __cplusplus
extern "C" {
#endif

extern const unsigned char g_attitude_model[];
extern const size_t g_attitude_model_len;

/* 量化/归一化元数据（与 model_meta.json 同源） */
extern const float kAttitudeNormMean[6];
extern const float kAttitudeNormStd[6];
extern const float kAttitudeInputScale;
extern const int32_t kAttitudeInputZeroPoint;

#ifdef __cplusplus
}
#endif

#endif  // ATTITUDE_MODEL_DATA_H
"""


def c_float_list(values: list[float]) -> str:
    return "{" + ", ".join(f"{v:.9g}f" for v in values) + "}"


def main() -> None:
    if not TFLITE.exists():
        sys.exit(f"缺少 {TFLITE}，先运行 export_tflite.py")
    meta = json.loads(META.read_text(encoding="utf-8"))
    data = TFLITE.read_bytes()

    OUT_H.parent.mkdir(parents=True, exist_ok=True)
    OUT_CC.parent.mkdir(parents=True, exist_ok=True)
    OUT_H.write_text(HEADER, encoding="utf-8")

    lines = [
        "// 生成文件：由 model/tools/gen_c_array.py 产生，请勿手改",
        '#include "model_data.h"',
        "",
        f"alignas(16) const unsigned char g_attitude_model[{len(data)}] = {{",
    ]
    for i in range(0, len(data), 12):
        chunk = data[i:i + 12]
        lines.append("    " + ",".join(f"0x{b:02x}" for b in chunk) + ",")
    lines.append("};")
    lines.append(f"const size_t g_attitude_model_len = {len(data)};")
    lines.append("")
    inp = meta["input"]
    lines.append(f"const float kAttitudeNormMean[6] = {c_float_list(inp['normalization']['mean'])};")
    lines.append(f"const float kAttitudeNormStd[6] = {c_float_list(inp['normalization']['std'])};")
    lines.append(f"const float kAttitudeInputScale = {inp['scale']:.9g}f;")
    lines.append(f"const int32_t kAttitudeInputZeroPoint = {inp['zero_point']};")
    OUT_CC.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"写入 {OUT_CC}（模型 {len(data)} 字节 + 元数据）与 {OUT_H}")
    print("下一步: cmake -DATTITUDE_ENABLE_TFLM=ON 重新配置，并把 kUseMockInference 置 false")


if __name__ == "__main__":
    main()
