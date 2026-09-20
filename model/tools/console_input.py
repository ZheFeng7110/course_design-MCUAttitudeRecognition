"""跨平台终端按键与串口缺省（供 model/tools 下的交互工具复用）。

按键读取（无需回车、不回显）:
    Windows    : msvcrt.kbhit()/getwch()
    Linux/macOS: stdin 切 cbreak + select 非阻塞读，退出/异常/中断时还原终端属性

用法（脚本直接运行，同目录自动在 sys.path 上）:
    from console_input import PORT_DEFAULT, key_input, keys_available, read_key

    with key_input():
        while True:
            key = read_key()      # 立即可返回；当前无输入时为 None
"""

from __future__ import annotations

import contextlib
import os
import sys
from collections.abc import Iterator

try:
    import msvcrt

    HAS_MSVCRT = True
except ImportError:  # Linux/macOS
    HAS_MSVCRT = False
    import select
    import termios
    import tty

# 串口缺省：Windows 为 COM5；Linux/macOS 为 /dev/ttyUSB0（实际端口用 argv 覆盖）
PORT_DEFAULT = "COM5" if os.name == "nt" else "/dev/ttyUSB0"


def keys_available() -> bool:
    """当前环境能否读到按键：Windows 控制台恒可；Linux/macOS 需要 stdin 是 TTY。"""
    return HAS_MSVCRT or sys.stdin.isatty()


@contextlib.contextmanager
def key_input() -> Iterator[None]:
    """Linux/macOS：stdin 切 cbreak（按键立即可读）并关闭回显，退出时还原。

    Windows 或 stdin 非 TTY（管道/重定向）时不做任何改动，read_key() 恒返回 None。
    """
    if HAS_MSVCRT or not sys.stdin.isatty():
        yield
        return
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        now = termios.tcgetattr(fd)
        now[3] &= ~termios.ECHO  # cbreak 只改 ICANON，回显需另关
        termios.tcsetattr(fd, termios.TCSADRAIN, now)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)  # 异常/中断也还原终端


def read_key() -> str | None:
    """非阻塞读一个字符；当前无输入返回 None。"""
    if HAS_MSVCRT:
        return msvcrt.getwch() if msvcrt.kbhit() else None
    if not sys.stdin.isatty():
        return None
    if select.select([sys.stdin], [], [], 0)[0]:
        return sys.stdin.read(1) or None
    return None
