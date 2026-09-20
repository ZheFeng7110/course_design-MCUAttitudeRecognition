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

## 7. 未决项（需用户决策，本次未改）

**端侧归一化单位不匹配**（`parity_check.py` 的 PC 参考与固件行为一致，因此门形同虚设）：

- `tflite_backend.cpp:115` 用 `kAttitudeNormMean/Std` 直接归一化**原始 int16 LSB**；
- 而这两个常量来自 `model_meta.json` ← `norm.json` = `preprocess` 统计量，单位是 **g/dps**
  （实测 `az mean=1.0, std=0.591`，陀螺 `std≈38.5`）；
- 后果：`x ≈ 1365/0.59 ≈ 2300` → int8 输入大量饱和到 ±127。本次 pty 假 MCU 按固件同款算法应答，
  50 个窗口全部返回 `[0, 0.996, 0]`（恒判 run）——`parity_check` 仍报 100% 一致、偏差 0，
  即**当前一致性门检测不出任何缺陷**；
- 先按 `kAccelLsbPerG=1365` / `kGyroLsbPerDps=16.384` 换算再归一化，三类输入不饱和且判断正确。
- 两条修法二选一（涉及端侧与模型契约，需人工定）：固件在归一化前 LSB→g/dps（并同步
  `model_meta.json` 的 `note`），或让统计量按 LSB 输出。本次未改动 `OfflineDevice/` 与
  `parity_check.py` 的数值路径。

## 8. 清理

验证用的合成会话、`data/processed`、`artifacts/`（合成数据训出的模型）、`data/field` 报告、
会话 PNG 均已删除——避免合成数据衍生的模型被 `gen_c_array.py` 误嵌入端侧。
