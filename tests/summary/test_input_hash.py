from dataclasses import replace

from app.services.summary.claims import Claim
from app.services.summary.input_hash import input_hash
from app.services.summary.lexicon import versions
from app.services.summary.pii import PromptComment

COMMENTS = [
    PromptComment(cid="c1", text="Phòng sạch", first_hand=True),
    PromptComment(cid="c2", text="Bữa sáng ít món", first_hand=False),
]
IDS = {"c1": ("cmt_1",), "c2": ("cmt_2",)}
CLAIMS = [Claim(id="clm_1", text="Biển xanh", source="caption")]
VERSIONS: dict[str, str | int] = {"safety": 3, "prompt": "summarize.v1"}


def test_same_input_gives_same_hash_even_if_order_and_codes_change() -> None:
    swapped = [replace(COMMENTS[1], cid="c1"), replace(COMMENTS[0], cid="c2")]
    swapped_ids = {"c1": ("cmt_2",), "c2": ("cmt_1",)}

    assert input_hash(COMMENTS, IDS, CLAIMS, VERSIONS) == input_hash(
        swapped, swapped_ids, CLAIMS, VERSIONS
    )


def test_any_change_that_alters_the_summary_changes_the_hash() -> None:
    base = input_hash(COMMENTS, IDS, CLAIMS, VERSIONS)
    edited = [replace(COMMENTS[0], text="Phòng bẩn"), COMMENTS[1]]

    assert input_hash(edited, IDS, CLAIMS, VERSIONS) != base
    assert input_hash(COMMENTS, IDS, [], VERSIONS) != base
    assert input_hash(COMMENTS, IDS, CLAIMS, VERSIONS | {"safety": 4}) != base


def test_versions_lists_every_lexicon_in_use() -> None:
    assert versions()["safety"] >= 3
    assert set(versions()) >= {"safety", "injection", "first_hand_cues", "complaint"}


def test_reply_context_changes_the_hash() -> None:
    with_context = [replace(COMMENTS[0], context=("Giá bao nhiêu?",)), COMMENTS[1]]

    assert input_hash(with_context, IDS, CLAIMS, VERSIONS) != input_hash(
        COMMENTS, IDS, CLAIMS, VERSIONS
    )
