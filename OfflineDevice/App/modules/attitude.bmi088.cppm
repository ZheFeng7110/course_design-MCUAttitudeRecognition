//! BMI088 加速度计 + 陀螺仪驱动（共用 SPI 总线、独立 CS 片选）
// 时序依据 Bosch datasheet BST-BMI088-DS004：
//  - 寄存器地址 bit7 = RW 位（读 1 / 写 0）
//  - 加速度计 SPI 读：首字节（寄存器地址）后插入 1 个 dummy byte；陀螺仪无 dummy
//  - 硬件 PS 引脚须接高电平选择 SPI 接口（接线问题，Phase 2 引脚表中确认）

module;

#include <array>
#include <cstddef>
#include <cstdint>
#include <span>
#include <string_view>

export module attitude.bmi088;

import attitude.config;
import emdevif.core.error_handler;
import emdevif.peripheral.gpio;
import emdevif.peripheral.spi;
import emdevif.timeline;

using namespace emdevif;

export namespace attitude {

class BMI088 {
public:
    /// 注册名配置（与 peripheral_registry.cpp 绑定一致）
    struct Config {
        std::string_view spi;      // "spi_imu"
        std::string_view cs_acc;   // "cs_acc"
        std::string_view cs_gyro;  // "cs_gyro"
    };

    explicit BMI088(const Config& c) noexcept
        : spi_(c.spi), cs_acc_(c.cs_acc), cs_gyro_(c.cs_gyro) {}

    BMI088() = delete;
    BMI088(const BMI088&) = delete;
    BMI088& operator=(const BMI088&) = delete;

    /// 双芯片 ID 校验通过返回 true
    bool init() noexcept
    {
        cs_acc_.write(Gpio::Set);
        cs_gyro_.write(Gpio::Set);
        return initAccel() && initGyro();
    }

    /// 阻塞读一帧（加速度计 + 陀螺仪各 6 字节原始数据）。
    /// 失败（超时/HAL 错误）返回 false，不重试不死等。
    bool read(ImuFrame& out) noexcept
    {
        return readAccel(out.accel) && readGyro(out.gyro);
    }

private:
    // ---- BMI088 寄存器地址 ----
    static constexpr uint8_t kRegAccChipId     = 0x00;  // 复位值 0x1E
    static constexpr uint8_t kRegAccData       = 0x12;  // ACC_DATA 起 6 字节自动递增
    static constexpr uint8_t kRegAccConf       = 0x40;  // acc_bwp[7:4] | acc_odr[3:0]
    static constexpr uint8_t kRegAccRange      = 0x41;  // 0x03 = ±24g
    static constexpr uint8_t kRegAccPwrConf    = 0x7C;  // 0x00 = active
    static constexpr uint8_t kRegAccPwrCtrl    = 0x7D;  // 0x04 = 使能加速度计（0x00 = off）
    static constexpr uint8_t kRegAccSoftReset  = 0x7E;  // 写 0xB6
    static constexpr uint8_t kRegGyrChipId     = 0x00;  // 复位值 0x0F
    static constexpr uint8_t kRegGyrRange      = 0x0F;  // 0x00 = ±2000dps
    static constexpr uint8_t kRegGyrBandwidth  = 0x10;  // 0x07 = ODR 100Hz / 滤波 32Hz
    static constexpr uint8_t kRegGyrLpm1       = 0x11;  // 0x00 = normal 模式
    static constexpr uint8_t kRegGyrSoftReset  = 0x14;  // 写 0xB6
    static constexpr uint8_t kRegGyrData       = 0x02;  // RATE_X_LSB 起 6 字节自动递增

    static constexpr uint8_t kAccChipIdValue = 0x1E;
    static constexpr uint8_t kGyrChipIdValue = 0x0F;
    static constexpr uint8_t kSoftResetValue = 0xB6;
    // ACC_PWR_CTRL：0x04 = 使能（datasheet 5.3.21，写 0x00 则保持关闭 → 数据恒为 0）
    static constexpr uint8_t kAccPwrCtrlOn   = 0x04;
    // ACC_CONF：acc_bwp[7:4] = 0x0A（normal OSR）| acc_odr[3:0] = 0x08（100Hz）
    // datasheet 5.3.10：acc_bwp 合法值仅 0x08/0x09/0x0A，acc_odr 合法值仅 0x05–0x0C
    static constexpr uint8_t kAccConf100Hz   = 0xA8;
    static constexpr uint8_t kReadBit        = 0x80;
    static constexpr uint32_t kSpiTimeoutMs  = 5;

    // ---- 加速度计初始化 ----
    bool initAccel() noexcept
    {
        // 上电默认 I2C 接口：先做一次哑读把加速度计切到 SPI 模式
        uint8_t id = 0;
        (void)readReg(true, kRegAccChipId, id);

        if (!writeReg(true, kRegAccSoftReset, kSoftResetValue)) return false;
        Timeline::pauseDelayMs(2);   // 软复位 ≥1ms

        // 加速度计软复位后 SPI 接口需重新使能：复位后的第一个 SPI 事务只用于
        // 拉高 CSB 完成切换，其数据被丢弃（实测：紧随复位的配置写被静默吞掉，
        // ACC_PWR_CTRL 仍读回 0x00、数据恒为 0）。故按 datasheet §3 补一次哑读
        // 作牺牲事务，之后的配置写才生效（与 Linux bmi088-accel 驱动一致）。
        (void)readReg(true, kRegAccChipId, id);

        // datasheet §3：软复位后必须写 0x04 到 ACC_PWR_CTRL 才能使能取数，
        // 再写 ACC_PWR_CONF = 0x00 解除 suspend（复位值 0x03 = suspend）。
        if (!writeReg(true, kRegAccPwrCtrl, kAccPwrCtrlOn)) return false;  // 使能加速度计
        Timeline::pauseDelayMs(5);
        if (!writeReg(true, kRegAccPwrConf, 0x00)) return false;  // suspend → active
        Timeline::pauseDelayMs(1);

        if (!writeReg(true, kRegAccRange, 0x03)) return false;    // ±24g
        if (!writeReg(true, kRegAccConf, kAccConf100Hz)) return false;  // 100Hz / normal

        for (int i = 0; i < 5; ++i) {
            if (readReg(true, kRegAccChipId, id) && id == kAccChipIdValue) return true;
            Timeline::pauseDelayMs(1);
        }
        return false;
    }

    // ---- 陀螺仪初始化 ----
    bool initGyro() noexcept
    {
        if (!writeReg(false, kRegGyrSoftReset, kSoftResetValue)) return false;
        Timeline::pauseDelayMs(35);  // 陀螺仪软复位典型 30ms

        if (!writeReg(false, kRegGyrRange, 0x00)) return false;     // ±2000dps
        if (!writeReg(false, kRegGyrBandwidth, 0x07)) return false; // ODR 100Hz / 32Hz
        if (!writeReg(false, kRegGyrLpm1, 0x00)) return false;      // normal 模式

        uint8_t id = 0;
        for (int i = 0; i < 5; ++i) {
            if (readReg(false, kRegGyrChipId, id) && id == kGyrChipIdValue) return true;
            Timeline::pauseDelayMs(1);
        }
        return false;
    }

    // ---- SPI 底层 ----
    bool writeReg(bool accel, uint8_t reg, uint8_t value) noexcept
    {
        const std::array<uint8_t, 2> tx{reg, value};  // reg bit7 = 0 写
        std::array<uint8_t, 2> rx{};
        return transfer(accel, tx, rx);
    }

    bool readReg(bool accel, uint8_t reg, uint8_t& value) noexcept
    {
        reg |= kReadBit;
        if (accel) {
            std::array<uint8_t, 3> tx{reg, 0x00, 0x00};  // 1 dummy byte
            std::array<uint8_t, 3> rx{};
            if (!transfer(accel, tx, rx)) return false;
            value = rx[2];
        } else {
            std::array<uint8_t, 2> tx{reg, 0x00};
            std::array<uint8_t, 2> rx{};
            if (!transfer(accel, tx, rx)) return false;
            value = rx[1];
        }
        return true;
    }

    /// 全双工收发，CS 由本函数控制；片选拉低到释放覆盖整个事务
    bool transfer(bool accel, std::span<const uint8_t> tx, std::span<uint8_t> rx) noexcept
    {
        Gpio& cs = accel ? cs_acc_ : cs_gyro_;
        cs.write(Gpio::Reset);
        const ErrorCode err = spi_.transmitReceive(false, tx, rx, kSpiTimeoutMs);
        cs.write(Gpio::Set);
        return err == ErrorCode::Success;
    }

    // ---- 数据突发读 ----
    bool readAccel(int16_t out[3]) noexcept
    {
        std::array<uint8_t, 8> tx{};  // [reg|0x80, dummy, 6 数据]
        tx[0] = kRegAccData | kReadBit;
        std::array<uint8_t, 8> rx{};
        if (!transfer(true, tx, rx)) return false;
        for (int i = 0; i < 3; ++i) {
            out[i] = static_cast<int16_t>(static_cast<uint16_t>(rx[2 + 2 * i])
                                          | static_cast<uint16_t>(rx[3 + 2 * i]) << 8);  // LSB first
        }
        return true;
    }

    bool readGyro(int16_t out[3]) noexcept
    {
        std::array<uint8_t, 7> tx{};  // [reg|0x80, 6 数据]
        tx[0] = kRegGyrData | kReadBit;
        std::array<uint8_t, 7> rx{};
        if (!transfer(false, tx, rx)) return false;
        for (int i = 0; i < 3; ++i) {
            out[i] = static_cast<int16_t>(static_cast<uint16_t>(rx[1 + 2 * i])
                                          | static_cast<uint16_t>(rx[2 + 2 * i]) << 8);  // LSB first
        }
        return true;
    }

    Spi spi_;
    Gpio cs_acc_;
    Gpio cs_gyro_;
};

}  // namespace attitude
