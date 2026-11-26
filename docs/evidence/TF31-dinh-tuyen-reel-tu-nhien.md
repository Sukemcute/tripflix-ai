# TF31 — Tripi: eval đúng ngày, định tuyến chắc hơn, reel và số đêm nói tự nhiên

- Notion: (Bảo dán link task) · Nhánh: `bao/TF31-tripi-dinh-tuyen-reel-tu-nhien` · Người làm: Bảo (dùng AI: có) · Ngày: 2026-11-26
- Nối sau PR #67, #68 (đã merge). Nhánh `bao/TF31-tripi-eval-gio-co-dinh` (commit 95685a4) nằm trọn trong nhánh này.

## Đã làm
- **Eval chạy đúng ngày** (`evals/assistant/run.py`): case và chain viết theo ngày cố định 16/11/2026, nhưng live/chain lấy giờ thật (26/11) nên "21/11" thành ngày đã qua. Giờ mọi mode dùng `NOW = 16/11/2026 08:00`.
- **Reel không chép caption** (Responder v6, `responder.py`): code từng thay `[r1]` bằng nguyên caption của reel, nên câu trả lời lặp caption. Giờ mã của thẻ video bị bỏ, không thay bằng title. Prompt `assistant-responder.v6.md` (v5 giữ nguyên) dặn tự kể ngắn các video nói về gì, gom 2–3 video một câu, cách nói đổi mỗi lần. Phòng và vé bay vẫn giữ tên cạnh giá.
- **Bỏ câu cứng "Tripi tạm tính 1 đêm"** (`turn.py`): code thêm fact `assumed_stay`. Responder tự nói các phòng đang tính cho 1 đêm và hỏi ở mấy đêm. Khi không có Responder, câu dự phòng là "Mình xem trước cho 1 đêm 27/11–28/11 nha, bạn ở mấy đêm thì báo để mình lọc lại."
- **Hỏi ngày khi Controller lỗi:** "hôm nay là thứ mấy rồi" vẫn được trả lời từ code (`date_question_ref`, dùng chung với `apply_guards`) thay vì rơi vào tìm kiếm. Câu nối sau đó theo đúng việc đang dở (tìm phòng hay xếp lịch).
- **Guard định tuyến** (`controller.py`, prompt Controller v12 không đổi):
  - "tìm/kiếm/xem/book phòng" là tìm phòng.
  - Tư vấn có nêu nơi đi đúng skill phòng hoặc thời tiết.
  - Reel đang mở + "ngày 2 / ngày thứ hai đi đâu" là lịch trình reel. Chỉ dựa vào chữ trong câu, không dựa vào cờ `uses_context_post`.
  - "cuối tuần sau" thắng "cuối tuần này".
  - Câu ví dụ "gợi ý nơi đi/đến…" bị chép vào query thì thay bằng câu người dùng.
  - "bạn làm được gì" là identity.
  - "… mang gì / mặc gì" là gợi ý đồ mang theo.
  - "bay ra Hà Nội" khi chưa có lộ trình là tìm vé.
  - "lên/xếp lịch trình" là lập lộ trình.
  - Sắp xếp giá không phải "rẻ hơn / đắt hơn lần trước".
  - "2 đêm", "3n2đ" trong câu thắng số đêm model đoán.
  - Model chép nguyên câu vào `reel_query` thì bỏ.
- **Kỳ vọng eval cũ:** thêm `consult` vào `alsoOk` của 6 case viết trước khi có tư vấn. Theo thiết kế tư vấn (Bảo duyệt), đây là các câu hỏi "đi đâu", không nêu nơi:
  - cases.v1 `search-03`.
  - cases.v3 `search-14`, `ask-03`.
  - cases.v9 `scope-travel`, `scope-travel-regression-4`.
  - chains.v3 `small-talk` lượt "vậy đi biển đâu cho chill".

## Đối chiếu "Xong khi"
| Tiêu chí | Đạt | Bằng chứng |
|---|---|---|
| Eval phản ánh đúng chất lượng (không sai vì ngày) | Có | chain 70,9% → 96,6% chỉ nhờ cố định ngày (bảng dưới) |
| "Tìm phòng Quy Nhơn" sau tư vấn ra phòng | Có | `test_tim_phong_with_place_is_find_stay`; chain `consult-then-stay` đúng 3/3 |
| Câu trả lời reel không lặp caption, tự nhiên, không viết cứng | Có (unit test); giọng văn cần Bảo test tay | `test_video_ref_is_dropped_not_replaced_by_title`, `test_lone_video_pointer_does_not_become_the_whole_answer`, prompt v6 |
| Hỏi "hôm nay thứ mấy" không bị từ chối | Có | `test_date_question_answered_without_controller`, `test_date_answer_follow_up_matches_pending_stay` |
| Tìm phòng không nói câu cứng "tạm tính", có hỏi số đêm | Có (unit test) | `test_assumed_night_is_a_fact_not_a_lead`, `test_assumed_night_fallback_text_without_responder`, `test_assumed_stay_dates_are_grounded_for_the_verifier` |
| Guard định tuyến | Có | 16 test mới trong `tests/assistant/test_consult.py` (`test_consult_with_place_*`, `test_reel_open_*`, `test_next_weekend_words_win_over_this_weekend`, `test_copied_example_query_is_replaced_by_message`, `test_real_goi_y_query_is_kept`, `test_goi_y_noi_den_query_is_replaced_by_message`, `test_what_can_you_do_is_identity_not_consult`, `test_mang_gi_is_packing`, `test_bay_ra_city_without_plan_is_find_flight`, `test_len_lich_trinh_is_plan_trip`, `test_sort_words_are_not_price_relative`, `test_stated_nights_win`, `test_copied_message_is_not_a_reel_name`) |

## Kết quả kiểm tra
- `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -q`: sạch, pyright 0 lỗi, **1409 pass, 7 skip**.
- `uv run python -m evals.assistant.run` (ci): **194/194**.
- Eval thật (gpt-5-nano + DeepSeek, `--runs 3`), cùng máy, ngày 26/11:

| Eval | `develop` sáng nay (giờ thật) | Chỉ cố định ngày | Nhánh này | Nhánh này + 6 kỳ vọng tư vấn* |
|---|---|---|---|---|
| Chain, số lượt đúng | 166/234 = 70,9% | 226/234 = 96,6% | 231/234 = 98,7% | **234/234 = 100%** |
| Chain, kịch bản đúng cả 3 lần | 5/18 | 14/18 | 17/18 | **18/18** |
| Live, intent + slot | 529/582 = 90,9% | 521/582 = 89,5% | 540/582 = 92,8% | **555/582 = 95,4%** |
| Live, case đúng cả 3 lần | 169/193 = 87,6% | 165/193 = 85,5% | 172/193 = 89,1% | **177/193 = 91,7%** |

\* Chấm lại trên chính lượt chạy "Nhánh này" sau khi sửa 6 kỳ vọng. Mọi lượt sai của 6 case đó đều là `consult`, và các case này không có slot kỳ vọng. Không chạy lại.

- Lỗi còn lại ở live (đều chỉ sai 1/3 lần hoặc do mạng):
  - "3 ngày nữa mình bay ra hà nội từ sài gòn" thỉnh thoảng ra `change_transport`.
  - Slot của `move-slot`, `move-unknown`.
  - `report-B11`, `report-B16`, `review-01`, `trip-01`, `tone-rude-*`, `cal-friday-next-week`.
  - 2 lượt `ReadTimeout`.

## Cách kiểm lại
1. `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -q`
2. `uv run python -m evals.assistant.run`
3. Có key LLM trong `.env`: `uv run python -m evals.assistant.run --mode chain --runs 3` và `--mode live --runs 3`.
4. Chạy local, hỏi: "chán quá muốn đi đâu đó cuối tuần", rồi "đi sa pa chơi gì" (câu trả lời không chép caption reel); "tìm phòng vũng tàu ngày mai" (không có "tạm tính", có hỏi ở mấy đêm); "hôm nay là thứ mấy rồi".

## Ảnh / video
- Không đổi giao diện.

## Ảnh hưởng tới phần của người khác
- Không. Chỉ sửa trong `tripflix-ai` (phần của Bảo).
- 2 test cũ đổi kỳ vọng theo hành vi mới:
  - `test_chat_two_agents.py::test_responder_replaces_refs_and_drops_invented_prices`: "Xem Săn mây Đà Lạt nè ☁️" thành "Xem nè ☁️", vì mã video bị bỏ, không thay bằng caption.
  - `test_report_regressions.py::test_b16_a_start_day_alone_is_one_night_and_said_so`: `lead` giờ là `None`, số đêm và ngày nằm trong `text`, có fact `assumed_stay`.
- Prompt mới: Responder v6. Controller v12, Responder v5, Consultant v1 không đổi.
