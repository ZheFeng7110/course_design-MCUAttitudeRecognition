# BMI088 + TFLM 姿态识别管线设计（走路/跑步/摔倒）

日期：2026-09-07
状态：已实现（硬件验收待实机）

## 1. 概述

基于 STM32H723VGT6 + BMI088 + TensorFlow Lite for Microcontrollers 的离线运动
姿态识别设备，区分 WALK / RUN / FALL 三类。应用层 C++23 模块（不使用
`import std`），外设抽象经 emdevif（静态多态，无虚函数），模型为 int8 全量化
CNN，推理路径编译期选择。

## 2. 架构

```
main.c (CubeMX, C)
  └─ attitude_app_main()  [USER CODE 区挂接，再生成不覆盖]
       ├─ BMI088          attitude.bmi088   SPI1(共用)/CS_ACC(PB0)/CS_GYRO(PB1)
       ├─ WindowBuffer    attitude.window   200帧环形，每50帧可取快照
       ├─ InferenceImpl   编译期选择 std::conditional_t<kUseMockInference, ...>
       │    ├─ MockInference      attitude.inference  阈值启发式（占位）
       │    └─ TfliteInference    attitude.tflite     → tflite_backend.cpp (C 接口)
       │                                                 └─ TFLM + CMSIS-NN (deps/)
       └─ Serial/Timeline emdevif           "debug_console" USART1 921600
                                emdevif::user_impl 注入（registry/timeline .cpp）
```

### 关键设计决策

| 决策 | 理由 |
|---|---|
| `ImuFrame = using attitude_imu_frame` | 应用层与 C 后端共享唯一定义，消除 reinterpret_cast UB |
| 推理后端 C 接口（attitude_tflite_backend.h） | flatbuffers/schema 头在 GCC15 模块单元触发 TU-local 错误，重型头隔离在普通 TU |
| `InferenceBase` 无 CRTP 模板参 | C++23 deducing this，Self 即派生类型；`std::forward<Self>(self)` 完美转发 |
| 加速度计 ±24g | datasheet 无 ±16g（BST-BMI088-DS004），取最大量程防跌倒冲击饱和 |
| SPI1 内核时钟 CLKP、分频 32 | SCLK ≈5.7MHz，BMI088 10MHz 上限内（时钟树由用户在 CubeMX 侧确认） |
| `.tensor_arena` → RAM_D1 (0x24000000) | DTCM 仅 128KB，arena 128KB 需独立段（链接脚本 NOLOAD） |
| OpResolver: Conv2D/DepthwiseConv2D/FullyConnected/Softmax/Mean/Reshape/Quantize/Dequantize | Keras Conv1D 导出后被转换为 Conv2D 系列、GAP1D 转为 MEAN |

## 3. 构建

- 默认（Mock 推理）：`cmake --preset Debug && cmake --build --preset Debug`
- TFLM 路径：训练导出后运行 `model/tools/gen_c_array.py`，
  再 `cmake -B build -DATTITUDE_ENABLE_TFLM=ON` 并置 `kUseMockInference=false`

### 资源占用（探针模型验证）

| 配置 | Flash | RAM |
|---|---|---|
| Debug（Mock） | 47.7KB | DTCM ~2.9KB |
| Release（Mock） | 27.4KB | ~2.4KB |
| Debug（TFLM 路径） | ~166KB（含模型+CIB） | RAM_D1 128KB arena + DTCM ~3KB |

## 4. 数据与模型管线（model/，uv 管理）

`record.py`（串口打标采集，过渡段 ±1s 丢弃）→ `preprocess.py`（100Hz 对齐、
200×6 切窗、MobiAct/SisFall/自采集合并）→ `train.py`（Conv1D(8,5,s2) →
DWConv1D(16,7) → GAP → Dense(3)，公开集训练 + 自采集微调）→
`export_tflite.py`（全 int8 + representative dataset + 元数据 JSON）→
`gen_c_array.py`（生成 model_data.cc/h + 量化常量）→ `parity_check.py`
（PC–MCU argmax 一致率 100%、概率偏差 <0.01）→ `field_test.py`（混淆矩阵）。

## 5. 验收状态

- ✅ 编译门：Debug/Release 通过；TFLM 路径真实 int8 模型链接通过
- ⏳ 硬件门：chip ID 校验、CSV 流 10ms±10%、mock 阈值动作识别（需实机）
- ⏳ 数据集门 / 模型指标门（F1≥0.85）/ 一致性门 / 实测混淆矩阵（需数据采集）
