//! TCP 桥实现：唯一传输层，单客户端、字节透明。
//!
//! 后续 BLE 只新增独立文件复用 uartLinkRead/uartLinkFlush 与同一 flush+resync 语义，本文件不动。

#include "tcp_bridge.hpp"

#include <cerrno>
#include <cstdlib>
#include <cstring>

#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "lwip/inet.h"
#include "lwip/sockets.h"

#include "bridge_config.hpp"
#include "uart_link.hpp"

namespace {

constexpr char kTag[]          = "tcp_bridge";
constexpr int  kListenBacklog  = 4;  // 同一时刻只服务一个连接，其余排队
constexpr int  kRetryDelayMs   = 1000;

uint8_t s_chunk[bridge::kChunkBytes];

struct Stats {
    uint64_t forward_bytes = 0;
    uint64_t drop_bytes    = 0;
    uint32_t sessions      = 0;
};

/// 建立监听 socket；任一步失败退避重试，永不返回。
int listenSocketCreate()
{
    for (;;) {
        const int fd = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
        if (fd < 0) {
            ESP_LOGW(kTag, "socket errno=%d", errno);
        } else {
            const int one = 1;
            setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));

            sockaddr_in addr{};
            addr.sin_family      = AF_INET;
            addr.sin_addr.s_addr = htonl(INADDR_ANY);
            addr.sin_port        = htons(static_cast<uint16_t>(CONFIG_BRIDGE_TCP_PORT));

            if (bind(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) == 0 && listen(fd, kListenBacklog) == 0) {
                ESP_LOGI(kTag, "listening on port %d (backlog %d)", CONFIG_BRIDGE_TCP_PORT, kListenBacklog);
                return fd;
            }
            ESP_LOGW(kTag, "bind/listen errno=%d", errno);
            close(fd);
        }
        vTaskDelay(pdMS_TO_TICKS(kRetryDelayMs));
    }
}

bool sendAll(int fd, const uint8_t* data, std::size_t len)
{
    std::size_t off = 0;
    while (off < len) {
        const int n = send(fd, data + off, len - off, 0);
        if (n <= 0) {
            ESP_LOGW(kTag, "send failed errno=%d", errno);
            return false;
        }
        off += static_cast<std::size_t>(n);
    }
    return true;
}

/// 服务单个客户端直到 send 失败（对端断开）。返回后调用方负责 shutdown/close。
void serveClient(int fd, Stats& st)
{
    const int one = 1;
    setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
    setsockopt(fd, SOL_SOCKET, SO_KEEPALIVE, &one, sizeof(one));

    timeval snd_timeout{};
    snd_timeout.tv_sec  = bridge::kSendTimeoutMs / 1000;
    snd_timeout.tv_usec = (bridge::kSendTimeoutMs % 1000) * 1000;
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &snd_timeout, sizeof(snd_timeout));

    // 无客户端期间驱动缓冲里积压的是陈旧数据，连接建立即丢弃。
    uartLinkFlush();

    bool    resync       = true;
    int64_t next_stats_us = esp_timer_get_time() + bridge::kStatsPeriodUs;

    for (;;) {
        const int n = uartLinkRead(s_chunk, sizeof(s_chunk), bridge::kReadTimeoutMs);
        if (n <= 0) {
            continue;  // 超时属正常；客户端断开由 send 失败暴露
        }

        uint8_t*    p   = s_chunk;
        std::size_t len = static_cast<std::size_t>(n);

        if (resync) {
            // STM32 可能正发到半行：丢弃到首个 '\n'，保证首条输出是完整行。
            const void* nl = std::memchr(p, '\n', len);
            if (nl == nullptr) {
                st.drop_bytes += len;
                continue;
            }
            const std::size_t consumed = static_cast<std::size_t>(static_cast<const uint8_t*>(nl) - p) + 1;
            st.drop_bytes += consumed;
            p += consumed;
            len -= consumed;
            resync = false;
            if (len == 0) {
                continue;
            }
        }

        if (!sendAll(fd, p, len)) {
            return;
        }
        st.forward_bytes += len;

        const int64_t now = esp_timer_get_time();
        if (now >= next_stats_us) {
            ESP_LOGI(kTag, "forward=%llu B drop=%llu B sessions=%u", static_cast<unsigned long long>(st.forward_bytes),
                     static_cast<unsigned long long>(st.drop_bytes), st.sessions);
            next_stats_us = now + bridge::kStatsPeriodUs;
        }
    }
}

void bridgeTask(void*)
{
    Stats     st        = {};
    const int listen_fd = listenSocketCreate();

    for (;;) {
        sockaddr_in peer{};
        socklen_t   peer_len = sizeof(peer);
        const int   fd       = accept(listen_fd, reinterpret_cast<sockaddr*>(&peer), &peer_len);
        if (fd < 0) {
            ESP_LOGW(kTag, "accept errno=%d", errno);
            vTaskDelay(pdMS_TO_TICKS(kRetryDelayMs));
            continue;
        }

        char addr[16] = {};
        inet_ntoa_r(peer.sin_addr, addr, sizeof(addr));
        ++st.sessions;
        ESP_LOGI(kTag, "client %s:%u connected", addr, static_cast<unsigned>(ntohs(peer.sin_port)));

        serveClient(fd, st);

        shutdown(fd, SHUT_RDWR);
        close(fd);
        ESP_LOGI(kTag, "client closed; sessions=%u forward=%llu B drop=%llu B", st.sessions,
                 static_cast<unsigned long long>(st.forward_bytes), static_cast<unsigned long long>(st.drop_bytes));
    }
}

}  // namespace

void tcpBridgeStart()
{
    if (xTaskCreate(bridgeTask, "tcp_bridge", bridge::kBridgeTaskStack, nullptr, bridge::kBridgeTaskPrio, nullptr) != pdPASS) {
        ESP_LOGE(kTag, "xTaskCreate failed");
        std::abort();
    }
}
