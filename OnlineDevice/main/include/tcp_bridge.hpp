//! TCP 桥：单客户端服务，把 UART2 收到的字节原样转发（字节透明，不加解析/时间戳）。
#pragma once

/// 创建桥接任务后立即返回（服务端 socket 在同一任务内无限重试建立）。
void tcpBridgeStart();
