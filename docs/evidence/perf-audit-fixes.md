# Perf & Bug Audit: báo cáo sửa lỗi (đợt 1, đợt 2) và việc còn lại

- Notion: chưa có task (không có mã TF) · Nhánh: `bao/perf-audit-fixes` (đã merge) · Người làm: Bảo (dùng AI: có, Claude Code + opencode) · Ngày: 2026-11-23
- Đợt 2: nhánh `bao/perf-audit-dot-2` (chưa push, chưa có PR), mục 4–6.
- PR đợt 1: [tripflix-be#327](https://github.com/Sukemcute/tripflix-be/pull/327) · [tripflix-fe#359](https://github.com/Sukemcute/tripflix-fe/pull/359) · [tripflix-ai#64](https://github.com/Sukemcute/tripflix-ai/pull/64). Cả 3 đã merge vào `develop`; publish và deploy xanh.
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
| Publish sau merge | AI, FE xanh. BE lần đầu fail ở `core-api` và `video-worker` (`Unexpected end of JSON input` trong `pnpm`, xem mục 4.3); chạy lại thì xanh, `deploy-api` xanh. Đợt 2 đã sửa (mục 4.1) |

Chưa có: ảnh/video evidence cho thay đổi giao diện; số đo lag trước/sau trên máy thật.

## 4. Đợt 2: làm tiếp việc còn lại (2026-11-23)

Cả nhóm đã đồng ý các việc ở mục 4 bản trước. Nhánh `bao/perf-audit-dot-2` ở cả 3 repo, tách từ `bao/perf-audit-bao-cao` (= `develop` + file này). BE 12 commit, FE 10 commit, AI chỉ cập nhật file này.

### 4.1 Đã làm
| Việc | Thay đổi | Kiểm bằng |
|---|---|---|
| Review: cache `trip_v1` có thể tốn hàng trăm MB (500 phiên × tới 5.000 bài) | Mỗi phiên chỉ giữ 300 bài đầu; cuộn quá thì xếp lại như trước | Test mới: 400 bài, cuộn hết không lặp, không mất; xếp lại đúng 3 lần |
| #2 Style màn `global-error` | Style inline theo `@tripflix/tokens`, nút giống nút primary của `ui-web` (web, admin dùng chung bản) | typecheck web, admin |
| #5 Lỗi race của pnpm khi build Docker | `npm_config_verify_deps_before_run=false` ở stage `base` của Dockerfile core-api, notification-service, video-worker | `docker build` core-api (stage build, prod) xanh |
| #6 Mobile bật ABR | `getAdaptiveReelPlaybackSources`: `master.m3u8` trước, bản lẻ làm dự phòng; trần 540p khi tiết kiệm dữ liệu vẫn qua `maxResolution`. Web giữ nguyên | Test `app-core` |
| #8 Ảnh mascot 55 MB | Ảnh tĩnh 1254px → 768px (giữ PNG, không giảm số màu để viền trong suốt không răng cưa): thư mục `assets/brand` 55 MB → 31 MB. Ảnh động 512px giữ nguyên | Xem lại bằng mắt một ảnh; Trang duyệt trên máy |
| #10 Redis `maxmemory` | `--maxmemory ${REDIS_MAXMEMORY:-0} --maxmemory-policy noeviction`; cách chọn giá trị ở `deploy/SERVER.md` | `docker compose config` |
| #11 Dọn `stream:dead-letter` trên production | Không cần `XTRIM` tay: lần ghi kế tiếp tự gọn về ~10.000 (`MAXLEN ~`), replayer gỡ bản đã gửi. Ghi vào `SERVER.md` | Đọc code |
| #12 Tune Postgres | `shm_size: 256mb` (mặc định 64 MB làm truy vấn song song lỗi), `shared_buffers=${PG_SHARED_BUFFERS:-128MB}` | `docker compose config` |
| Commerce: `READ_CALENDAR` | Tìm chuyến bay và dải giá đọc lịch từ bộ nhớ như trang khách sạn; giữ chỗ vẫn kiểm trong database | Test mới trong `flight-search.use-cases.spec.ts` |
| Content DB: index | GIN `posts(hashtags)`, `posts(updated_at, id)`, `post_counter_deltas(post_id)`. Migration chỉ có `CREATE INDEX` | Int test content trên Postgres thật |
| Content DB: job dọn | `ContentCleanupJob`: xoá `idempotency_keys` hết hạn theo lô 5.000 và outbox đã gửi quá 7 ngày, mỗi 24 giờ (giống commerce) | Test `runContentCleanup` |
| Discovery: lock `recordQueryGrams` | Upsert theo thứ tự gram để hai câu tìm cùng lúc không deadlock (ghi chạy nền nhưng giữ kết nối pool) | Test discovery |
| Discovery: `typoPool` | Index một phần `(left(key,1), length(key)) WHERE ns='df'` | `EXPLAIN ANALYZE` 160k dòng: Bitmap Index Scan, 1,6 ms |
| Discovery: `/api/places`, `/api/suggest` | Cache 60 giây. places trước đây đọc toàn bộ điểm OSM mỗi request; suggest quét cả bảng mỗi lần gõ (~13 ms trên 2.500 dòng) | Test mới cho cả hai |
| Deploy: S3 lifecycle | `staging/uploads/` (video gốc) xoá sau 30 ngày; áp bằng `deploy/aws/setup-dev-media.sh` | JSON hợp lệ |
| Deploy: `flock` | `deploy-web.sh` khoá như `deploy-api.sh` (web và admin cùng ghi `.env.web`) | `sh -n` |
| Deploy: OTel `--import` | `NODE_OPTIONS=--import @tripflix/observability/register` cho core-api, notification-service | Chạy image prod của cả hai với hook: nạp đủ module, dừng ở bước kiểm env như bản không có hook |
| Web: `ReelSeekBar` rAF | Video dừng thì kiểm lại 4 lần/giây thay vì mỗi khung hình | typecheck, test web |
| Web: `FeedHighlightFrame` | Bỏ `characterData`; chỉ observe lại khi danh sách con trực tiếp đổi | typecheck, test web |
| Mobile: seek bar | `scaleX` từ mép trái thay cho đổi `width` mỗi khung hình | typecheck |
| Mobile: `useAnimatedKeyboard` mỗi slide | Chỉ dựng panel bình luận khi mở (panel đóng vốn đã `return null`) | typecheck |
| Mobile: timer `ProfileHub` | Hẹn giờ đúng lúc chỗ giữ hết hạn sớm nhất, thôi vẽ lại mỗi giây | typecheck |
| Mobile: poll `HeldPosts` | 10 giây chỉ khi màn đang mở (`useIsFocused`) | typecheck |
| Mobile: query key `HotelRoomsScreen` | Cùng khoá với màn khách sạn (chỉ ngày + người lớn): mở danh sách phòng không gọi lại `getHotel` | typecheck |

### 4.2 Kiểm rồi, không sửa
| Việc | Lý do |
|---|---|
| Bug D (review): label worker không ack entry rỗng của `XAUTOCLAIM` | Redis 8 tự gỡ entry đã xoá khỏi PEL; không phải lỗi |
| Bug B (review): `complete()` lỗi thì gửi lại nhận 409 tới hết TTL | Đánh đổi đã chốt: thà 409 còn hơn chạy lần hai |
| Web: `generateMetadata` fetch hai lần | Sai: `features/seo/public-data.ts` dùng `React.cache`, metadata và trang chung một lần gọi |
| Web: `getBoundingClientRect` mỗi khung cuộn | Đã gộp bằng rAF, chỉ đọc không ghi xen kẽ nên không layout thrash |
| Web: `PostCard` chưa `memo` | Props có callback tạo mới mỗi lần render (`onViewItinerary`), `memo` không có tác dụng nếu không sửa lớn `social-feed-view.tsx`; chưa đo được là chậm |
| Web: tách `live-posts.tsx` | Refactor lớn, không tự làm nhanh hơn; nên là task riêng của Thành |
| Discovery: GIN cho `/api/suggest` | Index trigram đã có. Viết lại câu cho dùng được index (`<%`, LIKE trên cột) thì planner vẫn seq scan ở 2.500 dòng; đã cache thay (4.1) |
| `/api/stays` cache | Có giá và số phòng; commerce đã đọc lịch từ bản 10 giây trong bộ nhớ |
| Mobile: `getPost` mỗi lần lướt Reel | Một request cho Reel đang xem để lấy hashtag và trạng thái thích/lưu mới nhất. Muốn bỏ thì BE thêm hashtag vào thẻ feed (task riêng) |
| Cột `has_playable_video` | Audit ghi "khi catalog lớn"; chưa tới lúc |

### 4.3 Còn lại, cần người hoặc cần quyết định thêm
| # | Việc | Ai | Vì sao chưa xong |
|---|---|---|---|
| 1 | Ảnh evidence: avatar Reels, Explore rỗng, ABR, mascot (Android); màn `global-error`, font (web/admin) | Trang, Thành, Bảo | Cần chạy app thật; máy làm không có Android |
| 3 | Kiểm trên server: `/ai/chat`, SSE admin, `/ws` Socket.IO khi bật nén; đo trước/sau; đặt `REDIS_MAXMEMORY`, `PG_SHARED_BUFFERS` theo RAM rồi `dc up -d postgres redis`; chạy `setup-dev-media.sh` để áp lifecycle | Phong, Bảo | Cần quyền server và RAM của VM |
| 4 | Task Notion, mã TF cho cả hai đợt; tên nhánh và commit chưa có `Refs` | Bảo | Không có quyền Notion trong phiên này |
| 7 | Không dựng lại 6 player khi đổi tab Reels | Trang | Pool nằm trong `ReelsFeed` key theo tab; bỏ key phải tự reset vị trí, trang, trạng thái refresh. Cần đo trên Android trước như đã thống nhất |
| 9 | Tách gửi SMTP khỏi consumer realtime | Dũng | Group mới tạo ở id `0` sẽ đọc lại cả lịch sử stream và gửi lại email cũ. Cần thiết kế: tạo group ở `$`, khoá chống trùng riêng, replayer DLQ cho group mới |
| 12 | Nâng VM 2 vCPU, tách `APP_ROLE` | Phong, Tech Lead | Quyết định hạ tầng; tách role thêm một tiến trình Node, chỉ nên làm sau khi nâng VM |

## 5. Ảnh hưởng tới phần của người khác

| Phần | Chủ | Đợt 1 | Đợt 2 |
|---|---|---|---|
| BE `libs/`, `access`, `notification-service` | Dũng | MAXLEN, XDEL, idempotency, pool, keep-alive, `getPublicAuthors`, Cache-Control S3 | — |
| BE `deploy/` | Phong | compress, router file tĩnh, env admin, healthcheck | Redis/Postgres, S3 lifecycle, `flock`, OTel `--import` |
| BE `content/feed`, `content/media` | Phong | avatarUrl, TTL 60s, `getDurations`, Cache-Control | — |
| BE `content/social`, `content/db` | Thành (db: Phong, Thành, Trang) | `GET /v1/posts?ids=`, guard dùng chung, cursor, `findVisibleIds` | 3 index (migration), `ContentCleanupJob` |
| BE `discovery` | Duy | cache `trip_v1`, `findVisiblePostIds` | giới hạn cache, upsert theo thứ tự, index `typoPool` (migration), cache places/suggest |
| BE `commerce` | Thắng | metrics dùng sorted set | flight search dùng `READ_CALENDAR` |
| BE Dockerfile | Tech Lead | — | tắt verify-deps của pnpm |
| FE `apps/web`, `apps/admin` | Thành | các thay đổi ở mục 2 | `global-error` có style, seek bar, highlight frame |
| FE `apps/mobile`, `packages/app-core` | Trang | Explore spinner | ABR, mascot, seek bar, panel bình luận, ProfileHub, HeldPosts, query key phòng |
| AI | Bảo | label worker, dead-letter, timeout Redis, `/health` | — |

Đợt 2 có 2 migration chỉ thêm index (content, discovery); `CREATE INDEX` khoá ghi bảng trong lúc dựng, bảng pilot nhỏ nên không đáng kể. Không thêm thư viện, không đổi API.

## 6. Kết quả kiểm tra đợt 2

| Kiểm tra | Kết quả |
|---|---|
| BE `pnpm turbo run lint typecheck test --affected` | 37/37 task pass: core-api 3137 pass, 4 skip; notification 159; video-worker 53; libs pass |
| BE int test (Postgres thật) | `post.repository.int.spec.ts`, `drizzle-places.store.int.spec.ts` pass, chạy cả 2 migration mới |
| BE `docker build` | core-api, notification-service (stage prod) xanh; chạy được với `--import` OTel |
| FE `pnpm turbo run lint typecheck test --affected` | 15/15 task pass: web 582, api-client 330, app-core 263, admin 106, mobile 6 |
| FE `next build` | web, admin xanh |
| AI | Không đổi code, chỉ đổi file này |

Lần chạy đầu chạy BE và FE cùng lúc trên một máy nên quá tải: 1 test realtime theo thời gian của notification-service (token hết hạn trong 2 giây, chờ 4 giây), 1 test core-api và worker vitest của web bị chết. Chạy lại tuần tự thì pass hết, chưa sửa gì. Lint chỉ còn warning có từ trước.

Chưa có: ảnh evidence UI, đo trên Android (ABR, panel bình luận, seek bar), số đo trên server (mục 4.3).

## 7. Cách kiểm lại
1. BE: `pnpm turbo run lint typecheck test --affected`; `pnpm --filter @tripflix/core-api test:int` (cần Docker).
2. FE: `pnpm turbo run lint typecheck test --affected`; `pnpm --filter @tripflix/web build`.
3. AI: `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest`.
4. Trên server: mở DevTools trang gợi ý/tìm kiếm, thấy 1 request `GET /api/v1/posts?ids=` thay cho 7–12 request `/v1/posts/:id`; response có `Content-Encoding: gzip`/`br`; Reels Mobile hiện avatar.
5. Đợt 2 trên server: `dc exec redis redis-cli config get maxmemory-policy` ra `noeviction`; `dc exec postgres df -h /dev/shm` ra 256M; Tempo có span `pg`, `ioredis` của core-api; `\di content.idx_posts_hashtags` có sau migrate.
