# TF32 — Bộ câu test mới v1

Bộ dữ liệu có 300 câu tổng hợp tiếng Việt được viết mới cho ngữ cảnh Tripflix. Người dùng xác nhận toàn bộ nhãn hiện có trong chat ngày 11/11/2026, sau khi đã nhận kết quả model. Bản đã xác nhận nằm ở `reviewed/test.jsonl` và `reviewed/manifest.json`. File ở thư mục gốc giữ nguyên snapshot đề xuất để truy vết.

## Dùng với Colab

Ở ô `test_upload = files.upload()` trong notebook vòng hai, chọn file `reviewed/test.jsonl`. File có các trường id, text, toxic, kind và group_id cần cho notebook. Hai trường source và label_status ghi nguồn dữ liệu và trạng thái nhãn.

Đã tạo lại `notebooks/tf32-round2-test-results-reviewed/test-pack.json` từ 300 dự đoán có sẵn sau khi kiểm tra ID, nội dung, nhãn và nhóm đều khớp bản đã xác nhận. Chỉ metadata duyệt được cập nhật. Giữ file suy luận Colab cũ gắn với hash của snapshot gốc. Bản xác nhận có hash riêng và thông tin tái sử dụng dự đoán trong manifest/test pack.

Cấu hình dùng để chấm test lấy từ `frozen-config.json` đã chọn trên dev. Nếu dùng kết quả test để sửa ngưỡng hoặc model, bộ câu đã xem trở thành dữ liệu phát triển cho các lượt sau.

## Thành phần

| Nhóm | Số câu | Nhãn đề xuất |
|---|---:|---|
| harassment | 25 | toxic |
| hate | 25 | toxic |
| threat | 25 | toxic |
| violence | 25 | toxic |
| sexual | 25 | toxic |
| self_harm | 25 | toxic |
| slang_praise | 25 | clean |
| complaint | 25 | clean |
| safety | 25 | clean |
| beach | 25 | clean |
| neutral | 20 | clean |
| slang | 17 | clean |
| quoted_report | 10 | clean |
| standalone_profanity | 3 | clean |
| Tổng | 300 | 150 toxic, 150 clean |

Dữ liệu được xáo thứ tự cố định. Có 293 nhóm tình huống, trong đó 7 nhóm gồm cặp công kích/phản ánh liên quan. Các câu trong cùng group_id cần đi chung nếu sử dụng cho một phép chia dữ liệu sau này.

## Duyệt nhãn

REVIEW.md giữ bảng 300 dòng theo ID để đối chiếu hoặc ghi chú về sau. Xác nhận hiện tại được ghi theo lời người dùng trong chat. Chưa có bản ghi duyệt độc lập thứ hai cho bộ 300 câu, nên manifest chỉ ghi người dùng là người xác nhận. Thông tin Bảo cùng chốt policy được giữ ở phạm vi policy.

Mỗi câu được xét theo toàn bộ nội dung. Lời kể sự cố, trích dẫn phản đối hoặc lời khen có tiếng lóng có thể được gán clean khi không có hành vi công kích hay đe dọa của người viết. Nhãn toxic thể hiện tín hiệu cần kiểm duyệt, cách xử lý nội dung phụ thuộc chính sách sản phẩm.

## Sau khi có dự đoán ViSoBERT

Lưu file test.jsonl và visobert-test.json trong `C:\Users\ADMIN\Downloads\tf32-visobert-round2`. Từ PowerShell ở repo tripflix-ai, chạy các lệnh trong HUONG-DAN.md của gói vòng hai để lấy cache OpenAI, tạo test-pack.json và chấm bằng cấu hình đã khóa.

Nếu sửa nội dung sau khi đã chạy suy luận, cần tạo dự đoán lại cho đúng nội dung mới. Sửa nhãn mà giữ nguyên văn bản thì có thể dùng lại điểm dự đoán theo đúng ID/nội dung.

## Kiểm tra và giới hạn

Đã kiểm tra schema, ID duy nhất, văn bản không trùng sau chuẩn hóa, tách ID/nội dung khỏi 240 câu dev. So với bộ 3k lịch sử, snapshot candidate và bộ 30 câu, có 0 trùng chuỗi chuẩn hóa và 0 kết quả gần trùng tại cutoff 0,85 của difflib. Kiểm tra chuỗi chưa xác nhận được độc lập về ý nghĩa.

Dữ liệu được viết theo những quy tắc và nhóm lỗi đã biết. Kết quả phản ánh bộ tình huống tổng hợp này. Với 150 câu sạch, một false positive tương ứng khoảng 0,67 điểm phần trăm FPR. Với 50 câu harassment/hate, một câu bắt đúng tương ứng 2 điểm phần trăm recall nhóm mục tiêu. Bộ dữ liệu chưa đo tỷ lệ lỗi trên lưu lượng thực tế.

Khi soạn dữ liệu, chưa dùng model để chọn, loại hoặc sửa nhãn. Người dùng xác nhận giữ nguyên nhãn sau khi đã nhận kết quả model. Các hash và thông tin xác nhận được lưu trong reviewed/manifest.json.

Kiểm tra schema, hash manifest, phân bố nhãn và tách nội dung khỏi dữ liệu cũ đã pass. Test bản xác nhận đối chiếu từng ID, nội dung, nhãn và group_id với snapshot ban đầu. Kết quả chấm theo cấu hình đã khóa nằm ở `notebooks/tf32-round2-test-results-reviewed/test-report.json`.

