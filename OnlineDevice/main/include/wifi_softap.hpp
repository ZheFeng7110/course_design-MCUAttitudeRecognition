//! SoftAP 服务：固定 192.168.4.1，仅供上位机直连。
#pragma once

#include "esp_err.h"

/// 启动 SoftAP（SSID/密码/信道/最大连接数取自 Kconfig）。返回时 AP 已启动、IP 已就绪。
esp_err_t wifiSoftApStart();
