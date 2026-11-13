# TF44 — Sửa 4 mâu thuẫn logic nặng trong AI tóm tắt

- Nhánh: `bao/TF44-sua-mau-thuan-logic` · Người làm: Bảo (dùng AI: có) · Ngày: 2026-11-13
- **Nguồn:** rà soát toàn bộ module ngày 2026-11-13 tìm được 12 mâu thuẫn. PR này sửa 4 lỗi nặng nhất.

## Đã làm

| # | Mâu thuẫn | Trước | Sau |
|---|---|---|---|
| 1 | Tiêu chí "từ 5 người **có ý kiến**", nhưng cổng đếm cả người chỉ hỏi | 5 câu hỏi ("Giá phòng bao nhiêu vậy?"…) vẫn qua cổng, gọi LLM, rồi ra `insufficient_data` | `Selection.people` không tính người chỉ hỏi (và vẫn không tính bản chép L8). Câu hỏi vẫn được gửi để làm chủ đề, chỉ không được tính là người |
| 2 | "Hash trùng thì không gọi LLM", nhưng một lượt đã trả tiền mà ra `insufficient_data` thì không lưu hash | Cùng input, mỗi lượt sau lại gọi LLM | Lưu `input_hash`, `prompt_version`, `model_name` kèm `insufficient_data` sau LLM. Lượt sau cùng input thì dừng, không gọi LLM |
| 3 | Tiêu chí "ưu tiên người tự kể, bỏ nghe nói", nhưng tầng 1 xếp theo "đã trải nghiệm" của model, gồm cả nghe nói | Người nghe nói chiếm chỗ đầu ngân sách token, rồi prompt lại bảo LLM bỏ họ | Tầng 1 chỉ gồm người **tự kể**. Người nghe nói xếp tầng 2 (chê) hoặc 3. Luật dự phòng vốn đã làm như vậy, giờ hai đường giống nhau |
| 4 | Core đánh dấu tóm tắt cũ (`isStale`) khi `post.commentCount ≠ commentCountAtSummary`, nhưng AI gửi số bình luận **đã đọc** (mẫu tối đa 3.000) | Bài trên 3.000 bình luận luôn bị coi là cũ | Gửi `visibleCommentCount` của cả bài, lấy từ số đếm của core. Core cũ chưa có số đếm thì vẫn gửi số đã đọc |

**Chưa sửa được ở phía AI, phần 2 của lỗi 4:**
- Hash trùng thì AI không lưu (đúng thiết kế, để không tốn tiền), nên `generatedAt` không đổi.
- Core lại coi "có bình luận thay đổi sau `generatedAt`" là cũ. Thêm một bình luận emoji là bản tóm tắt bị coi là cũ mãi, dù nội dung vẫn đúng.
- Cần anh Thành đổi cách tính `isStale`, hoặc mở API để AI báo "đã kiểm, không đổi". Đã soạn tin nhắn.

## Đối chiếu tiêu chí

| Tiêu chí | Đạt | Bằng chứng |
|---|---|---|
| 5 câu hỏi không qua cổng, không gọi LLM | Có | `test_five_questions_do_not_pass_the_gate_or_call_the_llm`, `test_askers_are_not_people_with_a_view` |
| Cùng input sau một lượt trả tiền rỗng thì không gọi LLM lần hai | Có | `test_a_paid_empty_run_keeps_its_hash_so_the_same_input_is_not_paid_again` |
| Người nghe nói không ở tầng 1 | Có | `test_classifier_labels_keep_hearsay_out_of_tier_1_and_set_complaints` (đổi từ test cũ khẳng định điều ngược lại, theo quyết định của Bảo) |
| Số bình luận gửi core là của cả bài | Có | `test_the_comment_count_saved_is_the_whole_posts_not_the_sample` |

## Kết quả kiểm tra

- `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest`: ruff sạch, pyright 0 lỗi, **558 passed**, 5 skipped.
- **Eval live** `uv run python evals/run_evals.py --llm live --classifier-dir app/models/comment_classifier` (DeepSeek, 15 bài seed, 0,005 USD):

  | Chỉ số | Trước (TF33) | Sau |
  |---|---|---|
  | Đạt đủ cổng | 15/15 | **15/15** |
  | Trạng thái đúng | 1,0 | 1,0 |
  | Độ phủ ý | 0,966 | 0,966 |
  | Độ chính xác ý | 0,875 | **0,903** |
  | Bắt khác biệt video | 1,0 | 1,0 |
  | Trích dẫn sai | 0 | 0 |
  | Token vào | 33.925 | 33.925 |

  Bài seed nhỏ, mọi bình luận đều vừa ngân sách, nên input gửi LLM không đổi (token vào giữ nguyên). Đổi tầng chỉ có tác dụng khi bài vượt ngân sách. Độ chính xác ý tăng nhiều khả năng do LLM dao động giữa các lần chạy.

## Cách kiểm lại

1. `uv run pytest tests/summary/test_selection.py tests/summary/test_pipeline.py`
2. Eval live như trên (tốn tiền, báo trước).

## Ảnh hưởng tới phần của người khác

- Chỉ sửa repo AI. Không đổi hợp đồng API: `commentCount` và `inputHash` đã có sẵn trong body PUT.
- **Anh Thành:** sau khi deploy, `commentCountAtSummary` của bài lớn sẽ là số bình luận đang hiện của cả bài. Còn một điểm cần anh xem về `isStale` (phần 2 của lỗi 4).
