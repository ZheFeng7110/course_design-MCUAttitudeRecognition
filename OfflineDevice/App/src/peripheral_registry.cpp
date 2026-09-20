//! 链接期注入：把 CubeMX 生成的外设句柄绑定到 emdevif 模型实例。
//! 模块单元版本（计划 Assumption #9：GCC 下普通 TU 混用 #include + import
//! 报 conflicting linkage，故注入 TU 改为模块单元；findHandle 定义保持
//! 未导出、外部链接，链接器照常解析）。
//! 注册名契约（Phase 2 占位决策，永不更改）：
//!   "spi_imu" / "cs_acc" / "cs_gyro" / "imu_int1" / "imu_int3" /
//!   "debug_console" / "bridge_uart"
//! 引脚变更只改本文件绑定。

#include <cstddef>

#include "main.h"
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
    .handle = &hspi2,
    .transmit_receive_function = emdevif::stm32hal::spiTransmitReceiveBlock,
};

// ---- 片选 GPIO（BMI088_CSB_ACCEL: PC0 / BMI088_CSB_GYRO: PC3）----
constinit emdevif::stm32hal::GpioHandle cs_acc_handle{BMI088_CSB_ACCEL_GPIO_Port, BMI088_CSB_ACCEL_Pin};
constinit emdevif::stm32hal::GpioHandle cs_gyro_handle{BMI088_CSB_GYRO_GPIO_Port, BMI088_CSB_GYRO_Pin};

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

// ---- BMI088 数据就绪中断输入（EXTI，只读）----
constinit emdevif::stm32hal::GpioHandle imu_int1_handle{BMI088_INT1_GPIO_Port, BMI088_INT1_Pin};
constinit emdevif::stm32hal::GpioHandle imu_int3_handle{BMI088_INT3_GPIO_Port, BMI088_INT3_Pin};

constinit emdevif::GpioModel::Instance imu_int1_instance{
    .handle = &imu_int1_handle,
    .write_function = emdevif::stm32hal::gpioWrite,
    .read_function = emdevif::stm32hal::gpioRead,
    .toggle_function = emdevif::stm32hal::gpioToggle,
};

constinit emdevif::GpioModel::Instance imu_int3_instance{
    .handle = &imu_int3_handle,
    .write_function = emdevif::stm32hal::gpioWrite,
    .read_function = emdevif::stm32hal::gpioRead,
    .toggle_function = emdevif::stm32hal::gpioToggle,
};

// ---- 调试串口（USART10，PE2/PE3，921600）：接 PC 的 USB-TTL ----
constinit emdevif::SerialModel::Instance debug_console_instance{
    .handle = &huart10,
    .get_state_function = emdevif::stm32hal::uartGetState,
    .receive_function = emdevif::stm32hal::uartReceiveBlocking,
    .transmit_function = emdevif::stm32hal::uartTransmitBlocking,
};

// ---- 在线设备数据链（UART7，PE8=TX/PE7=RX，115200）：接 ESP32 UART2 RX(GPIO16) ----
constinit emdevif::SerialModel::Instance bridge_uart_instance{
    .handle = &huart7,
    .get_state_function = emdevif::stm32hal::uartGetState,
    .transmit_function = emdevif::stm32hal::uartTransmitBlocking,
};

namespace emdevif::user_impl::peripheral_handle_map {

void* findHandle(std::string_view name) noexcept
{
    if (name == "spi_imu") return &spi_imu_instance;
    if (name == "cs_acc") return &cs_acc_instance;
    if (name == "cs_gyro") return &cs_gyro_instance;
    if (name == "imu_int1") return &imu_int1_instance;
    if (name == "imu_int3") return &imu_int3_instance;
    if (name == "debug_console") return &debug_console_instance;
    if (name == "bridge_uart") return &bridge_uart_instance;
    return nullptr;
}

}  // namespace emdevif::user_impl::peripheral_handle_map
