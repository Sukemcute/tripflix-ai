# TF44 — Đếm người trước khi gọi model phân loại

- Nhánh: `bao/TF44-cong-truoc-phan-loai` · Người làm: Bảo (dùng AI: có) · Ngày: 2026-11-13
- **Nguồn:** khi rà lại kiến trúc, Bảo thấy thứ tự chưa đúng. Luồng phải là lọc → đếm đủ người → model → LLM. Code lại gọi model cho mọi câu qua lọc trước, rồi mới đếm người, nên bài dưới 5 người vẫn tốn CPU gắn nhãn. Báo cáo `DeepResearch_Khi_nao_tom_tat_va_tom_tat_lai.md` §5.4 đã đề xuất thứ tự này.

## Đã làm

- **Vì sao đếm trước được:** số người ở cổng không cần nhãn. Nó chỉ dùng luật: bỏ tài khoản chép (L8) và bỏ người chỉ đặt câu hỏi, mà câu hỏi cũng do luật nhận. Số người trên toàn bộ ứng viên luôn **lớn hơn hoặc bằng** số người mà cổng đếm trên các câu được chọn. Vậy nếu ứng viên đã dưới 5 người thì chắc chắn không qua cổng, dù nhãn nói gì.
- `selection.count_people(candidates)`: đếm người có ý kiến trên toàn bộ ứng viên, chỉ bằng luật.
- `pipeline.run_summary`: dưới 5 người thì model chỉ gắn nhãn cho **câu dính an toàn**, vì cảnh báo không cần đủ 5 người, và nhãn tự kể hay nghe nói quyết cảnh báo công khai hay chờ duyệt. Nhãn đã lưu sẵn trong kho vẫn được dùng lại như cũ.
- **Không đổi:**
  - trạng thái: bài dưới cổng vẫn ra `insufficient_data`, không gọi LLM;
  - cảnh báo an toàn;
  - hash: bài dưới cổng không lưu hash;
  - bài từ 5 người trở lên.
- **Cố ý không sửa "phản hồi dính an toàn bị phân loại hai lần"**, dù ban đầu định sửa. Rà lại thì đây không phải làm trùng cùng một việc:
  - label worker đọc phản hồi **không có** bình luận cha, chỉ để giữ kết quả an toàn cho phản hồi nằm ngoài mẫu;
  - lượt tóm tắt đọc phản hồi **kèm** bình luận cha, đúng cách model được huấn luyện.
  
  Bỏ một trong hai là quay lại mâu thuẫn số 10 đã sửa ở PR #26.

## Đối chiếu tiêu chí

| Tiêu chí | Đạt | Bằng chứng |
|---|---|---|
| Bài dưới 5 người: model chỉ đọc câu dính an toàn | Có | `test_below_the_gate_only_safety_hits_go_to_the_classifier` |
| Bài dưới 5 người vẫn có cảnh báo công khai từ nhãn model | Có | Cùng test, kiểm `safety.warnings` |
| Bài đủ 5 người: mọi ứng viên vẫn được gắn nhãn | Có | `test_at_the_gate_every_candidate_is_labelled` |

**Test đổi theo hành vi mới:** `test_the_summary_says_who_labelled_the_comments`. Bài 3 người trước đây ra `labeler = model`, giờ là `rules`, vì model không chạy cho ứng viên của bài dưới cổng.

## Kết quả kiểm tra

- `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest`: ruff sạch, pyright 0 lỗi, **573 passed**, 5 skipped.
- **Đo trên 15 bài seed:** số câu đưa vào model giảm từ **102 xuống 89**. Ba bài dưới cổng (`s05-it-nguoi`, `s06-mot-nguoi-noi-nhieu`, `s07-chu-bai-tra-loi`) từ 3, 6, 4 câu xuống 0. Cả ba vẫn đúng trạng thái `insufficient_data`.
- **Eval** `uv run python evals/run_evals.py --classifier-dir app/models/comment_classifier` (LLM giả, không tốn tiền): chạy được, 15/15 bài qua các cổng về đầu ra, trích dẫn, đếm người, an toàn, injection. Không chạy eval live: thay đổi chỉ chạm bài dưới cổng, mà những bài này không gọi LLM, nên input gửi LLM của mọi bài không đổi.

## Cách kiểm lại

1. `uv run pytest tests/summary/test_pipeline.py -k "gate"`

## Ảnh hưởng tới phần của người khác

- Không. Chỉ sửa repo AI, không đổi hợp đồng API.
- Trong `pipeline.py` và `summary_worker.py` đang có thay đổi chưa commit (hook `observe`), không thuộc task này. Commit này không gồm phần đó.
