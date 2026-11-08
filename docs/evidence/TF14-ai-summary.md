# TF14 — AI tóm tắt bình luận: classifier, DeepSeek, chọn ý theo độ phủ, prompt v3, che tên người

- Notion: (Bảo dán link TF14) · Nhánh: `bao/TF14-ai-summary` · Người làm: Bảo (dùng AI: có) · Ngày: 2026-11-08

## Đã làm

- **Bộ phân loại bình luận** (`comment_classifier.py`):
  - ViSoBERT chưng cất, int8 ONNX, chạy trên CPU (onnxruntime + tokenizers).
  - Bundle kiểm sha256 theo manifest lúc worker khởi động. Thiếu hoặc hỏng thì dùng luật như cũ.
  - Nhãn chỉ dùng để xếp hạng và gắn cờ (tầng 1 = người đã trải nghiệm; tự kể hay nghe kể quyết định cảnh báo công khai hay chờ kiểm duyệt). Nhãn không loại bình luận nào.
- **Adapter DeepSeek** (`app/clients/llm/deepseek.py`): provider LLM trước mắt. Key chỉ lấy từ `DEEPSEEK_API_KEY`.
- **Validator:**
  - Kiểm hết các ý rồi mới chọn theo độ phủ khía cạnh: mỗi khía cạnh một ý trước, đông người trước.
  - Thiếu một mục danh sách thì đọc là rỗng thay vì làm hỏng cả lượt.
  - Trường `short` được kiểm theo V6.
- **Prompt `summary.v3`:**
  - Thêm nhãn ngắn để đoạn 300 ký tự chứa đủ ý.
  - Gộp mỗi khía cạnh thành một ý, tối đa 5 khen và 5 chê.
- **Lexicon:**
  - `safety.v6`: thêm tai nạn (sứa đốt, trượt chân, bị cứa…).
  - `summary_bans.v2`: không còn coi "muỗi ban đêm" là đếm người.
- **Claim:** caption được tách theo vế.
- **Hiệu năng:** classifier chạy sau bộ lọc (25 s → 17 s cho 1.000 bình luận).
- **Che tên người** (`pii.py`):
  - Họ tên là dữ liệu cá nhân cơ bản (Nghị định 13/2023/NĐ-CP); trước đây chỉ che `@tên`.
  - Từ thân tộc/nghề (anh, chị, bạn, lễ tân, a/c/e…) + tên viết hoa → `[tên]`.
  - Họ phổ biến + Thị/Văn + tên → `[tên]`, trừ khi đứng sau đường/phố/quận.
  - Loại trừ địa danh như Ông Lang, Cô Tô, Bà Rịa. Validator V6 dùng lại nên chặn cả tên LLM tự viết.
  - Che cả caption (claim) vì caption cũng gửi cho LLM.
- **Eval:** chấm gap theo đúng claim; thêm cờ `--classifier-dir`.

## Đối chiếu "Xong khi"

Chép từ yêu cầu của Bảo trong phiên làm việc (chưa đối chiếu bản Notion).

| Tiêu chí | Đạt | Bằng chứng |
|---|---|---|
| Classifier dùng được trong pipeline, thiếu model không sập | Có | `test_missing_or_broken_bundle_falls_back_to_rules`, `test_classifier_*` trong `test_pipeline.py` |
| Bài 1.000 bình luận có rác, spam, injection: đạt mọi cổng cứng | Có | Eval live bài lớn: đạt 8/8 cổng ở cả 2 lượt |
| Không bỏ sót khía cạnh khi LLM viết thừa ý | Có | `test_v1_overflow_keeps_one_point_per_aspect_before_a_second_of_the_same` |
| Đoạn tóm tắt chứa đủ khen, chê, khác video | Có | `test_short_forms_let_the_text_hold_every_point`, `test_a_con_resting_on_the_writers_of_a_video_gap_is_left_to_the_gap` |
| Bắt được tai nạn tự kể mà không bắt nhầm | Có | Mẫu `match`/`no_match` trong `safety.v6.yaml`; đo trên 100.995 câu thật: 6 câu đổi kết quả, đều đúng |
| Không gửi tên người sang LLM | Có, theo mẫu | `test_person_names_after_a_cue_or_with_thi_van_are_masked`, `test_places_streets_and_common_words_keep_their_text`, `test_names_and_phones_in_the_caption_are_masked`; đo trên 3.058 review và 92.977 bình luận YouTube: khoảng 85% và 92% chỗ bắt là tên thật (đọc 40 mẫu mỗi bộ) |
| Đổi prompt hoặc agent có điểm trước/sau (RULES §10) | Có | Bảng bên dưới |

## Kết quả kiểm tra

`uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest`:
- ruff sạch;
- pyright 0 lỗi;
- pytest 390 passed, 5 skipped (6 skipped khi không có bundle model).
- Đã chạy lại riêng từng commit của nhánh: commit nào cũng pass.

**Eval live** (`uv run python evals/run_evals.py --llm live --classifier-dir app/models/comment_classifier`, DeepSeek):

| Bộ | Trước (summary.v2, chưa có classifier) | Sau (summary.v3 + classifier), 2 lượt |
|---|---|---|
| 15 bài seed: status đúng | 0.933 | 1.0 / 1.0 |
| 15 bài seed: point recall | 0.897 | **0.966 / 0.966** |
| 15 bài seed: point precision | 0.867 | 0.875 / 0.903 |
| 15 bài seed: gap recall | 0.25 | 1.0 / 1.0 (chấm theo claim, chặt hơn) |
| 15 bài seed: cổng cứng | trượt | đạt hết |
| Bài 1.000 bình luận: recall | 4/8 (trước khi sửa validator) | 6/8 / 8/8 |
| Bài 1.000 bình luận: cổng cứng | trượt an toàn | đạt hết |
| Bài 1.000 bình luận: thời gian | 34,6 s | khoảng 24,6 s |

- Chi phí: khoảng 0,005–0,007 USD cho mỗi lượt 15 bài, khoảng 0,005 USD cho bài 1.000 bình luận.
- Bài 1.000 bình luận là dữ liệu mô phỏng, sinh ở máy local, chưa commit.
- **Sau khi thêm che tên** (1 lượt): seed recall 0.931, precision 0.871, đạt mọi cổng; bài lớn 7/8, 10/10, đạt mọi cổng.
  - Hai bộ eval không có câu nào chứa tên (0/1.121), nên bước che tên không đổi prompt của chúng. Chênh lệch so với bảng trên là dao động của LLM.
  - Phần che tên được kiểm bằng unit test và kết quả đo ở dòng "Không gửi tên người sang LLM".

## Cách kiểm lại

1. `uv sync`, rồi chạy lệnh kiểm tra của repo như trên.
2. Lấy model: `uv run python -m scripts.fetch_classifier --tag comment-classifier-v1`. Bước này cần GitHub Release; chưa có thì pipeline chạy bằng luật.
3. Đặt `LLM_PROVIDER=deepseek` và `DEEPSEEK_API_KEY` trong `.env`, rồi chạy lệnh eval live ở trên.

## Ảnh / video

- Không đổi giao diện.

## Ảnh hưởng tới phần của người khác

- Không sửa code của người khác.
- Hợp đồng với core không đổi: body PUT ai-summary không thêm trường.
- **Còn chờ:**
  - Che tên mới bắt theo mẫu: chưa bắt tên viết thường hoặc không dấu, tên sau "và" hoặc dấu phẩy, tên không có từ dẫn (ghi `shortcut:` trong `pii.py`). Cần thêm bài eval có tên người.
  - Bước tải model trong CI/Dockerfile (chủ: Tech Lead/deploy) chưa làm; image hiện tại chạy bằng luật.
  - GitHub Release của bundle chưa tạo.
