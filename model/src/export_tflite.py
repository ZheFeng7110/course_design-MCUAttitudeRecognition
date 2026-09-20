"""TFLite 全整数量化导出。

representative dataset 取训练集子集；生成
    model/artifacts/model.tflite
    model/artifacts/model_meta.json（输入 scale/zero_point、标签序表）
验证门: model.tflite < 300KB；int8 相对 float 精度损失 < 2%。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import tensorflow as tf

DATA = Path(__file__).resolve().parent.parent / "data" / "processed"
ART = Path(__file__).resolve().parent.parent / "artifacts"


def main() -> None:
    x_train = np.load(DATA / "train.npy")
    y_train = np.load(DATA / "train_labels.npy")
    x_test = np.load(DATA / "test.npy")
    y_test = np.load(DATA / "test_labels.npy")

    model = tf.keras.models.load_model(ART / "attitude_model.keras")

    # 归一化（与 preprocess 一致，训练侧推断时同样处理）
    norm = json.loads((DATA / "norm.json").read_text(encoding="utf-8"))
    mean = np.array(norm["mean"], np.float32)
    std = np.array(norm["std"], np.float32)
    normed = lambda x: (x - mean) / std  # noqa: E731

    def representative():
        idx = np.random.default_rng(0).choice(len(x_train), size=min(500, len(x_train)), replace=False)
        for i in idx:
            yield [normed(x_train[i:i + 1]).astype(np.float32)]

    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    converter.representative_dataset = representative
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    converter.inference_input_type = tf.int8
    converter.inference_output_type = tf.int8
    tflite_model = converter.convert()

    out_path = ART / "model.tflite"
    out_path.write_bytes(tflite_model)
    print(f"model.tflite {len(tflite_model) / 1024:.1f} KB")
    if len(tflite_model) >= 300 * 1024:
        print("[未达标] 模型 ≥ 300KB")

    # ---- 量化参数与 int8 精度对照 ----
    interp = tf.lite.Interpreter(model_content=tflite_model)
    interp.allocate_tensors()
    inp = interp.get_input_details()[0]
    out_d = interp.get_output_details()[0]

    # float 基线
    pred_f = np.argmax(model.predict(normed(x_test), verbose=0), axis=1)

    # int8 推理
    scale, zp = inp["quantization"]
    pred_q = []
    for i in range(0, len(x_test), 64):
        batch = normed(x_test[i:i + 64]) / scale + zp
        interp.resize_tensor_input(inp["index"], batch.shape)
        interp.allocate_tensors()
        interp.set_tensor(inp["index"], np.clip(np.round(batch), -128, 127).astype(np.int8))
        interp.invoke()
        pred_q.append(np.argmax(interp.get_tensor(out_d["index"]), axis=1))
    pred_q = np.concatenate(pred_q)

    acc_f = float((pred_f == y_test).mean())
    acc_q = float((pred_q == y_test).mean())
    print(f"float acc={acc_f:.4f}  int8 acc={acc_q:.4f}  损失={acc_f - acc_q:.4f}")
    if acc_f - acc_q >= 0.02:
        print("[未达标] int8 精度损失 ≥ 2%")

    meta = {
        "labels": ["walk", "run", "fall"],
        "input": {"shape": [1, 200, 6], "dtype": "int8",
                  "scale": float(scale), "zero_point": int(zp),
                  "normalization": {"mean": norm["mean"], "std": norm["std"]}},
        "output": {"dtype": "int8", "scale": float(out_d["quantization"][0]),
                   "zero_point": int(out_d["quantization"][1])},
        "note": "端侧: x_norm=(x_lsb-mean)/std; int8=round(x_norm/scale)+zero_point",
    }
    (ART / "model_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"元数据 -> {ART / 'model_meta.json'}")


if __name__ == "__main__":
    main()
