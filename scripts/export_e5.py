"""Fetch the pinned e5-small ONNX export and quantize it to INT8 (build environment only).

Needs `onnx` besides the runtime deps; no torch: the checkpoint already ships an ONNX graph.
"""

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path

import numpy as np

from app.clients.embedding import FILES, MODEL_ID, REVISION, load_embedder, verify_bundle

BASE = f"https://huggingface.co/{MODEL_ID}/resolve/{REVISION}/onnx"
# Same checks used to accept the bundle: INT8 must keep near-identical directions.
SAMPLES = [
    "Săn mây trên đỉnh Tà Xùa lúc 5 giờ sáng",
    "Ăn bún chả ngon xỉu ở quán vỉa hè Hà Nội",
    "Resort yên tĩnh nhất Phú Quốc, hồ bơi vô cực",
]


def export(out: Path) -> None:
    from onnxruntime.quantization import QuantType, quantize_dynamic

    if out.exists():
        raise FileExistsError(f"Export target already exists: {out}")
    out.mkdir(parents=True)
    fp32_path = out / "model.fp32.onnx"
    urllib.request.urlretrieve(f"{BASE}/model.onnx", fp32_path)
    urllib.request.urlretrieve(f"{BASE}/tokenizer.json", out / "tokenizer.json")
    quantize_dynamic(
        fp32_path,
        out / "model.onnx",
        weight_type=QuantType.QInt8,
        per_channel=True,
        op_types_to_quantize=["MatMul", "Gemm", "Gather"],
    )

    def write_manifest(model_file: str) -> None:
        files = {}
        for name in FILES:
            source = out / (model_file if name == "model.onnx" else name)
            with source.open("rb") as stream:
                files[name] = hashlib.file_digest(stream, "sha256").hexdigest()
        manifest = {"model": MODEL_ID, "revision": REVISION, "pad_id": 1, "files": files}
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2), "utf-8")

    int8 = (out / "model.onnx").read_bytes()
    (out / "model.onnx").rename(out / "model.int8.onnx")
    fp32_path.rename(out / "model.onnx")
    write_manifest("model.onnx")
    reference = load_embedder(out, threads=2, batch_size=8).embed(SAMPLES)
    (out / "model.onnx").unlink()
    (out / "model.int8.onnx").write_bytes(int8)
    (out / "model.int8.onnx").rename(out / "model.onnx")
    write_manifest("model.onnx")
    actual = load_embedder(out, threads=2, batch_size=8).embed(SAMPLES)
    agreement = (reference * actual).sum(axis=1)
    if agreement.min() < 0.98:
        raise ValueError(f"INT8 drifted from FP32: cosine {agreement.min():.4f}")
    manifest = verify_bundle(out)
    print(json.dumps(manifest | {"int8_vs_fp32_min_cosine": float(agreement.min())}))
    np.testing.assert_allclose(np.linalg.norm(actual, axis=1), 1, atol=1e-4)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    export(parser.parse_args().out)
