# OnlineDevice：ESP32 串口→WiFi 数据桥（SoftAP + TCP）

## Context

系统由两块板组成：`OfflineDevice`（STM32H723，BMI088+TFLM 姿态识别，数据链 **UART7 PE8(TX)/PE7(RX) @ 921600-8N1**，**只发数据行**：`t_us,ax,ay,az,gx,gy,gz`（采集模式）或判断行 `ACT,WALK|RUN|FALL,p0,p1,p2,<ms>ms`；调试台 **USART10 PE2(RX)/PE3(TX) @ 921600-8N1** 接 PC 的 USB-TTL，记日志 + 数据行）与本次要做的**在线设备**（ESP32-WROOM-32）。在线设备从 UART7 数据链**只读**接入数据，原样（字节透明）通过 WiFi 转发给上位机；STM32 侧固件不改动。

本期交付：ESP32 固件（ESP-IDF v6.1，docker 内构建/烧写）+ 可复现的端到端验证。**上位机程序是后续计划**，本期只冻结接入契约：`SoftAP(ssid=attitude-bridge/pass=attitude123) → TCP 192.168.4.1:3333 → 纯文本、字节透明、行尾 \r\n`。蓝牙（BLE/SPP）也是后续计划，见 S6 的传输层隔离方式。不做下行：本期只做上行，UART7 的 RX(PE7) 悬空（该口已专用于在线设备，不再与 PC 的 USB-TTL 争用；要加下行时直接接 PE7 即可，见 Assumption 6）。

关键既有事实（本次已核实）：`.ioc` 中 `USART10.BaudRate=921600`（`PE2=USART10_RX`、`PE3=USART10_TX`，PC 调试台）与 `UART7.BaudRate=921600`（`PE7=UART7_RX`、`PE8=UART7_TX`，接在线设备），两者由 `OfflineDevice/Core/Src/usart.c` 实际配置；`attitude.app.cppm` 的输出**按类型分流**——日志/控制/错误行（`BMI088 init OK`、`TFLM arena used:`、失败提示）只走 `debug_console`(USART10)，数据行（CSV 原始流或 ACT 判断行）走 `debug_console` + `bridge_uart`(UART7)，因此在线设备链路里**只有数据行**；本机已有镜像 `espressif/idf:release-v6.1`（IDF v6.1.0，工具链 xtensa-esp-elf-g++ 15.2.0，**默认 `-std=gnu++26`，本工程用 `-std=gnu++23` 覆盖（见 S2）**，容器内 `python3` 自带 pyserial+esptool）。Docker Hub 当前不可达，**不要 `docker compose pull`**，直接用本地镜像。

## Approach

设计要点（一次定死，后续步骤不再选择）：语言标准固定 **C++23**（`-std=gnu++23`，见 S2，不用 IDF 默认的 gnu++26）；ESP32 侧 **UART0(GPIO1/3) 保留为烧写+日志控制台**，STM32 链路走 **UART2 RX=GPIO16 ← STM32 UART7_TX(PE8) @921600**（WROOM-32 无 PSRAM，GPIO16/17 空闲；UART1 默认 GPIO9/10 是 flash 引脚不可用）；共 4 个源文件（`app_main` / `uart_link` / `wifi_softap` / `tcp_bridge`），**单客户端**服务（`backlog=4`，同一时刻只服务一个连接，断开后 accept 下一个）；**字节透明**不做解析、不加时间戳/设备号；新客户端接入时 `uart_flush_input()` + 丢弃到首个 `\n` 做行对齐；无客户端时 UART 照读照丢（不缓存陈旧数据）。所有 IDF 结构体**禁止使用 C++ 指定初始化器**——C++20/23 的 designated init 与 C99 不同，要求按声明顺序、禁止嵌套；一律 `T cfg{};` + 逐字段赋值（本文 S6 中少量以 `sockaddr_in{...}` 形式书写的字段，落地同样逐字段赋值）。

### S1 — docker-compose 增加串口设备（烧写前提）

`OnlineDevice/docker-compose.yml`：保持 `services.esp-idf` 现有 `image/container_name/user/working_dir/volumes/environment/tty/stdin_open` 不变，仅做两处增补：

```yaml
    volumes:
      - .:/project
      - /dev:/dev          # 直通宿主机串口节点（ttyUSB0/ttyACM0 枚举变化都不用改本文件）
    group_add:
      - dialout            # 镜像内 dialout=gid 20（已核实），容器默认无附加组
```

`/dev` 整体挂载（而非 `devices:` 显式映射）是刻意的：设备未插或枚举成 `ttyACM0/ttyUSB1` 时 `docker compose run` 仍能启动，纯构建流程不被阻塞。

### S2 — IDF 工程骨架

`OnlineDevice/CMakeLists.txt`（顺序照 IDF v6 示例，不可调换）：

```cmake
cmake_minimum_required(VERSION 3.22)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
idf_build_set_property(MINIMAL_BUILD ON)
project(online_device)
```

`OnlineDevice/sdkconfig.defaults`（不提交 `sdkconfig`）：

```
CONFIG_IDF_TARGET="esp32"
CONFIG_ESPTOOLPY_FLASHSIZE_4MB=y
CONFIG_PARTITION_TABLE_SINGLE_APP_LARGE=y
```

理由（已核实镜像内默认值）：ESP32 目标默认 flash 2MB、`partitions_singleapp.csv` 的 factory 仅 **1M**，WiFi+lwIP 应用接近该上限；WROOM-32 标配 4MB，内置 `partitions_singleapp_large.csv` 给 factory **1500K**，够用且无需自定义分区表。

`OnlineDevice/.gitignore`：`build/`、`sdkconfig`、`sdkconfig.old`。

`OnlineDevice/main/CMakeLists.txt`（显式列源文件，仓库规范禁止 `GLOB`）：

```cmake
idf_component_register(
    SRCS "app_main.cpp" "uart_link.cpp" "wifi_softap.cpp" "tcp_bridge.cpp"
    INCLUDE_DIRS "include"
    PRIV_REQUIRES esp_wifi esp_netif nvs_flash esp_driver_uart esp_event lwip
)

# IDF 默认把 -std=gnu++26 追加进 CXX_COMPILE_OPTIONS（tools/cmake/build.cmake:208），
# 本工程固定 C++23：必须写在 idf_component_register 之后——只有此时 ${COMPONENT_LIB} 上的
# 目标级选项才排在本行之前；GCC 对重复的 -std 取最后一个。官方写法见
# docs/en/api-guides/cplusplus.rst（"C++ Language Standard"）。
target_compile_options(${COMPONENT_LIB} PRIVATE -std=gnu++23)
```

**改动说明（相对初版）**：初版沿用 IDF 默认的 `-std=gnu++26`；本期改为 C++23。风险对照：C++23 下 `std::expected`/`std::mdspan` 等可用性不变但本工程未用；唯一实际影响是同一份源码不再依赖 GCC 的 C++26 扩展，`-Werror -Wextra` 门槛不变。

### S3 — 参数源：`main/Kconfig.projbuild` + `main/include/bridge_config.hpp`

`main/Kconfig.projbuild`（menuconfig 可改，默认值即交付值）：

```
menu "Online device bridge"
    config BRIDGE_AP_SSID
        string "SoftAP SSID"
        default "attitude-bridge"
    config BRIDGE_AP_PASSWORD
        string "SoftAP password (8-63 chars; shorter => open AP)"
        default "attitude123"
    config BRIDGE_AP_CHANNEL
        int "SoftAP channel"
        range 1 13
        default 1
    config BRIDGE_AP_MAX_STA
        int "Max stations on SoftAP"
        range 1 4
        default 1
    config BRIDGE_TCP_PORT
        int "TCP server port"
        range 1024 65535
        default 3333
endmenu
```

`main/include/bridge_config.hpp`：仅放 Kconfig 不表达的编译期常量（`inline constexpr`，中文注释，风格对齐 `OfflineDevice/App/modules/attitude.config.cppm`）：

```cpp
namespace bridge {
inline constexpr uart_port_t kUartPort     = UART_NUM_2;
inline constexpr int         kUartRxPin    = 16;      // GPIO16 ← STM32 PE8(UART7_TX)；UART7 专用于与在线设备通信
inline constexpr int         kUartBaud     = 921600;  // 与 OfflineDevice UART7 一致
inline constexpr int         kUartRxBytes  = 8192;    // 驱动 RX 环形缓冲，吸收 WiFi 抖动
inline constexpr std::size_t kChunkBytes   = 1024;    // 单次读取/发送上限（文件静态缓冲，不占任务栈）
inline constexpr int         kReadTimeoutMs = 1000;
inline constexpr int         kSendTimeoutMs = 5000;
inline constexpr int64_t     kStatsPeriodUs = 10'000'000;
inline constexpr UBaseType_t kBridgeTaskPrio  = 5;
inline constexpr uint32_t    kBridgeTaskStack = 4096;
}  // namespace bridge
```

### S4 — `main/uart_link.cpp` + `main/include/uart_link.hpp`（UART2 只收）

接口（`uart_link.hpp`，`extern "C"` 不需要，纯 C++ 同工程内调用）：

```cpp
esp_err_t uartLinkInit();                                                   // 配置 UART2 921600-8N1 + 装驱动
int       uartLinkRead(uint8_t* dst, std::size_t cap, int timeout_ms);       // 超时返回 0，错误返回 -1
void      uartLinkFlush();                                                   // 丢弃驱动缓冲积压
```

`uart_link.cpp` 实现要点，顺序不可调换：`uart_param_config(kUartPort, &cfg)` → `uart_set_pin(kUartPort, UART_PIN_NO_CHANGE, kUartRxPin, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE)` → `uart_driver_install(kUartPort, kUartRxBytes, 0, 0, nullptr, 0)`。`uart_config_t cfg{}` 逐字段赋值：`baud_rate=kUartBaud`、`data_bits=UART_DATA_8_BITS`、`parity=UART_PARITY_DISABLE`、`stop_bits=UART_STOP_BITS_1`、`flow_ctrl=UART_HW_FLOWCTRL_DISABLE`、`source_clk=UART_SCLK_DEFAULT`。`uartLinkRead` 直接转 `uart_read_bytes`；`uartLinkFlush` 转 `uart_flush_input`。每步用 `ESP_RETURN_ON_ERROR(..., "uart_link", "...")` 返回错误，由 `app_main` 用 `ESP_ERROR_CHECK` 兜住。成功时日志一行（tag=`uart_link`）：`UART2 RX=GPIO16 921600 8N1`。

无需 TX 引脚：本期只做上行，STM32 的 UART7_RX(PE7) 悬空。

**链路余量（两侧 UART7 均 921600）**：STM32 用阻塞发送，`kStreamRaw` 采集模式下 CSV 行约 60 B @100Hz = 6 kB/s，占 921600 的 6.5%、单行阻塞约 0.65 ms（10 ms 采样周期内）；推理模式每 0.5 s 一行、可忽略。数据行还会额外写一遍调试台（同速同长），总占用约 13%。**分流后桥侧不再有日志行**（见下）。

**分流语义（STM32 侧）**：`sendLog`（`BMI088 init OK`、`TFLM init FAILED`、`TFLM arena used:`）只写 `debug_console`；`sendData`（CSV / ACT 行）写 `debug_console` + `bridge_uart`。调试台保留数据行是刻意的：`model/tools/record.py`、`field_test.py` 依赖 USB-TTL 直连该口采集数据。

### S5 — `main/wifi_softap.cpp` + `main/include/wifi_softap.hpp`（SoftAP）

```cpp
esp_err_t wifiSoftApStart();   // 返回时 AP 已启动，IP=192.168.4.1
```

调用顺序：`esp_netif_init()` → `esp_event_loop_create_default()` → `esp_netif_create_default_wifi_ap()`（返回 nullptr 则 `ESP_FAIL`）→ `wifi_init_config_t init{}; init = WIFI_INIT_CONFIG_DEFAULT(); esp_wifi_init(&init)` → `esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID, onWifiEvent, nullptr, nullptr)` → 填 `wifi_config_t ap{}` → `esp_wifi_set_mode(WIFI_MODE_AP)` → `esp_wifi_set_config(WIFI_IF_AP, &ap)` → `esp_wifi_start()`。

`ap` 字段逐项赋值（禁止指定初始化器）：`std::strncpy(reinterpret_cast<char*>(ap.ap.ssid), CONFIG_BRIDGE_AP_SSID, sizeof(ap.ap.ssid));`、`ap.ap.ssid_len = std::strlen(CONFIG_BRIDGE_AP_SSID)`（>32 时警告并截断到 32）、`ap.ap.password` 同法拷贝 `CONFIG_BRIDGE_AP_PASSWORD`、`ap.ap.channel = static_cast<uint8_t>(CONFIG_BRIDGE_AP_CHANNEL)`、`ap.ap.max_connection = static_cast<uint8_t>(CONFIG_BRIDGE_AP_MAX_STA)`、`ap.ap.authmode = WIFI_AUTH_WPA2_PSK`（Windows/安卓兼容性最好，不用 WPA3/SAE）、`ap.ap.pmf_cfg.required = false`。密码长度 <8 时置 `WIFI_AUTH_OPEN` 并 `ESP_LOGW`。

事件回调 `onWifiEvent(void*, esp_event_base_t, int32_t id, void* data)`：`WIFI_EVENT_AP_STACONNECTED` → `ESP_LOGI("wifi_ap", "station " MACSTR " join aid=%d", MAC2STR(ev->mac), ev->aid)`；`WIFI_EVENT_AP_STADISCONNECTED` → `ESP_LOGW(..., "station " MACSTR " leave aid=%d reason=%d", ...)`；其它事件忽略。

启动完成后 `esp_netif_get_ip_info(ap_netif, &ip)` → `esp_ip4addr_ntoa` 并打印（tag `wifi_ap`，此行是验证断言的目标字符串）：

```
I (xxx) wifi_ap: SoftAP ready ssid=attitude-bridge channel=1 max_sta=1 ip=192.168.4.1 port=3333
```

（`port` 取自 `CONFIG_BRIDGE_TCP_PORT`，不来自 netif。）

### S6 — `main/tcp_bridge.cpp` + `main/include/tcp_bridge.hpp`（桥接核心）

```cpp
void tcpBridgeStart();   // 创建任务后立即返回
```

文件静态：`static uint8_t s_chunk[bridge::kChunkBytes];`、`static constexpr char kTag[] = "tcp_bridge";`、`struct Stats { uint64_t forward_bytes; uint64_t drop_bytes; uint32_t sessions; };`

`static int listenSocketCreate()`：`socket(AF_INET, SOCK_STREAM, IPPROTO_TCP)`；成功则 `setsockopt(SO_REUSEADDR)`、`bind` 到 `sockaddr_in`（逐字段赋值：`sin_family=AF_INET`、`sin_addr.s_addr=htonl(INADDR_ANY)`、`sin_port=htons(CONFIG_BRIDGE_TCP_PORT)`）、`listen(fd, 4)`；任一步失败 → `close(fd)` + `ESP_LOGW` + `vTaskDelay(pdMS_TO_TICKS(1000))` 重试（永不返回 -1）。成功后打印 `listening on port %d (backlog 4)`。

`static bool sendAll(int fd, const uint8_t* data, size_t len)`：循环 `send(fd, data+off, len-off, 0)`，`n <= 0` → `ESP_LOGW("send failed errno=%d", errno)` 并返回 false；否则累加 `off`。

`static void serveClient(int fd, Stats& st)`：
1. `TCP_NODELAY=1`（避免 Nagle 延迟，行很小）、`SO_KEEPALIVE=1`、`SO_SNDTIMEO = {kSendTimeoutMs/1000, 0}`。
2. `uartLinkFlush()` 丢弃无客户端期间在驱动缓冲里积压的陈旧数据。
3. `bool resync = true;` 主循环：`n = uartLinkRead(s_chunk, sizeof(s_chunk), kReadTimeoutMs)`；`n <= 0` → `continue`（超时属正常，客户端断开由 send 失败暴露）。
4. `resync` 为真时：`memchr(p, '\n', len)`；找不到 → `st.drop_bytes += len; continue;`；找到 → `st.drop_bytes += (nl + 1 - p)`，`p = nl + 1`，剩余 `len` 相应缩减，`resync = false`，若 `len == 0` 则 `continue`。**目的**：新连接的第一条输出必须是完整行（STM32 可能正发到半行）。
5. `sendAll(fd, p, len)` 失败 → `return`（客户端判定断开，回 accept）；成功 `st.forward_bytes += len`。
6. 每 `kStatsPeriodUs` 打一行 `ESP_LOGI(kTag, "forward=%llu B drop=%llu B sessions=%u", ...)`（`esp_timer_get_time()` 计时）。

`static void bridgeTask(void*)`：`const int listen_fd = listenSocketCreate();` 后 `for (;;)` 循环 `accept()`：失败 → `ESP_LOGW("accept errno=%d", errno)` + 1s 退避；成功 → `inet_ntoa_r(peer.sin_addr, addr, sizeof addr)` 打印 `client %s:%u connected`，`++st.sessions`，`serveClient(fd, st)`，随后 `shutdown(fd, SHUT_RDWR); close(fd);` 并打印 `client closed; sessions=%u forward=%llu B drop=%llu B`。

`tcpBridgeStart()`：`xTaskCreate(bridgeTask, "tcp_bridge", kBridgeTaskStack, nullptr, kBridgeTaskPrio, nullptr)`，失败则 `ESP_LOGE` + `abort()`。

该文件是唯一传输层实现：后续 BLE 只新增 `ble_bridge.cpp` 复用 `uartLinkRead/uartLinkFlush` 与同一 flush+resync 语义，本文件不动。

### S7 — `main/app_main.cpp`

```cpp
extern "C" void app_main(void)   // IDF 要求 C 链接
{
    esp_err_t ret = nvs_flash_init();                       // WiFi 标定数据落 NVS
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);
    ESP_ERROR_CHECK(uartLinkInit());
    ESP_ERROR_CHECK(wifiSoftApStart());
    tcpBridgeStart();
    ESP_LOGI("app_main", "bridge running (IDF %s)", esp_get_idf_version());
}
```

顺序固定：先 UART（保证 AP 起来前不丢配置错误），再 WiFi（TCP 依赖 lwIP/事件循环已初始化），最后起任务。

### S8 — 仓库规范交付物（AGENTS.md 要求）

- 计划即本文件 `.agents/plan/ESP32_WIFI_BRIDGE_PLAN.md`（初版沿用此名，不再另存副本）。
- 新建设计文档 `.agents/docs/2026-09-17-online-device-wifi-bridge.md`，含：① 系统角色与串口/WiFi 连接图（STM32 UART7 PE8→GPIO16；调试台 USART10、ESP32 控制台 UART0）；② 接入契约（SSID/密码/192.168.4.1:3333/字节透明/单客户端/无客户端丢弃）；③ 关键决策与理由（UART2 而非 UART1、只上行、SoftAP 而非 STA、flush+resync、large 分区表、C++23 覆盖 gnu++26、flush 防陈旧）；④ 验证结果与实测数据（V1–V8 原始输出摘要）。

## Critical files & anchors

- `OnlineDevice/docker-compose.yml` — S1 增补 `/dev` 挂载与 `group_add`；无设备直通则无法烧写
- `OnlineDevice/main/CMakeLists.txt` — C++23 覆盖点（`target_compile_options` 必须在 `idf_component_register` 之后）
- `OnlineDevice/main/tcp_bridge.cpp` — 桥接核心：accept 单客户端、flush+resync、sendAll 超时判死
- `OnlineDevice/main/uart_link.cpp` — UART2 RX-only 921600 配置；参数顺序（param_config→set_pin→driver_install）
- `OnlineDevice/main/wifi_softap.cpp` — SoftAP + 事件日志；`SoftAP ready ... ip=192.168.4.1 port=3333` 是验证断言串
- `OfflineDevice/App/modules/attitude.app.cppm` — STM32 侧分流点：`sendLog`（只走调试台）/ `sendData`（调试台 + 在线设备链路）
- `OfflineDevice/App/src/peripheral_registry.cpp` — `debug_console`→`huart10`、`bridge_uart`→`huart7`；注册名缺失会让 `Serial(...)` 走 `EMDEVIF_FATAL_HANDLER`
- 只读参照：`OfflineDevice/OfflineDevice.ioc`（`USART10.BaudRate=921600` + PE2/PE3 调试台；`UART7.BaudRate=921600` + PE7/PE8 数据链）、`OfflineDevice/Core/Src/usart.c`（两个句柄的实测波特率）

## Verification

**执行状态**：2026-09-17 ESP32 未接入本机 → 本期只跑 **V1 构建门 + V1b 标准门 + V2 配置门**（已通过）。2026-09-18 变更：STM32 串口迁移（调试台 USART1→USART10、新增 UART7 数据链）→ 两侧 UART7/UART2 定 921600，STM32 输出按日志/数据分流。STM32 侧 Debug 构建+链接已通过；ESP32 侧 `kUartBaud` 最终回到已构建验证过的 921600，但本机 docker 守护进程已停止且无免密 sudo，**未再重跑 V1**。V3–V8 需硬件与 STM32，留待实机。详见 `.agents/docs/2026-09-17-online-device-wifi-bridge.md`。

前置：ESP32 开发板 USB 接 PC（控制台枚举为 `/dev/ttyUSB0`，先 `read /dev` 或 `ls /dev/ttyUSB*` 确认真实路径；**镜像已在本机，不要 pull**）；STM32 `PE8(UART7_TX)` → ESP32 `GPIO16`，两板 `GND` 互连（3.3V 直连，无需电平转换）；PC 的 USB-TTL 接 STM32 `PE3(USART10_TX)`/`PE2` 作调试台（921600，日志 + 数据行）；若要做 V6 对照，再把该 USB-TTL 的 RX 并在 `PE8` 上（监听原始数据流，921600）。所有命令在 `OnlineDevice/` 下执行。

**V1 构建门（无硬件）**：`docker compose run --rm esp-idf idf.py build` → 期望输出 `Project build complete.`，且存在 `build/online_device.bin`。若报找不到组件头（`MINIMAL_BUILD` 裁剪过度），删除 `OnlineDevice/CMakeLists.txt` 里的 `idf_build_set_property(MINIMAL_BUILD ON)` 行，`rm -rf build` 后重跑。

**V1b 语言标准门（无硬件）**：`grep -o '\-std=gnu++[0-9]*' build/compile_commands.json | sort -u` → 期望仅 `-std=gnu++23`（C 源文件为 `-std=gnu23`）。

**V2 配置门**：`grep -E "^CONFIG_(IDF_TARGET|ESPTOOLPY_FLASHSIZE_4MB|PARTITION_TABLE_SINGLE_APP_LARGE)" sdkconfig` → 期望 `CONFIG_IDF_TARGET="esp32"`、后两行为 `=y`。

**V3 烧写门**：`docker compose run --rm esp-idf idf.py -p /dev/ttyUSB0 flash` → 期望 `Hash of data verified.` 与 `Hard resetting via RTS pin...`。若 `Permission denied`，先 `docker compose run --rm esp-idf sh -c 'id; ls -l /dev/ttyUSB0'`：节点 gid 不是 20 时把 compose 的 `group_add` 改为实际 gid。

**V4 启动门（串口控制台，含复位后 10s 日志）**：容器内 pyserial 抓取（RTS 拉低复位，确保抓到开机日志）：

```bash
docker compose run --rm esp-idf sh -c 'cat > /tmp/console.py <<"PY"
import serial, sys, time
port, secs = sys.argv[1], float(sys.argv[2])
s = serial.Serial(); s.port = port; s.baudrate = 115200; s.timeout = 1
s.dtr = False; s.rts = False; s.open()
s.setDTR(False); s.setRTS(True); time.sleep(0.1); s.setRTS(False)
end = time.time() + secs
while time.time() < end:
    line = s.readline().decode("utf-8", "replace").rstrip()
    if line: print(line)
PY
python3 /tmp/console.py /dev/ttyUSB0 10'
```

期望按序出现：`I (xxx) uart_link: UART2 RX=GPIO16 921600 8N1`、`I (xxx) wifi_ap: SoftAP ready ssid=attitude-bridge channel=1 max_sta=1 ip=192.168.4.1 port=3333`、`I (xxx) tcp_bridge: listening on port 3333 (backlog 4)`、`I (xxx) app_main: bridge running (IDF v6.1`。（复位触发两次时以最后一次为准。）

**V5 端到端转发门（需 STM32 在跑）**：PC 先连 WiFi `attitude-bridge` / `attitude123`（Windows 提示“无 Internet”时选“仍然连接”），然后抓 10s：

```bash
python3 - <<'PY'
import socket, sys, time, re
HOST, PORT, SECS, OUT = "192.168.4.1", 3333, 10.0, "/tmp/tcp_capture.bin"
csv_re = re.compile(rb"^\d+,-?\d+,-?\d+,-?\d+,-?\d+,-?\d+,-?\d+$")
act_re = re.compile(rb"^ACT,(WALK|RUN|FALL),\d+\.\d{3},\d+\.\d{3},\d+\.\d{3},\d+\.\dms$")
s = socket.create_connection((HOST, PORT), timeout=5)
end, buf = time.time() + SECS, bytearray()
while time.time() < end:
    d = s.recv(4096)
    if not d: break
    buf += d
open(OUT, "wb").write(buf)
lines = [l for l in bytes(buf).split(b"\r\n") if l]
csv_n = sum(1 for l in lines if csv_re.match(l))
act_n = sum(1 for l in lines if act_re.match(l))
print(f"total={len(lines)} csv={csv_n} act={act_n} first={lines[:3]}")
print("CSV 门限(≈1000±2%):", "PASS" if abs(csv_n-1000) <= 20 else "FAIL/未在采集模式")
print("ACT 门限(≈20):", "PASS" if 16 <= act_n <= 24 else "FAIL/未在推理模式")
PY
```

判据：STM32 处于采集模式（`kStreamRaw=true`）时 `csv` 行数 ≈ 1000±20（100Hz×10s）**且 `total - csv_n <= 1`**（分流后桥侧只有数据行；仅末尾被截断的半行允许 1 行差额，出现 `BMI088 init OK`/`TFLM arena used:` 之类的行即为 FAIL）；推理模式时 `act` 行数 ≈ 20（0.5s 一行）且同样 `total - act_n <= 1`。同时 ESP32 控制台应打印 `client 192.168.4.2:5xxxx connected`。

**V6 透明性对照门（需 USB-TTL 直连）**：同时抓直连流与 TCP 流（直连先起，避免漏头；两条命令两个终端）：

```bash
docker compose run --rm esp-idf sh -c 'cat > /tmp/direct.py <<"PY"
import serial, sys, time
port, secs, out = sys.argv[1], float(sys.argv[2]), sys.argv[3]
s = serial.Serial(port, 921600, timeout=1)   # 直连抓的是 UART7(PE8) 原始流
end = time.time() + secs
with open(out, "wb") as f:
    while time.time() < end:
        d = s.read(4096)
        if d: f.write(d)
PY
python3 /tmp/direct.py /dev/ttyUSB1 15 /tmp/direct.bin'
```

（TCP 侧用 V5 的脚本抓同时段到 `/tmp/tcp_capture.bin`。）然后比对——TCP 流去掉首尾半行后必须是直连流的**保序子序列**：

```bash
python3 - <<'PY'
direct = open("/tmp/direct.bin","rb").read().split(b"\r\n")
tcp    = open("/tmp/tcp_capture.bin","rb").read().split(b"\r\n")
tcp_lines, i, ok = tcp[1:-1], 0, 0          # 首尾可能半行，丢弃
for line in tcp_lines:
    while i < len(direct) and direct[i] != line: i += 1
    if i == len(direct): break
    ok += 1; i += 1
print(f"matched {ok}/{len(tcp_lines)}", "PASS" if ok == len(tcp_lines) and ok > 0 else "FAIL")
PY
```

判据：`matched == len(tcp_lines)`（不丢行、不乱序、内容逐字节一致）。

**V7 重连门**：V5 抓取结束后立刻重跑一次 → 期望首行即完整行（首个 `\r\n` 之前的内容匹配 `csv_re`/`act_re`，无半行拼接），ESP32 控制台按序出现 `client closed; sessions=...` 与新的 `connected`；`drop_bytes` 允许 >0（连接瞬间的半行丢弃），但 `forward` 计数应持续增长。

**V8 陈旧数据门（验证 `uart_flush_input` 语义）**：先只跑直连抓取 30s 到 `/tmp/direct.bin`（期间**不**连 TCP），随即抓 TCP 5s。判据：TCP 首条 CSV 行的 `t_us` 与直连文件最后一条 CSV 行的 `t_us` 之差 < 1_000_000 µs（即转发的是当前数据，不是 30s 前的积压）：

```bash
python3 - <<'PY'
import re
rx = re.compile(rb"^(\d+),")
d = [int(m.group(1)) for m in (rx.match(l) for l in open("/tmp/direct.bin","rb").read().split(b"\r\n")) if m]
t = [int(m.group(1)) for m in (rx.match(l) for l in open("/tmp/tcp_capture.bin","rb").read().split(b"\r\n")) if m]
delta = t[0] - d[-1]
print(f"tcp_first={t[0]} direct_last={d[-1]} delta={delta}us", "PASS" if abs(delta) < 1_000_000 else "FAIL")
PY
```

## Assumptions & contingencies

1. 模块为 ESP32-WROOM-32（4MB flash）。若实物是 8MB/16MB：`sdkconfig.defaults` 改 `CONFIG_ESPTOOLPY_FLASHSIZE_8MB=y`（或 `16MB`），分区表仍用 `SINGLE_APP_LARGE`。
2. 串口枚举为 `/dev/ttyUSB0`（CP2102/CH340 开发板）。若为 `ttyUSB1`/`ttyACM0`：/dev 是整体挂载，只需把命令里的路径换成实际值，compose 不动。
3. `espressif/idf:release-v6.1` 已在本机（已核实 11.1GB）。Docker Hub 当前不可达：**禁止** `docker compose pull`；如镜像意外缺失则先解决网络或从别处 `docker load`，不要改 tag。
4. STM32 侧引脚/波特率取自 `.ioc` 与 `usart.c`（数据链 UART7：`PE8`=TX、`PE7`=RX、**921600**；调试台 USART10：`PE3`=TX、`PE2`=RX、921600）；若用户后续改了 CubeMX 引脚或波特率，只改接线与 `bridge_config.hpp` 的 `kUartRxPin`/`kUartBaud`，ESP32 固件逻辑不变。
5. UART0(GPIO1/3) 归烧写与日志控制台，不接 STM32；ESP32 日志与控制台共用该口，V4 抓取时若串口被其他程序占用（如已打开的串口助手）会读不到，先关闭占用程序。
6. UART2 的 TX(GPIO17) 悬空不接：本期只做上行。UART7 已**专用于**与在线设备通信（PE7 不再被 PC 的 USB-TTL 驱动），后续要加下行时把 ESP32 GPIO17 接到 PE7 即可，CubeMX 无需改动。
7. STM32 处于 `kStreamRaw` 哪种模式由 OfflineDevice 侧决定；V5/V6/V8 的 CSV 类判据需要采集模式，若只有推理模式，用 ACT 判据并相应降低行数门限（V6/V8 的逐行比对照常适用）。
