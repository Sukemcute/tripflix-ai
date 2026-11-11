# TF44 — AI summary chịu lỗi: hạn thuê job, retry có giới hạn, cầu dao, gỡ/thay model

- Jira: SCRUM-48 (TF44 · Tóm tắt bài đăng) · Nhánh: `bao/TF44-summary-ben-vung` · Người làm: Bảo (dùng AI: có) · Ngày: 2026-11-11
- Căn cứ:
  - `research_notes/.../04_resilience_reliability.md` §3: timeout, retry có giới hạn kèm backoff và jitter, circuit breaker, fallback, dead-letter;
  - `06_ai_system_engineering.md` §1: port và adapter;
  - bản rà soát kiến trúc ngày 2026-11-11.

## Đã làm

| # | Vấn đề (trước) | Sửa |
|---|---|---|
| 1 | Worker chết giữa lượt chạy thì **mất job**: sự kiện đã ACK, bài bị `ZREM` khỏi hàng đợi trước khi chạy | Bài được claim có **hạn thuê** 5 phút trong `ai:summary:inflight`. Lượt poll sau của bất kỳ replica nào trả bài đã hết hạn về hàng đợi |
| 2 | Mọi lỗi đều chờ 10 phút rồi thử lại, **không giới hạn**, nên lỗi vĩnh viễn lặp mãi | Retry lùi dần sau 1, 2, 4, 8 phút (cộng độ lệch cố định theo bài), tối đa 5 lần, rồi đưa vào `stream:dead-letter` kèm `postId`. Core trả 400, 413 hoặc 422 thì vào hàng lỗi ngay. 401 vẫn retry vì token tự lành |
| 3 | Lượt `failed` khi đã có bản `ready` thì **không lưu và không xếp lịch lại**, nên tóm tắt bị giữ lại vì nguồn ẩn có thể kẹt mãi | Lượt `failed` được retry như mục 2. Riêng kill switch thì không retry, vì người vận hành sẽ chạy backfill khi tắt switch |
| 4 | Một vòng lặp chạy tới 20 bài liên tiếp, nên sự kiện ẩn bình luận phải chờ | Mỗi vòng chỉ chạy **1 bài**, đọc sự kiện giữa hai lượt chạy |
| 5 | Bộ phân loại lỗi **lúc chạy** thì cả job lỗi và lặp mãi | Pipeline bắt lỗi rồi **dùng luật** cho lượt đó, và hash không ghi version của bộ phân loại, nên lượt sau khi model khoẻ lại sẽ tóm tắt lại. `GuardedClassifier` có cầu dao: lỗi 3 lần liên tiếp thì bỏ qua model 5 phút |
| 6 | Bài lớn làm bộ phân loại chạy tới khoảng 2 phút | `CLASSIFIER_MAX_COMMENTS=500` (khoảng 25 giây); các bình luận còn lại dùng luật, qua seam "thiếu nhãn thì dùng luật" có sẵn trong `selection.py` |
| 7 | Không tắt được bộ phân loại nếu không build lại image | `CLASSIFIER_ENABLED=false` thì chỉ dùng luật |
| 8 | DeepSeek chết thì mỗi bài vẫn chờ khoảng 96 giây timeout | `GuardedLlmClient` (cùng port `LlmClient`) có cầu dao: mở thì báo lỗi ngay, worker hoãn bài tới lúc cầu dao đóng, **không tính** vào số lần retry |
| 9 | Đổi model thì bài cũ vẫn bị "same input" | Tên model nằm trong `inputHash` (port `LlmClient` có thêm thuộc tính `model`) |
| 10 | `LLM_PROVIDER` nhận `openai` và `anthropic` dù không có adapter: worker chỉ chết lúc khởi động | **Có adapter thật cho cả 4 provider**, chọn bằng `LLM_PROVIDER`, chỉ `build_llm` biết danh sách này. Chi tiết ở bảng bên dưới |
| 11 | Comment ghi luật lọc theo tuổi là L3 | Sửa thành L2 |

### Các provider LLM cho tóm tắt (cùng port `LlmClient`)

| `LLM_PROVIDER` | Adapter | Model mặc định | Cách ép đầu ra JSON | Ghi chú |
|---|---|---|---|---|
| `fake` | `FakeLlmClient` | `fake` | Trả JSON cố định | Test, chạy offline |
| `deepseek` | `DeepSeekClient` (httpx) | `deepseek-flash` | `json_object` + schema gắn vào prompt | Như cũ |
| `openai` | `OpenAILlmClient` (httpx, kế thừa vòng retry của DeepSeek) | **Không có**: bắt buộc đặt `LLM_MODEL` | `json_schema` strict | Bắt buộc đặt `LLM_PRICE_INPUT`, `LLM_PRICE_CACHED_INPUT`, `LLM_PRICE_OUTPUT`; các nguồn đang lệch nhau về model hiện hành ngày 11/11 |
| `anthropic` | `AnthropicLlmClient` (SDK `anthropic` 1.17, Bảo đồng ý thêm) | `claude-haiku-5-5` (Bảo chọn): 0,10 / 0,50 USD mỗi 1M token | `output_config.format` json_schema | Effort `low`, cache prompt hệ thống, không gửi `temperature` |

- Không có provider dự phòng tự động. Muốn đổi provider thì đổi `LLM_PROVIDER` rồi khởi động lại worker.
- Tên model nằm trong hash, nên sau khi đổi provider, mỗi bài tóm tắt lại 1 lần.
- Chưa chạy live với OpenAI và Anthropic, vì chưa có key. Cần chạy `evals/run_evals.py --llm live` trên 15 bài seed trước khi dùng thật (tốn tiền).

### Phần 2: chịu được bài rất lớn (2026-11-11)

Căn cứ: `docs/research/reports/DeepResearch_AI_Summary_1_trieu_binh_luan.md`. Mã B trong bảng là mã badcase trong báo cáo đó.

| # | Vấn đề | Sửa | Đo |
|---|---|---|---|
| B10 | Bài làm worker hết RAM: process chết không có exception, bộ đếm lần thử không tăng, bài chạy lại và làm chết worker mãi | Đếm lần thử **lúc bắt đầu chạy**; lần bắt đầu thứ 6 thì đưa vào hàng lỗi. Cầu dao LLM mở thì trả lại lượt đã đếm | test |
| B8 | Đọc sự kiện và chạy job dùng chung vòng lặp; trong lúc chạy một lượt dài, sự kiện bị core cắt khỏi stream (`MAXLEN ~100k`) | 2 thread: vòng sự kiện và vòng job | test: vòng job không đụng tới stream |
| B14 | Bộ phân loại hỏng thì chuyển sang luật **im lặng** | `content.labeler = model / rules / mixed`, kèm trong log mỗi lần lưu | test |
| B5 | Lọc gần trùng O(n²) | MinHash LSH (8 băng × 4 hàng, `crc32`, seed cố định), Jaccard vẫn quyết định | 16.000 bình luận: **36 s xuống 2,1 s**; 64.000: 11 s. Kết quả **giống hệt** bản so từng cặp (test đối chiếu 900 câu; số ứng viên trùng khớp ở mọi cỡ) |
| B2 | Vượt trần thì lấy "N bình luận mới nhất" | Mẫu phân tầng (gốc hay phản hồi, theo tuần), chia slot theo tỉ lệ, weighted reservoir A-Res theo like; bình luận an toàn đi trước; ổn định giữa các lần chạy | test: tuần cũ và phản hồi giữ đúng phần của mình |
| B1, B7 | Mỗi lượt phân loại lại từ đầu | Port `LabelStore` + adapter Redis (Bảo chọn: Redis trước, core sau). Process mới `app.workers.label_worker` (nhóm `ai-labels`) gắn nhãn bình luận gốc lúc ghi; cascade: luật lọc đã bỏ thì không chạy model, trừ câu an toàn. Lượt tóm tắt dùng lại nhãn còn đúng (cùng version, cùng hash nội dung) và lưu nhãn mới | Bài 1.000 bình luận: lượt đầu 7,8 s, **chạy lại 0,29 s**; input hash giữ nguyên (test) |
| B4 | Đếm người trên khoảng 200 bình luận gửi LLM | `content.population` (đếm trên toàn bài, HyperLogLog) và `estimate` cho từng ý: tỉ lệ trong mẫu nhân tổng số người, khoảng Wilson 95%. Chỉ có khi bài lớn hơn phần đã đọc | test: 30/200 trên bài 30.000 người thành khoảng 4.500 |

- **Đường lui:**
  - kho nhãn lỗi thì lượt chạy tự gắn nhãn như trước;
  - worker gắn nhãn lỗi thì ack sự kiện rồi để lượt tóm tắt gắn nhãn;
  - không có bộ đếm thì chỉ ghi số đếm chính xác trên mẫu.
- **Eval live** (DeepSeek, có bộ phân loại): 15/15 cổng; token vào 33.925, **giống hệt trước khi sửa**, nghĩa là bài nhỏ không đổi input; tỉ lệ bắt khác biệt video 1,0; chi phí 0,0049 USD.
- **Redis thật** (container tạm 8.8): `RedisLabelStore` đếm đúng 999/333/700; gửi lặp không đếm 2 lần; có hạn giờ; 50/50 test worker pass.
- **Chưa làm, cần core (Thành):** API lấy mẫu và API bộ đếm phía core (để không phải đọc 10.000 bình luận mỗi lượt), nơi lưu nhãn lâu dài, đối soát các bài đang bị giữ lại. Process `label_worker` cần thêm service trong compose (anh Phong).

## Đối chiếu tiêu chí

| Tiêu chí | Đạt | Bằng chứng |
|---|---|---|
| Worker chết giữa lượt chạy thì không mất bài | Có | `test_a_worker_that_dies_mid_run_leaves_the_post_for_the_next_one`; kiểm thêm trên Redis 8.8 thật |
| Retry có giới hạn, lùi dần, rồi vào hàng lỗi | Có | `test_failures_back_off_then_go_to_dead_letter`, `test_retry_delay_is_fixed_per_post_and_capped` |
| Lỗi vĩnh viễn không retry; 401 vẫn retry | Có | `test_a_request_core_rejects_goes_to_dead_letter_at_once`, `test_a_401_is_retried_not_dead_lettered` |
| Retry không đè lịch chạy sớm hơn (ví dụ do sự kiện ẩn) | Có | `test_a_retry_never_pushes_back_an_earlier_event_run` |
| Lượt `failed` được thử lại, trừ khi kill switch bật | Có | `test_an_untrusted_llm_output_is_retried_unless_the_kill_switch_is_on` |
| LLM chết thì hoãn, không tốn lượt retry | Có | `test_an_open_llm_breaker_waits_without_spending_an_attempt` |
| Bộ phân loại lỗi lúc chạy thì vẫn ra tóm tắt bằng luật | Có | `test_a_classifier_failing_mid_run_falls_back_to_rules`, `tests/test_breaker.py` |
| Đổi model thì tóm tắt lại | Có | `test_the_model_is_part_of_the_input_hash` |
| Gỡ bộ phân loại bằng cấu hình; provider không có adapter bị từ chối | Có | `tests/test_config.py` |
| Có thể chọn DeepSeek, OpenAI, Anthropic bằng cấu hình | Có | `tests/clients/test_llm_providers.py`: kiểm hình dạng request, cách tính giá, retry 429, thiếu model hoặc thiếu giá thì không khởi động, `build_llm` chọn đúng adapter |

## Kết quả kiểm tra

- `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest`: ruff sạch, pyright 0 lỗi, **483 passed**, 5 skipped. Trước khi sửa: 448 passed.
- Sau phần 2 (HEAD `6e1cbbe`, chạy ngày 2026-11-11): ruff sạch, pyright 0 lỗi, **507 passed**, 5 skipped. Chạy riêng `5320612` được 485 passed, `5fb6c83` được 486 passed.
- Redis thật (container tạm `redis:8.8-alpine`, cùng phiên bản staging): `REDIS_TEST_URL=redis://localhost:6390/15 uv run pytest tests/workers` cho **40 passed**. Kiểm thêm: claim, hết hạn thuê, trả bài về hàng đợi; `retry` dùng `ZADD LT` giữ lịch sớm hơn; bộ đếm lần thử có TTL.

## Khi hỏng: cái gì vẫn chạy, gỡ ra thế nào

| Hỏng | Người dùng thấy | Gỡ hoặc tắt | Chạy bù |
|---|---|---|---|
| Worker bị kill hoặc hết RAM | Bản tóm tắt cũ vẫn hiện | — | Hết hạn thuê 5 phút thì replica khác chạy lại |
| DeepSeek chậm hoặc chết | Bản `ready` cũ vẫn hiện; bài mới chưa có tóm tắt | `SUMMARY_LLM_KILL=true` | Cầu dao tự đóng sau 5 phút; nếu đã bật kill switch thì chạy backfill sau khi tắt |
| Bộ phân loại lỗi hoặc chậm | Tóm tắt vẫn ra, chọn bình luận bằng luật | `CLASSIFIER_ENABLED=false`, hoặc cầu dao tự mở | Lượt chạy sau khi model khoẻ lại tự tóm tắt lại, vì hash khác |
| Core trả 400, 413, 422 | Tóm tắt không cập nhật | — | Bài nằm trong `stream:dead-letter`; sửa xong chạy backfill hoặc chờ sự kiện mới |
| Thay model phân loại | — | Bundle cùng khuôn: đổi `classifier_dir` hoặc image, không sửa code | Version mới làm đổi hash, nên mỗi bài tóm tắt lại 1 lần |

## Chưa làm (có lý do)

- **Claim nguyên tử bằng Lua:** cửa sổ mất bài chỉ là giữa 2 lệnh Redis liền nhau; backfill bù được. Đã ghi `shortcut:` trong code.
- **Cache nhãn theo bình luận, và cho bộ phân loại chạy sau bước so hash:** cần thống nhất với Thành có lưu cache kỹ thuật trên Redis không.
- **Cổng eval ở CI và cổng chất lượng khi thay model** (so macro F1 trên tập gold): tập gold và cassette nằm trong `data/`, không commit, nên cần quyết định cách lưu trước.
- **Tách bộ phân loại thành service riêng, metric (p95, độ tuổi job), bảng giá LLM theo cấu hình:** chờ có số đo.

## Ảnh hưởng tới phần của người khác

- Chỉ sửa repo AI. Hợp đồng PUT và GET với core giữ nguyên.
- **Khi deploy (anh Phong):**
  - mỗi bài `ready` tóm tắt lại 1 lần, vì hash có thêm tên model (khoảng 0,005 USD mỗi bài);
  - có thêm 2 biến tuỳ chọn `CLASSIFIER_ENABLED`, `CLASSIFIER_MAX_COMMENTS`;
  - nếu `LLM_PROVIDER` trên server đang là `openai` hoặc `anthropic` thì worker sẽ không khởi động. Hiện là `deepseek`, nên không bị ảnh hưởng.
