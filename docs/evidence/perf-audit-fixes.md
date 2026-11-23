# Perf & Bug Audit: báo cáo sửa lỗi và việc còn lại

- Notion: chưa có task (không có mã TF) · Nhánh: `bao/perf-audit-fixes` (đã merge) · Người làm: Bảo (dùng AI: có, Claude Code + opencode) · Ngày: 2026-11-23
- PR: [tripflix-be#327](https://github.com/Sukemcute/tripflix-be/pull/327) · [tripflix-fe#359](https://github.com/Sukemcute/tripflix-fe/pull/359) · [tripflix-ai#64](https://github.com/Sukemcute/tripflix-ai/pull/64). Cả 3 đã merge vào `develop`; publish và deploy xanh.
- File này giống hệt nhau ở cả 3 repo (`docs/evidence/perf-audit-fixes.md`) vì đợt sửa đi qua cả ba.

## 1. Bối cảnh

Báo cáo "TripFlix Perf & Bug Audit" (19/11) là audit tĩnh do công cụ sinh, chưa kiểm lại. Đợt này đối chiếu từng phát hiện với code thật trên `develop`, chỉ sửa những gì đúng, không làm thêm.

Trong số phát hiện của audit, các mục sau **sai hoặc đã được sửa từ trước**, nên không làm:
- `queryClient.clear()` lúc khởi động.
- Web tua về 0s khi bật tiếng.
- `BuildFeaturesJob` chiếm kết nối pool (thực tế job mở kết nối riêng).
- Search thiếu `LIMIT` (thực tế có 500).
- Thiếu index `recommend_interactions` (khoá chính đã phủ).
- Kiểm duyệt vượt 3s (core chờ tới 25s).
- 720p đứng đầu master và master cache 60s (cố ý, có ghi lý do).
- "Vòng lặp vô hạn" `fetchNextPage` (BE đã bỏ qua tối đa 3 trang rỗng).

## 2. Đã làm (35 commit)

### tripflix-be (17 commit)
| Thay đổi | Vì sao |
|---|---|
| `stream:dead-letter` có `MAXLEN ~10000`; replayer `XDEL` bản ghi đã gửi xong | Hàng đợi lỗi phình mãi; khoá trạng thái và khoá chống trùng hết hạn sau 7 ngày nên email cũ bị gửi lại |
| Idempotency: chỉ lỗi của handler mới `abort()` | `complete()` lỗi sau commit làm client gửi lại thì chạy lần hai |
| Pool `access 5→10`, `discovery 5→12` | Search chạy song song, chờ pool quá 3s thì lỗi 500 |
| Cache xếp hạng `trip_v1` theo phiên (RAM, 5 phút) | Mỗi trang cuộn đọc lại tới 5.000 ứng viên |
| `GET /v1/posts?ids=` (≤50 id, chỉ thêm tham số) | Gợi ý/tìm kiếm gọi `GET /v1/posts/:id` từng bài (1+7, 1+12) |
| `findVisiblePostIds` chỉ `SELECT id … WHERE` | Search đọc đủ bản ghi tới 1.000 bài chỉ để lấy id |
| Thẻ Reels có `author.avatarUrl` | Trước đây luôn `null`: Mobile không có avatar, Web gọi `/avatar` từng tác giả |
| Cache trang đầu Reels 10s → 60s; sự kiện xem chỉ đọc thời lượng | Cache gần như luôn trượt; `getByIds` dựng cả thẻ chỉ để lấy `durationSec` |
| Dùng `OptionalAuthGuard` của `@tripflix/auth`; cursor ngày sai không còn 500 | Bản copy thiếu timeout khi đọc blocklist |
| Commerce đếm instance bằng sorted set | `SCAN` cả keyspace Redis mỗi 5 giây |
| S3 multipart `Cache-Control: immutable` | Ảnh upload không được trình duyệt cache |
| `keepAliveTimeout 65s` (core-api, notification) | Node mặc định 5s, Traefik 90s gây 502 ngắt quãng |
| Traefik nén gzip/brotli (trừ SSE, `/ai/chat`), `/_next/static` không qua rate-limit; env BFF admin nội bộ; healthcheck web `/healthz` 30s | Không có nén HTTP; dễ 429 với 4G chung IP; BFF đi vòng qua Internet |

### tripflix-fe (13 commit)
- **api-client:** lấy cả trang bài bằng 1 request `?ids=`; poll quyền bình luận 10s → 60s; sinh lại client từ contracts.
- **web:**
  - Feed Bài viết không chạy ngầm khi tab bị ẩn.
  - Thích/Lưu không tải lại cả bảng tin.
  - hls.js `backBufferLength: 10`.
  - Avatar Reels lấy từ thẻ feed.
  - Reels dừng tự tải sau 2 trang rỗng.
  - `next/font` thay cho `@import` Google Fonts.
  - Thêm `global-error.tsx`.
- **admin:** SSE realtime tự mở lại sau khi token hết hạn (15 phút); thêm `global-error.tsx`.
- **mobile:** Explore khách sạn hết xoay mãi khi không khớp tỉnh.

### tripflix-ai (5 commit)
- Label worker bỏ qua sự kiện không phải bình luận; trước đây nó đổ mọi sự kiện bài viết, reaction vào dead-letter.
- Dead-letter `MAXLEN ~10000`.
- Label worker chờ 1s trước khi nối lại Redis (trước đây quay vòng 100% CPU).
- Redis đếm lượt `/chat` có `socket_timeout` 1s.
- `/health` chạy `async`.

### Thay đổi người dùng nhìn thấy
1. Mobile Reels có avatar tác giả (trước đây không bao giờ hiện).
2. Web/Admin có màn lỗi "Không tải được dữ liệu. Vui lòng thử lại." + nút "Thử lại" khi layout gốc lỗi; màn này **chưa có style**.
3. Mobile Explore hiện "Chưa tìm thấy khách sạn còn phòng…" thay vì xoay mãi.
4. Font Playfair Display tự host, kiểu nghiêng đậm (700/900) là font nghiêng thật.
5. Đổi độ trễ:
   - quyền bình luận cập nhật chậm tối đa 60s (trước 10s);
   - trang đầu Reels cache 60s (trước 10s);
   - tab Bài viết chỉ tải khi mở lần đầu.

## 3. Kết quả kiểm tra

| Kiểm tra | Kết quả |
|---|---|
| BE `pnpm turbo run lint typecheck test --affected` | 37/37 task pass (core-api 3132, notification 159, video-worker 53, …); int test `post.repository.int.spec.ts` (Postgres thật) pass |
| FE `pnpm turbo run lint typecheck test --affected` + `web build` | 12/12 task pass (web 582, api-client 330, admin 106, mobile pass) |
| AI `ruff`, `ruff format --check`, `pyright`, `pytest` | sạch; 1265 pass. 5 fail trong `tests/test_chat.py` là bản sửa cục bộ chưa commit trên máy người làm; bản trên `develop` pass |
| Scan lại bằng skill (`deploy_audit`, `container-cloud-auditor`, `sbom-supply-chain-auditor`) | Không có high/critical, không phát hiện nào trong file đã sửa |
| CI của PR | Cả 3 xanh |
| Publish sau merge | AI, FE xanh. BE lần đầu fail ở `core-api` và `video-worker` (`Unexpected end of JSON input` trong `pnpm`, xem mục 4.3); chạy lại thì xanh, `deploy-api` xanh |

Chưa có: ảnh/video evidence cho thay đổi giao diện; số đo lag trước/sau trên máy thật.

## 4. Việc còn lại và ai phụ trách

### 4.1 Cần làm sớm
| # | Việc | Ai | Ghi chú |
|---|---|---|---|
| 1 | Chụp ảnh evidence: avatar Reels (Mobile, chụp trên Android), màn lỗi Web/Admin, Explore rỗng (Mobile), font hero/coming-soon (Web) | Bảo, nhờ Trang (mobile), Thành (web/admin) | RULES §5 bắt buộc khi đổi giao diện |
| 2 | Quyết định style cho màn `global-error` (đang là chữ và nút mặc định của trình duyệt) | Thành | Màn này thay cả layout nên phải tự có CSS |
| 3 | Kiểm trên server sau deploy: `/ai/chat` stream và SSE admin không bị đệm khi bật nén; đo lại thời gian tải trang, đổi tab, lướt Reels | Phong, Bảo | Chưa có số đo trước/sau |
| 4 | Tạo task Notion cho đợt này (chưa có mã TF; commit không có `Refs`, tên nhánh lệch quy ước) | Bảo | RULES §2, §6, §7 |
| 5 | Chặn lỗi race của pnpm khi build Docker: thêm `ENV npm_config_verify_deps_before_run=false` vào stage `base` của các Dockerfile BE | Tech Lead | Lần sau merge có thể lại fail ngẫu nhiên |

### 4.2 Cần quyết định trước khi sửa
| # | Việc | Ai | Vì sao chưa làm |
|---|---|---|---|
| 6 | Mobile bật ABR (đưa `master.m3u8` lên đầu nguồn phát) | Trang, Phong | Code cố ý bỏ qua master (ghi chú "unsigned master playlist"), có thể vì cookie CloudFront |
| 7 | Không dựng lại 6 player khi đổi tab Reels | Trang | `key={contentTab}` là cố ý; phải refactor `usePlayerPool`, cần đo trên Android trước |
| 8 | Nén 55 MB ảnh mascot Mobile (`assets/brand`) | Trang | Sửa file binary, phải duyệt chất lượng ảnh |
| 9 | Tách gửi SMTP khỏi consumer realtime của notification | Dũng | Thay đổi kiến trúc; lượng email pilot chưa cần |
| 10 | Redis `maxmemory` | Phong, Dũng | `volatile-lru` có thể xoá khoá chống gửi trùng; DLQ đã có giới hạn |
| 11 | Dọn `stream:dead-letter` đang có trên production (`XTRIM`) | Phong | Không hoàn tác được. Replayer mới đã tự `XDEL` bản ghi `notification` ở trạng thái `done` |
| 12 | Nâng VM 2 vCPU, tune Postgres (`shared_buffers`, `shm_size`), tách `APP_ROLE` | Phong, Tech Lead | Quyết định hạ tầng, cần biết RAM của VM |

### 4.3 Audit có nêu nhưng chưa kiểm chứng
| Việc | Ai |
|---|---|
| Mobile: seek bar animate `width`, `useAnimatedKeyboard` mỗi slide, timer `ProfileHub`, poll `HeldPosts`, lệch query key `HotelRoomsScreen`, `getPost` mỗi lần lướt Reel | Trang |
| Web: `getBoundingClientRect` mỗi khung cuộn, `FeedHighlightFrame` MutationObserver, `PostCard` chưa `memo`, `rAF` của `ReelSeekBar`, `generateMetadata` fetch hai lần, tách `live-posts.tsx` (4.331 dòng) | Thành |
| Discovery: GIN của `/api/suggest`, cache `/api/places`, `/api/stays`, lock `recordQueryGrams`, `typoPool` (cần `EXPLAIN` trên dữ liệu thật) | Duy |
| Commerce: `FlightSearchUseCases` chưa dùng `READ_CALENDAR` | Thắng |
| Content DB: index `posts(hashtags)`, `posts(updated_at, id)`, `post_counter_deltas(post_id)`; job dọn `outbox_events`, `idempotency_keys`; cột `has_playable_video` khi catalog lớn | Phong, Thành, Trang |
| Deploy: S3 lifecycle `staging/uploads/`, `flock` cho `deploy-web.sh`, OTel `--import` cho trace Postgres/Redis | Phong, Dũng |

## 5. Ảnh hưởng tới phần của người khác

| Phần | Chủ | Đã đổi |
|---|---|---|
| BE `libs/`, `access`, `notification-service` | Dũng | MAXLEN, XDEL, idempotency, pool, keep-alive, `getPublicAuthors`, Cache-Control S3 |
| BE `deploy/` | Phong | compress, router file tĩnh, env admin, healthcheck |
| BE `content/feed`, `content/media` | Phong | avatarUrl, TTL 60s, `getDurations`, Cache-Control |
| BE `content/social` | Thành | `GET /v1/posts?ids=` (chỉ thêm), guard dùng chung, cursor, `findVisibleIds` |
| BE `discovery` | Duy | cache xếp hạng `trip_v1`, `findVisiblePostIds` |
| BE `commerce` | Thắng | metrics dùng sorted set |
| FE `apps/web`, `apps/admin` | Thành | các thay đổi web/admin ở mục 2 |
| FE `apps/mobile` | Trang | Explore spinner |
| AI | Bảo | label worker, dead-letter, timeout Redis, `/health` |

Không có migration mới, không thêm thư viện. API chỉ thêm tham số (`ids`) và thêm field có giá trị (`author.avatarUrl` trước đây luôn `null`).

## 6. Cách kiểm lại
1. BE: `pnpm turbo run lint typecheck test --affected`; `pnpm --filter @tripflix/core-api test:int` (cần Docker).
2. FE: `pnpm turbo run lint typecheck test --affected`; `pnpm --filter @tripflix/web build`.
3. AI: `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest`.
4. Trên server: mở DevTools trang gợi ý/tìm kiếm, thấy 1 request `GET /api/v1/posts?ids=` thay cho 7–12 request `/v1/posts/:id`; response có `Content-Encoding: gzip`/`br`; Reels Mobile hiện avatar.
