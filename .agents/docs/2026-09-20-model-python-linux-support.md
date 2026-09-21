# model/ 全部 Python 功能的非 Windows 支持

日期：2026-09-20
范围：`model/` 下全部 Python（`tools/` 4 个交互工具 + `src/` 流水线），使其在 Linux（及 macOS）可用，
Windows 行为保持不变。

## 1. 背景

原实现把平台假设散落在各工具里：按键只走 `msvcrt`（非 Windows 恒读不到键）、串口缺省写死 `COM5`、
图形输出只 `plt.show()`、JSON/文本读写不指定编码（Windows GBK ↔ Linux UTF-8 互读会炸）。
`src/` 流水线本身无平台分支，但有两个与平台无关、却只有在 Linux 上真跑才会暴露的 bug（见 §5）。

## 2. 平台层：`model/tools/console_input.py`（新增）

三个交互工具共用，避免同一套 cbreak 逻辑抄三份：

| 能力 | Windows | Linux/macOS |
|---|---|---|
| 按键 | `msvcrt.kbhit()/getwch()` | `stdin` 切 cbreak + `select` 非阻塞读 |
| 串口缺省 `PORT_DEFAULT` | `COM5` | `/dev/ttyUSB0`（argv 可覆盖） |

关键决策：

- **cbreak 而非 raw**：`tty.setcbreak()` 只关 `ICANON`，`ISIG` 保留 → Ctrl-C 仍产生 `SIGINT`，可以存盘退出。
- **手动关 `ECHO`**：`setcbreak()` 不改回显，不关的话 Linux 上按键会被终端回显（Windows `getwch` 不回显）。
- **`key_input()` 上下文管理器 + `finally`**：异常/中断都 `tcsetattr(..., TCSADRAIN, saved)`，绝不把终端留在 cbreak。
- **`read_key()` 前必须 `select`**：非阻塞判定，避免主循环卡在键盘上错过串口数据。
- **非 TTY（管道/重定向）**：不切 cbreak（`tcgetattr` 会失败），`read_key()` 恒 `None`，工具启动时提示。
- 工具仍以脚本方式运行（`uv run tools/xxx.py`），同目录自动在 `sys.path` 上，故直接 `from console_input import ...`。

## 3. 各工具改动

| 文件 | 改动 |
|---|---|
| `tools/record.py` | 删掉本文件的 msvcrt/cbreak 副本，改用 `console_input`；Ctrl-C 与 `q` 同效存盘；非 TTY 提示 |
| `tools/field_test.py` | 同上改用 `console_input`；Ctrl-C 后仍输出/落盘已完成的试验报告（原实现直接丢失整轮结果） |
| `tools/parity_check.py` | `PORT_DEFAULT` 取代写死的 `COM5`；`model_meta.json` 按 UTF-8 读 |
| `tools/plot_session.py` | 输出 `<会话>.png`（必存），仅在**有图形环境**时额外 `plt.show()`；无显示环境（SSH/容器）不再静默无输出 |
| `tools/gen_c_array.py` | 生成的 `.cc/.h`（含中文注释）显式 `encoding="utf-8"` 写出 |

`plot_session.has_gui()`：`win32`/`darwin` 视为有；Linux 看 `DISPLAY`/`WAYLAND_DISPLAY`。

## 4. 编码：显式 UTF-8

`norm.json`、`model_meta.json` 的 `note` 字段含中文；这些文件在 PC（Windows 录制/训练）与
Linux（验证/生成）之间来回传。全部 `read_text/write_text` 显式 `encoding="utf-8"`，消除
"Windows 写 GBK、Linux 读炸" 这一类问题；`record.py` 的 CSV 本就是 `utf-8` + `newline=""`。

## 5. `src/` 流水线在 Linux 上跑通时暴露并修掉的 3 个 bug

1. **`preprocess.load_self` 标签错误**：原实现整段会话只取首行标签（`df.iloc[0]["label"]`），
   而 `record.py` 是逐行打标、一个会话含 walk/run/fall 多段 → 2/3 窗口标签错误，训练停在
   `loss≈ln3`、`acc≈0.32`。改为按连续同标签区段切分。
2. **`train.py` 缺归一化**：训练喂 g/dps 原值，而 `export_tflite.py`、`parity_check.py` 与端侧约定
   都是 `x_norm=(x-mean)/std` 再量化 → 导出后精度无效（修前 `float acc≈0.3758`）。
   现在训练侧读取 `norm.json` 并对 train/val/test 归一化。
3. **`preprocess` 空会话守卫**：`record.py` 启动即创建 CSV，异常退出会留下 0 字节文件，
   `pd.read_csv` 抛 `EmptyDataError` 直接崩掉预处理 → 跳过空文件。

## 6. 验证（Linux，本机实测）

环境：`uv sync` 通过；Python 3.10.21 / TF 2.10.1 / pandas 2.3.3 / matplotlib 3.10.9 / pyserial 3.5
（`pyproject.toml` 里 "Windows wheel" 注释的钉版在 Linux 上同样有 wheel，无需改动）。

| 脚本 | 方法 | 结果 |
|---|---|---|
| `record.py` | pty 假串口 + pty 终端：单切换、两次切换 + Ctrl-C、终端还原 | 全部 PASS（过渡段 ±1s 丢弃、两段都落盘、`lflag 0x8a3b` 前后一致） |
| `field_test.py` | pty 假 MCU 持续发 ACT 行 + 按键驱动 | 混淆矩阵对角、准确率 1.000、Ctrl-C 后仍出报告 |
| `parity_check.py` | pty 假 MCU（按固件同款算法应答），50 窗口 | 50/50、偏差 0.00000；且窗口=CSV 第 2..7 列（回归旧的 `range(1,7)` 取到 `t_us`、丢 `gz`） |
| `plot_session.py` | 清空 `DISPLAY`/`WAYLAND_DISPLAY` 后运行 | 退出码 0，生成 260KB PNG，不阻塞；单通道模式同样通过 |
| `src/` 流水线 | 3 个合成会话（54k 行，三类可分）跑 preprocess→train→export | 三条命令退出 0；1053 窗口 351/351/351；min F1 = 1.0；`model.tflite` 4.9 KB；float/int8 acc = 1.0000 |
| `gen_c_array.py` | 导入模块并重定向输出到 `/tmp`，不写仓库内受控文件 | 5056 字节与 `model.tflite` 逐一相同、长度/量化常量与 `model_meta.json` 一致、中文注释完好 |

`ruff check` 全部 model 文件与改动前基线一致（仅剩既有的 `RUF100`/`DTZ005`）。

## 7. 端侧归一化单位不匹配 —— 已按「方案 A」修复

**问题回顾**：`tflite_backend.cpp` 用 `kAttitudeNormMean/Std` 直接归一化**原始 int16 LSB**，
而这两个常量来自 `norm.json`（= `preprocess` 统计量，单位 **g/dps**）。后果是加速度通道整体饱和：
本次在真实生成的 `model_data.cc` 上实测，旧口径 int8 输入饱和 **50%（walk 窗口）/ 81%（run 窗口）/
43%（fall 窗口）**，端侧恒判 run 而 `parity_check` 仍报 100% 一致、偏差 0 —— 一致性门形同虚设。

### 7.1 方案 A 的落地（物理量口径，端侧负责 LSB→物理量换算）

| 文件 | 改动 |
|---|---|
| `OfflineDevice/App/src/tflite/attitude_quantize.h`（新增） | 后端输入预处理抽成 `attitude_quantize_window()`：`LSB → ×phys_per_lsb → (x−mean)/std → int8`。单独成文件是为了能在主机侧编译**真实代码**做数值验证（MCU 无法在本机跑） |
| `OfflineDevice/App/src/tflite/tflite_backend.cpp` | 内联的量化循环改为调用上述函数（换算系数来自生成的 `model_data.h`） |
| `model/src/preprocess.py` | LSB 系数提为命名常量 `ACC_LSB_PER_G=1365.0` / `GYR_LSB_PER_DPS=16.384`（单一来源） |
| `model/src/export_tflite.py` | `model_meta.json` 新增 `sensor` 段（LSB 系数）；`note` 订正为“端侧先 LSB→g/dps 再归一化” |
| `model/tools/gen_c_array.py` | 把这组系数生成成固件常量 `kAttitudeAccelLsbPerG/kAttitudeGyroLsbPerDps`；**并与 `attitude.config.cppm` 的 `kAccelLsbPerG/kGyroLsbPerDps` 交叉校验**，不一致直接报错退出（改量程时两边必须同步）；顺带修掉生成端 `c_float()`：`f"{1365.0:.9g}f"` 会产出非法字面量 `1365f`，此前生成物从未被编译过所以没暴露 |
| `model/tools/parity_check.py` | `pc_reference()` 先按 `sensor` 段的系数把 LSB 换算成 g/dps 再归一化（与固件同口径）；缺 `sensor` 段直接提示重跑 `export_tflite.py` |

契约（写进 `model_meta.json` 的 `note`）：**统计量一律是 g/dps；LSB→物理量由端侧负责**，
PC 侧 `parity_check.py` 复刻同一步。这样模型工件与传感器量程解耦（改量程只需改两处常量且被生成端校验），
后续重训/换模型无需动固件换算。

### 7.2 验证

- **固件编译**：`cmake --preset Debug -DATTITUDE_ENABLE_TFLM=ON && cmake --build build/Debug`
  → 用 arm-none-eabi 编译 `model_data.cc` + `tflite_backend.cpp` 并链接 `OfflineDevice.elf` 成功
  （`attitude_quantize_window` 符号出现在目标文件里）。
- **真实固件代码 vs Python 逐元素比对**（主机侧编译 `attitude_quantize.h` + 生成的 `model_data.cc`，
  喂真实 LSB 窗口）：3 个窗口（walk/run/fall）int8 输出 **0/1200 个元素差异**；新口径**零饱和**，
  旧口径对照 594/968/516（每 1200）。
- **端到端**：把 C++ 量化出的 int8 直接喂 `model.tflite` → walk/run/fall **三类判断正确**
  （p = 0.836 / 0.984 / 0.801）。
- **一致性守卫**：把模型侧 acc 系数改成 ±12g 的 2730.6667 → `gen_c_array.py` 立即报错退出。
- **`parity_check.py`**：pty 假 MCU（按固件同款口径应答）50/50、偏差 0.00000。
  注意该门验证的是平台与协议路径；数值口径由上面的 C++↔Python 比对兜底。
- `ruff` 与基线一致。

**仍需实机**：按方案 A 重刷固件后跑 `parity_check.py`/`field_test.py`（假 MCU 不能替代真机）。

## 8. 新发现（记录，未处理）：MobiAct 数据集的单位未换算

- `preprocess.load_mobiact()` 把 MobiAct 的 accelerometer/gyroscope 列**原样**拼进训练集；
- 而 `load_sisfall()` 有换算（`×0.004` g/digit、`/14.375` dps/LSB）、`load_self()` 有换算
  （`÷1365.0`、`÷16.384`）；
- MobiAct v2 官方文档给的是 **m/s² 与 rad/s**，若属实，则“公开集预训练 + 自采集微调”在训练时
  并非同一单位（相差约 9.8 倍与 57.3 倍），归一化统计量（`norm.json`）也会被公开集主导而失真。
- **未核实**：本次 `model/data/external/` 为空（数据集未下载），无法用数据验证 MobiAct 的实际量纲。
  需要用户确认后决定是否补换算（`acc /= 9.80665`、`gyr *= 180/π`）。
