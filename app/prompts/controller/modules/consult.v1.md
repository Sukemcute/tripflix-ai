- consult: ví dụ xin ý tưởng "đi đâu chill chill"; kể tâm trạng "tôi vừa thất nghiệp, buồn quá, muốn đi đâu đó cuối tuần"; trả lời cộc lốc "chill thôi", "đi với bạn gái", "tầm 2 củ" khi trip.awaiting.intent là "consult". Có ngày thì vẫn điền day_ref hoặc start.
  - Câu có tên một nơi, dù viết thường hay không dấu, điền place và dùng intent bình thường ("đà lạt cuối tuần chơi gì" → search). Khi trip.awaiting.intent là "consult" mà người dùng nêu một nơi ("đà lạt đi") thì cũng theo intent của nơi đó.
  - Câu có "reel", "video" hoặc "clip" là find_reel, kể cả khi không có nơi đến.
Tư vấn:
"cuối tuần đi đâu chơi" → {"intent":"consult","day_ref":"this_weekend","query":"gợi ý nơi đi chơi cuối tuần"}
"tôi vừa thất nghiệp, buồn quá, muốn đi đâu đó cuối tuần" → {"intent":"consult","day_ref":"this_weekend","query":"gợi ý nơi đi xả stress cuối tuần"}
"chill thôi" (trip.awaiting {"intent":"consult","missing":"place"}) → {"intent":"consult","query":"đi chill"}
"tìm reel cuối tuần đi đâu" → {"intent":"find_reel","day_ref":"this_weekend","reel_query":"cuối tuần đi đâu"} (không phải consult: có chữ reel)
"da lat cuoi tuan choi gi" → {"intent":"search","place":"Đà Lạt","day_ref":"this_weekend","query":"Đà Lạt cuối tuần chơi gì"} (không phải consult: có tên nơi)
