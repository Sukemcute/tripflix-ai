# TF28 — POST /embed cho gợi ý for-you (ngăn trải nghiệm từ caption)

- Notion: TF28 · Nhánh: `duy/TF28-embed-caption` · Người làm: Duy (dùng AI: có) · Ngày: 2026-11-19

## Đã làm

Nhiều bài trên TripFlix chỉ có caption, không có hashtag rõ ràng. Vì vậy bộ gợi ý for-you v1 ở `discovery` không xếp được các bài này vào ngăn trải nghiệm (biển, núi, ăn uống…).

Cách giải: core-api nhúng caption thành vector, rồi so cosine với câu mô tả từng ngăn. Endpoint `/embed` ở đây **chỉ biến văn bản thành vector**: không biết gì về ngăn và không lưu dữ liệu. Câu mô tả ngăn, ngưỡng và cache vector nằm ở core.

- `POST /embed` `{texts: string[1..64], mỗi câu ≤ 2.000 ký tự}` trả `{model, vectors: number[][384]}`. Vector là vector đơn vị, đúng thứ tự đầu vào.
  - Xác thực bằng service token của core, giống `/moderate` (chỉ `core-api` gọi được).
  - Thiếu bundle mô hình thì trả 503. Core coi mọi lỗi là "không có vector" và vẫn xếp ngăn bằng tag như cũ.
- Mô hình là `intfloat/multilingual-e5-small`, ghim revision `614241f6`.
  - Dùng bản ONNX có sẵn trong checkpoint, lượng tử hoá động INT8 (MatMul/Gemm/Gather theo kênh), giống cách ViSoBERT làm.
  - Không cần torch, kể cả lúc build. Runtime chỉ dùng `onnxruntime` và `tokenizers` đã có.
  - Bundle được kiểm SHA256 khi nạp.
- `scripts/export_e5.py` tải bản FP32, lượng tử hoá, rồi tự so INT8 với FP32. Cosine nhỏ nhất phải ≥ 0,98; thực đo 0,9963.
- Dockerfile thêm stage `e5-model`. Stage này chỉ cài `onnxruntime`, `onnx` và `tokenizers` để xuất bundle, rồi COPY vào `base` cạnh ViSoBERT.
- Cấu hình cho máy chủ 2 vCPU / 8 GB RAM dùng chung với các service khác:
  - 1 luồng, mỗi lần chỉ một lượt suy luận (có lock).
  - Tắt arena của onnxruntime để RAM không phình.
  - Chỉ nạp mô hình ở lần gọi `/embed` đầu tiên. Core chưa gọi thì không tốn RAM.

## Vì sao chọn e5-small

Đã đo trên 283 caption thật (YouTube Shorts + TikTok) ở thư mục thí nghiệm riêng của Duy. Nhãn do Claude gắn nháp theo luật "chỉ gắn khi chữ nói rõ"; có 49 caption không nói gì về trải nghiệm.

| Mô hình | Gán khi biên ≥ 0,02: phủ / đúng / gán bừa caption không rõ | Ghi chú |
|---|---|---|
| e5-large (Colab) | 0,53 / 1,00 / 0,00 | 24 lớp, chiều ẩn 1024. Quá nặng cho máy 2 vCPU chung |
| **e5-small (Colab fp16)** | 0,37 / 0,98 / 0,00 | |
| **e5-small ONNX INT8 (bản này)** | 0,36 / 0,98 / 0,02 | Gần như y hệt fp16 |
| Qwen3-0.6B / bge-m3 | 0,89 / 0,94 / 0,49 và 0,81 / 0,96 / 0,35 | Gán bừa quá nhiều, loại |

## Đối chiếu "Xong khi"

| Tiêu chí | Đạt | Bằng chứng |
|---|---|---|
| Nhanh bằng hoặc hơn ViSoBERT (~24 câu/giây) | Có | 1 luồng, tắt arena: 93 caption/giây. Bật arena: 129–170. Qua HTTP: 63 câu trong 0,27 giây |
| Vừa máy 2 vCPU / 8 GB chung | Có | RSS khoảng 440 MB và đứng yên sau batch dài. Tokenizer 250k từ chiếm khoảng 250 MB, mô hình 118 MB |
| INT8 không làm lệch quyết định | Có | Bảng trên. Cosine INT8 so FP32 ≥ 0,996 |
| Chỉ core gọi được, thiếu bundle không làm sập service | Có | `tests/test_embedding_api.py` |

## Kết quả kiểm tra

```
uv run ruff check .            → All checks passed!
uv run ruff format --check .   → 222 files already formatted
uv run pyright                 → 0 errors
uv run pytest -q               → 1060 passed, 7 skipped
docker build --target e5-model → thành công; model.onnx SHA256 739c8f25…dd717, trùng bản dựng ở máy
```

`scripts.export_openapi` đã chạy. `contracts/openapi/ai-service.json` chỉ thêm `/embed`, `EmbedRequest` và `EmbedResponse`.

## Cách kiểm lại

1. `uv run --with onnx python -m scripts.export_e5 --out app/models/e5_embedding`. Lệnh in manifest và cosine INT8 so FP32.
2. `uv run pytest tests/clients/test_embedding.py tests/test_embedding_api.py -q`
3. `docker build --target e5-model .`

## Ảnh / video

- Không đổi giao diện.

## Ảnh hưởng tới phần của người khác

- Repo `tripflix-ai` là của Bảo. Duy đồng ý mở PR để Bảo review.
- Chỉ **thêm**, không sửa logic có sẵn:
  - `app/main.py` thêm router.
  - `ModerationSettings` thêm `embedding_dir`. Endpoint dùng chung phần xác thực core với `/moderate`.
  - `Dockerfile` thêm stage `e5-model` và một dòng COPY. Dockerfile là cấu hình chung (Tech Lead), nên xin Bảo và Tech Lead xem.
  - `.gitignore`, `.dockerignore` loại thư mục bundle; `.env.example` thêm `EMBEDDING_DIR`.
- Không gọi LLM nên không phát `ai.usage.recorded`. Mô hình chạy cục bộ, không tốn tiền theo lượt gọi.
- Bên dùng là `discovery` ở tripflix-be (Duy). Phía BE làm trên nhánh `duy/TF28-for-you-uu-tien-dia-diem`.
