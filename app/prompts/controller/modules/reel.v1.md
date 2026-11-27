- itinerary_day: "ngày thứ hai" → 2, "ngày cuối" → số ngày cuối nếu biết, không biết thì null.
- asks_days_count: true khi hỏi reel đi mấy ngày.
"Cho mình lộ trình video thứ hai trong hai video vừa gợi ý" → {"intent":"post_itinerary","card_ordinal":2}
"Cho mình xem lịch trình của reel săn mây Đà Lạt vừa gợi ý" → {"intent":"post_itinerary","reel_query":"săn mây Đà Lạt"}
"Ngày thứ hai thì mình đi đâu?" (đang nói về lộ trình reel) → {"intent":"post_itinerary","itinerary_day":2,"uses_context_post":true}
"ngay 2 di dau" (hasContextPost true) → {"intent":"post_itinerary","itinerary_day":2,"uses_context_post":true}
"reel nay di may ngay vay" → {"intent":"post_itinerary","asks_days_count":true,"uses_context_post":true}
"nguoi di roi noi gi ve cho nay" (hasContextPost true) → {"intent":"post_reviews","uses_context_post":true}
"quán ăn sáng trong lịch trình reel này tên gì" (hasContextPost true) → {"intent":"post_itinerary","uses_context_post":true} (hỏi tên điểm trong lộ trình, không phải review)
