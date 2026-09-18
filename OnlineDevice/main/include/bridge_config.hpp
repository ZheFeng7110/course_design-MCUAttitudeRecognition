//! 在线设备（ESP32 串口→WiFi 桥）——编译期常量参数源
//!
//! 仅放 Kconfig 不表达的常量；AP SSID/密码/信道/端口等可调项见 main/Kconfig.projbuild。
#pragma once

#include <cstddef>
#include <cstdint>

#include "freertos/FreeRTOS.h"

#include "driver/uart.h"

namespace bridge {

// ---- STM32 接入链路（只收）----
inline constexpr uart_port_t kUartPort  = UART_NUM_2;  // UART0 留给烧写+日志控制台，UART1 默认引脚占 flash
inline constexpr int         kUartRxPin = 16;          // GPIO16 ← STM32 PE8(UART7_TX)；UART7 专用于与在线设备通信
inline constexpr int         kUartBaud  = 921600;      // 与 OfflineDevice UART7 一致（见 OfflineDevice/Core/Src/usart.c）

// ---- 缓冲与超时 ----
inline constexpr int         kUartRxBytes   = 8192;       // 驱动 RX 环形缓冲，吸收 WiFi 抖动
inline constexpr std::size_t kChunkBytes    = 1024;       // 单次读取/发送上限（文件静态缓冲，不占任务栈）
inline constexpr int         kReadTimeoutMs = 1000;       // uart_read_bytes 等待上限，超时按无数据处理
inline constexpr int         kSendTimeoutMs = 5000;       // SO_SNDTIMEO：超时即判定客户端断开

// ---- 运行参数 ----
inline constexpr int64_t     kStatsPeriodUs   = 10'000'000;  // 10s 打印一次统计
inline constexpr UBaseType_t kBridgeTaskPrio  = 5;
inline constexpr uint32_t    kBridgeTaskStack = 4096;

}  // namespace bridge
