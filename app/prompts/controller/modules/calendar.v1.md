Ngày tương đối trong "calendar" (lịch thật do code tính): "days" (14 ngày từ hôm nay, mỗi ngày có "date" YYYY-MM-DD và "label" gồm thứ), "thisWeekend", "nextWeekend", "nextWeek" (thứ Hai đến Chủ nhật tuần sau), "holidays" (ngày lễ sắp tới, có "from", "to", "isLunar").
- Ngày không có trong day_ref ("thứ 6 tuần sau", "3 ngày nữa", "đầu tuần sau", "tuần sau"): BẮT BUỘC tra "calendar", ghi start {"day","month"} (và end nếu người dùng nói ngày về hoặc số đêm), day_ref "none". Đây là ngoại lệ của việc không đổi thứ thành ngày: thứ nào có trong day_ref thì vẫn dùng day_ref. "thứ X tuần sau": ngày thứ X trong "nextWeek". "N ngày nữa": phần tử thứ N trong "days" (hôm nay là 0). "đầu tuần sau": thứ Hai trong "nextWeek". Có tên nơi thì intent theo nơi đó, không phải consult.
- Dịp lễ ("dịp 30/4", "nghỉ Tết", "Giỗ Tổ", "Quốc khánh"): lấy "from" làm start và "to" làm end của lễ đó trong "holidays", day_ref "none". "năm sau" thì lấy lễ năm sau. Lễ không có trong "holidays" thì start/end null.
- Từ ngày "YYYY-MM-DD" của calendar: day là DD, month là MM, bỏ năm ("2026-12-04" → {"day":4,"month":12}). KHÔNG BAO GIỜ tự tính thứ hay cộng ngày trong đầu.
Ngày theo lịch (today 2026-11-26, thứ Năm):
"thứ 6 tuần sau đi vũng tàu được không" → {"intent":"weather","place":"Vũng Tàu","day_ref":"none","start":{"day":4,"month":12},"end":null}
"3 ngày nữa mình bay ra hà nội" → {"intent":"find_flight","to_city":"Hà Nội","day_ref":"none","start":{"day":29,"month":11}}
"dịp 30/4 năm sau đi đâu" → {"intent":"consult","day_ref":"none","start":{"day":30,"month":4},"end":{"day":1,"month":5},"query":"gợi ý nơi đi dịp 30/4"}
"nghỉ Tết đi Đà Lạt" → {"intent":"search","place":"Đà Lạt","day_ref":"none","start":{"day":5,"month":2},"end":{"day":9,"month":2},"query":"Đà Lạt dịp Tết"}
"Tết năm nay ngày mấy" → {"intent":"ask_date","day_ref":"none"}
