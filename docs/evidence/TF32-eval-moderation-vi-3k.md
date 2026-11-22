# SCRUM-75 — Đánh giá chất lượng kiểm duyệt tiếng Việt (3.000 mẫu)

- Jira: [SCRUM-75](https://tripflix.atlassian.net/browse/SCRUM-75) (liên quan: [SCRUM-36](https://tripflix.atlassian.net/browse/SCRUM-36) · TF32) · Nhánh: `trang/TF32-eval-moderation-vi-3k` · Người làm: Trang (dùng AI: có) · Ngày: 2026-11-10

## Bối cảnh và mục tiêu

Bộ kiểm thử cũ `vi_30.jsonl` (30 mẫu) quá nhỏ để đo chất lượng kiểm duyệt tiếng Việt một cách đáng tin cậy. Task này:
1. Xây dựng bộ dữ liệu đánh giá 3.000 mẫu có nhãn (`vi_3k.jsonl`: 1.500 độc hại + 1.500 sạch), bao gồm đầy đủ biến thể ngôn ngữ thực tế (có dấu, không dấu, teencode, emoji, chữ hoa, kéo dài nguyên âm cảm thán) và các trường hợp khó (hard negatives như tiếng lóng du lịch, cảnh báo an toàn, phàn nàn dịch vụ).
2. Nâng cấp script runner `evals/run_moderation_eval.py` hỗ trợ xử lý song song (concurrency pool), batching, lưu checkpoint tránh nghẽn API.
3. Đánh giá chất lượng trực tiếp với OpenAI `omni-moderation-latest` và rút ra bài học cho việc kết hợp giữa bộ lọc regex của Core API và mô hình AI.

## Đối chiếu "Xong khi"

| Tiêu chí | Đạt | Bằng chứng |
|---|---|---|
| Bộ dữ liệu ≥ 3000 mẫu có nhãn, không trùng lặp | Đạt | `vi_3k.jsonl` có đúng 3000 dòng (1.500 toxic + 1.500 clean), 3000 text phân biệt 100% |
| Runner chạy theo lô, không treo rate limit | Đạt | Concurrency semaphore 10, chạy 3000 mẫu trong 286.2s (10.5 req/s) |
| Đo đầy đủ Precision, Recall, phân tách theo kind | Đạt | Precision: 89.80%, Recall: 50.47%, F1: 64.62% |
| Báo cáo danh sách mẫu đoán sai và phân tích nguyên nhân | Đạt | Xem chi tiết bảng phân loại lỗi bên dưới |

## Kết quả đo lường chi tiết

- **Model:** `omni-moderation-latest`
- **Tổng số mẫu:** 3000 (Toxic: 1500, Clean: 1500)
- **Độ chính xác tổng thể (Accuracy):** 72.37%
- **Precision (Độ chuẩn xác khi bắt vi phạm):** 89.80% (Bắt trúng 757, bắt nhầm 86)
- **Recall (Độ phủ phát hiện vi phạm):** 50.47% (Bắt 757/1500 vi phạm, lọt 743)
- **F1 Score:** 64.62%

### Bảng kết quả theo từng nhóm (Kind)

| Nhóm (Kind) | Loại | Tổng số | Đoán đúng | Tỷ lệ đúng | Số lỗi | Đánh giá |
|---|---|---|---|---|---|---|
| `beach` | CLEAN | 167 | 163 | 97.60% | 4 | Tốt |
| `complaint` | CLEAN | 229 | 229 | 100.00% | 0 | Tốt |
| `harassment` | TOXIC | 385 | 151 | 39.22% | 234 | Cần core regex hỗ trợ |
| `hate` | TOXIC | 267 | 184 | 68.91% | 83 | Chấp nhận được |
| `neutral` | CLEAN | 237 | 237 | 100.00% | 0 | Tốt |
| `safety` | CLEAN | 204 | 174 | 85.29% | 30 | Tốt |
| `self_harm` | TOXIC | 189 | 109 | 57.67% | 80 | Cần core regex hỗ trợ |
| `sexual` | TOXIC | 186 | 8 | 4.30% | 178 | Cần core regex hỗ trợ |
| `slang` | CLEAN | 226 | 184 | 81.42% | 42 | Tốt |
| `slang_praise` | CLEAN | 437 | 427 | 97.71% | 10 | Tốt |
| `threat` | TOXIC | 316 | 201 | 63.61% | 115 | Chấp nhận được |
| `violence` | TOXIC | 157 | 104 | 66.24% | 53 | Chấp nhận được |

## Phân tích các trường hợp nhận định sai (False Positives & False Negatives)

### 1. Bắt nhầm câu sạch (False Positives - Clean bị flag)
Mô hình AI đa ngôn ngữ thường bị nhạy cảm quá mức với các từ mang tính bạo lực hoặc tự hại trong thành ngữ/tiếng lóng Việt Nam:
- **Tiếng lóng (`slang`):** Các câu như *"nóng muốn chết..."* bị gắn cờ `self-harm`, hoặc *"giá vé cắt cổ... chém khách..."* bị gắn cờ `violence`.
- **Cảnh báo an toàn (`safety`):** Các câu cảnh báo như *"bị sứa đốt..."*, *"trơn trượt té ngã..."* đôi khi bị xếp vào `violence`.

### 2. Bỏ sót câu độc hại (False Negatives - Toxic bị lọt)
- **Quấy rối & Đe dọa tiếng Việt không dấu / teencode (`harassment`, `threat`):** Khi người dùng viết tắt (`ko`, `dc`, `m`) hoặc bỏ dấu, điểm confidence của OpenAI giảm xuống dưới ngưỡng mặc định.
- **Gạ gẫm tình dục tiếng Việt ngầm (`sexual`):** Các từ ngữ mang tính ẩn dụ như *"anh chuyển khoản liền"*, *"ngủ với nhiều người"* có điểm category `sexual` khoảng 0.15–0.30, chưa vượt qua ngưỡng flag mặc định của OpenAI.

## Kết luận & Khuyến nghị cho Core API (TF32)

1. **Không thể dựa 100% vào AI:** Mô hình `omni-moderation-latest` rất mạnh về hình ảnh và các từ ngữ thù ghét/bạo lực rõ ràng, nhưng với tiếng Việt đời thường và teencode, tỷ lệ bỏ sót đòi hỏi **Core API phải duy trì bộ lọc regex tĩnh chạy song song**.
2. **Cấu hình ngưỡng linh hoạt:** Trong TF32, với các nhóm nghiêm trọng (`sexual/minors`, `violence/graphic`), nên duy trì ngưỡng score thấp hơn hoặc kết hợp báo cáo người dùng (≥ 3 reports) để tự ẩn.
3. **White-list tiếng lóng du lịch:** Core API cần tránh chặn nhầm các cụm từ phổ biến như "chém gió", "nóng muốn chết", "ngon xỉu", "giá cắt cổ".

## Cách kiểm lại

```bash
cd tripflix/tripflix-ai
uv run python -m evals.run_moderation_eval --data evals/moderation/vi_3k.jsonl
```

## Kết quả kiểm tra

- **Test suite:** `uv run pytest` -> **431 passed, 6 skipped** in 4.40s.
- **Linter & Formatter:** `uv run ruff check .` và `uv run ruff format --check .` -> Tất cả 98 files sạch, 0 lỗi.
- **Type check:** `uv run pyright` -> **0 errors, 0 warnings, 0 informations**.

## Ảnh / video

- Không đổi giao diện.

## Ảnh hưởng tới phần của người khác

- Không. Chỉ bổ sung script eval, tập dữ liệu benchmark 3k câu và runner offline cho kiểm duyệt.
