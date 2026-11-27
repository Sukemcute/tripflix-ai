Sửa lộ trình đang có:
- move_stop: stop_name là điểm cần chuyển; anchor_name là điểm làm mốc, placement là before/after; hoặc target_day (ngày thứ mấy, 1-based), target_slot (sáng/trưa/chiều/tối). Chỉ điền phần người dùng yêu cầu, phần khác null hoặc chuỗi rỗng. "đi cầu rồng trước rồi mới sang bảo tàng" là move_stop, không phải plan_trip. Không thay ngày đi bằng target_day.
"Tôi muốn đi cầu rồng trước rồi mới sang bảo tàng nghệ thuật điêu khắc, xếp lại" → {"intent":"move_stop","stop_name":"Cầu Rồng","anchor_name":"bảo tàng nghệ thuật điêu khắc","placement":"before"}
"chuyển chợ Hàn sang ngày 2" → {"intent":"move_stop","stop_name":"Chợ Hàn","target_day":2}
"để Marina Coffee buổi tối" → {"intent":"move_stop","stop_name":"Marina Coffee","target_slot":"tối"}
"đi bảo tàng sau Cầu Rồng" → {"intent":"move_stop","stop_name":"bảo tàng","anchor_name":"Cầu Rồng","placement":"after"}
