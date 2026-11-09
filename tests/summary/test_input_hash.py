from dataclasses import replace

from app.services.summary.claims import Claim
from app.services.summary.input_hash import compute_input_hash
from app.services.summary.lexicon import read_versions
from app.services.summary.pii import PromptComment
from app.services.summary.schemas import SafetyWarning, SummarySafety

COMMENTS = [
    PromptComment(cid="c1", text="Phòng sạch", is_first_hand=True),
    PromptComment(cid="c2", text="Bữa sáng ít món", is_first_hand=False),
]
IDS = {"c1": ("cmt_1",), "c2": ("cmt_2",)}
CLAIMS = [Claim(id="clm_1", text="Biển xanh", source="caption")]
VERSIONS: dict[str, str | int] = {"safety": 3, "prompt": "summarize.v1"}


def test_same_input_gives_same_hash_even_if_order_and_codes_change() -> None:
    swapped = [replace(COMMENTS[1], cid="c1"), replace(COMMENTS[0], cid="c2")]
    swapped_ids = {"c1": ("cmt_2",), "c2": ("cmt_1",)}

    assert compute_input_hash(COMMENTS, IDS, CLAIMS, VERSIONS) == compute_input_hash(
        swapped, swapped_ids, CLAIMS, VERSIONS
    )


def test_any_change_that_alters_the_summary_changes_the_hash() -> None:
    base = compute_input_hash(COMMENTS, IDS, CLAIMS, VERSIONS)
    edited = [replace(COMMENTS[0], text="Phòng bẩn"), COMMENTS[1]]

    assert compute_input_hash(edited, IDS, CLAIMS, VERSIONS) != base
    assert compute_input_hash(COMMENTS, IDS, [], VERSIONS) != base
    assert compute_input_hash(COMMENTS, IDS, CLAIMS, VERSIONS | {"safety": 4}) != base


def test_versions_lists_every_lexicon_in_use() -> None:
    assert read_versions()["safety"] >= 3
    assert set(read_versions()) >= {"safety", "injection", "first_hand_cues", "complaint"}


def test_safety_warnings_change_the_hash_and_none_keeps_the_old_hash() -> None:
    base = compute_input_hash(COMMENTS, IDS, CLAIMS, VERSIONS)
    warning = SafetyWarning(categories=["food_poisoning"], comment_ids=["cmt_9"])

    assert compute_input_hash(COMMENTS, IDS, CLAIMS, VERSIONS, SummarySafety(warnings=[])) == base
    public = compute_input_hash(COMMENTS, IDS, CLAIMS, VERSIONS, SummarySafety(warnings=[warning]))
    pending = SummarySafety(warnings=[], pending_warnings=[warning])
    assert public != base
    assert compute_input_hash(COMMENTS, IDS, CLAIMS, VERSIONS, pending) not in (base, public)


def test_reply_context_changes_the_hash() -> None:
    with_context = [replace(COMMENTS[0], context=("Giá bao nhiêu?",)), COMMENTS[1]]

    assert compute_input_hash(with_context, IDS, CLAIMS, VERSIONS) != compute_input_hash(
        COMMENTS, IDS, CLAIMS, VERSIONS
    )
