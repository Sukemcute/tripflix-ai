# TF31 — Cờ tắt Responder và Skill, gắn kiểm injection, so sánh một agent / hai agent (TF14)

- Notion: TF31 · Nhánh: `bao/TF31-co-tat-va-injection` · Người làm: Bảo (dùng AI: có) · Ngày: 2026-11-16
- Kế hoạch: bước A1 (phần còn lại của Giai đoạn A, `docs/architecture/tripi-agent-v3-de-xuat.md` §3.3, §3.7).

## Đã làm
- **`CHAT_RESPONDER_ENABLED`** (mặc định `true`):
  - `false` thì lượt chat chỉ còn một agent: Controller lập kế hoạch, Skill lấy dữ liệu, chữ là câu mẫu.
  - Dùng để hạ cấp nhanh khi Responder có vấn đề, và làm vế A của so sánh TF14.
- **`CHAT_SKILLS_DISABLED`** (danh sách tên Skill, ví dụ `flight,stay`):
  - Skill bị tắt không được gọi, được ghi vào `done.degraded`.
  - Câu trả lời là "Tripi chưa kiểm được … lúc này", **không bao giờ là hết chỗ**.
- **Gắn kiểm injection vào luồng chat:**
  - Dùng lại `match_injection` của phần tóm tắt (TF44).
  - Đầu vào Controller có thêm `suspectedInjection`.
  - Khi khớp, ghi log `chat.injection.suspected` với tên nhóm luật, **không ghi nội dung tin nhắn**.
  - Không chặn cứng: an toàn chính vẫn dựa vào cấu trúc. Controller chỉ ra ý định, Skill chỉ đọc, Responder không có tool (v3 §3.7).
- **Eval `--mode ab`:** cùng kế hoạch cố định của bộ v1 + v2, so câu mẫu (A) với câu của Responder thật đã qua Verifier (B).

## Đối chiếu "Xong khi"
| Tiêu chí (kế hoạch A1) | Đạt | Bằng chứng |
|---|---|---|
| Tắt Responder không cần deploy | Đạt | `test_responder_off_keeps_cards_and_fixed_text` |
| Tắt từng Skill, báo `degraded`, không nói hết chỗ | Đạt | `test_a_disabled_skill_is_reported_as_degraded_not_as_nothing_found` |
| Kiểm injection gắn vào chat | Đạt | `test_injection_rules_tag_the_controller_input` (2 câu chen lệnh có cờ, 1 câu thường không) |
| Bảng A/B cho TF14 | Đạt | Mục dưới |

## Kết quả kiểm tra
- `uv run ruff check .`, `ruff format --check .`, `pyright`: sạch.
- `uv run pytest`: **664 passed, 6 skipped** cộng 17/17 của bản `tests/test_chat.py` đã commit.
  - Bản local riêng của Bảo (skip-worktree) dùng chữ ký `understand` cũ nên lỗi trên máy này. Không liên quan thay đổi.
- `uv run python -m evals.assistant.run` (ci): **70/70**.
- **`uv run python -m evals.assistant.run --mode ab`** (Responder DeepSeek thật, core và thời tiết giả):

| | A: một agent (câu mẫu) | B: hai agent (Responder + Verifier) |
|---|---|---|
| Lượt có Responder chạy | 43 | 43 |
| Dùng được câu của Responder | — | 43/43 (0 lần quay về câu mẫu, 0 lỗi) |
| Câu bị Verifier bỏ | — | 17: `V3_ungrounded_name` 15, `V4_scarcity` 1, `V8_wrong_day` 1 |
| Độ trễ thêm | 0 | p50 1,05 giây, p95 1,24 giây |
| Chi phí thêm | 0 | 0,00644 USD cho 43 lượt (0,00015 USD/lượt) |

**Ví dụ:**
- search-06:
  - A: "Tripi tìm được 1 video phù hợp. Bấm vào thẻ để xem nhé."
  - B: "Mình chưa có food tour Sài Gòn trong dữ liệu nè, chỉ có Săn mây 4h sáng về săn mây thôi."
  - B nói thật khi kết quả lệch câu hỏi; A không nói được điều này.
- stay-01: câu chính do code viết ("Tripi tạm tính 1 đêm…") giữ nguyên ở cả A và B; B chỉ thêm ý.

**Điểm yếu tìm được (chưa sửa, ghi cho bước sau):**
- reel-02: B viết "video về biển Nha Trang" trong khi thẻ là "Săn mây 4h sáng".
  - Verifier cho qua vì "Nha Trang" có trong câu hỏi: kiểm từng tên riêng không bắt được lỗi nói sai quan hệ giữa thẻ và câu hỏi.
  - Core giả trả cùng một video cho mọi câu, nên lỗi lộ rõ hơn thực tế.
  - Hướng sửa [ĐỀ XUẤT]: Verifier chỉ cho nhắc tên nơi chốn ở câu có mã thẻ nếu tên đó có trong tiêu đề hoặc facts của chính thẻ.
- Đánh giá giọng văn để người đọc các cặp A/B do eval in ra; eval không tự chấm.

## Cách kiểm lại
1. `uv run pytest tests/assistant/test_chat_switches.py -q`
2. `CHAT_RESPONDER_ENABLED=false` hoặc `CHAT_SKILLS_DISABLED=flight` trong `.env`, chạy ai-service, hỏi một câu tìm chuyến bay. Kết quả đúng: `done.degraded` có `flight`, câu trả lời "chưa kiểm được chuyến bay".
3. `PYTHONIOENCODING=utf-8 uv run python -m evals.assistant.run --mode ab` (cần khoá DeepSeek, khoảng 0,007 USD).

## Ảnh / video
- Không đổi giao diện.

## Ảnh hưởng tới phần của người khác
- Không. Deploy có thể thêm 2 biến mới; mặc định giữ nguyên hành vi hiện tại.
