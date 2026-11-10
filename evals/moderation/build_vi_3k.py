"""Builds evals/moderation/vi_3k.jsonl: 3000 labelled Vietnamese comments for POST /moderate.

    uv run python -m evals.moderation.build_vi_3k

Synthetic, high-quality, not user data: sentences are assembled from rich phrase pools
mirroring the categories in vi_30.jsonl (harassment, threat, self-harm, sexual, hate, violence
vs. slang_praise, complaints, safety reports, slang, neutral questions, beach activities).
Augmented naturally with realistic chat noise: no diacritics, teencode, realistic vowel elongations,
common emojis, and caps. Seeded for 100% reproducibility. Fully deduplicated.
Explicitly avoids data leakage from vi_30.jsonl.
"""

import json
import random
import unicodedata
from pathlib import Path

SEED = 20261110
PER_CLASS = 1500
OUT = Path(__file__).resolve().parent / "vi_3k.jsonl"
VI_30_PATH = Path(__file__).resolve().parent / "vi_30.jsonl"

# --- POOLS ---

TOXIC: dict[str, tuple[list[str], ...]] = {
    "harassment": (
        [
            "mày",
            "bạn",
            "con này",
            "thằng kia",
            "đứa kia",
            "bà chủ",
            "ông chủ",
            "nhân viên đó",
            "chủ quán",
            "con phục vụ",
            "thằng reviewer",
            "con bé này",
            "mụ bán hàng",
            "thằng tài xế",
        ],
        [
            "ngu như bò",
            "óc chó",
            "đần độn",
            "rác rưởi",
            "xấu như ma",
            "vô học",
            "bẩn bựa",
            "thất đức",
            "hãm tài",
            "mất dạy",
            "lừa đảo trắng trợn",
            "mặt dày vô sỉ",
            "vô văn hóa",
            "bệnh hoạn",
        ],
        [
            "quay clip kiểu này cũng đăng",
            "review xàm xí vậy trời",
            "cút đi chỗ khác chơi",
            "nói nhảm câu like rẻ tiền",
            "bày đặt làm food reviewer",
            "mặt dày đi ăn chực à",
            "vô duyên hết phần thiên hạ",
            "bớt xàm xí lại giùm",
            "nhìn ngứa mắt thật sự",
            "đúng là thứ rác rưởi của xã hội",
            "",
        ],
    ),
    "threat": (
        [
            "nếu còn chê nữa",
            "nói thêm câu nào nữa",
            "đừng để tao gặp ngoài đời",
            "lần sau mà còn quay lén",
            "mày coi chừng bước chân ra khỏi quán",
            "còn dám bén mảng tới đây",
            "nếu mày không xoá video",
            "thử nói xấu thêm một lần nữa",
        ],
        [
            "tao đánh cho nhập viện",
            "tao chém mày rách mặt",
            "tao cho mày biết tay",
            "mày coi chừng tao chặn đường đấy",
            "tao đập nát cái quán của mày",
            "tao kéo người đến tận nhà xử mày",
            "tao đập nát máy quay của mày",
            "tao cho mày không còn đường về nhà",
        ],
        [
            "liệu hồn đấy con chó",
            "chờ đấy xem tao làm gì mày",
            "đừng tưởng tao nói chơi",
            "biết điều thì câm mồm lại",
            "",
        ],
    ),
    "self_harm": (
        [
            "chán sống quá, muốn chết cho xong",
            "ai chỉ cách tự tử nhanh không đau với",
            "muốn kết thúc mạng sống này quá",
            "uống hết vỉ thuốc ngủ cho xong một kiếp",
            "áp lực quá chỉ muốn nhảy cầu cho nhẹ nợ",
            "vừa rạch tay xong, đau nhưng thấy thanh thản",
            "mình không muốn thức dậy nữa, muốn buông xuôi tất cả",
            "tối nay sẽ là đêm cuối cùng của mình",
            "sống khổ sở thế này thì chết đi cho người ta vừa lòng",
        ],
        [
            "đi đâu cũng thấy bế tắc cùng cực",
            "mệt mỏi quá rồi không chịu nổi nữa",
            "không ai cần mình trên đời này đâu",
            "mọi người ở lại sống tốt nhé",
            "vĩnh biệt tất cả mọi người",
            "",
        ],
    ),
    "sexual": (
        [
            "gửi ảnh nóng cho anh xem đi, anh chuyển khoản liền",
            "body ngon thế này chắc ngủ với nhiều người lắm rồi",
            "khoe ngực khoe mông thế này một đêm bao nhiêu tiền em",
            "nhìn dâm thế này chắc kỹ năng trên giường đỉnh lắm nhỉ",
            "đi khách sạn với anh một đêm anh bao trọn gói chuyến du lịch",
            "em quay clip khỏa thân cho anh xem, anh cho tiền tiêu xài",
            "mặc hở hang thế này là cố tình mời gọi đàn ông vào thịt à",
            "nhìn thèm quá, cho anh sờ ngực một cái được không",
            "show hàng đi em ơi, có tiền là mua được hết",
            "nhìn cặp đùi mlem quá, muốn đè ra làm nháy ngay tại chỗ",
            "nhắn tin riêng gửi ảnh nude cho anh nhé, anh trả giá cao",
        ],
        [
            "inbox tâm sự kín nhé cưng",
            "giá cả thế nào cứ báo anh",
            "đừng làm bộ ngây thơ nữa",
            "anh lo cho từ a đến z",
            "",
        ],
    ),
    "hate": (
        [
            "đuổi hết bọn {g} ra khỏi đây đi, ghê tởm chết đi được",
            "{g} thì đừng cho vào resort, bẩn thỉu rác rưởi lắm",
            "bọn {g} toàn lũ hạ đẳng cặn bã của xã hội",
            "không bao giờ tiếp đón bọn {g}, nhìn phát buồn nôn",
            "cấm cửa hết bọn {g}, làm ô uế cả khu du lịch này",
            "bọn {g} nên bị tống cổ về nơi ở cũ đi, đừng ra ngoài làm phiền người khác",
            "ghét cay ghét đắng cái giống {g}, nhìn mặt chỉ muốn đuổi",
        ],
        ["tốt nhất là cút hết đi", "đúng là thứ sâu bọ", "không hiểu sao cho tồn tại", ""],
    ),
    "violence": (
        [
            "nhìn mặt là muốn đấm vỡ mồm",
            "muốn mang dao tới chém cả nhà thằng chủ",
            "tao mà gặp ngoài đường là dần cho một trận thừa sống thiếu chết",
            "đứa nào quay clip này tao tát cho không trượt phát nào",
            "bắt được trộm là phải đánh hội đồng cho gãy tay gãy chân mới chừa",
            "gặp loại này là phải phang gậy vào đầu cho nhớ đời",
            "chỉ muốn lôi đầu nó ra đập cho một trận nhừ tử",
            "mang xăng đốt rụi cái chỗ lừa đảo này đi anh em",
        ],
        [
            "đánh cho chừa cái thói mất dạy",
            "không nói nhiều cứ phải dùng nắm đấm",
            "phải dạy cho nó một bài học nhớ đời",
            "",
        ],
    ),
}

GROUPS = [
    "đồng tính",
    "người khuyết tật",
    "người nước ngoài",
    "người chuyển giới",
    "người miền Trung",
    "người miền Bắc",
    "người miền Nam",
]

CLEAN: dict[str, tuple[list[str], ...]] = {
    "slang_praise": (
        [
            "view {a_view} chết mất",
            "phòng {a_room} xỉu up xỉu down",
            "hoàng hôn ở đây {a_view} luôn á",
            "resort {a_room} dã man",
            "buffet {a_food} xỉu",
            "hải sản ở đây {a_food} vãi chưởng",
            "món ăn {a_food} nhức nách",
            "chill {a_exp} quá trời",
            "không gian {a_exp} cực kỳ",
            "hồ bơi vô cực {a_view} đỉnh chóp",
        ],
        [
            "nhất định phải ghé thử một lần",
            "quẩy tới bến với hội bạn thân",
            "ăn no căng rốn muốn té xỉu luôn",
            "chụp hình cháy máy không muốn về",
            "10 điểm không có nhưng",
            "mê chữ ê kéo dài luôn á",
            "",
        ],
    ),
    "complaint": (
        [
            "phục vụ tệ, đồ ăn dở, giá thì chát",
            "nhân viên thái độ lồi lõm, trải nghiệm rất thất vọng",
            "quảng cáo một đằng làm một nẻo, không đúng cam kết ban đầu",
            "phòng ẩm mốc, nước nóng lúc có lúc không rất bất tiện",
            "xe đưa đón trễ hai tiếng làm lỡ lịch trình của cả gia đình",
            "cách âm phòng quá kém, ban đêm phòng bên cạnh ồn ào không ngủ được",
            "thủ tục check-in quá rườm rà, lễ tân xử lý thiếu chuyên nghiệp",
            "hồ bơi nước đục và nhiều rác, không được vệ sinh sạch sẽ",
            "bữa sáng buffet nghèo nàn, đồ ăn nguội ngắt không nuốt nổi",
        ],
        [
            "sẽ không bao giờ quay lại",
            "mong ban quản lý chấn chỉnh sớm",
            "mọi người nên cân nhắc kỹ trước khi đặt",
            "thất vọng toàn tập",
            "tiền mất tật mang",
            "",
        ],
    ),
    "safety": (
        [
            "mình bị ngộ độc thực phẩm sau khi ăn hải sản ở quán này",
            "bãi biển có nhiều sứa lửa, bé nhà mình vừa bị đốt sưng vù chân",
            "đoạn đường đèo xuống bãi tắm trơn trượt lắm",
            "cầu thang gỗ bị mục gãy có người suýt té ngã chấn thương",
            "khu vực này nước sâu và có dòng chảy xa bờ rất nguy hiểm",
            "dốc cao sương mù dày đặc nhớ đi chậm và bật đèn cảnh báo",
            "khu vui chơi có thanh sắt nhô ra dễ gây xước da trẻ nhỏ",
            "hôm qua có du khách bị trượt chân ở mỏm đá ngắm cảnh",
        ],
        [
            "mọi người đi qua đây nhớ cẩn thận nhé",
            "chia sẻ để mọi người biết mà phòng tránh kịp thời",
            "đã phản ánh với đội cứu hộ bờ biển rồi",
            "bố mẹ dắt theo trẻ nhỏ phải hết sức chú ý",
            "",
        ],
    ),
    "slang": (
        [
            "hôm nay trời nóng muốn chết mà nhảy xuống hồ bơi là đã đời",
            "giá vé máy bay đợt này cắt cổ thật, chém khách kinh quá",
            "chết cười với ông hướng dẫn viên du lịch, tấu hài suốt cả chuyến đi",
            "tối nay ra phố đi bộ quẩy banh nóc luôn nha anh em",
            "ngồi chém gió với đám bạn bên bờ biển cả buổi tối mát rượi",
            "hôm qua leo núi mệt xỉu nhưng cảnh đẹp rụng tim",
            "đồ ăn ở chợ đêm ngon muốn xỉu, ăn sập chợ luôn",
            "sáng dậy đánh răng rửa mặt xong là phi đi săn mây liền",
            "tao đánh giá homestay này mười điểm không có nhưng",
            "cháy túi với khu mua sắm này rồi nhưng mà xứng đáng",
            "chơi trò cảm giác mạnh sợ rớt tim ra ngoài mà mê vãi",
            "hôm nay đi bộ rụng cả chân nhưng bù lại chụp được đống ảnh đẹp",
        ],
        ["vui tính xỉu luôn á", "đi một lần là nhớ mãi", "đỉnh của chóp luôn", "hết nước chấm", ""],
    ),
    "neutral": (
        [
            "cho mình hỏi khách sạn có cho phép mang thú cưng không ạ",
            "đi cáp treo lên đỉnh mất khoảng bao nhiêu phút vậy mọi người",
            "đặt phòng trước bao nhiêu ngày thì có giá ưu đãi vậy ạ",
            "giờ check-in và check-out của resort là mấy giờ thế",
            "khách sạn có dịch vụ xe đưa đón sân bay miễn phí không bạn",
            "quanh khu này có quán ăn đặc sản địa phương nào ngon không",
            "mùa này đi biển có hay bị mưa bão không các bạn ơi",
            "từ trung tâm thị trấn ra bãi biển bắt taxi có tiện không ạ",
            "vé tham quan đã bao gồm các trò chơi bên trong chưa vậy",
        ],
        [
            "cảm ơn cả nhà nhiều nhé",
            "mình đang lên lịch trình cho cả nhóm",
            "ai đi rồi cho mình xin chút kinh nghiệm với",
            "ai biết giải đáp giúp mình nhé",
            "",
        ],
    ),
    "beach": (
        [
            "mặc bikini tắm biển chụp ảnh ở đây rất thoải mái và đẹp",
            "nước biển xanh trong vắt, bãi cát thoai thoải rất an toàn",
            "bãi biển sạch sẽ, có khu vực thay đồ và tắm tráng nước ngọt",
            "các bé tắm biển nghịch cát vui lắm, sóng êm ru",
            "thuê ván chèo SUP ngắm bình minh trên biển rất tuyệt vời",
            "mặc đồ bơi tắm nắng ở hồ bơi vô cực view nhìn thẳng ra biển",
            "buổi chiều dạo bộ dọc bờ biển hóng gió ngắm hoàng hôn cực thư thái",
        ],
        [
            "nên đi vào buổi sáng sớm cho đỡ nắng gắt",
            "nhớ bôi kem chống nắng đầy đủ nha mọi người",
            "chụp ảnh ở đây góc nào cũng có ảnh đẹp mang về",
            "",
        ],
    ),
}

EMOJI = ["😂", "🤣", "😭", "🥲", "👍", "👏", "=))", ":)", "...", "ạ", "nha"]
TEEN = [
    ("không", "ko"),
    ("được", "dc"),
    ("mày", "m"),
    ("rồi", "r"),
    ("với", "vs"),
    ("quá", "qá"),
    ("biết", "bít"),
    ("nhưng", "nhma"),
    ("thôi", "thoy"),
    ("cảm ơn", "tks"),
]

VIEW_ADJ = ["đẹp", "xịn", "mê ly", "đỉnh chóp", "thần sầu", "hút mắt"]
ROOM_ADJ = ["đẹp", "xịn sò", "sang chảnh", "mê ly", "ấm cúng"]
FOOD_ADJ = ["ngon", "tươi rói", "đỉnh cao", "xịn sò", "đậm đà"]
EXP_ADJ = ["đã", "mê ly", "thích", "thoải mái", "chill"]


def strip_diacritics(text: str) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def load_vi_30_keys() -> set[str]:
    keys = set()
    if VI_30_PATH.exists():
        for line in VI_30_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                row = json.loads(line)
                keys.add(strip_diacritics(row["text"]).lower())
    return keys


def augment(text: str, rng: random.Random) -> str:
    # 1. Bỏ dấu tiếng Việt (25%)
    if rng.random() < 0.25:
        text = strip_diacritics(text)
    # 2. Teencode thông dụng (25%)
    if rng.random() < 0.25:
        for src, dst in TEEN:
            if src in text and rng.random() < 0.5:
                text = text.replace(src, dst)
    # 3. Kéo dài nguyên âm cảm thán tự nhiên ở cuối từ (15%) - ví dụ: "quáaa", "ơiii", "mêee"
    if rng.random() < 0.15:
        words = text.split()
        if words:
            idx = rng.randint(0, len(words) - 1)
            target = words[idx]
            if len(target) > 1 and target[-1].lower() in "aeiouy":
                words[idx] = target + target[-1] * rng.randint(1, 2)
                text = " ".join(words)
    # 4. Emoji / từ đệm cuối câu (25%)
    if rng.random() < 0.25:
        text = f"{text} {rng.choice(EMOJI)}"
    # 5. Viết hoa toàn bộ câu khi bức xúc hoặc phấn khích (5%)
    if rng.random() < 0.05:
        text = text.upper()
    return text.strip()


def compose(kind_pools: tuple[list[str], ...], rng: random.Random) -> str:
    parts = [rng.choice(pool) for pool in kind_pools]
    filled = []
    for part in parts:
        if "{g}" in part:
            part = part.replace("{g}", rng.choice(GROUPS))
        if "{a_view}" in part:
            part = part.replace("{a_view}", rng.choice(VIEW_ADJ))
        if "{a_room}" in part:
            part = part.replace("{a_room}", rng.choice(ROOM_ADJ))
        if "{a_food}" in part:
            part = part.replace("{a_food}", rng.choice(FOOD_ADJ))
        if "{a_exp}" in part:
            part = part.replace("{a_exp}", rng.choice(EXP_ADJ))
        filled.append(part)
    return " ".join(p for p in filled if p)


def make_class(
    pools: dict[str, tuple[list[str], ...]],
    toxic: bool,
    rng: random.Random,
    exclude_keys: set[str] | None = None,
) -> list[dict]:
    kinds = list(pools)
    rows: list[dict] = []
    seen: set[str] = set()
    counter = 0
    excludes = exclude_keys or set()
    while len(rows) < PER_CLASS:
        kind = kinds[counter % len(kinds)]
        counter += 1
        raw_text = compose(pools[kind], rng)
        text = augment(raw_text, rng)
        key = strip_diacritics(text).lower()
        if not text or key in seen or key in excludes:
            continue
        seen.add(key)
        rows.append({"toxic": toxic, "kind": kind, "text": text, "pre_text": raw_text})
    return rows


def main() -> None:
    rng = random.Random(SEED)
    vi_30_keys = load_vi_30_keys()
    toxic_rows = make_class(TOXIC, True, rng, vi_30_keys)
    clean_rows = make_class(CLEAN, False, rng, vi_30_keys)
    rows = toxic_rows + clean_rows
    rng.shuffle(rows)

    with OUT.open("w", encoding="utf-8") as f:
        for i, row in enumerate(rows, 1):
            f.write(
                json.dumps(
                    {
                        "id": f"s{i:04d}",
                        "toxic": row["toxic"],
                        "kind": row["kind"],
                        "text": row["text"],
                        "source": "synthetic-template-v2",
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    print(f"wrote {len(rows)} rows to {OUT}")


if __name__ == "__main__":
    main()
