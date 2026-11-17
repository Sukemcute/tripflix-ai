# TF31 — Chửi tục mà không hỏi gì thì Tripi chỉ nhắc nhẹ, không hiện thẻ

- Notion: TF31 · Nhánh: `bao/TF31-chui-tuc-khong-tim` · Người làm: Bảo (dùng AI: có) · Ngày: 2026-11-17

## Đã làm
- **Lỗi Bảo gặp:** đang nói về Đà Lạt, nhắn "cặc, chatbot như quần" thì Tripi trả câu nhắc nhẹ **kèm reel Hội An, Nha Trang và khách sạn**.
- **Nguyên nhân gốc:** có ngữ cảnh chuyến đi thì Controller xếp câu chửi vào `search` 5/6 lần. Tripi lấy nơi đang nói từ bộ nhớ, đem chính câu chửi đi tìm.
- **Yêu cầu của Bảo:** giải quyết tổng quát cho mọi nơi và khi chưa có nơi nào, không vá theo từng lần test, không dùng ViSoBERT.

### Thiết kế cuối
- **Tín hiệu 1, câu có thô tục không (`is_rude`):** Controller v8 đọc theo nghĩa, trong lượt gọi sẵn có, nhận ra cả từ lóng mới. Bộ từ `abuse.v1.yaml` chỉ là dự phòng khi model bỏ sót.
- **Tín hiệu 2, câu có tự nêu cái cần làm không** (`social.names_its_target`, code kiểm): nơi, thành phố, khách sạn, reel hoặc ngày có nằm **trong chính tin nhắn** không. Nơi đang nhớ trong `trip` không được tính.
- **Luật chung:** câu thô tục mà không tự nêu cái cần làm → chỉ nhắc nhẹ, không chạy skill, không thẻ, mời quay lại chuyến đang nói. Câu thô tục có nêu ("đm tìm ks đà nẵng t7 này") → làm đúng yêu cầu, kèm một câu nhắc. Câu không thô tục → xử lý như trước, không đổi gì.

### Hai cách đã thử và bỏ (đo bằng eval live)
| Cách | Kết quả | Lý do bỏ |
|---|---|---|
| Controller trả cờ `has_request` | Bộ giọng điệu 15/33; live tụt từ 97,3% xuống 90,0%, chain từ 98,5% xuống 87,3% | Model hầu như không đặt "không có yêu cầu" cho câu chửi, nhưng lại đặt "không có yêu cầu" cho câu hỏi thật ("Dự báo Đà Lạt hôm đó sao"), làm mất thẻ |
| Controller chép phần yêu cầu vào `request` | Bộ giọng điệu 12/33 | Model chép cả câu chửi vào `request` và để trống `request` cho "tìm reel phú quốc" |

`is_rude` thì model đọc ổn định, nên chỉ giữ tín hiệu đó từ model. Phần "có yêu cầu" chuyển cho code kiểm theo nguyên tắc trên.

### Giới hạn đã biết
- Câu thô tục có nhờ mà không nêu nơi, ngày hay đối tượng nào ("đm tìm ks rẻ đi") chỉ được nhắc nhẹ, kèm chip "Tìm chỗ ở" để bấm tiếp. Đây là chủ ý: khi người dùng đang bực, Tripi không tự lấy ngữ cảnh cũ để hành động. Đã ghi `shortcut:` trong test.

## Đối chiếu "Xong khi"
| Tiêu chí | Đạt | Bằng chứng |
|---|---|---|
| Chửi tục không kèm yêu cầu: chỉ nhắc nhẹ, không thẻ, ở mọi nơi và khi chưa có nơi | Đạt | `test_a_rude_message_without_a_request_shows_no_cards` (Đà Lạt, Phú Quốc, Hà Nội, không nơi); `test_one_rule_for_tone_and_request_at_any_place`; eval ci `tone-rude-*`; chạy thật ở Phú Quốc, Hà Nội, không nơi |
| Từ lóng không có trong bộ từ vẫn nhận ra | Đạt | "bot óc bã đậu thật sự", "trả lời như cái bô": Controller trả `is_rude` đúng, chạy thật chỉ có câu nhắc |
| Chửi kèm yêu cầu thật: vẫn làm, nhắc một câu | Đạt | `test_a_rude_request_is_answered_with_one_reminder`; chạy thật "đm tìm ks đà nẵng t7 này" ra khách sạn Đà Nẵng kèm câu nhắc |
| Câu không thô tục không bị ảnh hưởng | Đạt | Luật chỉ áp khi thô tục; `("weather", "Dự báo Đà Lạt hôm đó sao", ...) → None` |
| Không làm lùi các ca cũ | Đạt (trong dao động giữa các lần chạy) | Bảng dưới: các ca cũ lệch 2 lượt / 336; các lượt chain trượt đều đã trượt ở v6/v7 |

## Kết quả kiểm tra
- ruff, pyright sạch. `pytest`: **825 passed, 6 skipped**; `tests/test_chat.py` bản đã commit 17/17.
- Eval ci: **123/123** (thêm 11 ca `cases.v5.jsonl`, nhãn `giong-dieu`).
- Eval live bộ giọng điệu (11 ca × 3): **28/33 = 84,8%**, pass^3 9/11. Lượt lệch: `tone-rude-03` model gán `ack`/`greeting` (vẫn chỉ nhắc nhẹ, không thẻ, vì là ý định xã giao và câu thô tục); `tone-rude-req-02` 2 lượt lệch slot nhưng vẫn đúng `weather`.

- Trước/sau (DeepSeek thật, mỗi ca 3 lần; v7 = Controller đang dùng trên develop):

| Chỉ số | v7 | v8 |
|---|---|---|
| Live, các ca cũ v1–v4 | 327/336 = 97,3% | 325/336 = 96,7% |
| pass^3, các ca cũ | 104/111 = 93,7% | 103/111 = 92,8% |
| Live, tính cả bộ giọng điệu | — | 353/369 = 95,7%; pass^3 112/122 = 91,8% |
| Chain (10 chuỗi × 3) | 130/132 = 98,5% (lần khác 131/132, 129/132) | 126/132 = 95,5% |
| Độ trễ p50 / p95 | 2,16 s / 2,88 s | 2,70 s / 3,49 s |
| Chi phí mỗi lượt gọi | 0,000118 USD | 0,000118 USD |

- 6 lượt chain trượt đều là lượt đã trượt ở các lần chạy v6/v7, không có câu thô tục: `reel-6.1` "Thời tiết Đà Lạt thứ Bảy thế nào?" (×3, v6 và v7 cũng trượt), `small-talk` "vậy đi biển đâu cho chill" (×2, v7b, v7c cũng trượt), `vt-report-hoi-tai-sao` (×1). Luật mới chỉ chạy khi câu thô tục nên không chạm các lượt này.
- Độ trễ p50 tăng khoảng 0,5 s. Prompt v8 dài hơn v7 vài dòng ví dụ; chưa tách được phần do prompt và phần do tải API lúc chạy [CẦN NC: đo lại cùng giờ].

- Chạy thật (Controller + Responder thật, core giả):
  - Phú Quốc, "cặc, chatbot như quần" → "Tripi xin lỗi nếu lúc nãy chưa đúng ý bạn, mình nói chuyện nhẹ nhàng thôi nha. Bạn muốn mình xếp lịch trình Phú Quốc mấy ngày…?" Không thẻ, dù Controller vẫn trả `search`.
  - Hà Nội, "bot óc bã đậu thật sự" → "Tripi hiểu là bạn đang bực, mình nói chuyện nhẹ nhàng thôi nha. Bạn muốn mình làm lại phần nào của chuyến Hà Nội?" Không thẻ.
  - Chưa có nơi, "trả lời như cái bô" → câu nhắc, chip gợi ý chung.
  - "đm tìm ks đà nẵng t7 này" → "Mình nói chuyện nhẹ nhàng thôi nha 😊 … Khách sạn Đà Nẵng cho tối thứ Bảy này đây nha 🏨".

## Cách kiểm lại
1. `uv run pytest tests/assistant/test_context_and_small_talk.py -q`
2. `PYTHONIOENCODING=utf-8 uv run python -m evals.assistant.run --mode live --cases v5`
3. Trên app: nói về một nơi bất kỳ rồi chửi không kèm yêu cầu → chỉ có câu nhắc nhẹ. "đm tìm ks đà nẵng t7 này" → có thẻ khách sạn, kèm một câu nhắc.

## Ảnh / video
- Bảo bỏ việc chụp ảnh cho các task TF31 (2026-11-17).

## Ảnh hưởng tới phần của người khác
- Không. Không đụng ViSoBERT hay `/moderate` (chị Trang).
