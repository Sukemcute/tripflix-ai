# TF31 — Tin nhắn cho người liên quan (Tripi v3)

Soạn ngày 2026-11-16. Code đã push lên các nhánh dưới đây, **chưa mở PR**: PR mở sau khi người liên quan đồng ý.

| Repo | Nhánh | Nội dung |
|---|---|---|
| tripflix-ai | `bao/TF31-tripi-v3-nen` → `bao/TF31-tripi-v3-hai-agent` → `bao/TF31-tripi-v3-ngu-canh` | Nền, hai agent, nhớ chuyến đi và sửa lỗi Expo Web (3 PR nối nhau) |
| tripflix-fe | `bao/TF31-tripi-v3-mobile` | Tripi trên mobile |
| tripflix-be | `bao/TF31-router-chat` | Hạn mức gateway cho `/ai/chat` |

---

## 1. Chị Trang (`apps/mobile`)

> Chị Trang ơi, em là Bảo. Em làm phần Tripi v3 (TF31) và có sửa trong `apps/mobile`, nên nhờ chị xem và đồng ý trước khi em mở PR vào `develop`.
>
> **Nhánh:** `bao/TF31-tripi-v3-mobile` (https://github.com/Sukemcute/tripflix-fe/tree/bao/TF31-tripi-v3-mobile)
>
> **Em sửa gì trong phần của chị:**
> - `features/assistant/*`:
>   - mở Tripi từ reel thì gửi id reel đang xem;
>   - app giữ và gửi lại "trip" (nơi, ngày, số người Tripi đã nhớ);
>   - người đăng nhập lưu phiên chat trên máy 7 ngày, theo mẫu `cart-store.ts`; khách chỉ giữ trong bộ nhớ app; đổi tài khoản thì xoá;
>   - khách hết lượt thì có nút Đăng nhập (`/login?returnTo=/assistant`);
>   - lỗi không còn khoá ô nhập;
>   - thẻ thời tiết, checklist, lộ trình hiện từng dòng và nguồn; chip gợi ý bấm là gửi.
> - `features/feed/reel-social-overlay.tsx` và `trip-plan-sheet.tsx`: mỗi file 1 dòng, truyền `postId` cho Tripi.
> - `packages/api-client`, `packages/app-core`, `packages/i18n`: chỉ thêm, không đổi chữ ký hàm đang dùng.
>
> **Đã kiểm:** `pnpm turbo run lint typecheck test --affected` 16/16 xanh.
>
> **Chưa có:** ảnh chụp trên Expo Web hoặc Android. Em sẽ chụp bổ sung trước khi mở PR.
>
> **Cách thử:** bật BE và ai-service (cổng 8000), chạy `pnpm --filter @tripflix/mobile web`, mở một reel, bấm Tripi, hỏi "reel này đi mấy ngày" rồi "ngày 2 đi đâu".
>
> **Sau này** analytics cần đọc sự kiện `ai.usage.recorded` (token, chi phí mỗi lượt). Hiện ai-service mới ghi log, chưa có ai đọc.
>
> Chị thấy ổn thì báo em mở PR nha, cần đổi chỗ nào em sửa luôn ạ.

## 2. Dũng + Tech Lead (`deploy/traefik`, cấu hình chung)

> Dũng ơi, Bảo đây. Mình có sửa nhỏ cấu hình Traefik cho trợ lý Tripi (TF31), nhờ Dũng và Tech Lead xem trước khi mở PR.
>
> **Nhánh:** `bao/TF31-router-chat` (https://github.com/Sukemcute/tripflix-be/tree/bao/TF31-router-chat)
>
> - Thêm middleware `rate-limit-chat`: trung bình 20 request/phút mỗi IP, dồn tối đa 5.
>   - Lý do: mỗi lượt chat gọi LLM, mức của `rate-limit-api` (50 request/giây) quá rộng.
> - **`dynamic.yml` (dev):** thêm router `ai-chat` (`POST /ai/chat`, priority 100). Router `ai` giữ nguyên cho các đường `/ai` khác.
> - **`server.yml`:** router `ai-chat` có sẵn, đổi `rate-limit-api` thành `rate-limit-chat`.
> - README: thêm 1 dòng vào bảng hạn mức.
> - **Đã thử local:**
>   - 30 request song song vào `/ai/chat` thì 25 bị gateway trả 429;
>   - `/ai/health` không bị ảnh hưởng;
>   - `pnpm turbo run lint typecheck test --affected` 49/49 xanh.
>   - Lưu ý: trên Windows phải `docker restart tripflix-traefik-1` thì Traefik mới nạp file mới.
>
> Hạn mức theo từng người (6 lượt/phút, 40 lượt/ngày; khách 3 lượt/phút, 5 lượt/ngày) vẫn nằm trong ai-service. Gateway chỉ chặn dồn dập theo IP.
>
> Ổn thì mình mở PR nha.

## 3. Anh Phong (deploy ai-service)

> Anh Phong ơi, em Bảo. Tripi v3 (TF31) cần thêm cấu hình khi deploy ai-service, em gửi anh trước để chuẩn bị. Em chưa mở PR, giá trị bí mật em gửi riêng, không để trong tin này.
>
> **Biến môi trường mới của ai-service** (đã có trong `.env.example`):
> - **Bật trợ lý:**
>   - `CHAT_LLM_ENABLED=true`;
>   - `CHAT_CONTROLLER_PROVIDER=openai`, `CHAT_CONTROLLER_MODEL=gpt-5-nano`;
>   - giá token: `CHAT_CONTROLLER_PRICE_INPUT`, `CHAT_CONTROLLER_PRICE_CACHED_INPUT`, `CHAT_CONTROLLER_PRICE_OUTPUT`. Thiếu giá thì Controller không chạy, Tripi tự chuyển sang tìm kiếm thường.
>   - `CHAT_RESPONDER_PROVIDER=deepseek`.
> - **Khoá:** `OPENAI_API_KEY`, `DEEPSEEK_API_KEY` (em gửi riêng).
> - `CHAT_IDENTITY_SALT`: chuỗi ngẫu nhiên dài, dùng để băm IP của khách. Mỗi môi trường một chuỗi, không đổi thường xuyên (đổi thì hạn mức khách tính lại từ đầu).
> - `REDIS_URL`: dùng chung Redis của stack. Tripi giữ khoá lượt, đếm lượt/phút, lượt và token/ngày ở đây.
> - Hạn mức (để mặc định là được):
>   - `CHAT_USER_DAILY_TURNS` (40), `CHAT_GUEST_DAILY_TURNS` (5);
>   - `CHAT_USER_DAILY_TOKENS` (150.000), `CHAT_GUEST_DAILY_TOKENS` (20.000);
>   - `CHAT_SYSTEM_DAILY_USD` (3): hết 3 USD/ngày thì cả hệ thống tự chuyển sang tìm kiếm thường;
>   - `CHAT_MAX_INFLIGHT` (30 lượt chạy cùng lúc mỗi tiến trình, quá thì trả 503).
> - `FORWARDED_ALLOW_IPS` (biến của uvicorn, không có trong `.env.example`): đặt bằng IP hoặc dải mạng của Traefik trong Docker network. `fastapi run` chỉ tin header `X-Forwarded-For` từ các IP này; không đặt thì mọi khách bị tính chung một IP (của Traefik) và chạm hạn mức khách rất nhanh.
>
> **Nhờ anh thêm:**
> - Sau khi PR gateway (`bao/TF31-router-chat`) merge, Traefik trên server cần nạp lại cấu hình.
> - Đo tải `/chat` cùng lúc với `/moderate`, vì 2 việc chạy chung một tiến trình. Mỗi lượt chat gọi 2 LLM, p50 khoảng 2 giây cho Controller.
> - Thời hạn giữ log: log chat của ai-service **không ghi nội dung tin nhắn**, chỉ ghi mã người dùng (khách thì IP đã băm kèm salt), token, chi phí, luật Verifier đã bỏ câu. Em đề xuất giữ 14 ngày, anh thấy sao ạ?

## 4. Thắng (`commerce`)

> Thắng ơi, Bảo đây. Tripi v3 (TF31) gọi thêm vài API commerce có sẵn, không cần API mới, báo để Thắng biết khi sửa:
> - `GET /api/stays` có `priceMax` (Tripi gửi trần giá người dùng nói và lọc lại `unitPrice`).
> - `GET /api/flights` có `children`, `infants`; Tripi đọc `departTime`, `flightKey` để lọc giờ và gộp các hạng vé của cùng một chuyến.
> - `GET /api/hotels/{id}` có `checkIn`, `checkOut`, `adults` để kiểm còn phòng.
> - Nếu đổi tên hay bỏ các trường này thì báo mình trước nha.
>
> **Nhờ thêm:** dữ liệu seed hiện chưa có khách sạn ở Vũng Tàu, nên ca demo "ks Vũng Tàu cuối tuần" ra trống. Thắng thêm vài khách sạn Vũng Tàu được không, hay mình chọn điểm demo khác có sẵn (Đà Lạt, Nha Trang)?

## 5. Duy (`discovery`)

> Duy ơi, Bảo đây. Tripi v3 (TF31) đang dùng `GET /api/search` và `GET /api/suggest?types=hotel` (tìm id khách sạn theo tên người dùng gọi, ví dụ "Vinpearl Luxury Nha Trang"), không cần API mới trong đợt này.
> - Nếu đổi dạng trả về của `suggest` (`type`, `refId`, `name`) thì báo mình trước nha.
> - **Sau pilot:** Tripi cần `GET /api/places` (điểm tham quan có toạ độ) để gợi ý lộ trình và quãng đường. Mình sẽ viết đặc tả gửi Duy sau.

## 6. Thành (`content`)

> Thành ơi, Bảo đây. Báo Thành mấy điểm về Tripi v3 (TF31):
> - Tripi đọc `GET /api/v1/posts/{id}` (lộ trình, khách sạn của reel) và `GET /api/v1/posts/{id}/ai-summary`.
>   - `404` của ai-summary được hiểu là "reel chưa có tóm tắt" (chưa đủ bình luận), không phải reel bị ẩn.
>   - Nếu đổi ý nghĩa mã này thì báo mình nha.
> - Trong đợt này Tripi chỉ làm trên mobile; khung Tripi trên web để sau. Khi làm web mình sẽ nhờ Thành.
