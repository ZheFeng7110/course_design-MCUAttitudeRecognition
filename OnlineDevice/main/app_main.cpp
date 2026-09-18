//! 在线设备入口：UART 链路 → SoftAP → TCP 桥。
//!
//! 顺序固定：先 UART（AP 起来前不掩盖配置错误），再 WiFi（TCP 依赖 lwIP 与默认事件循环），
//! 最后起桥接任务。

#include <cstdint>

#include "esp_err.h"
#include "esp_log.h"
#include "esp_system.h"
#include "nvs_flash.h"

#include "tcp_bridge.hpp"
#include "uart_link.hpp"
#include "wifi_softap.hpp"

extern "C" void app_main(void)  // IDF 要求 C 链接
{
    esp_err_t ret = nvs_flash_init();  // WiFi 标定数据落 NVS
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
