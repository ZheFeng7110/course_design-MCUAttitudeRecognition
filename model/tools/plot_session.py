"""自采集会话可视化：6 通道波形 + 标注色带，人工剔除异常段参考。"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

LABEL_COLORS = {"walk": "green", "run": "orange", "fall": "red", "none": "lightgray"}


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(f"用法: uv run plot_session.py <session.csv> [channel]")
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
    plt.show()


if __name__ == "__main__":
    main()
