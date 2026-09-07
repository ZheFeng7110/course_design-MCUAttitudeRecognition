# emdevif 集成配置（模块单元 + CubeMX 支持）
# 必须在 target_link_libraries(emdevif) 之前 include。

set(EMDEVIF_USE_CPP_MODULES ON CACHE INTERNAL "" FORCE)
set(EMDEVIF_USE_STM32CUBEMX ON CACHE INTERNAL "" FORCE)

# 本期只启用 peripheral 与 timeline（日志用调试串口手写输出，无 RTOS）
set(EMDEVIF_ENABLED_MODULES "peripheral;timeline" CACHE INTERNAL "" FORCE)

add_subdirectory(
    ${CMAKE_SOURCE_DIR}/../deps/emdevif_collection/emdevif
    ${CMAKE_BINARY_DIR}/deps/emdevif_collection/emdevif
)

# STM32 HAL 外设封装：SPI（BMI088）、USART（调试/数据口）、GPIO（CS 片选）
set(EMDEVIF_DEVICE_ENABLED_PERIPHERAL_LIST "SPI;USART;GPIO" CACHE INTERNAL "" FORCE)
set(EMDEVIF_STM32_PERIPHERAL_DRIVER "HAL;HAL;HAL" CACHE INTERNAL "" FORCE)
add_subdirectory(
    ${CMAKE_SOURCE_DIR}/../deps/emdevif_collection/emdevif_stm32_peripheral
    ${CMAKE_BINARY_DIR}/deps/emdevif_collection/emdevif_stm32_peripheral
)
