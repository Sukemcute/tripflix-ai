- select_option: trip.hasChosenFlight chỉ cho biết đã chọn chuyến, không phải ID hay giá.
- confirm_booking: câu chốt cũng gồm "ok book đi", "chot", "book lun", "dat di". Khi có lựa chọn để đặt, câu chốt ưu tiên hơn ack; chưa chọn gì thì "chốt", "mình chốt vậy" vẫn là ack.
"lấy cái thứ 2" (trip có pendingCount 3) → {"intent":"select_option","card_ordinal":2}
"chốt và đặt" (trip.stay có lựa chọn) → {"intent":"confirm_booking"}
