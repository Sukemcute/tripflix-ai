# Tripi: lịch thời gian thực, ngày lễ Việt Nam, bỏ chuyến bay đã cất cánh

- Ngày 2026-11-26 · Người viết: Bảo (dùng AI) · Task: TF31 · Nhánh: `bao/TF31-tripi-tu-van` (nối sau bản sửa ngày tương đối)
- Bảo chọn hướng B: lịch dương lịch thời gian thực + ngày lễ Việt Nam (có Tết âm lịch), không thêm thư viện.

## Vì sao
Tripi đoán sai ngày: không biết "cuối tuần này" là ngày nào, không hiểu "thứ 6 tuần sau", "3 ngày nữa", "dịp 30/4", "nghỉ Tết".
Hỏi vé lúc 8h sáng vẫn được chuyến 7h sáng cùng ngày, vì code chỉ lọc theo ngày, không lọc theo giờ hiện tại.

## Thiết kế

### 1. Lịch `app/services/assistant/calendar.py`
- `now_in_vietnam(now: datetime | None = None) -> datetime` (giờ Asia/Ho_Chi_Minh, dùng `planner.VIETNAM` có sẵn).
- `build_calendar(now: datetime) -> dict` (JSON camelCase, gọn):
  - `now`: `"2026-11-26 08:15"`, `today`: `"2026-11-26"`, `weekday`: `"thứ Năm"` (dùng `understand.WEEKDAYS_VI`, có thể dời hằng số này sang `calendar.py` và import lại ở `understand.py`).
  - `days`: 14 ngày kể từ hôm nay, mỗi ngày `{"date":"2026-11-27","label":"T6 27/11","rel":"mai"}`. `rel` chỉ có ở hôm nay, mai, mốt.
  - `thisWeekend`, `nextWeekend`: `["2026-11-28","2026-11-29"]` theo đúng luật của `planner.start_day` (Chủ nhật thì "cuối tuần này" là hôm nay).
  - `nextWeek`: thứ Hai đến Chủ nhật của tuần sau.
  - `holidays`: các ngày lễ trong 400 ngày tới, `{"name":"Tết Nguyên Đán","from":"2027-02-05","to":"2027-02-09","isLunar":true}`.
- Ngày lễ `app/services/assistant/holidays.v1.yaml` (dữ liệu tham khảo, header ghi nguồn và **"chờ Bảo kiểm; lịch nghỉ bù chính thức do Nhà nước công bố mỗi năm, nhập tay"**):
  - Dương lịch, code tự sinh theo năm: Tết Dương lịch 1/1; Giải phóng miền Nam 30/4 và Quốc tế Lao động 1/5 (gộp "Lễ 30/4–1/5"); Quốc khánh 2/9 (khoảng 1–2/9).
  - Âm lịch, ghi sẵn ngày dương cho 2026–2030:
    - Mùng 1 Tết: 2026-02-17, 2027-02-06, 2028-01-26, 2029-02-13, 2030-02-03. Khoảng "Tết Nguyên Đán" dùng từ ngày 30 Tết (mùng 1 trừ 1 ngày) đến mùng 4 (mùng 1 cộng 3 ngày).
    - Giỗ Tổ Hùng Vương (10/3 âm lịch): 2026-04-26, 2027-04-16, 2028-04-04, 2029-04-23, 2030-04-12.
    - Builder đối chiếu các ngày này với một nguồn đáng tin (lịch vạn niên, văn bản nhà nước). Ngày nào không chắc thì ghi chú trong YAML và báo lại, không tự đoán.
- Mỗi lượt tính lịch **một lần** trong `chat.py` từ giờ thật, rồi truyền xuống. Test truyền `now` cố định.

### 2. Đưa lịch vào LLM
- Controller (`build_understanding_input`): thêm `calendar`. Prompt v12 (chưa phát hành, được sửa tại chỗ): ngày tương đối nào không có trong `day_ref` ("thứ 6 tuần sau", "3 ngày nữa", "đầu tuần sau", "dịp 30/4", "Tết", "Giỗ Tổ") thì tra `calendar` rồi ghi `start`/`end` dạng `{day, month}`. Ngày lễ thì lấy `from`/`to` của lễ đó. Không bao giờ tự tính thứ, luôn tra `calendar.days`.
- Consultant và Responder: thêm `calendar` (Responder chỉ cần `now`, `today`, `weekday`, `thisWeekend`, `holidays`) để nói đúng "cuối tuần này 28–29/11" hay "sắp tới dịp …". Khi Verifier chạy, các số trong `calendar` được tính là có căn cứ (thêm vào facts dùng để kiểm, không hiện cho người dùng).
- Câu hỏi ngày (`ask_date`, từ bản sửa trước): trả lời thêm được câu về ngày lễ ("Tết năm nay ngày mấy", "30/4 năm nay thứ mấy") từ `holidays`, viết bằng code.

### 3. Bỏ chuyến bay đã cất cánh hoặc sắp cất cánh
- `search_flights(core, understood, *, now: datetime | None = None)`: khi `flight_date` là hôm nay (giờ Việt Nam), bỏ chuyến có `departTime` sớm hơn `now + MIN_LEAD_MINUTES` với `MIN_LEAD_MINUTES = 120` [HIỆU CHỈNH] (cần ra sân bay và check-in).
  - Không còn chuyến nào thì trả `no_result` với câu "Hôm nay không còn chuyến nào cất cánh sau {HH:MM} nữa, bạn xem ngày mai nha?" và chip `["Xem ngày mai", "Đổi ngày"]`.
  - Card và text không đổi với các ngày khác.
- Luồng lộ trình (`skills/plan.py`, vé đi và vé về) đi qua cùng `search_flights`. Builder kiểm và truyền `now` xuống. Vé về là ngày khác nên không bị ảnh hưởng.
- Phòng: nhận phòng hôm nay vẫn hợp lệ (đặt phòng trong ngày là bình thường), đợt này không đổi.

### 4. Test
- `test_calendar_days_and_weekends` (now = Thứ Năm 2026-11-26 08:15: mai = T6 27/11, thisWeekend 28–29/11, nextWeek bắt đầu 30/11), `test_calendar_on_sunday` (cuối tuần này = hôm nay), `test_holidays_loaded_and_in_window` (Tết 2027 có from 2027-02-05 to 2027-02-09), `test_controller_input_has_calendar`.
- `test_today_flights_drop_departed` (now 08:00 hôm nay, chuyến 07:00 / 09:30 / 10:30 → chỉ còn 10:30), `test_today_no_flights_left_message`, `test_other_day_flights_untouched`, `test_plan_today_outbound_uses_now`.
- `test_date_question_about_tet` ("Tết năm nay ngày mấy" trả từ holidays).
- Eval ci giữ nguyên điểm (đang là 188/188 cộng các case của bản sửa trước). Thêm case Controller: "thứ 6 tuần sau", "3 ngày nữa", "dịp 30/4 đi đâu", "nghỉ Tết đi Đà Lạt".

## Không làm
- Không tính âm lịch bằng code, không thêm thư viện. Không tự cộng ngày nghỉ bù.
- Không đổi luồng phòng theo giờ.
