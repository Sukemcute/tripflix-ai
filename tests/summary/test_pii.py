from datetime import UTC, datetime

import pytest

from app.services.summary.filters import Candidate
from app.services.summary.pii import MASK, mask_pii, pseudonymize
from app.services.summary.selection import Selected


@pytest.mark.parametrize(
    "text",
    [
        "Liên hệ 0912345678 nhé",
        "zalo 0912 345 678",
        "gọi 0912.345.678",
        "số +84 912 345 678",
        "lễ tân 0283 8123 456",  # landline 02x
        "mail mình là ban.toi+trip@gmail.com",
        "CCCD 001095012345 bị giữ ở lễ tân",
    ],
)
def test_personal_data_is_masked(text: str) -> None:
    masked = mask_pii(text)

    assert MASK in masked
    assert not any(ch.isdigit() for ch in masked.split(MASK)[-1][:3])


@pytest.mark.parametrize(
    "text",
    [
        "Giá 1.500.000đ một đêm",
        "Ở 3 đêm, 14/05/2022 tới 17/05/2022",
        "Phòng 1205 tầng 12",
        "Cách sân bay 25 km, mất 30 phút",
    ],
)
def test_prices_dates_and_room_numbers_stay(text: str) -> None:
    assert mask_pii(text) == text


def test_pseudonymize_swaps_real_ids_for_temporary_codes() -> None:
    cand = Candidate(
        author_id="user_real_42",
        comment_ids=("cmt_9", "cmt_11"),
        text="Phòng đẹp, gọi 0912345678 để đặt",
        text_norm="",
        like_count=0,
        created_at=datetime(2026, 11, 1, tzinfo=UTC),
        is_suspect=False,
    )

    prompt, codes = pseudonymize(
        [Selected(candidate=cand, tier=3, is_first_hand=False, tokens=10, text=cand.text)]
    )

    assert prompt[0].cid == "c1"
    assert prompt[0].text == f"Phòng đẹp, gọi {MASK} để đặt"
    assert "user_real_42" not in repr(prompt)
    assert codes == {"c1": ("cmt_9", "cmt_11")}


def test_reply_context_is_masked_too() -> None:
    cand = Candidate(
        author_id="u1",
        comment_ids=("c1",),
        text="Gọi số đó rồi, không ai nghe",
        text_norm="goi so do roi khong ai nghe",
        like_count=0,
        created_at=datetime(2026, 11, 5, tzinfo=UTC),
        is_suspect=False,
        contexts=("Ai cần phòng gọi 0912 345 678",),
    )
    [prompt], _ = pseudonymize(
        [Selected(candidate=cand, tier=3, is_first_hand=False, tokens=10, text=cand.text)]
    )

    assert prompt.context == ("Ai cần phòng gọi [đã che]",)


def test_the_shortened_text_is_what_gets_masked_and_sent() -> None:
    cand = Candidate(
        author_id="u1",
        comment_ids=("c1",),
        text="Câu dài bị bỏ. Gọi 0912 345 678 bị ngộ độc.",
        text_norm="",
        like_count=0,
        created_at=datetime(2026, 11, 5, tzinfo=UTC),
        is_suspect=False,
    )
    sent = "… Gọi 0912 345 678 bị ngộ độc."
    [prompt], _ = pseudonymize(
        [Selected(candidate=cand, tier=2, is_first_hand=False, tokens=10, text=sent)]
    )

    assert prompt.text == "… Gọi [đã che] bị ngộ độc."


@pytest.mark.parametrize(
    ("text", "masked"),
    [
        ("Cảm ơn bạn Quế ở bộ phận đặt phòng", "Cảm ơn bạn [tên] ở bộ phận đặt phòng"),
        ("đặc biệt Anh Diệp Trọng Tín rất dễ mến", "đặc biệt Anh [tên] rất dễ mến"),
        ("lễ tân Hà dễ thương", "lễ tân [tên] dễ thương"),
        ("a Thương đẹp trai", "a [tên] đẹp trai"),  # teencode cue
        ("bạn Nguyễn Văn Đình Tuân cười hiền", "bạn [tên] cười hiền"),
        ("Lê Thị Hiền phụ trách đặt tour", "[tên] phụ trách đặt tour"),
    ],
)
def test_person_names_after_a_cue_or_with_thi_van_are_masked(text: str, masked: str) -> None:
    assert mask_pii(text) == masked


@pytest.mark.parametrize(
    "text",
    [
        "Bãi Ông Lang đẹp, đi Cô Tô, về Bà Rịa Vũng Tàu",  # places that start with a kinship word
        "Mình ở Hồ Tràm, gần Lý Sơn",  # surnames that start places
        "khách sạn trên đường Nguyễn Văn Linh",  # a street, not a person
        "cô chủ dễ thương, anh trai mình đi cùng",  # lowercase word after the cue
        "nhân viên Hành lý nhiệt tình, A Di Đà Phật",
    ],
)
def test_places_streets_and_common_words_keep_their_text(text: str) -> None:
    assert mask_pii(text) == text
