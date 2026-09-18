# 在线设备（ESP32 → WiFi 数据桥）设计

日期：2026-09-17；2026-09-18 更新（串口迁移 + 日志/数据分流 + UART7 定 921600）
状态：两侧固件已实现，**编译/链接门通过**；实机门（烧写/转发/透明性/重连/陈旧数据）待硬件
计划：`.agents/plan/ESP32_WIFI_BRIDGE_PLAN.md`

## 1. 系统角色与连接

```
STM32H723 (OfflineDevice)                      ESP32-WROOM-32 (OnlineDevice)       上位机
┌──────────────────────────────┐               ┌──────────────────────────────┐   ┌──────────┐
│ UART7  PE8 (TX) 921600-8N1   ├───3.3V───────►│ UART2 RX = GPIO16            │   │          │
│  只发数据行：CSV / ACT        │               │  (只收，GPIO17 TX 悬空)      │   │          │
│        PE7 (RX) 悬空（本期）  │               │                              │   │          │
│        GND ──────────────────┼────GND────────┤ GND                          │   │          │
│ USART10 PE3(TX)/PE2(RX)      ├──USB-TTL─────►│                              │   │          │
│   921600：日志行 + 数据行     │               │ UART0 GPIO1/3 = 烧写+日志台  │   │          │
└──────────────────────────────┘               │ SoftAP 192.168.4.1           │◄──┤ WiFi STA │
                                               │ TCP :3333 (单客户端)         │◄═►│ TCP 客户端│
                                               └──────────────────────────────┘   └──────────┘
```

- 软件分层：`app_main.cpp`（入口/顺序）→ `uart_link`（ESP32 UART2 只收）/ `wifi_softap`（AP）→ `tcp_bridge`（UART→TCP，唯一传输层实现）。
- STM32 侧**按类型分流**（`attitude.app.cppm`）：`sendLog`（`BMI088 init OK`、`TFLM arena used:`、失败提示等日志/控制行）只写 `debug_console`(USART10)；`sendData`（数据行）写 `debug_console` + `bridge_uart`(UART7)。因此**在线设备链路里只有数据行**，调试台保留数据行以便 PC 直连抓取（`model/tools/record.py`、`field_test.py` 依赖该口）。
- 只上行：本期 ESP32 不驱动 STM32，`GPIO17` 悬空、STM32 `PE7` 悬空。UART7 专用于在线设备，后续要加下行时把 `GPIO17` 接到 `PE7` 即可。

## 2. 接入契约（本期冻结）

| 项 | 值 |
|---|---|
| SSID / 密码 | `attitude-bridge` / `attitude123`（WPA2-PSK，信道 1，max_sta=1） |
| 服务地址 | TCP `192.168.4.1:3333`（`backlog=4`，同一时刻只服务 1 个连接） |
| 串口链路 | STM32 `UART7`(PE8→GPIO16) **921600-8N1**；ESP32 `UART2` RX-only |
| 链路内容 | **仅数据行**：采集模式 `t_us,ax,ay,az,gx,gy,gz`；推理模式 `ACT,WALK\|RUN\|FALL,p0,p1,p2,<ms>ms` |
| 调试串口 | STM32 `USART10`(PE3/PE2) **921600-8N1**，PC 的 USB-TTL：日志行 + 数据行（与桥无关，不进入 TCP 流） |
| 数据方向 | STM32 → ESP32 → 上位机，**字节透明**（不解析、不改写、不加时间戳/设备号） |
| 帧边界 | 沿用 STM32 行尾 `\r\n`；上行不重组、不补行 |
| 无客户端时 | UART 照读照丢；有客户端接入时先 `uart_flush_input()` 并丢弃到首个 `\n`（行对齐） |
| 断开判定 | `send` 失败（`SO_SNDTIMEO=5s`）即回收连接，回到 `accept` |
| 统计 | 每 10s 一行 `forward=<B> drop=<B> sessions=<n>` |

链路余量：采集模式 CSV 约 60 B @100 Hz = 6 kB/s，占 921600 的 ~6.5%，单行阻塞约 0.65 ms（10 ms 采样周期内）；数据行同时写调试台，总占用约 13%；推理模式每 0.5 s 一行可忽略。

## 3. 关键决策与理由

| 决策 | 理由 |
|---|---|
| 语言标准 **C++23**（`-std=gnu++23`），覆盖 IDF 默认 `gnu++26` | 显式固定标准；`target_compile_options(${COMPONENT_LIB} PRIVATE -std=gnu++23)` 写在 `idf_component_register` 之后，GCC 对重复 `-std` 取最后一个（官方写法见 IDF `docs/en/api-guides/cplusplus.rst`）。实测四支 TU 的 `__cplusplus == 202302L` |
| IDF 结构体一律 `T x{};` + 逐字段赋值，禁用 designated init | C++20/23 的 designated init 要求按声明顺序且禁止嵌套，与 C99 不同 |
| ESP32 侧 UART2(RX=GPIO16) 而非 UART1 | UART1 默认引脚 GPIO9/10 是 flash 引脚；WROOM-32 无 PSRAM，GPIO16/17 空闲 |
| ESP32 UART0 保留为控制台 | 烧写与日志共用，接 STM32 会与 esptool 复位时序冲突 |
| STM32 数据链用 **UART7** 而非原 USART1 | 调试台与数据链分离：USB-TTL 独占 USART10，UART7 点到点接 ESP32，互不干扰 |
| STM32 输出**按类型分流**（日志→调试台，数据→调试台+桥） | 契约要求桥侧"仅时间戳与判断"；分流点在 MCU 侧（知道行语义），ESP32 侧保持字节透明、不做任何解析。数据行仍留一份在调试台，避免破坏现有 PC 采集工具 |
| 两侧 921600 | 采集模式 100 Hz × 约 60 B 的阻塞发送需留在 10 ms 周期内；921600 下单行 0.65 ms，余量充足 |
| SoftAP 而非 STA | 现场无路由器也可以直连；上位机固定连 `192.168.4.1`，免配网环节 |
| `SINGLE_APP_LARGE` 分区表 + 4MB flash | 默认 `singleapp` 的 factory 仅 1M；large 给 1500K，实测占用约 788K（47% 空闲） |
| 连接建立即 `uart_flush_input()` + 丢弃到首个 `\n` | 无客户端期间缓冲里是陈旧数据；STM32 可能正发到半行，首条输出必须是完整行 |
| `TCP_NODELAY` | 行很小（约 60 B），Nagle 会引入无谓延迟 |
| 传输层与 UART 层解耦（4 个源文件） | 后续 BLE 只新增 `ble_bridge.cpp` 复用 `uartLinkRead/uartLinkFlush` 与同一 flush+resync 语义 |

## 4. 交付物与验证结果

ESP32：`OnlineDevice/{CMakeLists.txt, sdkconfig.defaults, .gitignore, docker-compose.yml}` + `main/{CMakeLists.txt, Kconfig.projbuild, app_main.cpp, uart_link.cpp, wifi_softap.cpp, tcp_bridge.cpp}` + `main/include/{bridge_config.hpp, uart_link.hpp, wifi_softap.hpp, tcp_bridge.hpp}`。

STM32（串口迁移与分流涉及）：`OfflineDevice/App/src/peripheral_registry.cpp`（`debug_console`→`huart10`、新增 `bridge_uart`→`huart7`）、`OfflineDevice/App/modules/attitude.app.cppm`（`sendLog`/`sendData` 分流）。CubeMX 侧（用户生成，未改）：`Core/Src/usart.c`、`Core/Inc/usart.h`、`Core/Src/stm32h7xx_it.c`。

| 门 | 命令 | 结果 |
|---|---|---|
| E1 ESP32 构建 | `docker compose run --rm esp-idf idf.py build` | ✅（2026-09-17）`Project build complete.`；`build/online_device.bin` 807,536 B，分区 1500K 空闲 47%。当前 `kUartBaud=921600` 与该次构建相同，未再重跑（见下） |
| E2 语言标准 | 解析 `build/compile_commands.json` + 预处理取 `__cplusplus` | ✅ 四个源文件均为 `... -std=gnu++26 -std=gnu++23`，`__cplusplus == 202302L` |
| E3 配置 | `grep -E "^CONFIG_(IDF_TARGET\|ESPTOOLPY_FLASHSIZE_4MB\|PARTITION_TABLE_SINGLE_APP_LARGE)=" sdkconfig` | ✅ `esp32` / `=y` / `=y` |
| S1 STM32 Debug 构建+链接 | `cmake -S . -B build-verify -G Ninja -DCMAKE_BUILD_TYPE=Debug -DCMAKE_TOOLCHAIN_FILE=cmake/gcc-arm-none-eabi.cmake && cmake --build build-verify` | ✅ `OfflineDevice.elf`：FLASH 48744 B (4.65%)、DTCMRAM 2600 B (1.98%) |
| S5 STM32 Release+TFLM 构建 | 同上，`-DCMAKE_BUILD_TYPE=Release -DATTITUDE_ENABLE_TFLM=ON`（`build-verify-tflm`） | ✅ 418 步全过：`libtflm.a` 1,769,876 B + `OfflineDevice.elf` 57,812 B（无 `model_data.cc`，按 CMakeLists 约定只出 tflm 静态库 + Mock 应用） |
| S2 绑定符号 | `arm-none-eabi-nm build-verify/OfflineDevice.elf \| grep huart` | ✅ `huart7`/`huart10` 均在，无 `huart1`；`UART7_IRQHandler`/`USART10_IRQHandler` 均存在 |
| S3 注册名一致性 | 比对 `attitude.app.cppm` 的 `Serial("…")` 与 `findHandle` 的注册串 | ✅ `bridge_uart`/`debug_console` 均有注册，缺失集合为空 |
| S4 分流静态检查 | `grep -n "sendLog\|sendData\|transmit" App/modules/attitude.app.cppm` | ✅ 日志行 5 处（`BMI088 init FAILED/OK`、`TFLM init FAILED`、`initInference` 的 arena 行）全走 `sendLog`；数据行（CSV 第 153 行、ACT 第 170 行）走 `sendData`；`bridge` 仅出现在 `sendData` 内；parity 命令的报文只走 `debug.transmit` |

验证环境说明（2026-09-18）：本机 GitHub 与 Docker Hub 不可达；`deps/*` 子模块由用户 `git submodule update` 提供（`emdevif@5a9c8b3`、`emdevif_stm32_peripheral@d09e463`）。起始时宿主 brew 版 `arm-none-eabi-gcc 16.2.0` 缺 newlib/libstdc++ 头文件，先用 Debian trixie 的 `gcc-arm-none-eabi 14.2.1`（解包到 `~/.cache`，未改系统与仓库）验证；随后用户安装了 **Arm GNU Toolchain 15.3.Rel1**（`~/local/arm-gnu-toolchain-x86_64-arm-none-eabi/current/bin`）与 ninja 1.13.2，最终一轮验证（S1/S5）改用它，无需任何环境注入。验证用构建目录为 `OfflineDevice/build-verify{,-tflm}`（gitignore 的 `build-*/` 已覆盖，可随时删除），未触碰用户自有 `OfflineDevice/build`。ESP32 侧未重跑 Docker 构建：docker 守护进程已停止且无免密 sudo，且 `kUartBaud` 已回到先前构建验证过的 921600。

未执行（需硬件 + STM32 在跑，命令与判据冻结在计划 Verification 节）：V3 烧写、V4 启动日志（断言串 `uart_link: UART2 RX=GPIO16 921600 8N1` / `wifi_ap: SoftAP ready ssid=attitude-bridge channel=1 max_sta=1 ip=192.168.4.1 port=3333` / `tcp_bridge: listening on port 3333 (backlog 4)`）、V5 端到端转发（CSV ≈1000±20 且无非数据行 / ACT ≈20 行）、V6 透明性保序子序列、V7 重连行对齐、V8 `uart_flush_input` 陈旧数据隔离。

## 5. 变更记录

**2026-09-18 — STM32 串口迁移与日志/数据分流（用户 CubeMX 重生成）**

| 项 | 迁移前 | 迁移后 |
|---|---|---|
| 调试台 | USART1 PA9(TX)/PA10(RX) 921600 | **USART10 PE3(TX)/PE2(RX) 921600**（PC 的 USB-TTL） |
| 在线设备链路 | 与调试台共用 USART1，ESP32 搭在 PA9 上 | **UART7 PE8(TX)/PE7(RX) 921600**（专口，接 ESP32 GPIO16） |
| 输出内容 | 单口输出全部行 | 分流：日志行→仅调试台；数据行→调试台 + 在线设备链路 |
| ESP32 侧 | `kUartBaud = 921600` | 先随默认值改为 115200，再随 UART7 定稿改回 **921600** |

同时修复一处既有回归：commit `15e91b0`（BMI088 引脚同步）误把 `findHandle` 中的 `if (name == "debug_console") return &debug_console_instance;` 替换为 imu_int1/imu_int3 两行，导致 `Serial debug("debug_console")` 解析不到实例——`emdevif` 的 `detail::PeripheralErrorHandler::checkInstanceIsExist` 对空句柄会走 `EMDEVIF_FATAL_HANDLER`（非常量求值时），即实机上会直接 fatal。本次恢复该行并新增 `bridge_uart`，并用 S3 一致性检查（`Serial(...)` 名字 ⊆ `findHandle` 注册名）覆盖这一类回归。
