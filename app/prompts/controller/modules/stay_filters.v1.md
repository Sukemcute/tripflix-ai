- stay_sort: "none" (mặc định), "price_asc" ("xếp từ rẻ đến đắt", "rẻ nhất trước"), "price_desc" ("đắt nhất trước"), "stars_desc" ("sao cao nhất trước"). min_stars: số sao tối thiểu 1 đến 5 ("4 sao trở lên" → 4), không nói thì null. price_relative: so với các chỗ ở vừa hiện, "đắt hơn", "xịn hơn", "cao cấp hơn" → "higher"; "rẻ hơn", "mềm hơn" → "lower"; còn lại "none". Không tự tính giá: code so với giá trong trip.lastCards.
- Lọc chỗ ở: khi trip.lastCards có thẻ kind "stay" và tin nhắn chỉ lọc, sắp xếp hoặc so sánh chỗ ở đó ("căn đắt hơn", "xếp theo giá", "có căn 5 sao không") → find_stay, giữ place của trip, day_ref "none". Nếu có lộ trình (trip.planDays > 0) thì là change_stay.
Lọc chỗ ở (trip.place Nha Trang, trip.lastCards có thẻ stay, planDays 0):
"tìm căn đắt hơn" → {"intent":"find_stay","place":"Nha Trang","price_relative":"higher"}
"xếp từ rẻ nhất đến đắt nhất" → {"intent":"find_stay","place":"Nha Trang","stay_sort":"price_asc"}
"có căn nào 4 sao trở lên không" → {"intent":"find_stay","place":"Nha Trang","min_stars":4}
"khách sạn Nha Trang từ 1tr đến 2tr" → {"intent":"find_stay","place":"Nha Trang","price_min_per_night":1000000,"price_max_per_night":2000000}
