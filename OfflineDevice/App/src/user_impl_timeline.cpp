//! 链接期注入：emdevif timeline 微秒时间源（模块单元，见 attitude.registry 注释）。
//! HAL_GetTick()*1000 + SysTick 当前计数值折算的亚毫秒微秒；HAL tick 1kHz。

#include <cstddef>

#include "main.h"

namespace emdevif::user_impl::timeline {

uint64_t getMicroseconds() noexcept
{
    const uint32_t reload = SysTick->LOAD;  // 1kHz tick：reload = SystemCoreClock/1000 - 1
    if (reload == 0U) {
        return static_cast<uint64_t>(HAL_GetTick()) * 1000ULL;
    }

    const uint32_t ms_before = HAL_GetTick();
    uint32_t counts = reload - SysTick->VAL;
    const uint32_t ms_after = HAL_GetTick();
    if (ms_after != ms_before) {
        // 毫秒回绕发生在两次读之间：重读计数值，与 ms_after 同一时刻
        counts = reload - SysTick->VAL;
    }

    return static_cast<uint64_t>(ms_after) * 1000ULL
         + (static_cast<uint64_t>(counts) * 1000ULL) / (static_cast<uint64_t>(reload) + 1ULL);
}

}  // namespace emdevif::user_impl::timeline
