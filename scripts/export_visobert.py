"""Export the evaluated checkpoint to a verified CPU ONNX bundle (build environment only)."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from app.clients.moderation.visobert import FILES, LABELS, MODEL_ID, REVISION, verify_bundle


def export(out: Path) -> None:
    import onnxruntime as ort
    import torch
    from onnxruntime.quantization import QuantType, quantize_dynamic
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    if out.exists():
        raise FileExistsError(f"Export target already exists: {out}")
    torch.set_num_threads(2)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, revision=REVISION, trust_remote_code=False)
    model, info = AutoModelForSequenceClassification.from_pretrained(
        MODEL_ID,
        revision=REVISION,
        trust_remote_code=False,
        use_safetensors=True,
        output_loading_info=True,
        attn_implementation="eager",
    )
    if info["missing_keys"] or info["mismatched_keys"] or model.config.num_labels != 3:
        raise ValueError("Checkpoint weights or labels differ from the evaluated model")
    model.eval()

    class Logits(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.model = model

        def forward(self, input_ids, attention_mask):
            return self.model(input_ids=input_ids, attention_mask=attention_mask).logits

    examples = ["Phong nghi rong va thoang", "Mày đúng là đồ ngu"]
    encoded = tokenizer(
        examples, padding=True, truncation=True, max_length=256, return_tensors="pt"
    )
    out.mkdir(parents=True)
    fp32_path = out / "model.fp32.onnx"
    with torch.inference_mode():
        torch.onnx.export(
            Logits().eval(),
            (encoded["input_ids"], encoded["attention_mask"]),
            str(fp32_path),
            input_names=["input_ids", "attention_mask"],
            output_names=["logits"],
            dynamic_axes={
                "input_ids": {0: "batch", 1: "sequence"},
                "attention_mask": {0: "batch", 1: "sequence"},
                "logits": {0: "batch"},
            },
            opset_version=17,
            dynamo=False,
        )
    tokenizer.backend_tokenizer.save(str(out / "tokenizer.json"))
    model.eval()
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    session = ort.InferenceSession(str(fp32_path), options, providers=["CPUExecutionProvider"])
    for texts in (examples, ["Cảnh ngoài ban công đẹp vcl, mình thích buổi sáng ở đây"]):
        batch = tokenizer(texts, padding=True, truncation=True, max_length=256, return_tensors="pt")
        with torch.inference_mode():
            expected = model(**batch).logits.numpy()
        (actual,) = session.run(
            ["logits"], {k: batch[k].numpy() for k in ("input_ids", "attention_mask")}
        )
        np.testing.assert_allclose(actual, expected, atol=1e-4, rtol=1e-4)
    del session
    int8_path = out / "model.onnx"
    quantize_dynamic(
        fp32_path,
        int8_path,
        weight_type=QuantType.QInt8,
        per_channel=True,
        op_types_to_quantize=["MatMul", "Gemm", "Gather"],
    )
    if int8_path.stat().st_size >= fp32_path.stat().st_size * 0.3:
        raise ValueError("INT8 bundle did not shrink as expected")
    session = ort.InferenceSession(str(int8_path), options, providers=["CPUExecutionProvider"])
    (logits,) = session.run(
        ["logits"], {k: encoded[k].numpy() for k in ("input_ids", "attention_mask")}
    )
    probabilities = np.exp(logits - logits.max(axis=-1, keepdims=True))
    toxic = probabilities[:, 1:].sum(axis=-1) / probabilities.sum(axis=-1)
    np.testing.assert_array_equal(toxic >= 0.97, [False, True])
    fp32_path.unlink()
    files = {}
    for name in FILES:
        with (out / name).open("rb") as stream:
            files[name] = hashlib.file_digest(stream, "sha256").hexdigest()
    manifest = {
        "model": MODEL_ID,
        "revision": REVISION,
        "labels": LABELS,
        "max_length": 256,
        "pad_id": model.config.pad_token_id,
        "precision": "dynamic-int8",
        "files": files,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), "utf-8")
    verify_bundle(out)
    print(json.dumps(manifest))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    export(parser.parse_args().out)
