//! 姿态识别应用 —— 全项目唯一参数源
module;

#include <cstdint>

#include "attitude_tflite_backend.h"  // attitude_imu_frame：ImuFrame 的唯一定义（见下）

export module attitude.config;

export namespace attitude {

// ---- 采样与窗口（与训练数据统一）----
inline constexpr int kSampleRateHz = 100;  // 采样率，与训练数据统一 100Hz
inline constexpr int kWindowLen    = 200;  // 2s 窗口 = 6×200 模型输入
inline constexpr int kWindowStride = 50;   // 推理步进 0.5s

// ---- BMI088 量程 ----
// 注意：datasheet（BST-BMI088-DS004）加速度计量程仅 ±3/±6/±12/±24g，无 ±16g；
// 取最大量程 ±24g 保证跌倒冲击不饱和（计划 Assumption #7：以 datasheet 修正）。
inline constexpr int   kAccelRangeG   = 24;
inline constexpr float kAccelLsbPerG  = 1365.0F;   // ±24g：32768/24 ≈ 1365 LSB/g
inline constexpr int   kGyroRangeDps  = 2000;
inline constexpr float kGyroLsbPerDps = 16.384F;   // ±2000dps：32768/2000

// ---- 模式开关 ----
inline constexpr bool kStreamRaw = false;         // CSV 原始流（采集模式）开关，Phase 5 置 true
inline constexpr bool kUseMockInference = true;   // Phase 7 置 false，切换 TFLM 推理

/// 一帧 IMU 原始数据（原始 LSB）。
/// 直接别名 attitude_tflite_backend.h 的 attitude_imu_frame，保证推理后端
/// 与应用层是同一类型（避免 reinterpret_cast 跨类型转换 UB）。
using ImuFrame = attitude_imu_frame;

}  // namespace attitude
