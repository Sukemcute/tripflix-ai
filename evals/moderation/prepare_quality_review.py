"""Freeze an unapproved candidate and a reproducible, stratified human review pack.

Run: uv run python -m evals.moderation.prepare_quality_review
Does not change generator, original labels, or the evaluation runner. No API calls.
"""

import csv
import hashlib
import json
import random
import re
import runpy
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "quality_review"

RULES = [
    (
        "Phạm vi",
        "toxic=True nghĩa là cần gắn cờ kiểm duyệt, không đồng nghĩa tự động xóa."
        " Nhóm kind là nhóm thiết kế dữ liệu, chưa phải nhãn category của nhà "
        "cung cấp.",
    ),
    (
        "harassment",
        "Gắn cờ công kích, hạ nhục một người/nhóm cụ thể. Phê bình dịch vụ hoặc "
        "giá cả đơn thuần là clean.",
    ),
    (
        "threat",
        "Gắn cờ lời đe dọa gây hại. Câu mơ hồ phải đọc ngữ cảnh. kind có thể chồng lấn violence.",
    ),
    (
        "self_harm",
        "Gắn cờ biểu đạt ý định tự hại hoặc tìm hướng dẫn. Không tự động gắn cờ "
        "thành ngữ như nóng muốn chết. Nhãn không quyết định hình thức xử lý "
        "người viết.",
    ),
    (
        "sexual",
        "Gắn cờ gạ gẫm/quấy rối tình dục rõ nghĩa. Bikini, body hoặc lời mời đi "
        "cùng tự nó chưa đủ để kết luận.",
    ),
    (
        "hate",
        "Gắn cờ miệt thị hoặc loại trừ theo đặc điểm nhóm. Cần chốt riêng phạm vi"
        " vùng miền và cách ánh xạ category của nhà cung cấp.",
    ),
    (
        "violence",
        "Gắn cờ ý định/lời cổ súy gây hại. Thuật lại tai nạn, cảnh báo an toàn và"
        " thành ngữ không mặc nhiên là toxic.",
    ),
    (
        "slang_praise / slang",
        "Giữ clean khi là nói lóng hoặc nghĩa bóng vô hại. Chốt quy định riêng về"
        " từ tục trong lời khen.",
    ),
    (
        "complaint / safety",
        "Phàn nàn và cảnh báo an toàn là clean nếu không kèm công kích/đe dọa. "
        "Clean ở moderation vẫn có thể cần xử lý cảnh báo ở luồng khác.",
    ),
    (
        "neutral / beach",
        "Câu hỏi thông thường và hoạt động biển thông thường là clean. Đánh giá "
        "cả câu, không dựa riêng từ khóa.",
    ),
    (
        "Mơ hồ",
        "Chọn Cần thảo luận, ghi lý do và để nhãn duyệt trống cho đến khi thống "
        "nhất. Không ép clean/toxic.",
    ),
    (
        "Quyết định",
        "Giữ: điền nhãn duyệt. Sửa câu: điền câu sửa và nhãn duyệt. Sửa nhãn: "
        "điền nhãn mới khác gốc. Loại/Cần thảo luận: ghi lý do.",
    ),
    (
        "Độc lập với model",
        "Duyệt theo quy tắc và ngữ cảnh. Không đổi ground truth chỉ để khớp dự đoán model.",
    ),
    (
        "Giới hạn mẫu",
        "20 câu mỗi nhóm gồm 10 ngẫu nhiên + 10 có chủ đích. Mẫu có chủ đích ưu "
        "tiên lỗi/biến đổi và câu gốc khác nhau. Không dùng tỷ lệ lỗi của 240 câu"
        " để suy ra tỷ lệ toàn bộ 3k.",
    ),
    (
        "Sau duyệt",
        "Sửa template, sinh lại candidate, duyệt lại phần bị ảnh hưởng. Chỉ đưa "
        "câu đã duyệt vào benchmark. Các biến thể cùng câu gốc cần nằm cùng split"
        " nếu dùng cả train/dev/test.",
    ),
]


def observations(kind: str, text: str) -> list[str]:
    notes = []
    if "tối nay đi với anh, trả tiền hậu hĩnh" in text:
        notes.append(
            "Thiếu ngữ cảnh tình dục. Đề xuất cách ly hoặc viết lại rõ hành vi trước khi chốt nhãn."
        )
    if "khoe body đi em, anh chơi cho" in text:
        notes.append("Gợi ý quấy rối nhưng từ chơi mơ hồ. Cần chốt ngữ cảnh và chính sách.")
    if "body ngon thế này chắc ngủ với nhiều người lắm" in text:
        notes.append(
            "Công kích mang tính tình dục, chồng lấn harassment. Không coi kind "
            "là category duy nhất."
        )
    if "thiểu năng" in text:
        notes.append("Từ chỉ khuyết tật dùng để xúc phạm, có thể chồng lấn hate/harassment.")
    if "tao cho mày biết tay" in text or "mày coi chừng tao" in text or "tao xử đẹp" in text:
        notes.append("Đe dọa gián tiếp, cần giữ ngữ cảnh có mục tiêu để phân biệt nghĩa bóng.")
    if kind == "slang_praise":
        notes.append(
            "Placeholder {a} dùng chung tạo kết hợp gượng như view ngon, đẹp đẹp "
            "hoặc chill ngon. Nên ghép tính từ theo danh từ."
        )
    if kind == "hate":
        notes.append(
            "Cần thống nhất phạm vi đặc điểm nhóm, nhất là vùng miền. Chưa xác "
            "nhận mapping sang category provider."
        )
    if kind in {"threat", "violence"}:
        notes.append(
            "Hai nhóm chồng lấn nghĩa. Có thể giữ nhãn nhị phân nhưng cần quy tắc"
            " phân nhóm nhất quán."
        )
    if "bị lừa khách" in text:
        notes.append(
            "Cụm bị lừa khách không tự nhiên. Đề xuất: quảng cáo sai sự thật, làm khách thất vọng."
        )
    if kind in {"slang", "neutral", "safety", "slang_praise"}:
        notes.append("Các vế ghép độc lập có thể lệch ngữ cảnh. Đọc lại toàn câu sau khi ghép.")
    if "vãi chưởng" in text:
        notes.append("Chốt cách xử lý từ tục trong lời khen, tách khỏi công kích cá nhân.")
    return notes


def main() -> None:
    OUT.mkdir(exist_ok=True)
    source = HERE / "build_vi_3k.py"
    module = runpy.run_path(str(source))
    globals_ = module["make_class"].__globals__
    original_compose = globals_["compose"]
    original_augment = globals_["augment"]
    bases = {}
    current = [""]

    def traced_compose(pools, rng):
        current[0] = original_compose(pools, rng)
        return current[0]

    def traced_augment(text, rng):
        result = original_augment(text, rng)
        bases[result] = current[0]
        return result

    globals_["compose"] = traced_compose
    globals_["augment"] = traced_augment
    rng = random.Random(module["SEED"])
    rows = module["make_class"](module["TOXIC"], True, rng)
    rows += module["make_class"](module["CLEAN"], False, rng)
    rng.shuffle(rows)
    for i, row in enumerate(rows, 1):
        row.update(id=f"s{i:04d}", source="synthetic-template-v1")
    assert len(rows) == 3000 and len({r["text"] for r in rows}) == 3000
    candidate = OUT / "vi_3k.candidate.jsonl"
    candidate.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")

    def canonical(text):
        return re.sub(r"\W+", " ", module["strip_diacritics"](text).lower()).strip()

    base_counts = Counter(canonical(bases[r["text"]]) for r in rows)
    seed = [
        json.loads(line) for line in (HERE / "vi_30.jsonl").read_text("utf-8").splitlines() if line
    ]
    seed_texts = {canonical(r["text"]) for r in seed}
    sample = []
    sample_rng = random.Random(module["SEED"] + 1)
    for kind in list(module["TOXIC"]) + list(module["CLEAN"]):
        group = [r for r in rows if r["kind"] == kind]
        random_rows = sample_rng.sample(group, 10)
        used = {r["id"] for r in random_rows}
        remaining = [r for r in group if r["id"] not in used]

        def priority(row, kind=kind):
            base = bases[row["text"]]
            return (
                len(observations(kind, base)),
                1 - SequenceMatcher(None, base, row["text"]).ratio(),
            )

        remaining.sort(key=priority, reverse=True)
        targeted = []
        selected_bases = {canonical(bases[r["text"]]) for r in random_rows}
        for row in remaining:
            base_key = canonical(bases[row["text"]])
            if base_key not in selected_bases:
                targeted.append(row)
                selected_bases.add(base_key)
            if len(targeted) == 10:
                break
        for row in remaining:
            if len(targeted) == 10:
                break
            if row not in targeted:
                targeted.append(row)
        for selection, selected in [("Ngẫu nhiên", random_rows), ("Có chủ đích", targeted)]:
            for row in selected:
                base = bases[row["text"]]
                notes = observations(kind, base)
                if row["text"] != base:
                    notes.append("Đã biến đổi. Kiểm tra còn đọc hiểu được và giữ nghĩa gốc.")
                if canonical(row["text"]) in seed_texts:
                    notes.append(
                        "Trùng bộ 30 câu sau chuẩn hóa dấu/chữ/punctuation. Tránh"
                        " coi là holdout độc lập."
                    )
                sample.append(
                    [
                        row["id"],
                        kind,
                        "toxic" if row["toxic"] else "clean",
                        row["text"],
                        "",
                        "",
                        "",
                        "",
                        base,
                        selection,
                        base_counts[canonical(base)],
                        " ".join(notes),
                    ]
                )
    assert len(sample) == 240 and len({r[0] for r in sample}) == 240
    assert set(Counter(r[1] for r in sample).values()) == {20}

    template_rows = []
    for label, pools in [("toxic", module["TOXIC"]), ("clean", module["CLEAN"])]:
        for kind, parts in pools.items():
            for part_no, choices in enumerate(parts, 1):
                for choice_no, text in enumerate(choices, 1):
                    notes = observations(kind, text)
                    template_rows.append(
                        [
                            f"{kind}-p{part_no}-{choice_no:02d}",
                            kind,
                            label,
                            part_no,
                            text or "(vế rỗng)",
                            "Cần xem" if notes else "Chưa thấy lỗi riêng",
                            " ".join(notes)
                            or "Hợp lý khi xét riêng. Vẫn cần đọc câu ghép và biến thể.",
                            "",
                            "",
                        ]
                    )
    for pool_name in ["GROUPS", "EMOJI", "TEEN"]:
        for i, value in enumerate(module[pool_name], 1):
            text = " → ".join(value) if isinstance(value, tuple) else value
            note = {
                "GROUPS": "Chốt định nghĩa đặc điểm nhóm và mapping category.",
                "EMOJI": "Gắn ngẫu nhiên có thể làm câu nghiêm trọng thiếu tự nhiên.",
                "TEEN": (
                    "Thay chuỗi không theo ranh giới từ. Kiểm tra vị trí thay và nghĩa sau thay."
                ),
            }[pool_name]
            template_rows.append(
                [f"{pool_name}-{i:02d}", pool_name, "n.a.", 0, text, "Cần xem", note, "", ""]
            )
    for i, value in enumerate(["đẹp", "ngon", "xịn", "mê ly"], 1):
        template_rows.append(
            [
                f"ADJECTIVE-{i:02d}",
                "ADJECTIVE",
                "clean",
                0,
                value,
                "Cần sửa cách ghép",
                "Không phải tính từ nào cũng tự nhiên với view, buffet, chill, "
                "phòng. Tách pool theo mẫu.",
                "",
                "",
            ]
        )

    headings = [
        "ID",
        "Nhóm",
        "Nhãn gốc",
        "Câu cần duyệt",
        "Nhãn duyệt",
        "Quyết định",
        "Câu sửa",
        "Lý do duyệt",
        "Câu trước biến đổi",
        "Cách chọn",
        "Số biến thể cùng câu gốc",
        "Gợi ý cần xem",
    ]
    template_headings = [
        "ID mẫu",
        "Nhóm",
        "Nhãn kế thừa",
        "Vế",
        "Mẫu gốc",
        "Nhận xét sơ bộ",
        "Lý do / đề xuất",
        "Quyết định duyệt",
        "Ghi chú / mẫu sửa",
    ]
    for name, header, data in [
        ("review_240.csv", headings, sample),
        ("template_audit.csv", template_headings, template_rows),
    ]:
        with (OUT / name).open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(data)
    stats = {
        "rows": len(rows),
        "classes": dict(Counter("toxic" if r["toxic"] else "clean" for r in rows)),
        "kinds": dict(Counter(r["kind"] for r in rows)),
        "distinct_pre_augmentation_sentences": len(base_counts),
        "largest_base_family": max(base_counts.values()),
        "template_entries": len(template_rows),
        "sample_rows": len(sample),
        "generator_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "candidate_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
        "seed": module["SEED"],
    }
    payload = {
        "stats": stats,
        "headings": headings,
        "sample": sample,
        "template_headings": template_headings,
        "templates": template_rows,
        "rules": RULES,
    }
    (OUT / "review_data.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), "utf-8"
    )
    report = f"""# Rà soát chất lượng bộ eval kiểm duyệt — 10/11/2026

Đây là candidate chưa được duyệt. Không thay generator, nhãn gốc hoặc runner. Không gọi API.

## Đã kiểm tra

- 3.000 câu, 1.500 toxic + 1.500 clean; không trùng chuỗi nguyên văn.
- Chỉ có **{len(base_counts)} câu ghép trước biến đổi** (chuẩn hóa dấu/chữ/punctuation). Một câu
gốc có tới **{max(base_counts.values())} biến thể**. Đây không phải 3.000 tình huống độc lập.
- Rà toàn bộ {len(template_rows)} mục gồm các vế câu, nhóm đối tượng, emoji, phép thay teencode
và 4 tính từ.
- Mẫu duyệt 240 câu: đúng 20 mỗi nhóm, trong đó 10 ngẫu nhiên và 10 có chủ đích. Cột đề xuất
không phải quyết định duyệt của con người.

## Phát hiện và sửa đề xuất

1. **Nhãn mơ hồ:** mẫu sexual “tối nay đi với anh, trả tiền hậu hĩnh” chưa đủ ngữ cảnh. Cách ly
hoặc viết lại trước khi chốt toxic. Mẫu “khoe body… chơi cho” cũng cần thống nhất cách hiểu.
2. **Ghép tính từ:** cùng pool đẹp/ngon/xịn/mê ly áp cho mọi mẫu, dẫn đến “view ngon”, “đẹp
đẹp”, “chill ngon”. Tách tính từ phù hợp từng mẫu. Các vế đuôi ở slang/neutral/safety cũng có
thể lệch ngữ cảnh.
3. **Phân nhóm:** threat/violence chồng lấn; sexual có thể đồng thời harassment. Chốt nhị phân
trước, mapping category riêng. “người miền Trung” cần quy tắc vùng miền rõ ràng.
4. **Biến đổi:** lặp ký tự từng vị trí có thể làm câu khó đọc; teencode dùng replace chuỗi;
emoji bất kỳ có thể không hợp ngữ cảnh. Đọc trước/sau, loại biến thể mất nghĩa.
5. **Đa dạng:** đủ chuỗi khác nhau nhưng nhiều biến thể từ ít ý gốc. Thêm ngữ cảnh/ý định mới,
câu thuật lại, phủ định, trích dẫn, phản đối hành vi và các cặp gần nhau khác nhãn.
6. **Cân bằng:** chỉ cân bằng toxic/clean; nhóm con không bằng nhau. Báo cáo cả theo nhóm và
tổng, không diễn giải accuracy của bộ 50/50 như tỷ lệ lỗi thực tế.
7. **Chống rò rỉ:** nếu dùng train/dev/test, chia theo câu gốc/template, không chia ngẫu nhiên
các biến thể. Candidate còn có câu chồng với vi_30, không mặc nhiên gọi là holdout mới.

## Cách duyệt

Mở Excel, sheet Duyet 240. Đọc câu, điền Nhãn duyệt và Quyết định ở các ô vàng. Khi sửa câu ghi
Câu sửa; khi sửa nhãn/loại/thảo luận ghi lý do. Sheet Mau goc ghi nhận xét từng mục. Sheet Huong
dan chứa quy tắc dự thảo và tiến độ tính từ quyết định nhập.

Quyết định: Giữ / Sửa câu / Sửa nhãn / Loại / Cần thảo luận. Nhãn: toxic / clean. Để trống nhãn
khi còn mơ hồ. Duyệt 240 câu không đồng nghĩa đã duyệt toàn bộ 3k.

Sau khi thống nhất quy tắc: sửa template → sinh candidate phiên bản mới → rà lại phần ảnh hưởng
→ nâng runner có giới hạn đồng thời/retry/lưu kết quả → chạy eval. Script hiện tại không nhập
quyết định Excel trở lại dataset tự động.

## Tái tạo và nguồn

Chạy `uv run python -m evals.moderation.prepare_quality_review` trong tripflix-ai để tái tạo
snapshot và CSV/JSON. Lệnh này ghi đè các file review được sinh; lưu bản Excel đã duyệt riêng
trước khi tái tạo. Workbook được tạo riêng từ review_data.json.

- Nguồn: evals/moderation/build_vi_3k.py; seed {module["SEED"]}.
- Generator SHA-256: {stats["generator_sha256"]}
- Candidate SHA-256: {stats["candidate_sha256"]}
"""
    (OUT / "QUALITY_REVIEW.md").write_text(report, "utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
