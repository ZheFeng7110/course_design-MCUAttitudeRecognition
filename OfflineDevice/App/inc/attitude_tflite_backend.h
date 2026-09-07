// TFLM 推理后端 C 接口（供 attitude.tflite 模块包装）。
// 为什么要一层 C 接口：flatbuffers/schema 头在 GCC15 模块单元中会触发
// TU-local 暴露错误，因此所有 TFLM/C++ 重型头只出现在普通 TU
// （tflite_backend.cpp），模块侧只看到本头文件。
#ifndef ATTITUDE_TFLITE_BACKEND_H
#define ATTITUDE_TFLITE_BACKEND_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// attitude.config 以 `using ImuFrame = attitude_imu_frame` 复用本类型，
// 应用层与后端共享同一定义，无需转换。
typedef struct {
    int16_t accel[3];
    int16_t gyro[3];
} attitude_imu_frame;

/// 一次性初始化（GetModel → OpResolver → AllocateTensors）。
/// @return 1 成功，0 失败（attitude_tflite_last_error 可取原因）
int attitude_tflite_init(void);

/// 阻塞推理：window 为 kWindowLen(200) 帧原始 LSB。
/// @return 1 成功并写入 probs[3]（和为1）与 *argmax（0/1/2）
int attitude_tflite_infer(const attitude_imu_frame* window, int len, float probs[3], int* argmax);

/// 首次 init 后返回 tensor arena 实际用量（字节）
unsigned attitude_tflite_arena_used(void);

const char* attitude_tflite_last_error(void);

#ifdef __cplusplus
}
#endif

#endif  // ATTITUDE_TFLITE_BACKEND_H
