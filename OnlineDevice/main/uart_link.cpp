//! UART2 只收链路实现。ESP32 不驱动 STM32（PE7 悬空，本期只做上行），故无 TX 引脚。

#include "uart_link.hpp"

#include "esp_check.h"
#include "esp_log.h"

#include "driver/uart.h"
#include "freertos/FreeRTOS.h"

#include "bridge_config.hpp"

namespace {
constexpr char kTag[] = "uart_link";
}  // namespace

esp_err_t uartLinkInit()
{
    uart_config_t cfg{};
    cfg.baud_rate  = bridge::kUartBaud;
    cfg.data_bits  = UART_DATA_8_BITS;
    cfg.parity     = UART_PARITY_DISABLE;
    cfg.stop_bits  = UART_STOP_BITS_1;
    cfg.flow_ctrl  = UART_HW_FLOWCTRL_DISABLE;
    cfg.source_clk = UART_SCLK_DEFAULT;

    ESP_RETURN_ON_ERROR(uart_param_config(bridge::kUartPort, &cfg), kTag, "uart_param_config failed");
    ESP_RETURN_ON_ERROR(
        uart_set_pin(bridge::kUartPort, UART_PIN_NO_CHANGE, bridge::kUartRxPin, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE),
        kTag, "uart_set_pin failed");
    ESP_RETURN_ON_ERROR(uart_driver_install(bridge::kUartPort, bridge::kUartRxBytes, 0, 0, nullptr, 0), kTag,
                        "uart_driver_install failed");

    ESP_LOGI(kTag, "UART%d RX=GPIO%d %d 8N1", static_cast<int>(bridge::kUartPort), bridge::kUartRxPin, bridge::kUartBaud);
    return ESP_OK;
}

int uartLinkRead(uint8_t* dst, std::size_t cap, int timeout_ms)
{
    return uart_read_bytes(bridge::kUartPort, dst, static_cast<uint32_t>(cap), pdMS_TO_TICKS(timeout_ms));
}

void uartLinkFlush()
{
    uart_flush_input(bridge::kUartPort);
}
