// TFLM 推理后端实现（普通 TU，链接期链接 tflm 静态库）。
// 所有 TFLM/flatbuffers C++ 头限制在本文件（见 attitude_tflite_backend.h 注释）。

#include "attitude_tflite_backend.h"
#include "attitude_quantize.h"

#include "model_data.h"

#include <tensorflow/lite/c/c_api_types.h>
#include <tensorflow/lite/c/common.h>
#include <tensorflow/lite/micro/micro_interpreter.h>
#include <tensorflow/lite/micro/micro_mutable_op_resolver.h>
#include <tensorflow/lite/schema/schema_generated.h>

#include <cmath>
#include <cstddef>
#include <cstring>

namespace {

constexpr int kWindowLen = 200;
constexpr size_t kArenaSize = 128U * 1024U;  // 128KB 起步，实际用量见 arena_used

alignas(16) uint8_t g_tensor_arena[kArenaSize] __attribute__((section(".tensor_arena")));

const tflite::Model* g_model = nullptr;
tflite::MicroInterpreter* g_interpreter = nullptr;
TfLiteTensor* g_input = nullptr;
TfLiteTensor* g_output = nullptr;
const char* g_last_error = "not initialized";
unsigned g_arena_used = 0;

bool fail(const char* msg) noexcept
{
    g_last_error = msg;
    return false;
}

float dequantize(int8_t v, float scale, int32_t zp) noexcept
{
    return (static_cast<float>(v) - static_cast<float>(zp)) * scale;
}

}  // namespace

int attitude_tflite_init(void)
{
    g_model = tflite::GetModel(g_attitude_model);
    if (g_model->version() != TFLITE_SCHEMA_VERSION) {
        fail("model schema version mismatch");
        return 0;
    }

    static tflite::MicroMutableOpResolver<8> resolver;
    // 算子按转换后注册：Keras Conv1D/DepthwiseConv1D 导出为 Conv2D/DepthwiseConv2D，
    // GlobalAveragePooling1D 导出为 MEAN
    if (resolver.AddConv2D() != kTfLiteOk
        || resolver.AddDepthwiseConv2D() != kTfLiteOk
        || resolver.AddFullyConnected() != kTfLiteOk
        || resolver.AddSoftmax() != kTfLiteOk
        || resolver.AddMean() != kTfLiteOk
        || resolver.AddReshape() != kTfLiteOk
        || resolver.AddQuantize() != kTfLiteOk
        || resolver.AddDequantize() != kTfLiteOk) {
        fail("op resolver full");
        return 0;
    }

    g_interpreter = new (g_tensor_arena)
        tflite::MicroInterpreter(g_model, resolver, g_tensor_arena, sizeof(g_tensor_arena));
    if (g_interpreter->AllocateTensors() != kTfLiteOk) {
        fail("AllocateTensors failed");
        return 0;
    }
    g_arena_used = static_cast<unsigned>(g_interpreter->arena_used_bytes());

    g_input = g_interpreter->input(0);
    g_output = g_interpreter->output(0);
    // Keras Conv1D 导出后为 Conv2D：输入可为 (1,200,6) 或 (1,200,1,6)
    bool shape_ok = false;
    if (g_input->type == kTfLiteInt8) {
        if (g_input->dims->size == 3) {
            shape_ok = g_input->dims->data[1] == kWindowLen && g_input->dims->data[2] == 6;
        } else if (g_input->dims->size == 4) {
            shape_ok = g_input->dims->data[1] == kWindowLen && g_input->dims->data[2] == 1
                       && g_input->dims->data[3] == 6;
        }
    }
    if (!shape_ok) {
        fail("unexpected input tensor");
        return 0;
    }
    g_last_error = "ok";
    return 1;
}

int attitude_tflite_infer(const attitude_imu_frame* window, int len, float probs[3], int* argmax)
{
    if (window == nullptr || len != kWindowLen || g_interpreter == nullptr) {
        fail("bad call");
        return 0;
    }

    // 窗口原始 LSB → 物理量 → 归一化 → int8（见 attitude_quantize.h）
    static int8_t quantized[kWindowLen * 6];
    attitude_quantize_window(window, len, quantized);
    std::memcpy(g_input->data.int8, quantized, sizeof(quantized));

    if (g_interpreter->Invoke() != kTfLiteOk) {
        fail("Invoke failed");
        return 0;
    }

    const float out_scale = g_output->params.scale;
    const int32_t out_zp = g_output->params.zero_point;
    float sum = 0.0F;
    for (int i = 0; i < 3; ++i) {
        probs[i] = dequantize(g_output->data.int8[i], out_scale, out_zp);
        if (probs[i] < 0.0F) probs[i] = 0.0F;
        sum += probs[i];
    }
    if (sum <= 0.0F) {
        fail("degenerate probs");
        return 0;
    }
    for (int i = 0; i < 3; ++i) probs[i] /= sum;

    int best = 0;
    for (int i = 1; i < 3; ++i) {
        if (probs[i] > probs[best]) best = i;
    }
    *argmax = best;
    return 1;
}

unsigned attitude_tflite_arena_used(void)
{
    return g_arena_used;
}

const char* attitude_tflite_last_error(void)
{
    return g_last_error;
}
