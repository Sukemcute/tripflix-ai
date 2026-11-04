# Đề xuất cấu trúc repo — Tripflix

**Phiên bản:** 1.1 · **Ngày:** 2026-11-04 · **Trạng thái:** Baseline v1.0 đã duyệt (còn chờ Q7: tên GitHub org); các thay đổi database ở v1.1 là đề xuất, chờ duyệt · **Người đọc:** cả team kỹ thuật · **Dựa trên:** [docs/10 v0.6](10-de-xuat-kien-truc-va-repo.md)

> Tóm tắt: giữ **3 repo** như docs/10 (`tripflix-be`, `tripflix-fe`, `tripflix-ai`). Hai repo TypeScript dùng chung một bộ công cụ: **pnpm + Turborepo**. Backend dùng **NestJS + Drizzle**. Mỗi module của `core-api` có **kết nối database và transaction riêng**, nên không thể vô tình mở transaction chéo module. `core-api` chạy được 2 vai trò từ cùng code: `api` (nhận request) và `worker` (job, consumer, outbox relay). Hợp đồng giữa các repo (OpenAPI, schema sự kiện) được sinh ra và commit vào thư mục `contracts/` của repo phát hành. **Cả hệ thống chạy bằng Docker với một lệnh** `pnpm stack:up` từ repo BE (§7): build từ 3 repo đặt cạnh nhau, tự migrate và seed, có chế độ tự cập nhật khi sửa code.

> **Phạm vi thay đổi v1.1 đang chờ duyệt:** gộp schema `commerce` vào database `core` và chuẩn bị đường tách `discovery`. Cho đến khi team chốt, kiến trúc đã duyệt vẫn là docs/10 v0.6 và sơ đồ v4.5 (Postgres `core` + `commerce`); các phần v1.1 liên quan database trong tài liệu này chỉ là phương án, chưa phải chỉ dẫn triển khai.

---

## 1. Các điểm cần duyệt

| # | Câu hỏi | Đề xuất | Lý do | Phương án khác |
|---|---|---|---|---|
| Q1 | Công cụ monorepo cho BE (docs/10 §10 còn mở) | **pnpm + Turborepo**, giống FE | Một công cụ cho cả 2 repo TS; nhẹ, ít cấu hình. Ranh giới module đã giữ bằng `eslint-plugin-boundaries` và quyền Postgres (§3.6) nên không cần Nx | Nx: có sẵn `@nx/enforce-module-boundaries`, nhưng muốn dùng phải tách mỗi module thành một lib Nx, thêm `project.json`, executor; nặng với nhóm 7 người trong 4 tuần |
| Q2 | ORM (docs/10 §10 còn mở) | **Drizzle**, ghim đúng bản `1.0.0-rc.5` | Team đã dùng Drizzle ở dự án trước. Viết SQL gần như thuần nên dễ làm cập nhật có điều kiện (`total - held - sold >= qty`), `tsvector`, `pgvector`. Khai báo schema Postgres theo module bằng `pgSchema`. Có adapter cho `@nestjs-cls/transactional` | Prisma: không so sánh được hai cột trong `where` (phải viết `$executeRaw`), nhiều client cho nhiều database thì rườm rà. Drizzle `0.45` (bản ổn định team đã dùng) nếu RC gặp lỗi; đổi lên 1.0 sau sẽ phải đổi định dạng thư mục migration |
| Q3 | Mỗi module một kết nối database | **Có**: 5 kết nối có tên (`access`, `content`, `discovery`, `analytics`, `commerce`), cùng vào database `core`, mỗi kết nối một user Postgres chỉ có quyền trên schema của mình | Quy tắc "không query chéo schema, không transaction chéo module" (docs/10 §3.2) được Postgres và code chặn luôn, không chỉ dựa vào review | Một kết nối chung cho cả core: ít pool hơn nhưng quy tắc chỉ còn trên giấy |
| Q4 | Tách tiến trình job khỏi API | `core-api` có biến `APP_ROLE=api\|worker\|all`. Dev chạy `all`; deploy chạy riêng `api` và `worker` | Job hết hạn đơn, mở lịch trống, outbox relay, consumer của `discovery` và `analytics` không tranh CPU với request; scale API mà không nhân đôi job | Tách app riêng: thêm Dockerfile, CI, mà không thêm lợi ích ở MVP |
| Q5 | Đồng bộ hợp đồng giữa repo | Repo phát hành **commit** file sinh ra vào `contracts/`; repo dùng đọc từ thư mục anh em `../tripflix-be/contracts` rồi commit code client sinh ra | Repo để private nên không đọc raw URL được nếu không có token; FE, AI build được mà không cần BE đang chạy | Publish package npm/PyPI riêng: quá nặng cho 4 tuần |
| Q6 | Sinh API client cho FE | **Orval**: hook TanStack Query + schema zod | Ra sẵn hook truy vấn, mutation, query key; zod dùng lại cho form | `openapi-typescript` + `openapi-fetch`: nhẹ hơn, nhưng phải tự viết hook |
| Q7 | Tên GitHub organization | Cần anh/chị chọn, ví dụ `tripflix-vsf` | 3 repo private chung một org, đặt branch protection và CODEOWNERS | — |
| Q8 | Chạy cả hệ thống bằng Docker | Một file `deploy/compose.yaml` trong repo BE, **build từ mã nguồn của 3 repo cạnh nhau**, chia profile; lệnh `pnpm stack:*` (§7) | Ai cũng chạy được cả hệ thống mà không cần cài đúng bản Node, Python của phần không phải mình làm; bản chạy luôn khớp code mới nhất trên máy | Kéo image dựng sẵn từ GHCR: nhanh hơn nhưng chậm một nhịp so với code đang sửa; để dành cho staging |
| Q9 | Lưu video, ảnh ở môi trường dev | **Bucket S3 thật dành cho dev** (`tripflix-media-dev`) + 1 CloudFront dev; mỗi người một thư mục `dev/<tên>/` và một IAM key chỉ ghi được thư mục đó. Không dùng MinIO | Đúng kiến trúc S3 + CloudFront đã chốt, nên lỗi CORS, upload nhiều phần, cache HLS lộ ra ngay ở dev. Điện thoại thật tải video được luôn, không phải cấu hình IP. MinIO bản cộng đồng đã ngừng phát hành image (10/2025) và repo bị archive (04/2026) | S3 giả lập chạy local (SeaweedFS): chạy offline, không tốn phí, nhưng lại phải xử lý địa chỉ cho điện thoại và vẫn khác S3 thật |

## 2. Tổng quan

### 2.1. Ba repo và cách đặt trên máy

```
tripflix/                  # thư mục cha trên máy mỗi người, clone 3 repo cạnh nhau
├─ tripflix-be/            # core-api, notification-service, video-worker, hạ tầng local
├─ tripflix-fe/            # mobile (Expo), web, admin (Next.js)
└─ tripflix-ai/            # ai-service (FastAPI)
```

Clone cạnh nhau là quy ước bắt buộc: script sinh client của FE và AI đọc hợp đồng từ `../tripflix-be/contracts`.

### 2.2. Phiên bản dùng chung

| Thành phần | Bản | Ghim ở đâu |
|---|---|---|
| Node.js | 24 LTS | `.nvmrc`, `engines` trong `package.json` |
| pnpm | 10.x | `packageManager` trong `package.json` (bật bằng `corepack enable`) |
| Turborepo | 2.x | devDependency gốc |
| TypeScript, zod 4, React 19.2 | bản stable lúc tạo repo | **pnpm catalog** trong `pnpm-workspace.yaml`, mọi app dùng `catalog:` để không lệch bản |
| NestJS | 11 trở lên (stable mới nhất) | catalog BE |
| Drizzle ORM + drizzle-kit | `1.0.0-rc.5` (ghim chính xác) | catalog BE |
| Expo SDK | 56 (React Native 0.85, React 19.2) | `apps/mobile` |
| Next.js | 16 | catalog FE |
| Python | 3.13, quản lý bằng uv | `.python-version`, `pyproject.toml` |
| Postgres | 17, image `pgvector/pgvector:pg17` (có sẵn `pgvector`; `unaccent`, `pg_trgm` có sẵn trong Postgres) | `deploy/compose.yaml` |
| Redis | 7.4 trở lên, bật AOF | `deploy/compose.yaml` |

Expo SDK 56 và Next.js 16 cùng dùng React 19.2, nên một bản React trong catalog là đủ. Expo hỗ trợ pnpm ở chế độ isolated từ SDK 54, không cần `nodeLinker: hoisted` ([Expo — Monorepos](https://docs.expo.dev/guides/monorepos/)).

## 3. `tripflix-be`

### 3.1. Cây thư mục

```
tripflix-be/
├─ apps/
│  ├─ core-api/
│  │  ├─ src/
│  │  │  ├─ main.ts                # đọc APP_ROLE: api | worker | all
│  │  │  ├─ app.module.ts
│  │  │  ├─ platform/              # gắn libs vào Nest: config, health, swagger, filter lỗi, trace-id
│  │  │  └─ modules/
│  │  │     ├─ access/             # auth, sessions, vai trò, JWKS
│  │  │     ├─ content/            # social/ media/ feed/ moderation/
│  │  │     ├─ discovery/          # search/ recommend/
│  │  │     ├─ commerce/           # inventory/ booking/ payment/   → schema commerce (đề xuất v1.1)
│  │  │     └─ analytics/          # ingest/ marts/ api/
│  │  ├─ scripts/                  # migrate.ts, seed.ts, export-openapi.ts
│  │  ├─ test/                     # integration (Testcontainers), e2e
│  │  ├─ Dockerfile
│  │  └─ package.json
│  ├─ notification-service/
│  │  ├─ src/
│  │  │  ├─ consumers/             # consumer group "notification"
│  │  │  ├─ inbox/                 # in-app: bảng inbox + WebSocket (Socket.IO, adapter Redis)
│  │  │  ├─ delivery/              # out-app: hàng đợi push, email (BullMQ), thử lại, dead-letter
│  │  │  ├─ preferences/           # tắt từng loại, giờ im lặng, giới hạn mỗi giờ
│  │  │  ├─ grouping/              # gom "Lan và 11 người khác…"
│  │  │  └─ db/                    # schema, migrations của database notification
│  │  ├─ Dockerfile
│  │  └─ package.json
│  └─ video-worker/
│     ├─ src/
│     │  ├─ consumer/              # consumer group "video-worker"
│     │  ├─ transcode/             # thang chất lượng 360p/540p/720p, đoạn 2 giây, ảnh bìa
│     │  └─ storage/               # đọc file gốc, ghi HLS vào thư mục r{n}/ trên S3
│     ├─ Dockerfile                # base image có sẵn FFmpeg
│     └─ package.json
├─ libs/
│  ├─ contracts/                   # zod: phong bì sự kiện + payload theo version; enum vai trò; xuất JSON Schema
│  ├─ event-bus/                   # interface EventBus + adapter Redis Streams (XADD, XREADGROUP, XAUTOCLAIM, dead-letter)
│  ├─ outbox/                      # hàm tạo bảng outbox theo schema + relay outbox → event-bus
│  ├─ db/                          # tạo pool + Drizzle theo tên kết nối, đăng ký transaction host, helper partition
│  ├─ auth/                        # guard kiểm JWT qua JWKS, @Roles, token service-to-service
│  ├─ idempotency/                 # interceptor Idempotency-Key, bảng idempotency_keys
│  ├─ observability/               # logger pino, trace-id, metrics
│  ├─ config/                      # đọc biến môi trường bằng zod, thiếu biến thì dừng ngay khi khởi động
│  ├─ storage/                     # interface ObjectStorage (ký URL tải lên nhiều phần, đọc, ghi, link CDN); adapter S3 + adapter bộ nhớ cho test
│  └─ testing/                     # Testcontainers (Postgres, Redis), factory dữ liệu
├─ contracts/                      # FILE SINH RA, có commit; CI báo lỗi nếu chưa cập nhật
│  ├─ openapi/
│  │  ├─ core-api.json
│  │  └─ notification-service.json
│  └─ events/
│     └─ <tên-sự-kiện>.v1.schema.json
├─ deploy/
│  ├─ compose.yaml                 # chạy cả hệ thống, chia profile (§7)
│  ├─ .env.example                 # cổng, đường dẫn 3 repo, thông tin bucket S3 dev; chép thành deploy/.env
│  ├─ postgres/init/               # chạy 1 lần bằng superuser
│  │  ├─ 01-databases.sql          # core, notification (phương án v1.1; baseline còn commerce)
│  │  ├─ 02-roles-schemas.sql      # user và schema cho từng module
│  │  └─ 03-extensions.sql         # vector, unaccent, pg_trgm
│  ├─ traefik/                     # route, rate limit, kiểm JWT
│  └─ aws/                         # cấu hình bucket media (CORS, lifecycle xoá file tải dở), policy IAM theo thư mục dev/<tên>/, CloudFront
├─ turbo/generators/               # `pnpm turbo gen module`: tạo khung module mới
├─ docs/adr/                       # ghi lại quyết định kỹ thuật, mỗi quyết định 1 file
├─ .github/
│  ├─ workflows/                   # ci.yml, docker.yml, contracts-check.yml
│  ├─ CODEOWNERS
│  └─ pull_request_template.md
├─ .env.example
├─ .dockerignore
├─ .gitattributes                  # * text=auto eol=lf (script, SQL chạy trong container không bị CRLF)
├─ eslint.config.mjs               # luật ranh giới module (§3.6)
├─ tsconfig.base.json
├─ turbo.json
├─ pnpm-workspace.yaml
└─ package.json
```

Tên package trong workspace: `@tripflix/core-api`, `@tripflix/contracts`, `@tripflix/event-bus`…

### 3.2. Bên trong một module (ví dụ `commerce`)

```
modules/commerce/
├─ index.ts                        # PUBLIC API duy nhất: CommerceModule, CommerceFacade, kiểu dữ liệu trả ra
├─ commerce.module.ts
├─ commerce.facade.ts              # checkAvailability(ids, dates), getProductCards(ids)… cho module khác gọi
├─ inventory/
│  ├─ api/                         # controller, DTO (zod) — admin "Lịch trống & giá"
│  ├─ application/                 # use case: UpdateRatesUseCase… (@Transactional('commerce'))
│  ├─ domain/                      # quy tắc thuần, không import Nest hay Drizzle
│  ├─ infra/                       # repository Drizzle
│  └─ jobs/                        # mở lịch trống 180 ngày, 6 giờ/lần
├─ booking/
│  ├─ api/                         # POST /checkout, GET /orders/:id
│  ├─ application/                 # CheckoutUseCase, ExpireHoldsUseCase
│  ├─ domain/                      # Order, trạng thái PENDING → PAID/EXPIRED, giữ chỗ 30 phút
│  ├─ infra/
│  └─ jobs/                        # hết hạn đơn, mỗi phút
├─ payment/
│  ├─ api/                         # POST /orders/:id/pay, webhook cổng giả lập
│  ├─ application/                 # PayOrderUseCase, RefundUseCase, ReconcileUseCase
│  ├─ domain/
│  ├─ infra/                       # gateway thanh toán giả lập
│  └─ jobs/                        # đối soát định kỳ
├─ events/                         # sự kiện module phát ra (dùng schema trong libs/contracts)
└─ db/
   ├─ schema/                      # bảng Drizzle, pgSchema('commerce'): properties, room_inventory, orders, payments, refunds, outbox…
   ├─ migrations/                  # migration riêng của module
   ├─ seed/                        # seed dữ liệu giả lập, chạy lại được
   └─ drizzle.config.ts
```

Các module khác theo cùng khuôn: thư mục phần con (`content/social`, `content/feed`…) chứa `api/ application/ domain/ infra/`, có thêm `consumers/` nếu nghe sự kiện, `jobs/` nếu có job định kỳ. Thư mục `db/` đặt ở cấp module vì các phần con dùng chung schema.

| Thư mục | Được làm | Không được làm |
|---|---|---|
| `api/` | Nhận request, kiểm DTO, gọi use case | Mở transaction, gọi repository trực tiếp |
| `application/` | Use case, `@Transactional('<module>')`, ghi outbox | Gọi dịch vụ ngoài **bên trong** transaction |
| `domain/` | Quy tắc nghiệp vụ thuần, test nhanh | Import `@nestjs/*`, `drizzle-orm` |
| `infra/` | Repository, client dịch vụ ngoài | Chứa quy tắc nghiệp vụ |
| `consumers/`, `jobs/` | Nghe sự kiện, job định kỳ; chỉ đăng ký khi `APP_ROLE` là `worker` hoặc `all` | — |

### 3.3. Kết nối database và transaction theo module

> **Đề xuất v1.1, chưa triển khai:** các kết nối trong bảng dưới đây đưa `commerce` vào database `core`. Baseline đã duyệt vẫn tách database `commerce` riêng; chỉ đổi sơ đồ và cấu hình khi team phê duyệt.

| Tên kết nối | Database | User Postgres | Schema được phép | Pool (gợi ý) |
|---|---|---|---|---|
| `access` | `core` | `tf_access` | `access` | 5 |
| `content` | `core` | `tf_content` | `content` | 10 |
| `discovery` | `core` | `tf_discovery` | `discovery` | 5 |
| `analytics` | `core` | `tf_analytics` | `analytics` | 3 (giới hạn để thống kê không chiếm kết nối) |
| `commerce` | `core` | `tf_commerce` | `commerce` | 10 |

`libs/db` đăng ký mỗi kết nối thành một `ClsPluginTransactional` có `connectionName` riêng ([nestjs-cls — Transactional, mục Multiple databases](https://papooch.github.io/nestjs-cls/plugins/available-plugins/transactional); [adapter Drizzle](https://papooch.github.io/nestjs-cls/plugins/available-plugins/transactional/drizzle-orm-adapter)). Use case khai báo rõ transaction thuộc module nào:

```ts
// modules/commerce/booking/application/checkout.use-case.ts
@Injectable()
export class CheckoutUseCase {
  constructor(
    @InjectTransactionHost('commerce') private readonly tx: TransactionHost<CommerceDb>,
    private readonly inventory: InventoryRepository,
    private readonly orders: OrderRepository,
    private readonly outbox: CommerceOutbox,
  ) {}

  @Transactional('commerce')
  async execute(cmd: CheckoutCommand): Promise<CheckoutResult> {
    await this.inventory.holdAll(cmd.items);        // UPDATE có điều kiện, thiếu 1 mục thì throw → rollback
    const order = await this.orders.createPending(cmd, { holdMinutes: 30 });
    await this.outbox.add('commerce.order.created', { orderId: order.id /* … */ });
    return order.toResult();
  }
}
```

Vì mỗi module là một kết nối riêng, một use case của `content` **không thể** ghi vào bảng `commerce` trong cùng transaction: hai kết nối khác nhau, và user `tf_content` không có quyền trên schema `commerce`.

`commerce` nằm chung database `core` với các module khác (v1.1). Tồn kho, đơn hàng và thanh toán đều là dữ liệu của chính nền tảng (không có hệ thống bán hàng bên ngoài), đơn hàng gắn với `user_id` và bài đăng nguồn, nên tách database riêng chỉ làm khó việc tra cứu chéo ở trang quản trị và thống kê. Ranh giới vẫn được giữ bằng schema `commerce` và user `tf_commerce`.

`discovery` (search, recommend) cũng nằm trong `core` nhưng được chuẩn bị để tách ra khi search tải lớn (v1.1):

- Có biến môi trường riêng `DB_DISCOVERY_URL`. Hôm nay trỏ vào `core`; khi cần thì trỏ sang read replica hoặc một instance Postgres khác và chạy migration của `discovery` ở đó, không phải sửa code.
- Điều kiện để tách được: `discovery` chỉ đọc, ghi schema của mình, không `JOIN` và không khoá ngoại sang schema khác. Dữ liệu cần từ module khác được chép vào bảng riêng (`posts_search`, `products_search`) qua hàm `indexPost` / `removePost` và job nạp định kỳ.
- Giới hạn để search không làm chậm module khác khi dùng chung instance: pool 5 kết nối và `ALTER ROLE tf_discovery SET statement_timeout = '500ms'`.
- Tách khi đo thấy cần: p95 phần SQL của search vượt 300 ms, hoặc checkout chậm đi rõ khi search tải cao. Chi tiết ở tài liệu Search (`10-nghiep-vu-kien-truc-search.md`, mục 7 và D11).

### 3.4. Migration

- Mỗi module có `db/drizzle.config.ts` riêng: chỉ quét schema của mình, bảng lịch sử migration nằm trong schema của module (`content.__migrations`). Module nào sửa bảng thì chỉ sinh migration trong thư mục của module đó; tách module thành service sau này chỉ cần mang thư mục đi.
- Phần Drizzle không khai báo được (partition theo ngày của `analytics.events`, index BRIN, trigger `tsvector`) viết bằng migration SQL tự viết (`drizzle-kit generate --custom`).
- Extension (`vector`, `unaccent`, `pg_trgm`), database và user tạo một lần trong `deploy/postgres/init/` bằng superuser. Migration của module chạy bằng user của module.
- Lệnh: `pnpm db:migrate` chạy lần lượt `access → content → discovery → analytics → commerce`, rồi `notification-service`. `pnpm db:generate <module>` sinh migration cho một module. `pnpm db:seed` và `pnpm demo:reset` (seed lại schema `commerce` và ≤ 500 bài mẫu).

### 3.5. Hai vai trò của `core-api`

| `APP_ROLE` | Chạy gì | Dùng khi |
|---|---|---|
| `api` | Controller HTTP, `/events` (nhận sự kiện hành vi từ app), Swagger | Deploy, scale theo request |
| `worker` | Outbox relay của 5 module, consumer `core-discovery`, `core-analytics`, BullMQ processor, job định kỳ (hết hạn đơn, mở lịch trống, đối soát, làm mới `mart_*`, tạo partition) | Deploy, 1–2 replica |
| `all` | Cả hai | Dev local, demo |

Cùng một Docker image, chỉ khác biến môi trường.

### 3.6. Giữ ranh giới bằng công cụ

`eslint-plugin-boundaries` trong `eslint.config.mjs`, CI chạy lint là chặn:

| Từ | Được import | Bị chặn |
|---|---|---|
| `modules/A/**` | `modules/B/index.ts`; `libs/*` | `modules/B/**` ngoài `index.ts` |
| `modules/A/*/domain/**` | `domain/` khác trong cùng module | `@nestjs/*`, `drizzle-orm`, `infra/`, `api/` |
| `libs/*` | `libs/*` khác | `apps/**` |
| `apps/X/**` | `libs/*` | `apps/Y/**` |

Thêm 2 lớp chặn ngoài lint: quyền Postgres theo user (§3.3) và `CODEOWNERS` theo thư mục (§6.3).

### 3.7. Hạ tầng local

Toàn bộ cách chạy bằng Docker ở §7.

### 3.8. Test

| Loại | Công cụ | Ví dụ bắt buộc |
|---|---|---|
| Unit | Vitest (+ `unplugin-swc` cho decorator của Nest) | Quy tắc trong `domain/` |
| Integration | Vitest + Testcontainers (Postgres, Redis thật) | Hai người tranh phòng cuối chỉ một người giữ được; gửi lại `Idempotency-Key` không trừ tiền lần hai; xoay vòng refresh token |
| E2E | Supertest trên app đã khởi động | Đăng ký → đăng nhập → `/auth/me` |

## 4. `tripflix-fe`

```
tripflix-fe/
├─ apps/
│  ├─ mobile/                      # Expo SDK 56, Expo Router, Android trước
│  │  ├─ app/                      # route theo file: (tabs)/feed, explore, trips, inbox, me; post/[id]; checkout/…
│  │  ├─ src/
│  │  │  ├─ features/              # feed (PlayerPool, Preloader), post, search, booking, assistant, inbox, auth
│  │  │  ├─ components/
│  │  │  └─ lib/                   # gắn token (expo-secure-store), hàng đợi thao tác dở khi mất mạng, gửi sự kiện hành vi
│  │  ├─ app.config.ts
│  │  └─ eas.json                  # profile build: development, preview (APK demo), production
│  ├─ web/                         # Next.js 16, App Router, output: 'standalone'
│  │  ├─ Dockerfile
│  │  └─ src/
│  │     ├─ app/                   # tìm kiếm, bài đăng, chi tiết khách sạn, checkout, chuyến đi của tôi
│  │     └─ features/
│  └─ admin/                       # Next.js 16, output: 'standalone'
│     ├─ Dockerfile
│     └─ src/
│        ├─ app/                   # moderation/, analytics/, inventory/ (Lịch trống & giá), orders/, staff/
│        └─ features/
├─ packages/
│  ├─ api-client/                  # Orval sinh: hook TanStack Query + zod; FILE SINH RA có commit
│  │  ├─ orval.config.ts           # đọc ../tripflix-be/contracts/openapi/*.json, ../tripflix-ai/contracts/openapi/*.json
│  │  └─ src/http.ts               # fetch chung: Bearer token, tự refresh, Idempotency-Key, trace-id
│  ├─ app-core/                    # logic nghiệp vụ không có giao diện (giỏ lộ trình, tính tiền, đếm ngược giữ chỗ, kiểm form); cấm import react-native, react-dom
│  ├─ ui-web/                      # shadcn/ui + Tailwind v4, dùng cho web và admin
│  ├─ tokens/                      # màu, font, khoảng cách theo brand; xuất CSS variables (web) và object (mobile)
│  ├─ i18n/                        # chuỗi tiếng Việt
│  ├─ utils/                       # định dạng VND, ngày, rút gọn số đếm
│  └─ config/                      # eslint, tsconfig, prettier dùng chung
├─ .github/  (workflows, CODEOWNERS, pull_request_template.md)
├─ .env.example
├─ turbo.json
├─ pnpm-workspace.yaml             # khai báo catalog: react, typescript, zod, @tanstack/react-query
└─ package.json
```

#### Ranh giới Front Office / Back Office

- `apps/mobile` và `apps/web` là **Front Office** cho khách/thành viên: khám phá, xem nội dung và đặt dịch vụ. `apps/admin` là **Back Office** (Admin Console nội bộ) dành cho `moderator` và `superadmin`.
- Hai phía là ứng dụng riêng, cùng đi qua API Gateway và `core-api`. Back Office dùng API quản trị cho `content`, `analytics`, `commerce` và `access`; backend bắt buộc kiểm tra role, không dựa vào ẩn nút phía client.
- Chức năng Back Office gồm kiểm duyệt, analytics, đơn hàng, lịch trống/giá và nhân sự. MVP chưa có portal cho khách sạn/đối tác.

- Mobile không dùng `ui-web` (khác nền tảng) nhưng dùng chung `api-client`, `tokens`, `i18n`, `utils`. Cách viết style ở mobile (StyleSheet hay NativeWind) do chủ `apps/mobile` chọn.
- Thư mục chia theo **tính năng** (`features/booking`) thay vì theo loại file, khớp với module BE để dễ tìm người phụ trách.
- Lệnh: `pnpm dev --filter web`, `pnpm --filter mobile start`, `pnpm gen:api` (sinh lại client), `pnpm --filter mobile build:apk` (EAS, bản demo).

## 5. `tripflix-ai`

```
tripflix-ai/
├─ app/
│  ├─ main.py                      # tạo FastAPI app
│  ├─ core/                        # settings (pydantic-settings), logging, kiểm JWT qua JWKS của core
│  ├─ api/                         # route: parse_query, chat (SSE), summarize, moderate, embed, health
│  ├─ services/                    # logic từng chức năng
│  ├─ agents/                      # trợ lý + định nghĩa tool gọi search của core
│  ├─ prompts/                     # prompt có version (parse_query.v1.md…)
│  ├─ clients/                     # core_client (httpx), llm_client; ghi chi phí → sự kiện ai.usage.recorded
│  └─ contracts/                   # pydantic SINH RA từ ../tripflix-be/contracts/events, có commit
├─ contracts/
│  └─ openapi/ai-service.json      # SINH RA từ FastAPI, có commit; FE đọc file này
├─ evals/
│  ├─ search_50.jsonl
│  ├─ assistant_100.jsonl
│  └─ run_evals.py
├─ scripts/                        # gen_contracts.py, export_openapi.py
├─ tests/
├─ .github/  (workflows, CODEOWNERS)
├─ .env.example
├─ .python-version                 # 3.13
├─ Dockerfile
├─ pyproject.toml                  # uv; ruff (lint + format), pyright, pytest
└─ uv.lock
```

Lệnh: `uv sync`, `uv run fastapi dev app/main.py`, `uv run pytest`, `uv run python evals/run_evals.py`, `uv run python scripts/gen_contracts.py`.

## 6. Quy ước chung

### 6.1. Hợp đồng giữa các repo

| Hợp đồng | Repo phát hành, lệnh sinh | Repo dùng, lệnh sinh |
|---|---|---|
| OpenAPI `core-api`, `notification-service` | BE: `pnpm contracts:build` → `contracts/openapi/*.json` | FE: `pnpm gen:api` → `packages/api-client`; AI: `scripts/gen_contracts.py` (chỉ phần search, product) |
| OpenAPI `ai-service` | AI: `scripts/export_openapi.py` → `contracts/openapi/ai-service.json` | FE: `pnpm gen:api` |
| Schema sự kiện | BE: zod trong `libs/contracts` → `contracts/events/*.schema.json` | AI: `scripts/gen_contracts.py` → pydantic |

- CI của repo phát hành chạy lệnh sinh rồi kiểm `git diff`; quên commit file sinh ra thì CI báo lỗi.
- Đổi hợp đồng: chỉ **thêm** trường. Đổi phá vỡ thì tạo bản mới (`commerce.order.paid.v2`, `/v2/...`) và giữ bản cũ tới khi bên dùng chuyển xong.
- PR đổi hợp đồng ghi rõ trong mô tả, kèm PR tương ứng ở repo dùng.

### 6.2. Nhánh, commit, PR

Chi tiết đầy đủ nằm trong **`RULES.md`** ở gốc mỗi repo (cùng một nội dung cho cả 3 repo). `CLAUDE.md` chỉ có một dòng `@RULES.md`, để Claude Code của mọi người tự đọc luật. `.claude/settings.json` tắt dòng co-author mà Claude tự thêm vào commit và PR. Bản gốc của bộ file này nằm ở `repo-rules/` trong thư mục tài liệu dự án.

- Luồng: nhánh `<tên>/<TFxx>-<mô-tả>` (tạo từ `develop`) → PR vào `develop` (squash merge, 1 review, CI xanh) → test trên staging → PR release `develop` → `main` (merge commit, leader tuần duyệt). Hotfix: nhánh từ `main`, PR vào `main`, rồi PR `main` → `develop`.
- `main` và `dev` đều được bảo vệ: không commit, push hay force push thẳng.
- Commit theo Conventional Commits, scope là module, footer `Refs: TFxx`; không có Co-Authored-By của AI.
- Xong task phải có evidence: file `docs/evidence/<TFxx>-<mô-tả>.md`, PR có link Notion, task Notion chuyển sang `Test` kèm link PR.

### 6.3. CODEOWNERS (theo docs/10 §7)

| Đường dẫn | Chủ |
|---|---|
| BE: `/libs/`, `/deploy/`, `/apps/core-api/src/platform/`, `/apps/core-api/src/modules/access/`, `/apps/notification-service/` | Dũng |
| BE: `/apps/core-api/src/modules/commerce/` | Thắng |
| BE: `/apps/core-api/src/modules/content/feed/`, `/content/media/`, `/apps/video-worker/` | Phong |
| BE: `/apps/core-api/src/modules/content/social/` | Thành |
| BE: `/apps/core-api/src/modules/content/moderation/`, `/apps/core-api/src/modules/analytics/` | Trang |
| BE: `/apps/core-api/src/modules/content/db/` | Phong, Thành, Trang (migration schema `content` cần cả 3 duyệt) |
| BE: `/apps/core-api/src/modules/discovery/` | Duy |
| BE: `/contracts/` | Dũng + chủ module đổi hợp đồng |
| FE: `/apps/mobile/` | Trang |
| FE: `/apps/web/`, `/apps/admin/`, `/packages/ui-web/` | Thành |
| AI: toàn repo | Bảo |

Cần GitHub username của từng người để điền file thật.

### 6.4. Biến môi trường

- Mỗi app có `.env.example` liệt kê đủ biến, không có giá trị bí mật. `.env` nằm trong `.gitignore`.
- BE đọc biến qua `libs/config` (zod), thiếu hoặc sai kiểu thì dừng ngay khi khởi động. AI dùng `pydantic-settings`. FE Next.js chỉ lộ biến có tiền tố `NEXT_PUBLIC_`, Expo chỉ lộ `EXPO_PUBLIC_`.
- Bí mật của staging, demo để trong GitHub Actions secrets.
- AWS key dev cấp riêng từng người (chỉ ghi được `dev/<tên>/` trên bucket dev), khoá lại khi người đó rời nhóm. Không ai dùng key có quyền trên bucket production.

### 6.5. CI (GitHub Actions)

| Repo | Khi mở PR | Khi merge vào `develop` (deploy staging); khi merge vào `main` (bản demo) |
|---|---|---|
| BE | `turbo run lint typecheck test build --affected`; integration test có Testcontainers; kiểm `contracts/` | Build và đẩy image `core-api`, `notification-service`, `video-worker` lên GHCR; deploy staging |
| FE | `turbo run lint typecheck test build --affected` | Build web, admin; mobile build APK bằng EAS khi gắn tag `mobile-v*` |
| AI | `ruff check`, `ruff format --check`, `pyright`, `pytest`; kiểm `contracts/` | Build image lên GHCR; chạy `evals/` và lưu kết quả |

## 7. Docker: chạy cả hệ thống bằng một lệnh

### 7.1. Các lệnh

Chạy trong `tripflix-be`. Lệnh đọc biến từ `deploy/.env`: lần đầu chép từ `deploy/.env.example`. Ai không cài Node thì dùng lệnh `docker compose` tương đương, ghi trong README.

| Lệnh | Tương đương | Dùng khi |
|---|---|---|
| `pnpm stack:up` | `docker compose -f deploy/compose.yaml --profile be --profile ai --profile fe --profile gateway up -d --build` | Chạy cả hệ thống: làm mobile, thử demo, người mới vào |
| `pnpm stack:watch` | Như trên nhưng dùng `watch` thay cho `up -d` | Như trên, và sửa code BE, AI, web, admin thì container tự cập nhật, không phải build lại |
| `pnpm stack:infra` | `docker compose -f deploy/compose.yaml up -d` | Làm BE: chỉ bật hạ tầng, app của mình chạy trên máy bằng `pnpm dev` |
| `pnpm stack:tools` | `… --profile tools up -d` | Mở Adminer (xem database), RedisInsight (xem stream, hàng đợi) |
| `pnpm stack:logs [service]` | `… logs -f [service]` | Xem log |
| `pnpm stack:down` | `… down` | Dừng, **giữ** dữ liệu |
| `pnpm stack:reset` | `… down -v` rồi `stack:up` | Xoá sạch dữ liệu, migrate và seed lại từ đầu |

Kết hợp được: chạy `pnpm stack:up`, rồi `docker compose stop core-api` và chạy `core-api` trên máy để debug. App trên máy vẫn nối được Postgres, Redis qua `localhost`.

### 7.2. Các service

| Service | Profile | Cổng trên máy | Khởi động khi | Ghi chú |
|---|---|---|---|---|
| `postgres` | (luôn chạy) | 5432 | — | `pgvector/pgvector:pg17`; phương án v1.1 tạo 2 database (`core`, `notification`), user/schema/extension; baseline đã duyệt còn database `commerce` riêng |
| `redis` | (luôn chạy) | 6379 | — | AOF bật |
| `mailpit` | (luôn chạy) | 8025 (web), 1025 (SMTP) | — | Xem email gửi đi |
| `migrate` | be | — | `postgres` healthy | Chạy một lần: migrate mọi module + `notification`, seed nếu database trống |
| `core-api` | be | 3000 | `migrate` xong, `redis` healthy | `APP_ROLE=all` |
| `notification-service` | be | 3001 | `migrate` xong | |
| `video-worker` | be | — | `redis` sẵn sàng | Image có FFmpeg; đọc file gốc, ghi HLS lên bucket S3 dev |
| `ai-service` | ai | 8000 | `core-api` healthy | Build từ `../tripflix-ai` |
| `web`, `admin` | fe | 3100, 3200 | — | Build từ `../tripflix-fe` |
| `traefik` | gateway | 8080, 8081 (dashboard) | — | Một địa chỉ cho FE và mobile |
| `adminer`, `redisinsight` | tools | 8090, 5540 | — | Công cụ xem dữ liệu |

Mọi service có `healthcheck`; `depends_on` chờ `service_healthy` hoặc `service_completed_successfully`, nên `stack:up` chạy một lần là lên đủ, không phải bật từng cái theo thứ tự. Dữ liệu nằm trong named volume (`pg-data`, `redis-data`), tắt máy không mất. Video, ảnh nằm trên bucket S3 dev, không nằm trong Docker.

**Media ở dev:** không có container lưu trữ. `core-api` ký URL tải lên thẳng bucket `tripflix-media-dev`, `video-worker` ghi HLS lên đó, app phát qua CloudFront dev, y như production. Mỗi người có IAM key riêng (trong `deploy/.env`, không commit) chỉ ghi được thư mục `dev/<tên>/`, nên dữ liệu không lẫn nhau. Lifecycle tự xoá upload dở sau 1 ngày. `stack:reset` xoá database nhưng không xoá file trên S3. Có lệnh riêng `pnpm media:clean` xoá thư mục của mình. Test tự động dùng adapter bộ nhớ của `libs/storage`, không cần mạng.

Địa chỉ sau khi chạy:

| Gì | Địa chỉ |
|---|---|
| API qua gateway (web, admin, mobile dùng) | `http://localhost:8080` |
| Swagger `core-api` | `http://localhost:3000/docs` |
| Tài liệu API `ai-service` | `http://localhost:8000/docs` |
| Web, Admin | `http://localhost:3100`, `http://localhost:3200` |
| Mailpit | `http://localhost:8025` |

### 7.3. Trích `deploy/compose.yaml`

```yaml
name: tripflix

x-be-env: &be-env
  NODE_ENV: development
  PG_HOST: postgres
  REDIS_URL: redis://redis:6379
  AWS_REGION: ${AWS_REGION:-ap-southeast-1}
  AWS_ACCESS_KEY_ID: ${AWS_ACCESS_KEY_ID}          # key riêng từng người, chỉ ghi được dev/<tên>/
  AWS_SECRET_ACCESS_KEY: ${AWS_SECRET_ACCESS_KEY}
  S3_MEDIA_BUCKET: tripflix-media-dev
  S3_KEY_PREFIX: dev/${DEV_NAME}/
  MEDIA_CDN_URL: ${MEDIA_CDN_URL}                  # domain CloudFront dev

services:
  postgres:
    image: pgvector/pgvector:pg17
    environment:
      POSTGRES_PASSWORD: ${PG_SUPERUSER_PASSWORD:-postgres}
    volumes:
      - pg-data:/var/lib/postgresql/data
      - ./postgres/init:/docker-entrypoint-initdb.d:ro
    ports: ["5432:5432"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      retries: 20

  migrate:
    profiles: [be]
    build: { context: .., dockerfile: apps/core-api/Dockerfile, target: dev }
    command: pnpm --filter @tripflix/core-api db:migrate-and-seed
    environment: *be-env
    depends_on:
      postgres: { condition: service_healthy }

  core-api:
    profiles: [be]
    build: { context: .., dockerfile: apps/core-api/Dockerfile, target: dev }
    environment:
      <<: *be-env
      APP_ROLE: all
    ports: ["3000:3000"]
    depends_on:
      migrate: { condition: service_completed_successfully }
      redis: { condition: service_healthy }
    develop:
      watch:
        - { action: sync, path: ../apps/core-api/src, target: /repo/apps/core-api/src }
        - { action: sync, path: ../libs, target: /repo/libs }
        - { action: rebuild, path: ../pnpm-lock.yaml }

  ai-service:
    profiles: [ai]
    build: { context: "${AI_REPO:-../../tripflix-ai}", target: dev }
    environment:
      CORE_API_URL: http://core-api:3000
      JWKS_URL: http://core-api:3000/.well-known/jwks.json
    ports: ["8000:8000"]
    develop:
      watch:
        - { action: sync, path: "${AI_REPO:-../../tripflix-ai}/app", target: /app/app }
        - { action: rebuild, path: "${AI_REPO:-../../tripflix-ai}/uv.lock" }

volumes:
  pg-data:
  redis-data:
```

Đường dẫn tới repo FE, AI để trong biến (`FE_REPO`, `AI_REPO`), mặc định là thư mục anh em; ai đặt repo chỗ khác thì sửa trong `deploy/.env`. Mật khẩu của user Postgres theo module trong `postgres/init/` chỉ dùng cho dev.

### 7.4. Dockerfile

Mỗi app một Dockerfile. App TypeScript build với context là gốc repo, để lấy được cả `libs/`, `packages/`.

| App | Base image | Các stage |
|---|---|---|
| `core-api`, `notification-service` | `node:24-slim` | `prune` (`turbo prune <app> --docker`, chỉ lấy phần monorepo app cần) → `deps` (`pnpm install --frozen-lockfile`, cache pnpm store) → **`dev`** (toàn bộ mã nguồn, chạy chế độ watch) → `build` → **`prod`** (chỉ `dist` + dependency production, chạy bằng user không phải root) |
| `video-worker` | `node:24-slim` + FFmpeg | Như trên |
| `web`, `admin` | `node:24-slim` | `prune` → `deps` → **`dev`** (`next dev`) → `build` (`next build`, output `standalone`) → **`prod`** (chỉ thư mục `standalone` + static) |
| `ai-service` | `python:3.13-slim` + `uv` | `deps` (`uv sync --locked --no-install-project`, cache uv) → **`dev`** (`fastapi dev`, tự reload) → **`prod`** (`uv sync --no-dev`, `fastapi run`) |

- Stage `dev` dùng cho máy local và `stack:watch`. Stage `prod` dùng để build image đẩy lên GHCR (CI, §6.5), chạy ở staging và demo.
- Có `.dockerignore` ở mỗi repo: bỏ `node_modules`, `.turbo`, `dist`, `.next`, `.venv`, `.env`.
- Thứ tự `COPY` để thay đổi code không làm cài lại dependency: lockfile trước, mã nguồn sau.

### 7.5. Chạy app mobile với Docker

App Expo chạy trên máy (Expo không chạy được trong Docker để nối điện thoại). Backend chạy trong Docker.

| Thiết bị | `EXPO_PUBLIC_API_URL` trong `apps/mobile/.env` |
|---|---|
| Android emulator | `http://10.0.2.2:8080` |
| Điện thoại thật cùng wifi | `http://<IP LAN của máy>:8080` |

- Chỉ API cần trỏ về máy mình. Video và link tải lên là địa chỉ S3, CloudFront thật nên điện thoại nào có mạng cũng tới được, không phải cấu hình thêm.
- Windows: cho phép cổng 8080 trong Windows Firewall (mạng Private), không thì điện thoại không gọi tới được API.

### 7.6. Lưu ý khi dùng Windows

- Dùng Docker Desktop chạy trên WSL2. Cấp **≥ 6 GB RAM** cho WSL2 trong file `.wslconfig`, vì cả hệ thống có hơn 10 container.
- `.gitattributes` đặt `* text=auto eol=lf` ở cả 3 repo. Nếu không, file `.sh`, `.sql` checkout trên Windows sẽ mang dấu xuống dòng CRLF và lỗi khi chạy trong container.
- Dùng `stack:watch` (Compose Watch) để sửa code chạy trong container, không mount thư mục code vào container. Watch chép file vào container nên không bị chậm và không mất sự kiện đổi file như khi mount từ ổ Windows.
- Nếu dùng Postgres, Redis cài sẵn trên máy, đổi cổng trong `deploy/.env` cho khỏi trùng (5432, 6379).

### 7.7. Staging và demo

Cùng các Dockerfile, stage `prod`, image lấy từ GHCR. Nếu chốt deploy lên VPS (docs/10 §10), staging chạy `compose.yaml` cộng thêm một file `compose.prod.yaml` để đổi image, bỏ `develop`, bỏ cổng công khai của Postgres, Redis, và thêm HTTPS cho Traefik. Nếu chọn AWS ECS thì dùng image như vậy nhưng không dùng compose.

## 8. Thứ tự dựng repo

Mục tiêu ngày đầu là **walking skeleton**: một đường đi xuyên suốt chạy được trước, rồi mỗi người lấp module của mình.

| Bước | Việc | Người làm |
|---|---|---|
| 1 | Tạo GitHub org, 3 repo, nhánh `main` và `develop`, branch protection, CODEOWNERS; chép `RULES.md`, `CLAUDE.md`, `.claude/settings.json` từ `repo-rules/` vào cả 3 repo | Trang |
| 2 | BE: khung Turborepo, `libs/config`, `libs/db`, `libs/observability`, `core-api` có `/health`, CI. Docker: `deploy/compose.yaml`, script init Postgres, Dockerfile `core-api`, lệnh `pnpm stack:*` | Dũng |
| 3 | BE: `access` đăng ký, đăng nhập, `/auth/me`, JWKS; `libs/outbox`, `libs/event-bus` | Dũng |
| 4 | BE: generator `turbo gen module` tạo khung module; mỗi chủ module tạo module của mình, migration đầu tiên, 1 endpoint đọc | Từng chủ module |
| 5 | FE: khung Turborepo, 3 app chạy được, `tokens`, `api-client` sinh từ `contracts/` của bước 3; Dockerfile `web`, `admin` | Thành, Trang |
| 6 | AI: khung FastAPI, `/health`, `/parse-query` trả dữ liệu giả, CI, Dockerfile, image lên GHCR | Bảo |
| 7 | Kiểm skeleton bằng `pnpm stack:up` trên máy sạch: app mobile đăng nhập → gọi `/auth/me` → thấy bảng tin từ bài seed; đăng bài → sự kiện đi qua outbox → stream → `notification-service` ghi log nhận được | Cả team |

Bước 2–3 nên xong trước khi các bước khác bắt đầu viết nghiệp vụ, vì mọi module dùng `libs/db`, `libs/outbox`, `libs/auth`.

## 9. Khác gì so với docs/10 §5

| docs/10 v0.6 | Bản này | Lý do |
|---|---|---|
| BE dùng Nx hoặc NestJS monorepo mode | pnpm + Turborepo, giống FE | Q1 |
| Prisma hoặc Drizzle | Drizzle `1.0.0-rc.5` | Q2 |
| Ranh giới bằng `@nx/enforce-module-boundaries` | `eslint-plugin-boundaries` + quyền Postgres theo module + CODEOWNERS | Q1, Q3 |
| `libs/db-tx` | Gộp vào `libs/db` (pool, Drizzle, transaction host theo tên kết nối) | Một chỗ cấu hình kết nối |
| — | Thêm `libs/config`, `libs/testing`, `apps/core-api/src/platform/` | Đọc biến môi trường an toàn; dùng chung hạ tầng test |
| — | `core-api` có `APP_ROLE` | Q4 |
| — | Thư mục `contracts/` ở BE và AI | Q5 |
| `packages/ui` | Tách `ui-web` (web, admin) và `tokens` (dùng cả mobile) | Component web không dùng được trên React Native, nhưng màu, font thì dùng chung được |
| — | `discovery` có `DB_DISCOVERY_URL` riêng, `statement_timeout` riêng, sẵn sàng tách instance khi đo thấy cần (v1.1) | Search là phần dùng nhiều; giữ đường tách ra mà chưa phải vận hành thêm máy ở pilot |
| — | *(Đề xuất v1.1, chờ duyệt)* `commerce` là schema trong database `core`, không tách database riêng | Tồn kho do nền tảng tự quản lý, đơn hàng gắn với user và bài đăng; tách database chỉ thêm việc ghép dữ liệu |
| Dev dùng MinIO thay S3 | Dev dùng bucket S3 dev + CloudFront dev, thêm `libs/storage` | Q9 |
| `deploy/docker-compose.yml` chỉ có hạ tầng | `deploy/compose.yaml` chạy cả hệ thống (build từ 3 repo), profile `be`, `ai`, `fe`, `gateway`, `tools`; service `migrate` tự migrate, seed; Compose Watch; Dockerfile nhiều stage (`dev`, `prod`) cho mọi app; lệnh `pnpm stack:*` | Q8: ai cũng chạy được cả hệ thống bằng một lệnh |

docs/10 §5 và §10 đã cập nhật trỏ sang tài liệu này (2026-11-04).

## Tham khảo

- Drizzle — [Latest releases](https://orm.drizzle.team/docs/latest-releases) (1.0.0-rc.5, 21/10/2026)
- nestjs-cls — [Transactional plugin, nhiều database](https://papooch.github.io/nestjs-cls/plugins/available-plugins/transactional), [Drizzle adapter](https://papooch.github.io/nestjs-cls/plugins/available-plugins/transactional/drizzle-orm-adapter)
- Expo — [SDK 56](https://expo.dev/sdk/56), [Monorepos](https://docs.expo.dev/guides/monorepos/)
- Docker — [Compose Watch](https://docs.docker.com/compose/how-tos/file-watch/), [Compose profiles](https://docs.docker.com/compose/how-tos/profiles/); Turborepo — [Docker và `turbo prune`](https://turborepo.com/docs/guides/tools/docker); uv — [Dùng uv trong Docker](https://docs.astral.sh/uv/guides/integration/docker/)
- So sánh Turborepo và Nx — [pkgpulse](https://www.pkgpulse.com/guides/turborepo-vs-nx-monorepo-2026), [bejamas](https://bejamas.com/stack/framework/turborepo-vs-nx)
- So sánh công cụ sinh client OpenAPI — [pkgpulse](https://www.pkgpulse.com/guides/orval-vs-openapi-typescript-vs-kubb-openapi-client-2026), [DEV — openapi-typescript vs hey-api vs orval vs kubb](https://dev.to/nyaomaru/which-openapi-codegen-should-you-choose-openapi-typescript-vs-hey-api-vs-orval-vs-kubb-100p)
