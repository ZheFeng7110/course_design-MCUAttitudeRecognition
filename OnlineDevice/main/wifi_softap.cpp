//! SoftAP 实现：WPA2-PSK、单/少量客户端（Windows 与安卓兼容性最好，不用 WPA3/SAE）。

#include "wifi_softap.hpp"

#include <cstddef>
#include <cstring>

#include "esp_check.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_wifi.h"

namespace {

constexpr char        kTag[]           = "wifi_ap";
constexpr std::size_t kSsidMaxLen      = 32;  // wifi_ap_config_t::ssid 数组长度
constexpr std::size_t kPasswordMinLen  = 8;   // 短于 8 视为不加密
constexpr std::size_t kIpStrLen        = 16;  // "255.255.255.255" + NUL

void onWifiEvent(void*, esp_event_base_t event_base, int32_t event_id, void* event_data)
{
    if (event_base != WIFI_EVENT) {
        return;
    }
    if (event_id == WIFI_EVENT_AP_STACONNECTED) {
        const auto* ev = static_cast<const wifi_event_ap_staconnected_t*>(event_data);
        ESP_LOGI(kTag, "station " MACSTR " join aid=%d", MAC2STR(ev->mac), ev->aid);
    } else if (event_id == WIFI_EVENT_AP_STADISCONNECTED) {
        const auto* ev = static_cast<const wifi_event_ap_stadisconnected_t*>(event_data);
        ESP_LOGW(kTag, "station " MACSTR " leave aid=%d reason=%d", MAC2STR(ev->mac), ev->aid, ev->reason);
    }
}

}  // namespace

esp_err_t wifiSoftApStart()
{
    ESP_RETURN_ON_ERROR(esp_netif_init(), kTag, "esp_netif_init failed");
    ESP_RETURN_ON_ERROR(esp_event_loop_create_default(), kTag, "esp_event_loop_create_default failed");

    esp_netif_t* ap_netif = esp_netif_create_default_wifi_ap();
    ESP_RETURN_ON_FALSE(ap_netif != nullptr, ESP_FAIL, kTag, "esp_netif_create_default_wifi_ap failed");

    wifi_init_config_t init_cfg{};
    init_cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_RETURN_ON_ERROR(esp_wifi_init(&init_cfg), kTag, "esp_wifi_init failed");
    ESP_RETURN_ON_ERROR(esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID, onWifiEvent, nullptr, nullptr),
                        kTag, "esp_event_handler_instance_register failed");

    wifi_config_t ap{};
    const std::size_t ssid_len = std::strlen(CONFIG_BRIDGE_AP_SSID);
    if (ssid_len > kSsidMaxLen) {
        ESP_LOGW(kTag, "SSID longer than %zu bytes; truncated", kSsidMaxLen);
    }
    std::strncpy(reinterpret_cast<char*>(ap.ap.ssid), CONFIG_BRIDGE_AP_SSID, sizeof(ap.ap.ssid));
    ap.ap.ssid_len = static_cast<uint8_t>(ssid_len > kSsidMaxLen ? kSsidMaxLen : ssid_len);

    std::strncpy(reinterpret_cast<char*>(ap.ap.password), CONFIG_BRIDGE_AP_PASSWORD, sizeof(ap.ap.password));
    if (std::strlen(CONFIG_BRIDGE_AP_PASSWORD) < kPasswordMinLen) {
        ap.ap.authmode = WIFI_AUTH_OPEN;
        ESP_LOGW(kTag, "password shorter than %zu chars -> open AP", kPasswordMinLen);
    } else {
        ap.ap.authmode = WIFI_AUTH_WPA2_PSK;
    }

    ap.ap.channel        = static_cast<uint8_t>(CONFIG_BRIDGE_AP_CHANNEL);
    ap.ap.max_connection = static_cast<uint8_t>(CONFIG_BRIDGE_AP_MAX_STA);
    ap.ap.pmf_cfg.required = false;

    ESP_RETURN_ON_ERROR(esp_wifi_set_mode(WIFI_MODE_AP), kTag, "esp_wifi_set_mode failed");
    ESP_RETURN_ON_ERROR(esp_wifi_set_config(WIFI_IF_AP, &ap), kTag, "esp_wifi_set_config failed");
    ESP_RETURN_ON_ERROR(esp_wifi_start(), kTag, "esp_wifi_start failed");

    esp_netif_ip_info_t ip{};
    ESP_RETURN_ON_ERROR(esp_netif_get_ip_info(ap_netif, &ip), kTag, "esp_netif_get_ip_info failed");

    char ip_str[kIpStrLen] = {};
    esp_ip4addr_ntoa(&ip.ip, ip_str, static_cast<int>(sizeof(ip_str)));

    ESP_LOGI(kTag, "SoftAP ready ssid=%s channel=%d max_sta=%d ip=%s port=%d", CONFIG_BRIDGE_AP_SSID, CONFIG_BRIDGE_AP_CHANNEL,
             CONFIG_BRIDGE_AP_MAX_STA, ip_str, CONFIG_BRIDGE_TCP_PORT);
    return ESP_OK;
}
