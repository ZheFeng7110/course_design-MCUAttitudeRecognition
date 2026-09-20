"""自采集会话可视化：6 通道波形 + 标注色带，人工剔除异常段参考。

输出 <会话>.png（同目录）；有图形环境（Windows/macOS 桌面、X11/Wayland）时
额外弹窗显示，无显示环境（SSH、容器）只存图，不阻塞。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

LABEL_COLORS = {"walk": "green", "run": "orange", "fall": "red", "none": "lightgray"}


def has_gui() -> bool:
    """是否有可用图形环境（决定 plt.show() 是否有意义）。"""
    if sys.platform in ("win32", "darwin"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("用法: uv run plot_session.py <session.csv> [channel]")
    path = Path(sys.argv[1])
    df = pd.read_csv(path)
    t = df["t_us"] / 1e6

    channels = ["ax", "ay", "az", "gx", "gy", "gz"] if len(sys.argv) < 3 else [sys.argv[2]]
    fig, axes = plt.subplots(len(channels), 1, sharex=True, figsize=(14, 2 * len(channels)))
    if len(channels) == 1:
        axes = [axes]
    for ax, ch in zip(axes, channels):
        ax.plot(t, df[ch], lw=0.6)
        ax.set_ylabel(ch)
        # 标注色带
        for label, color in LABEL_COLORS.items():
            mask = df["label"] == label
            if mask.any():
                ax.fill_between(t, *ax.get_ylim(), where=mask, color=color, alpha=0.15)
    axes[-1].set_xlabel("t (s)")
    fig.suptitle(path.name)
    plt.tight_layout()

    out = path.with_suffix(".png")
    fig.savefig(out, dpi=110)
    print(f"图 -> {out}")
    if has_gui():
        plt.show()


if __name__ == "__main__":
    main()
