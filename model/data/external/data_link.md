# 数据集下载来源

| 路径                                                                                       | 链接                                                                    |
|--------------------------------------------------------------------------------------------|-------------------------------------------------------------------------|
| [MobiAct_Dataset_v2.0-MobiFall_Dataset_v2.0](./MobiAct_Dataset_v2.0-MobiFall_Dataset_v2.0) | https://github.com/yehowlong/MobiAct_Dataset_v2.0-MobiFall_Dataset_v2.0 |
| [SisFall](./SisFall)                                                                       | https://github.com/BIng2325/SisFall/releases/tag/dataset                |

## 本地布局与口径（`model/src/preprocess.py` 按此解析）

```
MobiAct_Dataset_v2.0-MobiFall_Dataset_v2.0/
    DataDescribe.txt                      # 活动/受试者/传感器说明
    sub<N>/{ADL,FALLS}/<CODE>/<CODE>_{acc,gyro,ori}_<subj>_<trial>.txt
                                          # 头部 `#` 注释 + `@DATA` 标记，CRLF
SisFall/SisFall_dataset/
    Readme.txt
    <受试者>/<CODE>_<受试者>_R<NN>.txt    # 每行 9 个整数、行尾带 `;`
```

- MobiAct 时间戳单位 ns；加速度 ≈94Hz、陀螺 ≈200Hz，两者按时间交集对齐到 100Hz。
- MobiAct 量纲：acc m/s²、gyro rad/s（`DataDescribe.txt`）→ 预处理换算成 g / dps。
- SisFall 200Hz；9 列 = ADXL345 xyz | ITG3200 xyz | MMA8451Q xyz（取前 6 列）。
- SisFall 量纲：ADXL345 13bit ±16g → 32/2¹³ g/LSB；ITG3200 16bit ±2000dps → 4000/2¹⁶ dps/LSB
  （`Readme.txt` 的 `(2·Range)/2^Resolution`；用满量程数据核实过，见 `.agents/docs/2026-09-23-public-dataset-adaptation.md`）。
