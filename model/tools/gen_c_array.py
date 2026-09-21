"""生成端侧模型数组与量化元数据常量:
model.tflite + model_meta.json → App/src/model_data.cc + App/inc/model_data.h

模型数据是生成物，保持普通 TU（不进模块）。
生成后以 -DATTITUDE_ENABLE_TFLM=ON 重新配置，并把 attitude.config 的
kUseMockInference 置 false。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent  # 仓库根
TFLITE = ROOT / "model" / "artifacts" / "model.tflite"
META = ROOT / "model" / "artifacts" / "model_meta.json"
CONFIG = ROOT / "OfflineDevice" / "App" / "modules" / "attitude.config.cppm"
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

/* 传感器 LSB 系数：窗口原始 LSB → 物理量（g / dps）换算用。
   与 attitude.config 的 kAccelLsbPerG / kGyroLsbPerDps 同值（gen_c_array.py 校验）。 */
extern const float kAttitudeAccelLsbPerG;
extern const float kAttitudeGyroLsbPerDps;

#ifdef __cplusplus
}
#endif

#endif  // ATTITUDE_MODEL_DATA_H
"""


def c_float(value: float) -> str:
    """C++ float 字面量：'1365f' 不是合法数字，必须补小数/指数位（写成 1365.0f）。"""
    s = f"{value:.9g}"
    if not any(c in s for c in ".eE"):
        s += ".0"
    return s + "f"


def c_float_list(values: list[float]) -> str:
    return "{" + ", ".join(c_float(v) for v in values) + "}"


def config_lsb_constants() -> tuple[float, float] | None:
    """读 attitude.config.cppm 的量程常量（全项目参数源）。解析不了则返回 None 并告警。"""
    text = CONFIG.read_text(encoding="utf-8")

    def value(name: str) -> float | None:
        m = re.search(rf"{name}\s*=\s*([0-9.]+)F?", text)
        return float(m.group(1)) if m else None

    acc, gyr = value("kAccelLsbPerG"), value("kGyroLsbPerDps")
    if acc is None or gyr is None:
        print(f"[警告] 无法从 {CONFIG.name} 解析量程常量，跳过 LSB 系数一致性校验")
        return None
    return acc, gyr


def check_lsb_constants(sensor: dict) -> tuple[float, float]:
    """模型侧 LSB 系数必须与端侧量程常量一致，否则生成出来的固件必然算错。"""
    acc = float(sensor["accel_lsb_per_g"])
    gyr = float(sensor["gyro_lsb_per_dps"])
    cfg = config_lsb_constants()
    if cfg is not None and cfg != (acc, gyr):
        sys.exit(f"LSB 系数不一致：模型侧 acc={acc} gyr={gyr}，"
                 f"{CONFIG.name} acc={cfg[0]} gyr={cfg[1]}。改量程时 "
                 "preprocess.ACC_LSB_PER_G/GYR_LSB_PER_DPS 与 attitude.config 的 "
                 "kAccelLsbPerG/kGyroLsbPerDps 必须同步")
    return acc, gyr


def main() -> None:
    if not TFLITE.exists():
        sys.exit(f"缺少 {TFLITE}，先运行 export_tflite.py")
    meta = json.loads(META.read_text(encoding="utf-8"))
    sensor = meta.get("sensor")
    if sensor is None:
        sys.exit(f"{META} 缺少 sensor 段（LSB 系数）：重新运行 export_tflite.py")
    acc_lsb, gyr_lsb = check_lsb_constants(sensor)
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
    lines.append(f"const float kAttitudeInputScale = {c_float(inp['scale'])};")
    lines.append(f"const int32_t kAttitudeInputZeroPoint = {inp['zero_point']};")
    lines.append(f"const float kAttitudeAccelLsbPerG = {c_float(acc_lsb)};")
    lines.append(f"const float kAttitudeGyroLsbPerDps = {c_float(gyr_lsb)};")
    OUT_CC.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"写入 {OUT_CC}（模型 {len(data)} 字节 + 元数据）与 {OUT_H}")
    print("下一步: cmake -DATTITUDE_ENABLE_TFLM=ON 重新配置，并把 kUseMockInference 置 false")


if __name__ == "__main__":
    main()
