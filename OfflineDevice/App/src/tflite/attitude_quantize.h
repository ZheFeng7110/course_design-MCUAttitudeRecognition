// 窗口 → 模型输入 int8 量化（TFLM 后端的输入预处理）。
//
// 顺序固定（与训练/导出/PC 侧 tools/parity_check.py 同口径）：
//   原始 int16 LSB → 物理量（acc→g, gyro→dps）→ 归一化(model_data 元数据) → int8
//
// LSB 系数由 model/tools/gen_c_array.py 从 model_meta.json 生成
// （kAttitudeAccelLsbPerG / kAttitudeGyroLsbPerDps），生成端会校验它们与
// attitude.config.cppm 的 kAccelLsbPerG / kGyroLsbPerDps 一致。
//
// 注意：kAttitudeNormMean/Std 是物理量（g / dps）统计量，若直接把原始 LSB 喂进去
// 归一化，加速度通道会整体饱和到 ±127（实测恒判 run），这正是本函数存在的意义。
#ifndef ATTITUDE_QUANTIZE_H
#define ATTITUDE_QUANTIZE_H

#include "attitude_tflite_backend.h"  // attitude_imu_frame
#include "model_data.h"               // kAttitudeNormMean/Std、kAttitudeInputScale/ZeroPoint、LSB 系数

#include <cmath>
#include <cstdint>

/// 把 len 帧原始 LSB 量化为 len*6 个 int8（行主序，通道序 ax,ay,az,gx,gy,gz）。
inline void attitude_quantize_window(const attitude_imu_frame* window, int len, int8_t* out) noexcept
{
    const float phys_per_lsb[6] = {
        1.0F / kAttitudeAccelLsbPerG,
        1.0F / kAttitudeAccelLsbPerG,
        1.0F / kAttitudeAccelLsbPerG,
        1.0F / kAttitudeGyroLsbPerDps,
        1.0F / kAttitudeGyroLsbPerDps,
        1.0F / kAttitudeGyroLsbPerDps,
    };

    for (int i = 0; i < len; ++i) {
        const float chans[6] = {
            static_cast<float>(window[i].accel[0]),
            static_cast<float>(window[i].accel[1]),
            static_cast<float>(window[i].accel[2]),
            static_cast<float>(window[i].gyro[0]),
            static_cast<float>(window[i].gyro[1]),
            static_cast<float>(window[i].gyro[2]),
        };
        for (int c = 0; c < 6; ++c) {
            const float phys = chans[c] * phys_per_lsb[c];
            const float x = (phys - kAttitudeNormMean[c]) / kAttitudeNormStd[c];
            float q = std::nearbyint(x / kAttitudeInputScale)
                      + static_cast<float>(kAttitudeInputZeroPoint);
            if (q > 127.0F) q = 127.0F;
            if (q < -128.0F) q = -128.0F;
            out[i * 6 + c] = static_cast<int8_t>(q);
        }
    }
}

#endif  // ATTITUDE_QUANTIZE_H
