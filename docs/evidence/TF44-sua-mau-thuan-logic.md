# TF44 — Sửa 12 mâu thuẫn logic trong AI tóm tắt

- Nhánh: `bao/TF44-sua-mau-thuan-logic` · Người làm: Bảo (dùng AI: có) · Ngày: 2026-11-13
- **Nguồn:** rà soát toàn bộ module ngày 2026-11-13 tìm được 12 mâu thuẫn. Phần 1 sửa 4 lỗi nặng; phần 2 sửa 8 lỗi còn lại và các ghi chú lệch code.

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


---

## Phần 2: 8 mâu thuẫn còn lại (2026-11-13)

| # | Mâu thuẫn | Sửa |
|---|---|---|
| 5 | Câu dính an toàn được ưu tiên gửi cho LLM, rồi validator bỏ hết bằng chứng từ chúng (V5). Một tác giả có một câu an toàn thì mất luôn mọi ý khác | Luật **L14**: bình luận dính luật an toàn rời đường tóm tắt (đường an toàn vẫn báo chúng). Các bình luận khác của cùng tác giả vẫn được dùng. Câu an toàn bị phủ định ("không bị ngộ độc") không bị bắt nên vẫn giữ |
| 6 | Ước lượng "khoảng X người" tính cả tài khoản bị đánh dấu chép (L8), trong khi số chính xác loại họ | Trọng số, số người theo tầng và tác giả được trích dẫn đều bỏ bản chép |
| 7 | Docstring hứa model lỗi thì hash không mang version model, nhưng khi có nhãn lưu sẵn thì vẫn mang | Lượt có một phần nhãn từ luật (`labeler = mixed`) thêm `labeler` vào hash, nên khác lượt dùng model hoàn toàn. Lượt dùng model hoàn toàn và lượt chỉ dùng luật giữ nguyên hash như cũ |
| 8 | LLM chết hay lỗi thì nhãn vừa gắn bị bỏ, nên mỗi lần hoãn 5 phút lại chạy model lại | Pipeline gọi `keep_labels` **trước** khi gọi LLM |
| 9 | `population` gọi là số đếm toàn bài, nhưng hash trùng thì không lưu nên không theo kịp bình luận mới | Định nghĩa lại cho khớp: đó là số đếm **tại thời điểm** của bản tóm tắt, đi cùng ước lượng đã tính từ chúng. Số trực tiếp đọc qua `comment-stats` của core |
| 10 | Cùng một phản hồi dính an toàn: label worker dùng luật, lượt tóm tắt dùng model để quyết công khai hay chờ duyệt | Label worker cũng đọc phản hồi dính an toàn bằng model (không có nội dung cha), và không lưu nhãn đó |
| 11 | Label worker bỏ qua sự kiện `restored` | Coi `restored` là sự kiện ghi. Sự kiện hiện chưa có `body` nên chưa làm gì; core thêm `body` là tự chạy |
| 12 | "Không có trong mẫu" bị hiểu là "nằm ngoài mẫu", kể cả khi đã đọc cả bài, nên kết quả an toàn của bình luận đã ẩn quay lại | Chỉ gộp kết quả an toàn đã lưu khi số đếm của core cho thấy lượt chỉ đọc một phần bài |

**Ghi chú lệch code đã sửa:**
- CONTEXT: "120 bình luận" thành ngân sách 12.000 token; "≥ 5 bình luận" thành 5 người có ý kiến; nhà cung cấp LLM thành 4 adapter đã commit.
- Code: ghi chú tốc độ bộ phân loại (34 câu/s), giới hạn 500 câu mỗi lượt.

**Test đổi theo hành vi mới:**
- `test_rule_keeps_usable_comment`: câu "Ngộ độc" chuyển sang nhóm bị bỏ với mã L14.
- `test_agreeing_replies_…`: bình luận cha đổi từ câu ngộ độc sang câu chê thường. Test kiểm phiếu đồng ý, không kiểm an toàn.
- `test_safety_hits_are_kept_…`: phản hồi giờ do model quyết công khai hay chờ duyệt.
- `test_stored_labels_feed_the_run_…`: nhãn được giữ qua callback.
- `test_kept_safety_results_…`: thêm số đếm cho thấy chỉ đọc một phần bài.

**Test mới:**
- an toàn không được gửi cho LLM;
- đọc cả bài thì bỏ kết quả an toàn cũ;
- LLM lỗi vẫn giữ nhãn;
- lượt có một phần nhãn từ luật cho hash khác lượt dùng model;
- phản hồi không lưu nhãn.

**Kết quả phần 2:**
- `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest`: ruff sạch, pyright 0 lỗi, **564 passed**, 5 skipped.
- **Eval live** (DeepSeek, 15 bài seed, 0,005 USD): 15/15 cổng, trạng thái đúng 1,0, độ phủ ý 0,966, độ chính xác ý 0,875, khác biệt video 1,0, 0 trích dẫn sai. Token vào 33.925 → **33.740**: câu dính an toàn không còn được gửi. Độ chính xác ý lên xuống giữa 0,875 và 0,903 qua các lần chạy, do LLM dao động.

**Ảnh hưởng tới người khác:**
- **Anh Thành:** đề xuất thêm `body` vào sự kiện `content.comment.restored` (chỉ thêm field).
- **Phía FE:** `population` là số đếm tại thời điểm tóm tắt, không phải số trực tiếp.
- **Hash:** chỉ đổi cho các lượt `mixed`, nên sau deploy hầu hết bài không bị tóm tắt lại hàng loạt.
