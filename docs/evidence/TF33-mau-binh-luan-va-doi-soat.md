# TF33 — Worker đọc mẫu bình luận của core, đối soát bài bị giữ, sửa ước lượng

- Nhánh: `bao/TF33-mau-binh-luan-va-doi-soat`, tách từ `bao/TF44-summary-ben-vung`, **phụ thuộc PR ai #21 và be #128** · Người làm: Bảo (dùng AI: có) · Ngày: 2026-11-11
- **Phía core:** Thành làm ở PR be #128 (`thanh/TF33-lay-mau-binh-luan-va-doi-soat-ai`). Bốn điểm đã chốt nằm trong `docs/research/CONTEXT.md`, mục "Đã chốt với Thành, 2026-11-11".
- **Căn cứ:**
  - `docs/research/reports/DeepResearch_AI_Summary_1_trieu_binh_luan.md`: B2, B4, B6, B8;
  - Cochran (cỡ mẫu cho một tỉ lệ);
  - Holt và Smith (1979), post-stratification.

## Đã làm

| # | Trước | Sau |
|---|---|---|
| 1 | Mỗi lượt đọc tối đa **10.000 bình luận mới nhất**, mất 50 request | Gọi **1 request** lấy mẫu ngẫu nhiên 3.000 bình luận của core (`seed` = id bài, nên mẫu ổn định giữa các lượt), kèm `visibleCommentCount` và `uniqueAuthorCount` của cả bài. Core cũ chưa có route thì quay về đọc phân trang như trước |
| 2 | Bài nhỏ đọc phẳng | Mẫu được xếp lại đúng thứ tự của API phẳng (`createdAt` giảm dần, rồi `id`). Bài nhỏ hơn mẫu cho **cùng input, cùng hash**, nên không bị tóm tắt lại oan |
| 3 | Phản hồi chỉ có ngữ cảnh khi bình luận cha nằm trong danh sách | `CommentIn.parent_body` mang chữ của bình luận cha (lấy từ `parentCommentBody` của core), dùng cho cả LLM lẫn bộ phân loại. Id của cha vẫn nằm trong `sourceCommentIds`. Cha nằm ngoài mẫu thì không được tính phiếu "đồng ý" |
| 4 | Sự kiện ẩn bị core cắt khỏi stream (`MAXLEN ~100k`) thì tóm tắt bị giữ lại mãi | **Đối soát:** 6 giờ một lần, một replica (khoá `SET ai:summary:reconcile NX PX 6h`) đọc hết các trang của `GET /internal/ai-summary/reconciliation` rồi xếp lịch các bài như backfill (`ZADD NX`, giữ khoảng cách 10 phút). Lỗi thì thử lại sau 10 phút. Core cũ trả 404 thì chỉ ghi cảnh báo |
| 5 | `estimate` = tỉ lệ trên khoảng 200 người đã gửi LLM, nhân với số người cả bài. Lệch, vì 200 người này đã được xếp người trải nghiệm lên trước | Mỗi người gửi đi ở tầng t được tính là `N_t / n_t` người của mẫu (post-stratification). Tỉ lệ được tính trên toàn bộ người viết trong mẫu ngẫu nhiên, rồi nhân với `uniqueAuthorCount` (trừ chủ bài). Khoảng Wilson dùng n = số người thật sự đã đọc. Ví dụ trong test: 20 người được trích dẫn ra **400**, công thức cũ ra **2.000** (gấp 5 lần) |
| 6 | `population` đếm bằng bộ đếm Redis và HyperLogLog: không trừ được bình luận đã xoá, chỉ đếm bình luận gốc đã gắn nhãn | `population` lấy số **chính xác** của core (`comments`, `writers`), kèm số đã đọc (`sampledComments`, `sampledWriters`). Đã bỏ bộ đếm Redis và HyperLogLog |
| 7 | Câu dính an toàn nằm ngoài phần đã đọc thì bị sót | Label worker lưu **kết quả** an toàn (nhóm an toàn; công khai hay chờ duyệt) của mọi bình luận, gốc lẫn phản hồi, vào `ai:safety:{post}`, TTL 30 ngày, **không lưu nội dung**. Sửa, xoá hoặc ẩn bình luận thì gỡ. Lượt tóm tắt gộp các kết quả này cho bình luận nằm ngoài mẫu |

- **Chưa bật trên UI:** FE chưa hiện "khoảng X người" (Thành, 2026-11-11). Công thức mới mới được kiểm bằng test tổng hợp, chưa so với nhãn thật.
- **Đường lui:**
  - không có route mẫu thì đọc phân trang như cũ, không có `population` và `estimate`;
  - đọc kết quả an toàn trong Redis lỗi thì chỉ dùng phần trong mẫu;
  - đối soát lỗi thì thử lại sau 10 phút, worker vẫn chạy.

## Đối chiếu tiêu chí

| Tiêu chí | Đạt | Bằng chứng |
|---|---|---|
| Đọc mẫu bằng service token, đúng `size` và `seed`, parse đúng response của PR #128 | Có | `test_the_sample_is_asked_with_a_service_token_size_and_seed`, end-to-end bên dưới |
| Core cũ không có route thì vẫn chạy | Có | `test_an_older_core_without_the_sample_route_says_so`, `test_an_older_core_falls_back_to_the_newest_pages` |
| Bài nhỏ: đọc bằng mẫu và đọc phẳng cho cùng input | Có | `test_a_sample_is_put_in_the_flat_order_so_a_small_post_keeps_its_input`; eval live: token vào 33.925, **giống hệt** trước khi sửa |
| Phản hồi có cha ngoài mẫu vẫn có ngữ cảnh, không tính phiếu | Có | `test_a_parent_outside_the_sample_gives_context_but_takes_no_vote`, `test_a_reply_whose_parent_is_outside_the_sample_keeps_it_as_context` |
| Đối soát: một replica chạy, đọc hết các trang, xếp lịch như backfill, lỗi thì thử lại sớm | Có | `test_reconciliation_runs_on_one_replica_and_schedules_held_posts_like_backfill`, `test_a_failed_reconciliation_is_tried_again_soon`, `test_held_summaries_are_read_until_the_cursor_ends` |
| Ước lượng không bị thổi phồng bởi thứ tự chọn | Có | `test_sent_writers_count_for_their_tier_not_for_the_whole_post` |
| Cảnh báo an toàn ngoài mẫu không bị mất, không lưu nội dung | Có | `test_safety_hits_are_kept_for_roots_and_replies_without_the_text`, `test_kept_safety_results_outside_the_sample_reach_the_summary` |

## Kết quả kiểm tra

- `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest`: ruff sạch, pyright 0 lỗi, **525 passed**, 5 skipped. Trước khi sửa: 507 passed.
- **Eval live** `uv run python evals/run_evals.py --llm live --classifier-dir app/models/comment_classifier` (DeepSeek, 15 bài seed):

  | Chỉ số | Trước (TF44) | Sau |
  |---|---|---|
  | Đạt đủ cổng | 15/15 | **15/15** |
  | Độ phủ ý | 0,897 | 0,966 |
  | Độ chính xác ý | — | 0,875 |
  | Bắt khác biệt video | 1,0 | 1,0 |
  | Trích dẫn sai | 0 | 0 |
  | Token vào | 33.925 | **33.925** |
  | Chi phí | 0,0049 USD | 0,0051 USD |

  Input giống hệt, nên chênh lệch độ phủ ý là do LLM dao động giữa các lần chạy, không do code.
- **End-to-end với core của PR be #128:** xem mục dưới.

## End-to-end với core của PR be #128

Core chạy local từ nhánh `thanh/TF33-lay-mau-binh-luan-va-doi-soat-ai` (commit `9b3c387`): migrate và seed xong, có 10 bài, 25 bình luận.

| Kiểm | Kết quả |
|---|---|
| `GET /posts/:id/comments/sample` không có token | **401**, nghĩa là route có tồn tại (không phải 404), nên worker không rơi nhầm về đọc phân trang |
| `GET /internal/ai-summary/reconciliation` không có token | **401** |
| `GET /posts/:id/comment-stats` không có token | **200** `{"visibleCommentCount":10,"uniqueAuthorCount":8}`: route công khai, đã hỏi Thành |
| Lấy service token rồi gọi mẫu thật | **Chưa làm được**: `POST /api/auth/service-token` trả 400, vì database local chưa có client `ai-service`, hoặc secret không khớp. Cần tạo client bằng `auth:create-service-client ai-service core-api` rồi chạy lại script probe |

Phần có xác thực mới được kiểm bằng test, với response mẫu chép từ DTO của PR #128 (`SampleCommentsResponseDto`, `ReconcileHeldSummariesResponseDto`). **Chạy lại end-to-end trước khi merge.**

## Cách kiểm lại

1. `uv run pytest tests/clients/test_core_api.py tests/summary tests/workers`
2. Core local từ PR be #128:
   - trong `tripflix-be`: `gh pr checkout 128`, rồi `docker compose -f deploy/compose.yaml --profile be up -d --build postgres redis migrate core-api`;
   - tạo client: `auth:create-service-client ai-service core-api`;
   - đặt `SERVICE_CLIENT_SECRET` trong môi trường, rồi chạy script probe (gọi mẫu hai lần, so với đọc phẳng, gọi đối soát).

## Ảnh hưởng tới phần của người khác

- Chỉ sửa repo AI. Không sửa code của Thành.
- **Gửi Thành** (khi đọc PR #128):
  - `GET /comment-stats` là công khai (`OptionalAuthenticated`): có chủ ý không?
  - `::uuid` trong câu query đối soát sẽ làm lỗi cả câu nếu `sourceCommentIds` chứa id không phải uuid;
  - `hashtext` 32 bit, bài rất lớn có thể có vài id trùng hash, không ảnh hưởng tính đúng.
- **Anh Phong:** không có env mới. Label worker giờ ghi thêm `ai:safety:*` (rất nhỏ), và không còn ghi `ai:labelstats:*`, `ai:writers:*`.
