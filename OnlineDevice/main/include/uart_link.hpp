//! UART2 只收链路：从 STM32 的 UART7 数据链（921600-8N1）读取字节流。
#pragma once

#include <cstddef>
#include <cstdint>

#include "esp_err.h"

/// 配置 UART2（RX=GPIO16，921600-8N1）并安装驱动。ESP_OK 时链路可用。
esp_err_t uartLinkInit();

/// 读取至多 cap 字节；返回实际字节数，超时返回 0，错误返回 -1。
int uartLinkRead(uint8_t* dst, std::size_t cap, int timeout_ms);

/// 丢弃驱动 RX 缓冲中的积压数据（新客户端接入时做陈旧数据隔离）。
void uartLinkFlush();
