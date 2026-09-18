//! 姿态应用主入口：BMI088 100Hz 采样 → 窗口缓冲 → 推理 → 双串口分流输出
//! 串口分流（两个口均 921600）：
//!   - "debug_console" = USART10(PE2/PE3)：调试台，输出全部行（日志 + 数据）
//!   - "bridge_uart"   = UART7(PE8/PE7)：在线设备（ESP32）数据链，**只**输出数据行
//!     即 CSV `t_us,ax,ay,az,gx,gy,gz` 或判断行 `ACT,WALK|RUN|FALL,p0,p1,p2,<ms>ms`；
//!     日志/控制/错误行（`BMI088 init OK`、`TFLM arena used:` 等）不进入该口。
//! 模式由 attitude.config 的开关控制：
//!   - kStreamRaw == true ：CSV 原始流 `t_us,ax,ay,az,gx,gy,gz`（Phase 5 采集模式）
//!   - 否则输出推理结果  `ACT,WALK|RUN|FALL,p0,p1,p2,<耗时>ms`
//! 推理实现编译期选择：kUseMockInference ? MockInference : TfliteInference
//! （TFLM 路径需 -DATTITUDE_ENABLE_TFLM=ON 且已生成 model_data.cc）。
//! 另含 PC–MCU 一致性验证命令（'W'，见 model/tools/parity_check.py）。

module;

#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <span>
#include <type_traits>

export module attitude.app;

import attitude.config;
import attitude.bmi088;
import attitude.inference;
import attitude.window;
import emdevif.peripheral.serial;
import emdevif.timeline;
import emdevif.core.error_handler;
#ifdef ATTITUDE_ENABLE_TFLM
import attitude.tflite;
#endif

using namespace emdevif;

namespace attitude {

namespace {

#ifndef ATTITUDE_ENABLE_TFLM
static_assert(kUseMockInference, "kUseMockInference=false 需要 -DATTITUDE_ENABLE_TFLM=ON（先运行 gen_c_array.py）");
#endif
#ifdef ATTITUDE_ENABLE_TFLM
using InferenceImpl = std::conditional_t<kUseMockInference, MockInference, TfliteInference>;
#else
using InferenceImpl = MockInference;
#endif

/// 模板内 if constexpr 才能真正丢弃分支（MockInference 无 init/arenaUsedBytes）
template <typename Inf>
bool initInference(Inf& inference, const auto& send) noexcept
{
    if constexpr (requires { inference.init(); }) {
        if (!inference.init()) return false;
        char arena_line[64]{};
        (void)std::snprintf(arena_line, sizeof(arena_line), "TFLM arena used: %zu bytes\r\n",
                            inference.arenaUsedBytes());
        send(arena_line);
    }
    return true;
}

/// PC–MCU 一致性验证命令（model/tools/parity_check.py）：
/// 收到 'W' 后接收 kWindowLen×12 字节 int16（LE）原始帧，
/// 推理后回发 3×float32（LE）概率。
template <typename Inf>
void handleParityCommand(Serial& debug, Inf& inference) noexcept
{
    uint8_t cmd = 0;
    if (debug.receive(false, std::span<uint8_t>(&cmd, 1), 0) != ErrorCode::Success) return;
    if (cmd != 'W') return;

    ImuFrame frames[kWindowLen]{};
    const auto raw = std::span<uint8_t>(reinterpret_cast<uint8_t*>(frames), sizeof(frames));
    if (debug.receive(false, raw, 5000) != ErrorCode::Success) {
        static constexpr uint8_t kMsg[] = "PARITY,ERR,rx\r\n";
        (void)debug.transmit(false, std::span<const uint8_t>(kMsg, sizeof(kMsg) - 1),
                             Serial::max_delay);
        return;
    }

    Activity act = Activity::Walk;
    float probs[3] = {0.0F, 0.0F, 0.0F};
    if (!inference.infer(frames, kWindowLen, act, probs)) {
        static constexpr uint8_t kMsg[] = "PARITY,ERR,inf\r\n";
        (void)debug.transmit(false, std::span<const uint8_t>(kMsg, sizeof(kMsg) - 1),
                             Serial::max_delay);
        return;
    }
    const auto out =
        std::span<const uint8_t>(reinterpret_cast<const uint8_t*>(probs), sizeof(probs));
    (void)debug.transmit(false, out, 1000);
}

}  // namespace

export extern "C" void attitude_app_main()
{
    Serial debug("debug_console");  // USART10(PE2/PE3) 921600：调试台（日志 + 数据）
    Serial bridge("bridge_uart");   // UART7(PE8/PE7) 921600：在线设备数据链（仅数据行）
    const auto write = [](Serial& port, const char* text) noexcept {
        (void)port.transmit(false,
                            std::span<const uint8_t>(reinterpret_cast<const uint8_t*>(text),
                                                     std::strlen(text)),
                            Serial::max_delay);
    };
    // 分流：日志/控制/错误行只走调试台；数据行额外转发到在线设备链路。
    // 调试台保留数据行，供 PC 的 USB-TTL 直接抓取（model/tools 的采集与现场测试依赖该口）。
    const auto sendLog = [&](const char* text) noexcept { write(debug, text); };
    const auto sendData = [&](const char* text) noexcept {
        write(debug, text);
        write(bridge, text);
    };

    BMI088 imu({.spi = "spi_imu", .cs_acc = "cs_acc", .cs_gyro = "cs_gyro"});
    if (!imu.init()) {
        // 无 LED 引脚（gpio.c 占位）：UART 报错后停机循环占位
        sendLog("BMI088 init FAILED\r\n");
        for (;;) {
            Timeline::pauseDelayMs(100);
        }
    }
    sendLog("BMI088 init OK\r\n");

    InferenceImpl inference;
    if (!initInference(inference, sendLog)) {
        sendLog("TFLM init FAILED\r\n");
        for (;;) {
            Timeline::pauseDelayMs(100);
        }
    }

    WindowBuffer window;
    ImuFrame frame{};
    ImuFrame snapshot[kWindowLen]{};
    char line[96]{};

    const uint64_t start_us = Timeline::getMicroseconds();
    constexpr uint64_t kPeriodUs = 1000000ULL / static_cast<uint64_t>(kSampleRateHz);
    uint64_t next_tick_us = start_us + kPeriodUs;
    Duration<float> infer_timer;

    for (;;) {
        if (imu.read(frame)) {
            const uint64_t t_us = Timeline::getMicroseconds() - start_us;
            if (kStreamRaw) {
                (void)std::snprintf(line, sizeof(line), "%llu,%d,%d,%d,%d,%d,%d\r\n",
                                    static_cast<unsigned long long>(t_us), frame.accel[0],
                                    frame.accel[1], frame.accel[2], frame.gyro[0], frame.gyro[1],
                                    frame.gyro[2]);
                sendData(line);
            }
            window.push(frame);
        }

        if (window.ready()) {
            window.takeSnapshot(snapshot);
            infer_timer.update();
            Activity act = Activity::Walk;
            float probs[3] = {0.0F, 0.0F, 0.0F};
            if (inference.infer(snapshot, kWindowLen, act, probs)) {
                const float infer_ms = infer_timer.getMilliDuration();
                if (!kStreamRaw) {
                    static constexpr const char* kNames[] = {"WALK", "RUN", "FALL"};
                    (void)std::snprintf(line, sizeof(line), "ACT,%s,%.3f,%.3f,%.3f,%.1fms\r\n",
                                        kNames[static_cast<int>(act)], probs[0], probs[1], probs[2],
                                        static_cast<double>(infer_ms));
                    sendData(line);
                }
            }
        }

        handleParityCommand(debug, inference);

        // 100Hz 固定周期（Duration/Timeline 微秒时间源保证）
        const uint64_t now_us = Timeline::getMicroseconds();
        if (now_us < next_tick_us) {
            Timeline::pauseDelayUs(next_tick_us - now_us);
        }
        next_tick_us += kPeriodUs;
    }
}

}  // namespace attitude
