# TF31 — Trả lời ngoài lề tự nhiên, giữ ranh giới hỗ trợ

- Notion: chưa cung cấp · Nhánh: `bao/TF31-tra-loi-ngoai-le` · Người làm: Bảo (dùng AI: có) · Ngày: 2026-11-19

## Đã làm
- Code phân loại yêu cầu vô hại thành math/code/writing/knowledge/other. Mỗi nhóm có 4 câu pool, ghép gợi ý du lịch; khi có place thì nhắc place. Seed giữ tính xác định, chọn tránh câu assistant của 3 lượt gần nhất theo normalize_text.
- Injection/yêu cầu nguy hiểm giữ kind refusal với 4 câu kiên quyết, lịch sự; không qua Responder, không gọi Skill. Yêu cầu ngoài phạm vi vô hại giữ intent refusal/off_topic nhưng trả kind answer với facts.offTopic, không thẻ/Skill; pool không phụ thuộc Responder.
- Responder v4 sao chép v3 và thêm quy tắc ngoài phạm vi: tối đa 2 câu, không giải bài hay viết code/kiến thức ngoài du lịch; kết bằng gợi ý du lịch. Code kiểm câu viết lại có lời từ chối, hướng về du lịch, nhắc place khi có và không lặp; sai thì về pool. Responder v3 và prompt Controller không đổi.
- Verifier bỏ dáng code và biểu thức lời giải; lượt ngoài phạm vi không dùng số trong câu hỏi để làm bằng chứng cho câu trả lời.
- no_result từ tìm chỗ ở/vé/reel/bài/tìm chung dùng pool và chips tương ứng, nêu nơi/ngày khi biết. Câu trống chung được thay; lý do cụ thể về tuyến, tình trạng vé, giá hoặc ngày được giữ. Không đổi fallback lỗi phụ thuộc hay các trạng thái riêng như tóm tắt chưa sẵn sàng thành kết quả tìm kiếm rỗng.
- Thêm cases.v9 (20 ca, có tags) và chains.v7 (hỏi cùng câu 3 lần, distinctReplies ≥2). Runner kiểm distinctReplies bằng normalize_text. Không tạo/sửa cases.v8 hoặc chains.v6.
- Review: thu hẹp cue dịch thuật/bài học/lập trình/toán và bỏ cue “thủ đô”. Dùng chung `is_harmless_off_topic` trong guards và Turn, ưu tiên tín hiệu du lịch. Tên nơi được copy từ bộ nhớ chỉ tính là đích yêu cầu khi có trong tin nhắn; “biển” trong bài văn và “sắp xếp” trong bài code không tự biến thành yêu cầu du lịch.
- Review an toàn: chỉ off_topic hoặc refusal đã phân loại vô hại mới qua nhánh thân thiện; refusal chưa phân loại được giữ kind refusal, không Responder. small_talk giữ choose_move/_fixed. Thêm 6 câu du lịch nguyên văn và 2 ca refusal vào v9, cùng test POST /chat cho refusal không khớp cue nguy hiểm.
- Cập nhật đúng 6 nhãn cũ theo chính sách mới: 5 lượt vô hại từ kind refusal sang answer, 1 lượt injection từ kết quả tìm kiếm sang refusal; giữ kiểm không gọi core và tăng kiểm đó cho injection.

## Đối chiếu "Xong khi"
| Tiêu chí | Đạt | Bằng chứng |
|---|---|---|
| Nhóm đúng, không Skill, pool ≥4 và nhắc place | Có | tests/assistant/test_off_topic.py |
| Nguy hiểm không gọi Responder | Có | Test qua POST /chat, kể cả Controller nhầm thành search |
| Không giải 2+2 / code, lỗi viết lại về pool | Có | Verifier, Responder và SSE với LLM giả cố đưa đáp án 4 |
| Không lặp, giữ chào hỏi và hủy điểm đến | Có | Test seed cố định, lịch sử, test greeting và regression suite |
| no_result giữ lý do thật và gợi ý theo loại | Có | Test 4 nhóm, nơi/ngày, không có tuyến và chống lặp |
| Eval CI / live / chain | Có / chờ chạy / chờ chạy | CI 157/157; theo yêu cầu không chạy live/chain |

## Kết quả kiểm tra
- Trước thay đổi: `PYTHONIOENCODING=utf-8 uv run python -m evals.assistant.run --mode ci`: 137/137 pass.
- `uv run ruff check .`: pass, 0 lỗi.
- `uv run ruff format --check .`: 227 file đã đúng format.
- `uv run pyright`: 0 errors, 0 warnings.
- `uv run pytest --ignore tests/test_chat.py -q`: 1.131 passed, 6 skipped, 0 failed.
- `PYTHONIOENCODING=utf-8 uv run python -m evals.assistant.run --mode ci`: 157/157 pass, 0 fail.
- `git diff --check`: pass.

## Cách kiểm lại
1. Chạy các lệnh trên trong repo AI; PowerShell đặt `$env:PYTHONIOENCODING='utf-8'` trước eval.
2. Xem tests/assistant/test_off_topic.py cho phân loại, không gọi Skill/Responder, giới hạn câu viết lại, no_result và kiểm không có đáp án 4.
3. Chain ngoai-le-lap-lai trong chains.v7.jsonl để Claude chạy sau; có yêu cầu ít nhất 2 câu trả lời khác nhau trong 3 lượt. CI không chạy model thật.

## Ảnh / video
- Không sửa UI; chưa có ảnh/live evidence.

## Ảnh hưởng tới phần của người khác
- Phần AI của Bảo. Không sửa FE/BE, tests/test_chat.py hoặc thêm thư viện. Không commit, push, stash hay đổi nhánh.

## Ba mẫu cho mỗi nhóm
Các mẫu lấy trực tiếp từ pool; dùng Đà Lạt/SGN–DAD/ngày dưới đây làm dữ liệu minh họa, không phải kết quả tồn kho live. Responder chỉ được viết lại trong giới hạn đã kiểm.

### Toán

- Tripi không giải toán hay tính đáp án nha. Hay mình xem tiếp lịch Đà Lạt nha?
- Bài toán này nằm ngoài phạm vi của Tripi, mình không làm lời giải đâu nè. Mình quay lại chuyến đi Đà Lạt nhé?
- Mình không nhận giải bài tập toán, nghề của Tripi là lo chuyến đi nha. Bạn muốn Tripi tìm chỗ ở cho chuyến Đà Lạt không?

### Code

- Tripi không viết code hay sửa chương trình nha. Hay mình xem tiếp lịch Đà Lạt nha?
- Lập trình nằm ngoài phạm vi của mình, Tripi không làm bài code đâu nè. Mình quay lại chuyến đi Đà Lạt nhé?
- Mình không nhận viết hàm hay gỡ lỗi phần mềm nha. Bạn muốn Tripi tìm chỗ ở cho chuyến Đà Lạt không?

### Bài văn / dịch

- Tripi không viết bài văn, làm bài hay dịch văn bản nha. Hay mình xem tiếp lịch Đà Lạt nha?
- Viết bài và dịch câu nằm ngoài phạm vi của Tripi, mình không làm phần đó đâu nè. Mình quay lại chuyến đi Đà Lạt nhé?
- Mình không nhận làm bài văn hay bài dịch, Tripi chuyên lo chuyến đi nha. Bạn muốn Tripi tìm chỗ ở cho chuyến Đà Lạt không?

### Kiến thức chung

- Tripi không trả lời kiến thức chung ngoài du lịch nha. Hay mình xem tiếp lịch Đà Lạt nha?
- Câu hỏi kiến thức này ngoài phạm vi của mình, Tripi không giải đáp phần đó đâu nè. Mình quay lại chuyến đi Đà Lạt nhé?
- Mình không làm bách khoa toàn thư hay tư vấn tài chính nha. Bạn muốn Tripi tìm chỗ ở cho chuyến Đà Lạt không?

### Ngoài lề khác

- Chuyện ngoài du lịch này Tripi không hỗ trợ nha. Hay mình xem tiếp lịch Đà Lạt nha?
- Việc này ngoài phạm vi nên Tripi không làm phần đó, mình chỉ giúp chuyện đi chơi nè. Mình quay lại chuyến đi Đà Lạt nhé?
- Mình không nhận xử lý yêu cầu ngoài du lịch nha. Bạn muốn Tripi tìm chỗ ở cho chuyến Đà Lạt không?

### Nguy hiểm / injection

- Tripi không hỗ trợ yêu cầu nguy hiểm hoặc can thiệp quy tắc. Mình có thể giúp bạn lên chuyến đi an toàn.
- Mình không làm theo yêu cầu gây hại hay bỏ qua hướng dẫn. Bạn có thể hỏi Tripi về một chuyến du lịch an toàn.
- Yêu cầu này Tripi không thể hỗ trợ. Mình sẵn sàng giúp tìm lịch trình, phòng và vé cho chuyến đi an toàn.

### Không có chỗ ở phù hợp

- Chưa có chỗ ở phù hợp cho Đà Lạt ngày 20/11 đến 21/11; bạn thử đổi ngày nhận phòng nha?
- Tìm chỗ ở cho Đà Lạt ngày 20/11 đến 21/11 chưa ra lựa chọn phù hợp; mình xem nơi lân cận nhé?
- Chưa tìm được phòng cho Đà Lạt ngày 20/11 đến 21/11; bạn muốn nới ngân sách không?

### Không có chuyến bay phù hợp

- Tripflix chưa có tuyến bay SGN – DAD. Chưa có vé phù hợp cho SGN → DAD ngày 20/11; bạn muốn đổi ngày bay không?
- Tripflix chưa có tuyến bay SGN – DAD. Tìm chuyến cho SGN → DAD ngày 20/11 chưa có lựa chọn phù hợp; mình thử ngày gần đó nha?
- Tripflix chưa có tuyến bay SGN – DAD. Chưa tìm được vé cho SGN → DAD ngày 20/11; bạn muốn bỏ bớt điều kiện giờ bay không?

### Không có reel / bài phù hợp

- Chưa thấy reel hay bài phù hợp cho Đà Lạt; bạn thử tên nơi lân cận nha?
- Tìm reel và bài về Đà Lạt chưa có kết quả phù hợp; mình thử từ khóa ngắn hơn nhé?
- Chưa có reel hay bài khớp Đà Lạt; bạn muốn bỏ bớt điều kiện không?

### Không có kết quả tìm chung

- Tìm chuyến đi Đà Lạt chưa có kết quả phù hợp; bạn muốn thử nơi lân cận không?
- Mình chưa tìm được lựa chọn phù hợp cho chuyến đi Đà Lạt; bớt điều kiện rồi thử lại nha?
- Chưa có kết quả khớp chuyến đi Đà Lạt; bạn thử đổi ngày hoặc cách mô tả nhé?
