//! 链接期注入：把 CubeMX 生成的外设句柄绑定到 emdevif 模型实例。
//! 模块单元版本（计划 Assumption #9：GCC 下普通 TU 混用 #include + import
//! 报 conflicting linkage，故注入 TU 改为模块单元；findHandle 定义保持
//! 未导出、外部链接，链接器照常解析）。
//! 注册名契约（Phase 2 占位决策，永不更改）：
//!   "spi_imu" / "cs_acc" / "cs_gyro" / "debug_console"
//! 引脚变更只改本文件绑定。

#include <cstddef>

#include "spi.h"
#include "usart.h"

#include <string_view>

import emdevif.peripheral.model.gpio;
import emdevif.peripheral.model.serial;
import emdevif.peripheral.model.spi;
import emdevif.stm32_peripheral.hal.gpio;
import emdevif.stm32_peripheral.hal.spi;
import emdevif.stm32_peripheral.hal.usart;

// ---- SPI（BMI088 共用总线）----
constinit emdevif::SpiModel::Instance spi_imu_instance{
    .handle = &hspi1,
    .transmit_receive_function = emdevif::stm32hal::spiTransmitReceiveBlock,
};

// ---- 片选 GPIO（占位 PB0/PB1，随用户引脚表更新）----
constinit emdevif::stm32hal::GpioHandle cs_acc_handle{GPIOB, GPIO_PIN_0};
constinit emdevif::stm32hal::GpioHandle cs_gyro_handle{GPIOB, GPIO_PIN_1};

constinit emdevif::GpioModel::Instance cs_acc_instance{
    .handle = &cs_acc_handle,
    .write_function = emdevif::stm32hal::gpioWrite,
    .read_function = emdevif::stm32hal::gpioRead,
    .toggle_function = emdevif::stm32hal::gpioToggle,
};

constinit emdevif::GpioModel::Instance cs_gyro_instance{
    .handle = &cs_gyro_handle,
    .write_function = emdevif::stm32hal::gpioWrite,
    .read_function = emdevif::stm32hal::gpioRead,
    .toggle_function = emdevif::stm32hal::gpioToggle,
};

// ---- 调试/数据串口（USART1）----
constinit emdevif::SerialModel::Instance debug_console_instance{
    .handle = &huart1,
    .get_state_function = emdevif::stm32hal::uartGetState,
    .transmit_function = emdevif::stm32hal::uartTransmitBlocking,
};

namespace emdevif::user_impl::peripheral_handle_map {

void* findHandle(std::string_view name) noexcept
{
    if (name == "spi_imu") return &spi_imu_instance;
    if (name == "cs_acc") return &cs_acc_instance;
    if (name == "cs_gyro") return &cs_gyro_instance;
    if (name == "debug_console") return &debug_console_instance;
    return nullptr;
}

}  // namespace emdevif::user_impl::peripheral_handle_map
