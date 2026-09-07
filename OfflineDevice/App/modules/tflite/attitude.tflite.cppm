//! TFLM 推理模块（计划 Phase 7.3）—— 轻量包装层。
//! TFLM/flatbuffers 重型头全部限制在普通 TU App/src/tflite/tflite_backend.cpp
//! （GCC15 模块单元下供应商头会触发 TU-local 暴露错误，见 backend 头注释）。
//! 仅在 ATTITUDE_ENABLE_TFLM=ON 且已生成 model_data 时参与构建。

module;

#include "attitude_tflite_backend.h"

#include <cstdint>

export module attitude.tflite;

import attitude.config;
import attitude.inference;

export namespace attitude {

class TfliteInference final : public InferenceBase {
public:
    /// 一次性初始化；失败原因见 attitude_tflite_last_error()
    bool init() noexcept
    {
        return attitude_tflite_init() != 0;
    }

    bool inferImpl(const ImuFrame* window, int len, Activity& out, float probs[3]) noexcept
    {
        if (window == nullptr || len != kWindowLen) return false;
        int argmax = 0;
        // ImuFrame 即 attitude_imu_frame（attitude.config 别名），类型相同直接传递
        if (attitude_tflite_infer(window, len, probs, &argmax) == 0) {
            return false;
        }
        out = static_cast<Activity>(argmax);
        return true;
    }

    /// tensor arena 实际用量（首次 init 后有效）
    size_t arenaUsedBytes() const noexcept
    {
        return attitude_tflite_arena_used();
    }
};

}  // namespace attitude
