idf_component_register(
    SRCS "app_main.cpp" "uart_link.cpp" "wifi_softap.cpp" "tcp_bridge.cpp"
    INCLUDE_DIRS "include"
    PRIV_REQUIRES esp_wifi esp_netif nvs_flash esp_driver_uart esp_event esp_timer lwip
)

# IDF 默认把 -std=gnu++26 追加进 CXX_COMPILE_OPTIONS（tools/cmake/build.cmake），本工程固定
# C++23。必须写在 idf_component_register 之后：只有此时 ${COMPONENT_LIB} 上的目标级选项才排在
# 本行之前，而 GCC 对重复的 -std 取最后一个。官方写法见 docs/en/api-guides/cplusplus.rst。
target_compile_options(${COMPONENT_LIB} PRIVATE -std=gnu++23)
