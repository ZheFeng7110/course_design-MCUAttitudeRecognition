//! 推理契约与 Mock 实现（静态多态，deducing this，无虚函数）

module;

#include <cmath>
#include <cstdint>
#include <utility>

export module attitude.inference;

import attitude.config;

export namespace attitude {

enum class Activity : uint8_t { Walk = 0, Run = 1, Fall = 2 };

/// 推理基类：具体实现类须提供
/// `bool inferImpl(const ImuFrame*, int, Activity&, float[3])`。
/// deducing this 使基类无需 CRTP 模板参：Self 天然是派生类型，
/// 完美转发保持值类别（无虚函数，静态分派）。
class InferenceBase {
public:
    template <typename Self>
    bool infer(this Self&& self, const ImuFrame* window, int len, Activity& out, float probs[3])
    {
        return std::forward<Self>(self).inferImpl(window, len, out, probs);
    }
};

/// 阈值启发式 Mock 推理。
/// 占位实现（Phase 7 替换为 TFLM 真模型），仅用于验证窗口时序与管线正确性。
class MockInference final : public InferenceBase {
public:
    bool inferImpl(const ImuFrame* window, int len, Activity& out, float probs[3]) noexcept
    {
        if (window == nullptr || len != kWindowLen) return false;

        // 合加速度幅值均值/最大值（g）与陀螺仪幅值方差（dps²）
        float acc_sum = 0.0F;
        float acc_max = 0.0F;
        float gyro_mean = 0.0F;
        float gyro_m2 = 0.0F;  // Welford 单趟方差
        int n = 0;
        for (int i = 0; i < len; ++i) {
            const float ax = static_cast<float>(window[i].accel[0]) / kAccelLsbPerG;
            const float ay = static_cast<float>(window[i].accel[1]) / kAccelLsbPerG;
            const float az = static_cast<float>(window[i].accel[2]) / kAccelLsbPerG;
            const float acc_mag = std::sqrt(ax * ax + ay * ay + az * az);
            const float gx = static_cast<float>(window[i].gyro[0]) / kGyroLsbPerDps;
            const float gy = static_cast<float>(window[i].gyro[1]) / kGyroLsbPerDps;
            const float gz = static_cast<float>(window[i].gyro[2]) / kGyroLsbPerDps;
            const float gyro_mag = std::sqrt(gx * gx + gy * gy + gz * gz);

            acc_sum += acc_mag;
            if (acc_mag > acc_max) acc_max = acc_mag;

            ++n;
            const float d = gyro_mag - gyro_mean;
            gyro_mean += d / static_cast<float>(n);
            gyro_m2 += d * (gyro_mag - gyro_mean);
        }
        const float acc_mean = acc_sum / static_cast<float>(n);
        const float gyro_var = gyro_m2 / static_cast<float>(n);

        // ---- 阈值（占位，Phase 7 替换）----
        Activity act = Activity::Walk;
        if (acc_max > kFallAccMaxG || acc_mean > kFallAccMeanG) {
            act = Activity::Fall;    // 大冲击 / 长时间超重
        } else if (gyro_var > kRunGyroVarDps2) {
            act = Activity::Run;     // 剧烈摆动
        }

        out = act;
        const uint8_t idx = static_cast<uint8_t>(act);
        for (int i = 0; i < 3; ++i) probs[i] = (i == idx) ? 0.7F : 0.15F;
        return true;
    }

private:
    // ---- Mock 阈值常量（占位，Phase 7 替换）----
    static constexpr float kFallAccMaxG     = 2.8F;   // 窗口内最大合加速度（g）
    static constexpr float kFallAccMeanG    = 1.6F;   // 窗口平均合加速度（g）
    static constexpr float kRunGyroVarDps2  = 2500.0F;  // 陀螺仪幅值方差（dps²）
};

}  // namespace attitude
