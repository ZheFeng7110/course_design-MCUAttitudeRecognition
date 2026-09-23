# 公开数据集适配（MobiAct v2 / MobiFall v2 + SisFall）

日期：2026-09-23
范围：`model/src/preprocess.py` 与公开数据集实测口径对齐；删除 `model/src/download_data.py`。

## 1. 背景

计划 Phase 6（`.agents/plan/bmi088-tflm-pipeline-plan.md`）原先把"数据集下载"写成脚本步骤
（Assumption #5：下载受限则打印手动指引）。用户已把两份公开数据集下载并**提交进 git**
（`model/data/external/`，6022 个受控文件），来源见 `model/data/external/data_link.md`。
因此下载脚本失去意义，改为**按真实目录树/文件格式/量纲适配预处理**。

上一次会话在 `2026-09-20-model-python-linux-support.md` §8 记录了"未核实"的疑问：
`load_mobiact()` 未做量纲换算，而 MobiAct 官方文档给的是 m/s² 与 rad/s。本次用数据核实并修正。

## 2. 数据实测形态

| 项 | MobiAct v2 / MobiFall v2 | SisFall |
|---|---|---|
| 目录 | `<root>/sub<N>/{ADL,FALLS}/<CODE>/` | `<root>/<受试者>/` |
| 文件 | `<CODE>_{acc,gyro,ori}_<subj>_<trial>.txt`（1890 个数据文件 + `DataDescribe.txt`） | `<CODE>_<受试者>_R<NN>.txt`（4094 个） |
| 头部 | `#` 注释行 + **`@DATA` 标记行**，CRLF 行尾 | 无 |
| 正文 | `timestamp(ns),x,y,z` | 每行 9 个整数，**行尾带 `;`** |
| 通道 | 加速度 ≈94Hz、陀螺 ≈200Hz（同一起始时钟，试验长度 5~300s） | 200Hz；ADXL345 xyz、ITG3200 xyz、MMA8451Q xyz |
| 规模 | 24 个受试者（sub1~21、29~31）；ADL 只在其中 9 个受试者（sub1/sub6 无 ADL） | 33 个受试者（SA01~23、SE01~09、SE15）；比 Readme 的 4510 文件少 416（本镜像缺 SE10~SE14） |
| 采样率实测 | 加速度中位 93.9Hz、陀螺中位 200.1Hz（由 ns 时间戳反推，与文档 200Hz 一致 → 时间戳确为 ns） | Readme 声明 200Hz 等间隔 |

原实现的三处硬伤（都会静默产出错数据）：

1. `load_mobiact()` 扫的是 `<root>/<活动代码>_<试验>/accelerometer.txt`，与实际目录树不符 → 加载 0 条；
   且列名假设 `time_s/seconds/...`，实际的列名是 `timestamp`，单位 ns，原换算 `(t-t0)/1000` 按 ms 处理 → 时间轴错 10⁶ 倍。
2. `load_sisfall()` 取 `f.stem.split("_")[1]` 作活动代码，而实际命名是 `D01_SA01_R01.txt` →
   拿到的是受试者号 `SA01`，`startswith("S")` 恒真 → **全部 4094 个文件都被打成 fall**；
   陀螺还取错列（`raw[:, 6:9]` 是 MMA8451Q 的加速度，不是 ITG3200）。
3. `np.loadtxt(delimiter=",")` 解析 SisFall 行尾 `;` 会直接抛错（把 `-279;` 当数字）。

## 3. 量纲换算与证据

统一口径为 **g / dps**（与 `norm.json`、`model_meta.json`、端侧 `attitude_quantize.h` 一致）。

| 数据集 | 换算 | 依据 | 实测交叉验证 |
|---|---|---|---|
| MobiAct acc | `÷9.80665` | `DataDescribe.txt`：x,y,z (m/s²) | 静止段合矢量均值 9.71 m/s² → 0.990 g |
| MobiAct gyro | `×180/π` | `DataDescribe.txt`：x,y,z (rad/s) | 原始 \|max\| 8.62 rad/s → 494 dps |
| SisFall ADXL345 | `×32/2¹³` = 3.90625e-3 g/LSB | Readme：13bit、±16g；`(2·Range)/2^Resolution` | 合矢量均值 263.6 bit → 1.030 g |
| SisFall ITG3200 | `×4000/2¹⁶` = 1/16.384 dps/LSB | Readme：16bit、±2000dps | 原始 \|max\| 32767 bit → 1999.9 dps（正好满量程） |

注意 ITG3200 有两种流行系数：datasheet 常见的 14.375 LSB/(dps) 与 Readme 公式给出的
16.384 LSB/dps。数据支持后者：32767 bit 按 16.384 恰好是 ±2000dps 满量程，按 14.375 会得到
2279dps（超出量程）。故采信 **16.384**（与设备 gyro 的 `GYR_LSB_PER_DPS` 也一致）。

换算正确性还体现在训练集统计量（`norm.json`）：`mean≈[-0.03,-0.45,-0.08, -0.5,1.4,-0.24]`、
`std≈[0.51,0.76,0.56, 44.1,39.7,31.2]`；acc 合矢量均值 1.069 g、gyro 合矢量中位 80 dps。
若漏掉 m/s²→g 或 rad/s→dps 换算，这里会出现 9.8 倍/57 倍量级的偏移。

## 4. 标签映射

保持 walk/run/fall 三类口径（不引入第 4 类）：

| 数据集 | walk | run | fall | 丢弃 |
|---|---|---|---|---|
| MobiAct | WAL | JOG | FOL、FKL、BSC、SDL | STD/JUM/STU/STN/SCH/CSI/CSO（站/跳/上下楼/坐/上下车） |
| SisFall | D01、D02（慢走、快走） | D03、D04（慢跑、快跑） | F01~F15 | D05~D19（上下楼/坐立/躺/弯腰/绊/跳） |

取舍说明：

- 上下楼（STU/STN、D05/D06）**不并入 walk**：信号与平地步行差异明显，且当初设计即为丢弃 ADL，
  这里不扩大范围；若日后要覆盖上下楼，应作为独立类别而不是混进 walk。
- D02（快走）与 D03（慢跑）是步速连续谱上的相邻档，标签边界本身模糊，是 walk/run 混淆的下限来源之一。
- SisFall 取 ADXL345（±16g，与设备 ±24g 最接近）而非 MMA8451Q（±8g）。

## 5. 代码改动

`model/src/preprocess.py`（重写加载层，其余保持）：

- 目录常量改为真实路径 `MOBIACT_ROOT` / `SISFALL_ROOT`，文件名用正则解析（`MOBIACT_FILE`/`SISFALL_FILE`），
  非数据文件（`DataDescribe.txt`、`Readme.txt`、`desktop.ini`）自然跳过。
- 新增 `read_mobiact()`（跳过 `#`/`@DATA`/空行）、`read_sisfall()`（先去掉 `;` 与 `,` 再解析成 (N,9)）。
- 新增 `align_imu()`：acc 与 gyro 起止时间、采样率都不同，取**时间交集**重采样到同一 100Hz 网格再拼接；
  `resample()` 增加 `t_start/t_end` 与乱序防御。MobiAct 时间戳按 ns 处理（`×1e-9`）。
- 三个 loader 统一返回 `Trial(series, label, group)`；`group` = `mobiact/sub<N>`、`sisfall/<受试者>`、
  `self/<会话>`。
- **划分改为按 group 分组划分**（`split_by_group()`）：步长 50 意味着同一试验内相邻窗口重叠 75%，
  窗口级随机划分会把近乎相同的窗口同时放进训练与测试，指标虚高。分组后一个受试者只出现在一个划分里，
  评估才是"未见过的人"的口径。组规模按 70/15/15 贪心分配（大组优先，同规模组随机归属，种子 42）。
- `norm.json` 的 `note` 订正为与 `model_meta.json` 一致的口径：端侧先 LSB→物理量，再 `(x-mean)/std`。
- 删除未使用的 `CHANNELS` 常量（通道序已在模块 docstring 与端侧约定中）。

其他：

- **删除 `model/src/download_data.py`**（数据集已入库，脚本失去意义）。
- `model/data/external/data_link.md` 补充本地目录布局与量纲说明。

## 6. 验证（本机 Linux，实测）

环境：`uv run`（Python 3.10.21 / TF 2.10.1 同 `2026-09-20` 文档）。

```
$ uv run src/preprocess.py
MobiAct: 324 个试验入集；跳过 306 个非三类试验、0 个数据不完整试验
SisFall: 1922 个文件入集；跳过 2172 个非三类 ADL
窗口总数 85119；类别分布 walk/run/fall = [18093, 13868, 53158]；分组 56 个
  train: 30 组 / 59618 窗口（目标 59583）
  val:   12 组 / 12827 窗口（目标 12768）
  test:  14 组 / 12674 窗口（目标 12768）
输出 -> model/data/processed        # 耗时 8.6s，三个 npy 合计 391MB
```

- 入集规模校验：MobiAct 324 个试验 = 跌倒 288（FOL/FKL/BSC/SDL 各 72）+ JOG 27 + WAL 9；
  SisFall 1922 个文件 = 跌倒 1798（F01~F15; F01/F10 各 119）+ D01~D04 恰 124。
- 类别分布与源数据一致：SisFall 跌倒文件 1798 个 vs 走/跑 124 个 → 加上 MobiAct 后 fall 占 62%。

```
$ uv run src/train.py          # 30 epoch，约 42s（CPU）
val  acc=0.9121  F1 = walk 0.8606 / run 0.9249 / fall 0.9291
test acc=0.8031  F1 = walk 0.7360 / run 0.7679 / fall 0.8558
$ uv run src/export_tflite.py
model.tflite 4.9 KB   float acc=0.8031  int8 acc=0.8049  损失=-0.0018
```

- 端到端打通：预处理 → 训练 → 全 int8 导出，int8 精度损失 < 2%（实测为负，量化无损失）。
- 测试集混淆矩阵（归一化，行=真值）：`[[0.62,0.12,0.26],[0.06,0.74,0.21],[0.02,0.00,0.98]]`
  —— 主要误差是走/跑被判成跌倒（假跌倒 26%/21%）。
- 按来源拆分测试集：MobiAct acc 0.784（run F1 仅 0.48）、SisFall acc 0.811（walk F1 0.72）。

## 7. 未达标项与后续（不在本次范围）

- 计划 Phase 6 的验证门是 **per-class F1 ≥ 0.85**，当前公开数据单独训练**未达标**
  （walk 0.736 / run 0.768 / fall 0.856）。注意这是首次用真实数据、无泄漏划分得到的数字；
  此前的划分方式（窗口级随机）会因 75% 重叠而系统性虚高，不可作为基线。
- 已排除"类别不平衡"是主因：按训练集频次加逆频权重（1.87/2.27/0.49）重训，
  run F1 0.768→0.825、fall 0.856→0.843、walk 0.736→0.708，总体 acc 不变（0.8008），
  即收益是类别间腾挪而非整体改善。**故本次不引入 class_weight**。
- 结论：瓶颈在模型容量/特征（GAP 抹掉周期结构）与跨数据集域差（MobiAct 手机口袋 vs SisFall 腰部固定，
  轴系朝向不同），属于 Phase 6 模型设计 / Phase 8 自采集微调的范畴，需另行决策。

## 8. 产物与仓库状态

- `model/data/processed/`（391MB）、`model/artifacts/`（keras + tflite + 报告）均为可再生产物，
  目前未加入 `.gitignore`，是否入库由用户决定（`uv run src/preprocess.py` + `uv run src/train.py`
  可原样重建）。
- 已删除：`model/src/download_data.py`。
