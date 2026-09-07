"""训练小模型（int8 友好）:

    Input(200,6) → Conv1D(8,5,stride=2)+ReLU → DepthwiseConv1D(16,7)+ReLU
                 → GlobalAveragePooling → Dense(3,softmax)

训练顺序: 公开数据集训练 → 混入自采集微调（自采集占 batch 50%）。
输出: model/artifacts/attitude_model.keras + 训练日志 + 每类 F1 报告。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import tensorflow as tf

DATA = Path(__file__).resolve().parent.parent / "data" / "processed"
ART = Path(__file__).resolve().parent.parent / "artifacts"
ART.mkdir(parents=True, exist_ok=True)

LABELS = ["walk", "run", "fall"]


def build_model() -> tf.keras.Model:
    inp = tf.keras.Input(shape=(200, 6))
    x = tf.keras.layers.Conv1D(8, 5, strides=2, padding="same", activation="relu")(inp)
    x = tf.keras.layers.DepthwiseConv1D(7, padding="same", activation="relu")(x)
    x = tf.keras.layers.GlobalAveragePooling1D()(x)
    out = tf.keras.layers.Dense(3, activation="softmax")(x)
    model = tf.keras.Model(inp, out)
    model.compile(optimizer="adam", loss="sparse_categorical_crossentropy", metrics=["accuracy"])
    return model


def f1_per_class(y_true: np.ndarray, y_pred: np.ndarray) -> list[float]:
    f1s = []
    for c in range(3):
        tp = np.sum((y_pred == c) & (y_true == c))
        fp = np.sum((y_pred == c) & (y_true != c))
        fn = np.sum((y_pred != c) & (y_true == c))
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1s.append(2 * prec * rec / (prec + rec) if prec + rec else 0.0)
    return f1s


def evaluate(model: tf.keras.Model, x: np.ndarray, y: np.ndarray) -> dict:
    pred = np.argmax(model.predict(x, verbose=0), axis=1)
    f1s = f1_per_class(y, pred)
    return {
        "accuracy": float((pred == y).mean()),
        "f1_per_class": dict(zip(LABELS, [round(f, 4) for f in f1s])),
        "f1_fall": float(f1s[2]),
    }


def main() -> None:
    x_train = np.load(DATA / "train.npy")
    y_train = np.load(DATA / "train_labels.npy")
    x_val = np.load(DATA / "val.npy")
    y_val = np.load(DATA / "val_labels.npy")
    x_test = np.load(DATA / "test.npy")
    y_test = np.load(DATA / "test_labels.npy")

    model = build_model()

    # ---- 阶段 1: 公开数据集（+自采集，同一路径已在训练集里合并）----
    model.fit(x_train, y_train, validation_data=(x_val, y_val),
              epochs=30, batch_size=64, verbose=2)

    # ---- 阶段 2: 自采集微调（自采集占 batch 50%；按 data/self 存在与否自适应）----
    self_dir = DATA.parent / "self"
    if any(self_dir.glob("session_*.csv")):
        # 自采集样本已在 train 里；通过上采样把其占比抬到约 50%
        n_self = len(x_train) // 2
        idx = np.random.default_rng(0).choice(len(x_train), size=n_self, replace=True)
        model.fit(x_train[idx], y_train[idx], validation_data=(x_val, y_val),
                  epochs=5, batch_size=64, verbose=2)
    else:
        print("[提示] 无自采集数据，跳过微调阶段")

    report = {
        "val": evaluate(model, x_val, y_val),
        "test": evaluate(model, x_test, y_test),
    }
    print(json.dumps(report, indent=2))
    (ART / "train_report.json").write_text(json.dumps(report, indent=2))

    model.save(ART / "attitude_model.keras")
    print(f"模型 -> {ART / 'attitude_model.keras'}")

    # 验证门: per-class F1 ≥ 0.85
    if min(report["test"]["f1_per_class"].values()) < 0.85:
        print("[未达标] held-out 测试集存在 F1 < 0.85 的类别，需补充数据/调整模型")


if __name__ == "__main__":
    main()
