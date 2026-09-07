"""下载公开数据集：MobiAct v2（主数据源）与 SisFall（跌倒补充）。

落位:
    model/data/external/mobiact/
    model/data/external/sisfall/

若数据集需要注册/手动下载（计划 Assumption #5），打印说明后退出，
不阻塞其余阶段。
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "external"

MOBIACT_URL = "https://zenodo.org/records/12056907/files/MobiAct_Dataset_v2.0.zip"
SISFALL_URL = "http://www.sisfall.ufsc.br/dataset/SisFall_dataset.zip"  # 无官方直链时常失效

MANUAL = """
数据集手动下载指引（自动下载失败/需注册时）:

1. MobiAct v2.0（NTUA）
   - 官方页面: https://bmi.bee.duth.gr/mobiact/  （或 Zenodo 检索 "MobiAct"）
   - 下载完整数据集压缩包，解压到: {mobiact}
   - 期望目录形如 MobiAct_Dataset_v2.0/<活动代码>/<试验>/...

2. SisFall（Universidad del Cauca）
   - 官方页面: https://sites.google.com/site/sisfall/
   - 下载 SisFall_dataset，解压到: {sisfall}
   - 期望目录形如 SisFall_dataset/S01A_WA_1.txt ...
"""


def download(url: str, dest: Path) -> bool:
    if dest.exists() and any(dest.iterdir()):
        print(f"[跳过] {dest} 已存在")
        return True
    dest.mkdir(parents=True, exist_ok=True)
    zip_path = dest.parent / (dest.name + ".zip")
    try:
        print(f"下载 {url} ...")
        urllib.request.urlretrieve(url, zip_path)
        import zipfile

        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(dest)
        zip_path.unlink()
        print(f"已解压到 {dest}")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[失败] {url}: {e}")
        return False


def main() -> None:
    ok_mobiact = download(MOBIACT_URL, DATA_DIR / "mobiact")
    ok_sisfall = download(SISFALL_URL, DATA_DIR / "sisfall")
    if not (ok_mobiact and ok_sisfall):
        print(MANUAL.format(mobiact=DATA_DIR / "mobiact", sisfall=DATA_DIR / "sisfall"))
        sys.exit(0)


if __name__ == "__main__":
    main()
