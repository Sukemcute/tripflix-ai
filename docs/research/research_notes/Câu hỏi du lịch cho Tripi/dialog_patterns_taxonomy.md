# Dialogue patterns, intent taxonomies and failure modes of LLM travel assistants (for a Vietnamese hybrid controller/tools/responder/verifier chatbot)

Method note: web search worked; WebFetch was blocked for arxiv.org and zenml.io, so findings rest on search-result summaries, not full-text reads. Items marked "(background)" are from model memory, NOT verified this session. Everything else carries a link.

## Q1. Which intents/slots are standard for travel dialogue, and what would a domestic VN app likely miss?

### Takeaway
Public datasets agree on a small core: informable constraint slots (area, price range, dates, party size), requestable slots (phone, address, price), and a separate "booking" step. The only Vietnamese dataset (PhoATIS) is flight-only and translated from English, so there is no public Vietnamese hotel/attraction/restaurant intent-slot corpus; Tripi must define its own taxonomy.

### Cited Findings
- MultiWOZ splits slots into informable (constraints such as price range, area, booking day), requestable (extra info the user may ask, e.g. phone number) and book slots — [Korean KLUE paper describing the scheme](https://arxiv.org/pdf/2105.09680).
- MultiWOZ 2.2 adds an active user intent and requested slots for every user turn, and removes open-vocabulary slots with huge value sets (restaurant name, booking time) from the ontology — [MultiWOZ 2.2](https://arxiv.org/pdf/2007.12720). Example intent name `find_attraction`; slot names like `attraction-area`, `hotel-name`, `taxi-departure` — [HF card](https://huggingface.co/datasets/pfb30/multi_woz_v22/blob/main/README.md?code=true). Full ontology is in the GitHub repo data/MultiWOZ_2.2 (not read).
- Schema-Guided Dialogue (SGD, Google, DSTC8): predictions over a dynamic set of intents/slots supplied as schema with natural-language descriptions; covers hotels, travel, flights, restaurants, weather, events among 16-20 domains (count varies by source); slots are categorical (fixed list) or non-categorical (city, address); eval set contains unseen services — [SGD paper](https://arxiv.org/pdf/1909.05855v2.pdf), [DSTC8 system paper](https://arxiv.org/pdf/2006.09035), [HF GEM card](https://huggingface.co/datasets/GEM/schema_guided_dialog/resolve/main/README.md).
- ATIS (flight domain) uses BIO slot tags (e.g. `B-fromloc.airport_name`), intents like `atis_flight`, `atis_airfare`, `atis_ground_service`; multi-intent variants exist (MixATIS; OpenSLU joins labels as `atis_flight#atis_airfare`). Intent count differs by release (21 in one HF view) — [OpenSLU](https://huggingface.co/datasets/LightChen2333/OpenSLU), [MixATIS](https://huggingface.co/datasets/chirunder/MixAtis_for_DecoderOnly/viewer/default/train?p=176).
- PhoATIS (VinAI, 2021): first public Vietnamese intent+slot dataset, manual translation of ATIS, 5,871 utterances, 28 intents, 82 slot types (4,478/500/893 split); joint model JointIDSF; flight-only — [arXiv 2104.02021](https://arxiv.org/abs/2104.02021), [search summary](https://arxiv.org/pdf/2104.02021).
- No public Vietnamese hotel/tourism intent-slot corpus found. Closest: a 2023 tourism-recommendation chatbot paper (11 topics, 7,319 samples from TWCS, not clearly released) and VN-SLU (smart-home, not tourism) — [ACS 2023](https://reference-global.com/article/10.2478/acss-2023-0023), [DOAJ](https://doaj.org/article/4249ca6d9d294e278343b4d55b9afc5f).
- TravelPlanner (OSU, ICML 2024): 1,225 queries, sandbox of ~4M records via six tools; constraints are explicit (budget etc.) and implicit commonsense (e.g. must have transport between cities) — [arXiv 2402.01622](https://arxiv.org/html/2402.01622v4).
- LLM-based DST via function calling: converting domain schemas to function specs beat ChatGPT baseline JGA on MultiWOZ by 5.6% — [Towards LLM-driven DST](https://arxiv.org/pdf/2310.14970).

### Inferences
- Recommended core taxonomy for Tripi (derived from the above, background knowledge for exact slot names): intents = search_stay / search_flight / search_attraction / search_restaurant / get_weather / compare / get_detail (requestable) / refine / book_or_handoff / chitchat / out_of_scope; slots = destination, area/district, check_in/out or duration+flexible dates, guests (adults/children/rooms), budget (per night vs total, currency VND), star/type, amenities, sort preference, plus requestable (price, address, phone, cancellation policy, distance).
- Likely gaps for a domestic VN app vs. English datasets: Vietnamese date idioms ("cuối tuần này", "dịp 30/4", "Tết", "20 tháng 11 âm"), budget shorthand ("1tr2", "dưới 500k", "tầm 2 củ"), unit scale ("2 triệu/đêm" vs total), group-composition words ("gia đình 2 lớn 1 nhỏ", "đi với bố mẹ"), accommodation types specific to VN (homestay, villa, nhà nghỉ, resort), place-name ambiguity and diacritic-less input ("da lat", "Hà Nội cũ/Hanoi"), landmark-relative location ("gần biển", "gần chợ đêm", "cách trung tâm"), transport modes beyond flights (xe giường nằm, tàu hỏa, xe limousine), and intents such as "đi đâu chơi/ăn gì" (open recommendation) that ATIS/MultiWOZ lack. PhoATIS teaches none of these. (Inference; no source quantifies it.)
- Use schema-with-descriptions (SGD style) as the controller's tool schema; it lets new services be added without retraining.

### Gaps
- Exact hotel/train/attraction/restaurant slot lists of MultiWOZ and SGD service schemas were not retrieved (fetch blocked/page lacked them); read github.com/budzianowski/multiwoz and google-research-datasets/dstc8-schema-guided-dialogue directly.
- PhoATIS intent label list and baseline scores not retrieved.
- ATIS official intent count unresolved (21 vs 26 vs PhoATIS 28).

## Q2. Which multi-turn failure modes are most reported, and how are they mitigated?

### Takeaway
LLMs answer too early, commit to wrong guesses and do not recover (under-clarification, "lost in conversation"); tool-using agents additionally fail on policy/argument errors and consistency across repeated runs. Mitigations: explicit tracked state, a clarify-vs-answer decision step, input rewriting, and code-side validation.

### Cited Findings
- Laban et al. "LLMs Get Lost In Multi-Turn Conversation" (ICLR 2026): across six tasks, multi-turn performance averages roughly 35-39% below single-turn (v1 says 39%, later version 35% over 15 LLMs); small aptitude loss but big rise in unreliability; models guess missing details early, commit and over-rely on those guesses — [arXiv 2505.06120](https://arxiv.org/abs/2505.06120v1), [ICLR page](https://iclr.cc/virtual/2026/oral/10009147).
- 2026 follow-up: the bottleneck is pragmatic intent mismatch between user expression and model interpretation; adaptively rewriting user inputs before the model recovers a substantial share of the loss — [arXiv 2602.07338](https://arxiv.org/pdf/2602.07338).
- ClarifyMT-Bench (Dec 2025): 6,120 multi-turn interactions, five-dimension ambiguity taxonomy, six user personas; ten LLMs (incl. GPT-4.1, Gemini-2.5-Flash, Llama-3.1) answer prematurely (under-clarification bias) and degrade with dialogue depth; proposed ClarifyAgent (Perceive-Predict-Track-Plan) reportedly +32.7% accuracy (unverified against paper) — [arXiv 2512.21120](https://arxiv.org/html/2512.21120v1). AskBench and RIFTS report the same bias (models rarely initiate repair vs humans) — [survey 2504.04717](https://arxiv.org/pdf/2504.04717).
- Herlihy et al. (Microsoft): in public chat logs LLM-recommender queries are often under-specified; miscalibrated response strategy attributed to single-turn fine-tuning data; lightweight recalibration from logs proposed — [MSR](https://www.microsoft.com/en-us/research/?p=1042029).
- Anaphora/ellipsis across turns remains an open challenge; LLMs fail to link content from earlier rounds or detect ellipsis/implicit meaning — [survey 2504.04717](https://arxiv.org/pdf/2504.04717); classic fix is explicit ellipsis/coreference resolution (GECOR) — [arXiv 1909.12086](https://arxiv.org/pdf/1909.12086).
- τ-bench (Sierra, ICLR 2025): gpt-4o with function calling reaches ~61% pass^1 retail and ~35% airline; pass^k (all k trials succeed) drops quickly as k grows; scoring compares final DB state to goal state; airline tasks = booking/modification/cancellation/refund under policy — [arXiv 2406.12045](https://arxiv.org/pdf/2406.12045), [ICLR](https://proceedings.iclr.cc/paper_files/paper/2025/hash/1b126cc38b8638e07bef37e7b2bb72bf-Abstract-Conference.html).
- TravelPlanner: GPT-4 produced a fully valid plan for 0.6% of tasks; failures include wrong tool arguments, loops, hallucination; ReAct/Reflexion insufficient for multi-constraint — [arXiv 2402.01622](https://arxiv.org/html/2402.01622v4).
- Function-calling DST and state-update prompts: LLM as black-box tracker with self-refined prompt gave SOTA strict JGA on MultiWOZ 2.4 (+3%) with up to 90% fewer API calls — [arXiv 2409.15861](https://arxiv.org/html/2409.15861v2).

### Inferences
- Map to Tripi phenomena (design implications, not sourced): keep a code-owned `SearchState` (slots + last result list with stable ids/ranks) and have the controller emit *state deltas* (add/replace/remove/exclude), not a full re-parse; resolve "căn thứ 2", "cái đó", "rẻ hơn cái này" in code against the stored ranked list; represent negation/exclusion ("không muốn gần đường lớn", "trừ Sapa") as explicit exclude slots; treat "thôi đổi sang Đà Nẵng" as slot replace with a decision whether dependent slots (dates, area) carry over; split multi-intent messages into an ordered plan of tool calls.
- Ask-vs-assume: because models under-clarify, put the policy in code: ask only when a missing slot makes the tool call impossible or results would diverge widely (destination, dates for availability); otherwise assume a stated default ("mình tạm tính 2 người lớn, 1 đêm, bạn chỉnh nếu khác nhé"), show assumption chips, and cap to one question per turn. Explicitly test against ClarifyMT-style personas (terse, vague, contradictory, impatient).
- pass^k suggests running each eval case several times; consistency matters more than best-case.

### Gaps
- No travel-specific quantified study of anaphora/comparative/negation errors was found; evidence is general multi-turn LLM work.
- Full τ-bench airline error-analysis categories not retrieved (fetch blocked).

## Q3. How do production assistants balance LLM freedom vs. grounded tool data, and what are the lessons on price/availability hallucination?

### Takeaway
Vendors publicly describe the same pattern: the LLM understands and phrases, while inventory/prices come from the company's own search/APIs, plus grounding checks and hybrid workflows for risky actions. Public engineering detail is thin; liability for wrong statements sits with the company (Air Canada).

### Cited Findings
- Booking.com AI Trip Planner (OpenAI-based): generates ideas/itineraries and pulls real-time availability and pricing from Booking.com's database; launched in ~10 weeks; CEO advised users to double-check before paying; a hands-on test found it could not book directly and showed glitches — [OpenAI case study](https://openai.com/index/booking-com/) (vendor-authored), [search summary of USA Today test](https://openai.com/index/booking-com/).
- Expedia Romie (May 2024): planning, shopping, booking, in-trip changes; group-chat mode that (per ZenML's reading, an inference) uses lightweight monitoring and triggers costly LLM calls only on explicit invocation — [Expedia](https://www.expedia.com/product/release/), [ZenML](https://zenml.io/llmops-database/ai-powered-travel-assistant-for-trip-planning-and-personalization). Not read in full.
- Trip.com TripGenie: Gemini 3 as reasoning model for multi-constraint requests; Agent Search + Grounding on Gemini to verify answers against sources and cut hallucination; earlier version on OpenAI and routed "cheap flight" queries to a Flight Deals page and drew on Trip.com ranking lists; 2026 added in-chat booking for eSIM and attraction tickets; metrics self-reported — [Google Cloud case study](https://cloud.google.com/customers/tripgenie), [Trip.com](https://www.trip.com/newsroom/introducing-tripgenie-groundbreaking-ai-travel-assistant), [Skift](https://skift.com/?p=608581).
- Kayak AI Mode (Oct 2025): natural-language search box combining Kayak data with ChatGPT for real-time results from hundreds of providers — [TechCrunch](https://techcrunch.com/2025/10/16/kayak-launches-an-ai-mode-for-travel-questions-search-and-bookings/).
- Google AI Mode: agentic booking announced Nov 2025 with Booking.com, Expedia, Marriott etc. as partners; hotel booking later live in US, flight price tracking in 180 countries, flight booking not launched (Aug 2026 report). This is Search AI Mode, not Gemini app — [Skift](https://skift.com/2025/11/17/google-is-building-agentic-travel-booking-plus-other-travel-ai-updates/), [TechCrunch](https://techcrunch.com/2026/08/27/googles-ai-mode-can-now-track-flight-prices-help-book-hotels-and-more/).
- Airbnb: Automation Platform v2 hybrid of LLM conversation and traditional workflows with a Guardrails Framework (parallel guardrails against hallucination/jailbreak); support taxonomy routes cancellations/refunds; QCon 2026 talk covers LLM-as-judge labeling of production traffic, golden/holdout datasets, shadow runs; agent handles ~1/3 of NA support issues; CEO said in Feb 2025 it was too early for AI trip planning — [ZenML summary](https://www.zenml.io/llmops-database/evolving-a-conversational-ai-platform-for-production-llm-applications), [QCon SF](https://qconsf.com/presentation/nov2026/how-airbnb-guardrailed-its-ai-customer-support-agent), [TechCrunch](https://techcrunch.com/2025/02/14/airbnb-ceo-says-its-still-too-early-for-ai-trip-planning).
- Air Canada (Moffatt, Feb 2024): tribunal held the airline liable for its chatbot's wrong bereavement-fare statement, rejecting "separate entity" defence; C$812.02 ordered — [ABA](https://www.americanbar.org/groups/business_law/resources/business-law-today/2024-february/bc-tribunal-confirms-companies-remain-liable-information-provided-ai-chatbot/), [Skift](https://skift.com/2024/02/16/air-canada-ordered-to-pay-for-its-chatbots-false-info).
- 2023 Axios coverage: AI chatbots "not 100% ready" for trip planning — [Axios](https://axios.com/2023/11/15/ai-chatbot-chat-gpt-travel-trip-planning) (snippet only).

### Inferences
- Pattern for Tripi: (1) controller LLM outputs a typed plan/slots (JSON schema); (2) code runs tools; (3) responder LLM receives only tool results as a structured fact table with ids and writes Vietnamese prose using placeholders or id references for every price/rating/availability; (4) verifier in code extracts all numbers/names/dates from the draft (regex for "k/tr/đ/VND", dates) and checks them against the fact table, then regenerates or falls back to a templated card on mismatch; (5) facts the tool did not return are phrased as "chưa có thông tin" rather than filled; (6) show the data timestamp ("giá tại lúc 14:05, có thể thay đổi") given the Air Canada liability precedent. Even better: render price/availability from structured cards, and let LLM text only reference them.
- Free-form LLM knowledge should be allowed only for non-transactional content (vibes, tips, itinerary ideas) and labelled as general advice, not tied to a listed inventory item.
- Industry consensus visible in these sources: hybrid workflow + guardrails (Airbnb), own-database grounding (Booking.com, Trip.com), and handoff for risky actions.

### Gaps
- No primary engineering blog from Expedia, Booking.com, Kayak, or Trip.com on hallucination controls or intent taxonomy was found; sources are vendor case studies/press.
- No verified case of Google Gemini/AI Mode hallucinating prices found.
- Airbnb QCon talk content not available beyond abstract.

## Q4. How should such agents be evaluated (intent accuracy, slot F1, task success, groundedness)?

### Takeaway
Use layered metrics: NLU (intent accuracy, slot F1 / joint goal accuracy), tool-call correctness, end-to-end state-based task success with repeated trials (pass^k), and LLM-judge plus code-checked groundedness on production-like traffic.

### Cited Findings
- Joint goal accuracy (JGA) = fraction of turns where the entire predicted state exactly matches gold; slot accuracy = average over slots; MultiWOZ 2.4 corrected annotations and models score higher there than earlier versions (so numbers across versions are not comparable) — [MultiWOZ 2.4](https://arxiv.org/pdf/2104.00773).
- PhoATIS baselines are evaluated on intent and slot metrics with JointBERT+CRF and the intent-slot-attention JointIDSF — [arXiv 2104.02021](https://arxiv.org/abs/2104.02021).
- TravelPlanner scores constraint satisfaction (commonsense and hard constraints, with a final pass rate; exact metric names not retrieved) — [arXiv 2402.01622](https://arxiv.org/html/2402.01622v4).
- τ-bench: success = final database state equals annotated goal state, with LLM-simulated user; pass^k measures reliability across k trials — [arXiv 2406.12045](https://arxiv.org/pdf/2406.12045).
- ClarifyMT-Bench: action accuracy (Clarify vs Answer) per turn, plus LLM-judge and human rating of clarifying-question quality — [arXiv 2512.21120](https://arxiv.org/html/2512.21120v1).
- Airbnb production practice: LLM-as-judge labeling of production traffic, tiered golden and holdout datasets, shadow runs before release — [QCon SF](https://qconsf.com/presentation/nov2026/how-airbnb-guardrailed-its-ai-customer-support-agent).
- User-aware agent evaluation with automated error analysis ("Talk, Evaluate, Diagnose") is a 2026 follow-up on τ-bench — [arXiv 2603.15483](https://arxiv.org/pdf/2603.15483) (snippet only).

### Inferences
- Suggested Tripi eval suite: (a) controller: intent accuracy + slot-delta F1 + JGA on a hand-built Vietnamese multi-turn set (include diacritic-less, slang budgets, anaphora, negation, change-of-mind, multi-intent); (b) tool-call exact-match on arguments; (c) groundedness = % of numeric/entity claims in the response found in tool output (computed in code, no LLM needed) plus verifier rejection rate; (d) end-to-end scenario success with scripted user simulator, run k times for pass^k; (e) clarification action accuracy (ask vs assume) and over-asking rate; (f) human/LLM judge for naturalness.
- Seed the set from real Tripi logs rather than translated ATIS.

### Gaps
- Exact end-to-end metrics for MultiWOZ (Inform/Success/BLEU) and slot-F1 numbers for LLMs on hotel domains were not retrieved.
- No source gives a standard groundedness metric specific to travel; the code-side claim-check is my proposal.
