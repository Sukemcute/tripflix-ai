# Rà soát chất lượng bộ eval kiểm duyệt — 10/11/2026

Đây là candidate chưa được duyệt. Không thay generator, nhãn gốc hoặc runner. Không gọi API.

## Đã kiểm tra

- 3.000 câu, 1.500 toxic + 1.500 clean; không trùng chuỗi nguyên văn.
- Chỉ có **1429 câu ghép trước biến đổi** (chuẩn hóa dấu/chữ/punctuation). Một câu
gốc có tới **12 biến thể**. Đây không phải 3.000 tình huống độc lập.
- Rà toàn bộ 233 mục gồm các vế câu, nhóm đối tượng, emoji, phép thay teencode
và 4 tính từ.
- Mẫu duyệt 240 câu: đúng 20 mỗi nhóm, trong đó 10 ngẫu nhiên và 10 có chủ đích. Cột đề xuất
không phải quyết định duyệt của con người.

## Phát hiện và sửa đề xuất

1. **Nhãn mơ hồ:** mẫu sexual “tối nay đi với anh, trả tiền hậu hĩnh” chưa đủ ngữ cảnh. Cách ly
hoặc viết lại trước khi chốt toxic. Mẫu “khoe body… chơi cho” cũng cần thống nhất cách hiểu.
2. **Ghép tính từ:** cùng pool đẹp/ngon/xịn/mê ly áp cho mọi mẫu, dẫn đến “view ngon”, “đẹp
đẹp”, “chill ngon”. Tách tính từ phù hợp từng mẫu. Các vế đuôi ở slang/neutral/safety cũng có
thể lệch ngữ cảnh.
3. **Phân nhóm:** threat/violence chồng lấn; sexual có thể đồng thời harassment. Chốt nhị phân
trước, mapping category riêng. “người miền Trung” cần quy tắc vùng miền rõ ràng.
4. **Biến đổi:** lặp ký tự từng vị trí có thể làm câu khó đọc; teencode dùng replace chuỗi;
emoji bất kỳ có thể không hợp ngữ cảnh. Đọc trước/sau, loại biến thể mất nghĩa.
5. **Đa dạng:** đủ chuỗi khác nhau nhưng nhiều biến thể từ ít ý gốc. Thêm ngữ cảnh/ý định mới,
câu thuật lại, phủ định, trích dẫn, phản đối hành vi và các cặp gần nhau khác nhãn.
6. **Cân bằng:** chỉ cân bằng toxic/clean; nhóm con không bằng nhau. Báo cáo cả theo nhóm và
tổng, không diễn giải accuracy của bộ 50/50 như tỷ lệ lỗi thực tế.
7. **Chống rò rỉ:** nếu dùng train/dev/test, chia theo câu gốc/template, không chia ngẫu nhiên
các biến thể. Candidate còn có câu chồng với vi_30, không mặc nhiên gọi là holdout mới.

## Cách duyệt

Mở Excel, sheet Duyet 240. Đọc câu, điền Nhãn duyệt và Quyết định ở các ô vàng. Khi sửa câu ghi
Câu sửa; khi sửa nhãn/loại/thảo luận ghi lý do. Sheet Mau goc ghi nhận xét từng mục. Sheet Huong
dan chứa quy tắc dự thảo và tiến độ tính từ quyết định nhập.

Quyết định: Giữ / Sửa câu / Sửa nhãn / Loại / Cần thảo luận. Nhãn: toxic / clean. Để trống nhãn
khi còn mơ hồ. Duyệt 240 câu không đồng nghĩa đã duyệt toàn bộ 3k.

Sau khi thống nhất quy tắc: sửa template → sinh candidate phiên bản mới → rà lại phần ảnh hưởng
→ nâng runner có giới hạn đồng thời/retry/lưu kết quả → chạy eval. Script hiện tại không nhập
quyết định Excel trở lại dataset tự động.

## Tái tạo và nguồn

Chạy `uv run python -m evals.moderation.prepare_quality_review` trong tripflix-ai để tái tạo
snapshot và CSV/JSON. Lệnh này ghi đè các file review được sinh; lưu bản Excel đã duyệt riêng
trước khi tái tạo. Workbook được tạo riêng từ review_data.json.

- Nguồn: evals/moderation/build_vi_3k.py; seed 20261110.
- Generator SHA-256: 3ad9f94021c3d7ff110c7eb1e2733f240a0432edb3f2fac5e40d616e1ea10549
- Candidate SHA-256: abaf7b55dccc8fdc9b0b7a69e89ec2fafcdab2a93d4e9a1476df74e34eca95f5
