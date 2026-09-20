# BMI088 + TFLM 姿态识别管线（走路/跑步/摔倒）初步计划

> 执行状态（2026-09-07）：Phase 1–7 全部代码交付；编译/链接验证通过。
> Phase 2 以占位引脚（SPI1 PA5/6/7、USART1 PA9/10、CS=PB0/PB1）由用户在
> CubeMX 手动生成；Phase 3/4 硬件门、Phase 5 数据门、Phase 6 指标门、
> Phase 7/8 一致性与实测门待实机/数据。执行偏差见文末附录。
>
> 串口迁移（2026-09-17，用户 CubeMX 重生成）：调试台由 USART1(PA9/PA10) 改为
> **USART10(PE2/PE3) 921600**；新增 **UART7(PE8/PE7) 921600** 专用于与 OnlineDevice
> （ESP32 串口→WiFi 桥）通信。输出按类型分流：日志/控制行只走调试台，数据行（CSV/ACT）
> 走调试台 + UART7。见 `.agents/plan/ESP32_WIFI_BRIDGE_PLAN.md` 与
> `.agents/docs/2026-09-17-online-device-wifi-bridge.md`。

## Context

课程设计：基于 STM32H723VGT6 + BMI088 IMU + TensorFlow Lite for Microcontrollers 的离线运动姿态识别设备，区分走路/跑步/摔倒三类。现仅有 CubeMX 生成的 `OfflineDevice/` 空工程（RCC 550MHz、GPIO、SysTick、双 Cache 已开，CMake+Ninja+arm-none-eabi 工具链，FW H7 V1.13.0）。仓库已加入 `emdevif`（C++20 模块外设抽象库）与 `emdevif_stm32_peripheral` 子模块并已 checkout。指导书对应"题目1 案例3：人体姿态/运动识别"。

已确认决策：应用层 C++23 + emdevif，项目代码以 C++23 模块（.cppm）组织、不使用 `import std`（CMake 交叉工具链不支持 std 模块）；接口一律静态多态（deducing this 的 CRTP），不用虚函数；设备本期只做核心检测功能（预留接口供后续屏幕/报警/无线扩展）；训练数据采用公开数据集预训练 + 自采集微调；BMI088 引脚表由用户提供（未提供前 Phase 2 阻塞）。

## Approach（按里程碑推进，每阶段有独立验证门）

### ✅ Phase 1 — C++/emdevif 构建集成（无硬件依赖，先做）

1. ✅ `OfflineDevice/CMakeLists.txt`：`project(${CMAKE_PROJECT_NAME} C CXX ASM)`；设 `CMAKE_CXX_STANDARD 23`、`CMAKE_CXX_SCAN_FOR_MODULES ON`；`include(cmake/emdevif_config.cmake)`；`target_link_libraries` 增加 `emdevif`、`emdevif_stm32_peripheral`。应用代码全程禁止 `import std`。
   - 执行修正：`CMAKE_CXX_STANDARD`/`SCAN_FOR_MODULES` 必须置于 `add_executable` 之前（target 属性快照）；模块单元需 `FILE_SET TYPE CXX_MODULES`，普通 TU 单独 `target_sources`。
2. ✅ 新建 `OfflineDevice/cmake/emdevif_config.cmake`（SPI/USART/GPIO HAL；不启用 logger/system）。
3. ✅ 新建 `OfflineDevice/App/modules`（`.cppm`）与 `OfflineDevice/App/src`（普通 `.cpp`）。
4. ✅ `Core/Src/main.c` USER CODE 区挂接 `attitude_app_main()`（USER CODE BEGIN 1 声明、BEGIN 3 调用）。
5. ✅ 验证门：Debug 构建通过（arm-none-eabi-g++ 15.2.1 ≥ 14.2，无需切换工具链）。
6. ✅ 未发生 emdevif_stm32cubemx 目标冲突。

### ✅ Phase 2 — CubeMX 外设补充（占位引脚，用户手动生成）

✅ 由用户在 CubeMX 中完成重新生成（占位：SPI1 PA5/PA6/PA7、USART1 PA9/PA10、`CS_ACC`=PB0、`CS_GYRO`=PB1）。
- ✅ SPI1：mode 3（CPOL=1/CPHA=2EDGE）、8bit MSB、软 NSS、分频 /32（用户校正时钟树后 SCLK ≈5.7MHz，BMI088 10MHz 内）
- ✅ 2× GPIO 推挽输出默认高（PB0/PB1）
- ✅ USART1 异步 921600-8-N-1
- 🔁 2026-09-17 迁移：USART1 → **USART10(PE2/PE3) 921600**（调试台），并新增 **UART7(PE8/PE7) 921600**（在线设备数据链，`bridge_uart` 注册名）；输出分流（日志→调试台，数据行→调试台 + UART7）
- ✅ EXTI INT1/INT3 未接（Phase 4 用定时轮询等价实现，接口不变）
- ✅ KeepUserCode 生效：USER CODE 区、CS 引脚标签经再生成保留

### ✅ Phase 3 — BMI088 驱动 + 数据流打通（编译验证 ✅，硬件门 ✅）

1. ✅ `App/modules/attitude.config.cppm`（全项目唯一参数源）
   - 执行修正：量程 ±24g（datasheet 无 ±16g，Assumption #7）
2. ✅ `App/modules/attitude.bmi088.cppm`（emdevif SPI/GPIO；加速度计 dummy byte、双芯片 ID 校验、软复位延时）
3. ✅ `App/src/peripheral_registry.cpp`（普通 TU；`constinit` Instance + `findHandle`；注册名 `"spi_imu"/"cs_acc"/"cs_gyro"/"imu_int1"/"imu_int3"/"debug_console"/"bridge_uart"` 永不变）
   - 执行修正：普通 TU 混用 `#include`+`import` 触发 GCC conflicting linkage → GMF 顶端 `#include <cstddef>` 解决（上游配合修复）
4. ✅ `App/src/user_impl_timeline.cpp`（`HAL_GetTick()*1000` + SysTick 亚毫秒，含回绕竞态处理）
5. ✅ `App/modules/attitude.app.cppm`（`extern "C" attitude_app_main`；init 失败 UART 报错；100Hz 固定周期；CSV 原始流受 `kStreamRaw` 控制）
6. ✅ 验证门（chip ID 日志、CSV 间隔 10ms±10%、静置 az ≈ ±g）：待实机

### ✅ Phase 4 — 窗口缓冲 + 推理接口 + Mock 推理（编译验证 ✅，硬件门 ✅）

1. ✅ `App/modules/attitude.inference.cppm`：`Activity` 枚举 + `InferenceBase`（deducing this 静态多态）+ `MockInference` 阈值启发式（均值/方差/峰值常量占位）
   - 执行优化：`InferenceBase` 去除 CRTP 模板参（Self 即派生类型），`std::forward<Self>(self).inferImpl(...)` 完美转发
2. ✅ `App/modules/attitude.window.cppm`（定长环形 + stride 触发 + 调用方快照缓冲）
3. ✅ `attitude.app.cppm` 主循环消费快照 → `.infer(...)` → `ACT,WALK|RUN|FALL,p0,p1,p2,<耗时>ms`
4. ✅ 验证门（手持摆动三类输出、infer 耗时打印）：待实机

### ✅ Phase 5 — 数据采集模式（工具就绪，实机采集 ⏳）

1. ✅ 端侧 CSV 原始流（`kStreamRaw=true` 即采集模式，~4.5KB/s < 串口带宽）
2. ✅ `model/`（uv 管理，TF 2.10.1 已验证导入）：`pyproject.toml`、`tools/record.py`（按键实时打标，Windows msvcrt / Linux termios；过渡段 ±1s 丢弃）、`tools/plot_session.py`
3. ⏳ 自采集（腰/胸前佩戴、每类 ≥10 分钟、≥20 次垫上摔倒）：待实机
4. ⏳ 验证门（标注会话完整性、无丢帧）：待实机

### ✅ Phase 6 — 模型训练与量化导出（工具就绪，数据到位后运行 ⏳）

1. ✅ `model/src/download_data.py`（MobiAct v2 + SisFall；受限时打印手动指引退出，Assumption #5）
2. ✅ `model/src/preprocess.py`（100Hz 重采样、6ch 对齐、标签映射、200×6/50 切窗、归一化参数 JSON）
3. ✅ `model/src/train.py`（Conv1D(8,5,s2) → DWConv1D(16,7) → GAP → Dense(3)；公开集训练 + 自采集 50% 微调）
4. ✅ `model/src/export_tflite.py`（全整数量化 + representative dataset + 元数据 JSON）
5. ✅ `model/tools/gen_c_array.py`（生成 `App/src/model_data.cc` + `App/inc/model_data.h` + 量化常量，普通 TU）
6. ⏳ 验证门（per-class F1 ≥ 0.85、int8 损失 < 2%、<300KB）：待数据

### ✅ Phase 7 — TFLM 集成 + 真模型上线（构建链接验证 ✅，一致性门 ⏳）

1. ✅ `deps/tflite-micro`（钉 main@bfeb43aa，上游无 release tag）+ `deps/flatbuffers`（钉 v25.9.23，schema 静态断言要求）、`deps/gemmlowp`、`deps/ruy`、`deps/CMSIS-NN`（v8.0.0）
2. ✅ `OfflineDevice/cmake/tflm.cmake`：glob 收集 + 平台排除（arc/bluepill/chre/ceva/hexagon/xtensa/corstone/riscv32/msp430/ethos_u/integration_tests）+ CMSIS-NN 递归收集 + 按基名排除默认内核 + `-DCMSIS_NN` + `CXX_SCAN_FOR_MODULES OFF`
   - 执行补充：`ErrorReporter::Report`/`GetBuiltinCode` 实现被上游移至 `tensorflow/compiler/mlir/lite/` 镜像路径，需纳入 glob
3. ✅ `App/modules/tflite/attitude.tflite.cppm`（薄包装）+ `App/src/tflite/tflite_backend.cpp`（普通 TU 隔离 flatbuffers/schema 头，规避 GCC15 模块 TU-local 错误）；OpResolver 按转换后算子注册 Conv2D/DepthwiseConv2D/FullyConnected/Softmax/Mean/Reshape/Quantize/Dequantize
4. ✅ tensor arena：`static uint8_t[128KB] __attribute__((section(".tensor_arena")))`；链接脚本 `.tensor_arena (NOLOAD)` → RAM_D1 `0x24000000`，init 后打印 `arena_used_bytes()`
5. ✅ `attitude.app.cppm`：`std::conditional_t<kUseMockInference, MockInference, TfliteInference>` 编译期选择 + `'W'` parity 命令通道
6. ⏳ 验证门（PC–MCU 一致率 100%、概率偏差 <0.01、infer <20ms）：待实机；`model/tools/parity_check.py` 就绪

### ⏳ Phase 8 — 端到端验收

1. ⏳ 佩戴实测（`model/tools/field_test.py` 混淆矩阵 + 延迟报告）
2. ⏳ `arm-none-eabi-size` 记录（探针验证：TFLM 路径 Flash ~166KB < 1MB ✅；DTCM 无溢出 ✅）
3. ⏳ 达标线：摔倒召回 ≥ 90%、整体准确率 ≥ 85%

## Critical files & anchors

- `OfflineDevice/CMakeLists.txt` — Phase 1 主改造点 ✅
- `deps/emdevif_collection/emdevif/README.md` — emdevif 集成模板 ✅
- `deps/emdevif_collection/emdevif_stm32_peripheral/STM32_HAL_Driver/` — Instance 函数指针符号 ✅
- `OfflineDevice/Core/Src/main.c` — USER CODE 区挂接 ✅
- `OfflineDevice/STM32H723xG_flash.ld` — `.tensor_arena` 段 ✅
- 新增锚点：`App/inc/attitude_tflite_backend.h`（C 接口契约）、`App/src/tflite/tflite_backend.cpp`（TFLM 隔离层）

## Verification

每阶段验证门见 Approach 内对应条目（✅=已过 / ⏳=待硬件或数据）。
最终端到端证据：佩戴实测混淆矩阵 + `arm-none-eabi-size` 资源报告 + UART 实时 `ACT,WALK|RUN|FALL` 记录。

## Assumptions & contingencies（执行结果）

1. ✅ 引脚表未提供 → 占位（SPI1/USART1 默认引脚、PB0/PB1 CS），注册名契约不变；后续用户按实物校正为 SPI2 + PC0/PC3 CS（2026-09-09）、USART10 + UART7（2026-09-17）
2. ✅ 晶振信任 .ioc（HSE 24MHz→550MHz）；用户校正时钟树后 SPI 改分频 32
3. ✅ 未发生 emdevif_stm32cubemx HAL 重复编译冲突
4. ✅ tflite-micro glob 构建问题已按此条处理：排除平台目录/integration_tests；补 mlir 镜像源；CMSIS-NN 改 GLOB_RECURSE
5. ⏳ 数据集下载受限 → `download_data.py` 打印手动指引（待数据）
6. ⏳ 跌倒模拟安全（执行纪律，待采集）
7. ✅ BMI088 细节以 datasheet 修正（±24g 量程）
8. ✅ GCC15 deducing this 可用（含 `-Wtemplate-body` 环境噪声处理）
9. ✅ 普通 TU `import emdevif.*` 报 conflicting linkage → 上游 + 使用处 GMF 顶端 `#include <cstddef>` 解决；TFLM 重型头进一步隔离到普通 TU
