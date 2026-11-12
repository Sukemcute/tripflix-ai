# TF32 — Kế hoạch thử ViSoBERT cho kiểm duyệt tiếng Việt

Mục tiêu: đo ViSoBERT bắt thêm bao nhiêu câu **quấy rối (`harassment`) và thù ghét (`hate`)** mà OpenAI bỏ sót, và đổi lại gắn cờ nhầm thêm bao nhiêu câu sạch. Chạy offline trên văn bản; giữ nguyên `/moderate`, regex của Core và cấu hình production.

## Chạy trên Google Colab

Mở [notebook Colab](../../notebooks/tf32-visobert-eval-colab.ipynb), upload file vào [Google Colab](https://colab.research.google.com/) và chọn **Runtime → Change runtime type → T4 GPU**. Chạy lần lượt các cell từ trên xuống. Notebook tự clone nhánh `develop`, tải checkpoint, chạy 30 câu, chạy 3.000 câu, nhận file cache OpenAI qua hộp upload, tạo bảng so sánh và tải xuống một file ZIP kết quả.

Khi notebook yêu cầu cache OpenAI, chọn file `evals/moderation/.eval_cache.json` trên máy. File này bị Git ignore nên không có trong bản clone Colab.

## 1. Chốt model và baseline

- Dùng [`nd-khoa/vihsd-uit-visobert-v2`](https://huggingface.co/nd-khoa/vihsd-uit-visobert-v2), revision `5e8e892f45bf3d52bc3d4c780b6235b65714f07b`. Đây là bản fine-tune cho ViHSD; checkpoint gốc [`uitnlp/visobert`](https://huggingface.co/uitnlp/visobert) chỉ là `fill-mask`. Config của bản fine-tune ghi `LABEL_0/1/2`; theo model card, thứ tự tương ứng là `clean/offensive/hate`.
- Quy đổi thành `score_toxic = P(offensive) + P(hate)` sau softmax. Lưu cả ba xác suất để phân tích, không diễn giải điểm này như xác suất vi phạm mọi loại chính sách.
- Baseline lịch sử: [`vi_3k.jsonl`](../../evals/moderation/vi_3k.jsonl) có 1.500 toxic và 1.500 clean. Cache cục bộ `evals/moderation/.eval_cache.json` đã đối chiếu đủ 3.000 ID và nội dung, cùng model `omni-moderation-latest`: **TP 757, FN 743, FP 86, TN 1.414; F1 64,62%, recall 50,47%, FPR 5,73%**. Riêng `harassment`: 151/385; `hate`: 184/267. Xem [báo cáo OpenAI](TF32-eval-moderation-vi-3k.md).

## 2. Chạy thử 30 câu, rồi chạy 3.000 câu

Chạy các lệnh sau bằng PowerShell từ thư mục `tripflix-ai`. Môi trường thử nghiệm và kết quả nằm ngoài repo; không cần API key. Lần đầu cần mạng để cài thư viện và tải checkpoint, còn nội dung câu được xử lý trên máy.

```powershell
$evalDir = Join-Path $env:LOCALAPPDATA 'Tripflix\visobert-eval'
New-Item -ItemType Directory -Force -Path $evalDir | Out-Null
uv venv --python 3.12 (Join-Path $evalDir '.venv')
$evalPython = Join-Path $evalDir '.venv\Scripts\python.exe'
uv pip install --python $evalPython --index https://download.pytorch.org/whl/cpu torch
uv pip install --python $evalPython 'transformers==4.51.0' 'tokenizers==0.21.2' sentencepiece safetensors
uv pip install --python $evalPython 'httpx>=0.27,<1' 'pydantic-settings>=2.6,<3' 'pyyaml>=6,<7'
uv pip freeze --python $evalPython

$env:VISOBERT_DATA = 'evals/moderation/vi_30.jsonl'
$env:VISOBERT_OUT = Join-Path $evalDir 'visobert-30.json'
```

Chạy block sau trong cùng cửa sổ PowerShell. Nó dùng `mask_pii` giống runner OpenAI, giữ dấu, emoji và teencode, và không ghi nội dung câu vào kết quả.

```powershell
@'
import hashlib
import json
import os
import time
from pathlib import Path

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from app.services.summary.pii import mask_pii

model_id = "nd-khoa/vihsd-uit-visobert-v2"
revision = "5e8e892f45bf3d52bc3d4c780b6235b65714f07b"
raw = Path(os.environ["VISOBERT_DATA"]).read_bytes()
rows = [json.loads(line) for line in raw.decode("utf-8-sig").splitlines() if line.strip()]
assert rows and len({r["id"] for r in rows}) == len(rows)

tokenizer = AutoTokenizer.from_pretrained(model_id, revision=revision, trust_remote_code=False)
model, info = AutoModelForSequenceClassification.from_pretrained(
    model_id, revision=revision, trust_remote_code=False,
    use_safetensors=True, output_loading_info=True,
)
assert not info["missing_keys"] and not info["mismatched_keys"], info
assert model.config.num_labels == 3
model.eval()

predictions = {}
start = time.perf_counter()
with torch.inference_mode():
    for offset in range(0, len(rows), 16):
        batch = rows[offset:offset + 16]
        inputs = tokenizer([mask_pii(r["text"]) for r in batch], return_tensors="pt",
                           padding=True, truncation=True, max_length=256)
        probs = model(**inputs).logits.softmax(dim=-1)
        assert torch.isfinite(probs).all()
        for row, (clean, offensive, hate) in zip(batch, probs.tolist(), strict=True):
            predictions[row["id"]] = dict(clean=clean, offensive=offensive, hate=hate,
                                          toxic=offensive + hate)
elapsed = time.perf_counter() - start
result = dict(model=model_id, revision=revision, sha256=hashlib.sha256(raw).hexdigest(),
              device="cpu", batch_size=16, max_length=256, seconds=elapsed,
              predictions=predictions)
with Path(os.environ["VISOBERT_OUT"]).open("x", encoding="utf-8") as output:
    json.dump(result, output, indent=2, allow_nan=False)
print(f"{len(predictions)} predictions in {elapsed:.2f}s ({len(predictions) / elapsed:.1f} rows/s)")
'@ | & $evalPython -
```

Kiểm tra đủ 30 ID, xác suất hữu hạn, và đọc vài câu sạch/xúc phạm/thù ghét để phát hiện lỗi ánh xạ nhãn rõ ràng. Nếu pass, đặt lại hai biến dưới đây rồi chạy lại nguyên block Python. Mỗi lượt chạy dùng một tên output mới; script chủ động không ghi đè.

```powershell
$env:VISOBERT_DATA = 'evals/moderation/vi_3k.jsonl'
$env:VISOBERT_OUT = Join-Path $evalDir 'visobert-3k.json'
```

## 3. So sánh trên cùng mẫu

Với `VISOBERT_DATA` và `VISOBERT_OUT` đang trỏ vào lượt 3k, block sau dùng lại hàm tính điểm của repo và đối chiếu từng ID. `0.50` chỉ là ngưỡng báo cáo ban đầu, chưa phải ngưỡng đã hiệu chỉnh.

```powershell
$env:VISOBERT_THRESHOLD = '0.50'
@'
import hashlib
import json
import os
from pathlib import Path

from app.clients.moderation.base import ModerationResult
from evals.run_moderation_eval import compute_metrics, format_report

raw = Path(os.environ["VISOBERT_DATA"]).read_bytes()
rows = [json.loads(line) for line in raw.decode("utf-8-sig").splitlines() if line.strip()]
run = json.loads(Path(os.environ["VISOBERT_OUT"]).read_text(encoding="utf-8"))
cache = json.loads(Path("evals/moderation/.eval_cache.json").read_text(encoding="utf-8-sig"))
assert run["sha256"] == hashlib.sha256(raw).hexdigest()
scores = run["predictions"]
assert set(scores) == {r["id"] for r in rows} and len(rows) == len(scores)
threshold = float(os.environ["VISOBERT_THRESHOLD"])
assert 0 <= threshold <= 1
results = {name: {} for name in ("OpenAI", "ViSoBERT", "OpenAI OR ViSoBERT")}
for row in rows:
    key = row["id"]
    entry = cache[key]
    assert entry["text"] == row["text"] and entry["model"] == "omni-moderation-latest", key
    score = scores[key]["toxic"]
    extra = score >= threshold
    results["OpenAI"][key] = ModerationResult(entry["flagged"], entry["categories"],
                                             entry["scores"], entry["model"])
    results["ViSoBERT"][key] = ModerationResult(extra, {}, {"toxic": score}, run["model"])
    results["OpenAI OR ViSoBERT"][key] = ModerationResult(
        entry["flagged"] or extra, {}, {"visobert_toxic": score}, "hybrid")
baseline = compute_metrics(rows, results["OpenAI"])
for name, predictions in results.items():
    metrics = compute_metrics(rows, predictions)
    print(format_report(metrics, name))
    print(f"FPR: {metrics['fp'] / (metrics['fp'] + metrics['tn']):.2%}; "
          f"delta TP={metrics['tp'] - baseline['tp']:+d}; delta FP={metrics['fp'] - baseline['fp']:+d}\n")
'@ | & $evalPython -
```

Chốt danh sách test trước khi đọc lỗi để chỉnh ngưỡng hoặc model. Trên dev, đọc kỹ các ID mà ViSoBERT gắn cờ còn OpenAI bỏ qua: tách câu vi phạm bắt thêm theo `harassment`/`hate` và câu sạch bắt nhầm theo `slang`, `slang_praise`, `safety`, `complaint`. Kiểm tra riêng recall của `threat`, `violence`, `sexual`, `self_harm` để thấy khoảng trống. Ghi tốc độ CPU và batch size; nếu đánh giá khả năng phục vụ trực tiếp, đo thêm độ trễ p50/p95 cho batch 1 sau warm-up, không so thời gian đọc cache với thời gian suy luận.

## 4. Hiệu chỉnh và quyết định

1. **Chia dữ liệu trước khi chọn ngưỡng.** Bộ 3k là dữ liệu tổng hợp từ khoảng 1.429 câu trước biến đổi, nên dùng để đối chiếu lịch sử. Chọn ngưỡng trên một tập dev, nhóm mọi biến thể theo câu gốc/template. Dùng mẫu đã chốt nhãn từ [đợt rà soát 240 câu](../../evals/moderation/quality_review/QUALITY_REVIEW.md) làm điểm xuất phát cho test; loại các họ câu đã dùng để chọn ngưỡng hoặc soi lỗi nhằm chỉnh model. Nếu không còn đủ mẫu độc lập, bổ sung câu Tripflix đã khử thông tin cá nhân và duyệt nhãn. Chưa đủ mẫu thì ghi kết quả là sơ bộ.
2. **Giữ nguyên ngưỡng khi chạy test.** Trên dev, chọn ngưỡng bắt được nhiều `harassment` + `hate` nhất trong giới hạn bắt nhầm cho phép; ghi ngưỡng và số mẫu trước khi xem kết quả test. Với câu chỉ sửa nhãn nhưng giữ nguyên nội dung, có thể chấm lại cache; nếu sửa câu hoặc thêm câu mới, cần kết quả OpenAI tương ứng với đúng input. Không chấm hai model trên hai tập khác nhau.
3. **Mốc đề xuất để thử tiếp:** trên test độc lập, phương án kết hợp tăng recall `harassment` + `hate` **ít nhất 10 điểm phần trăm** và tăng FPR trên câu sạch **không quá 1 điểm phần trăm** so với OpenAI trên cùng tập. Ghi cả tử số/mẫu số. Nếu không đạt, phân loại nguyên nhân (ngưỡng, nhãn hay lệch dữ liệu) trước khi quyết định có fine-tune hay không.

Đầu ra cần lưu: file điểm theo ID, model/revision, hash dataset, phiên bản thư viện, ngưỡng đã khóa, bảng ba phương án và vài ID lỗi tiêu biểu. Kết quả tốt là cơ sở để thử offline tiếp. Trước khi cân nhắc production, xác minh quyền dùng checkpoint và model nền: [paper ViSoBERT](https://aclanthology.org/2023.emnlp-main.315.pdf) ghi model gốc phát hành cho mục đích nghiên cứu.
