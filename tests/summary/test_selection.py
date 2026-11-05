from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.services.summary.filters import Candidate
from app.services.summary.selection import (
    GAP,
    MIN_PEOPLE,
    MIN_SHARE_TOKENS,
    estimate_tokens,
    fit_to_share,
    select_comments,
    summary_status,
)
from app.services.summary.vi_text import to_norm

NOW = datetime(2026, 11, 5, tzinfo=UTC)
FIRST_HAND = "Mình ở đây tháng trước, phòng sạch, nhân viên dễ thương"
COMPLAINT = "Phòng bẩn, đồ ăn dở tệ, nhân viên thô lỗ, thất vọng"
NEUTRAL = "Resort nằm gần biển, nhìn khá rộng"


def cand(i: int, text: str, likes: int = 0, days: float = 1, suspect: bool = False) -> Candidate:
    return Candidate(
        author_id=f"u{i}",
        comment_ids=(f"c{i}",),
        text=text,
        text_norm=to_norm(text),
        like_count=likes,
        created_at=NOW - timedelta(days=days),
        suspect=suspect,
    )


def test_tiers_order_first_hand_then_complaint_then_rest() -> None:
    picked = select_comments([cand(1, NEUTRAL), cand(2, COMPLAINT), cand(3, FIRST_HAND)], NOW)

    assert [s.candidate.author_id for s in picked.items] == ["u3", "u2", "u1"]
    assert [s.tier for s in picked.items] == [1, 2, 3]


def test_token_budget_caps_long_comments_not_a_fixed_count() -> None:
    long_text = NEUTRAL + " " + "rất rộng " * 100
    budget = estimate_tokens(long_text) * 3

    # target 1: one share is the whole budget, so this checks the total cap alone
    picked = select_comments(
        [cand(i, long_text) for i in range(10)], NOW, token_budget=budget, target_comments=1
    )

    assert len(picked.items) == 3
    assert picked.tokens <= budget
    assert picked.skipped == 7


def test_short_comments_fill_up_to_the_comment_cap() -> None:
    picked = select_comments([cand(i, NEUTRAL) for i in range(500)], NOW, max_comments=300)

    assert len(picked.items) == 300


def test_item_too_long_for_what_is_left_is_skipped_and_shorter_ones_still_fit() -> None:
    long_text = "phòng rộng " * 100  # one unpunctuated sentence: cut close to the share
    first, second = cand(1, long_text, likes=10), cand(2, long_text, likes=5)
    short = cand(3, NEUTRAL)
    # budget 100 -> share 53 (the floor): the first long one is shortened to fit,
    # the second no longer fits the 47 tokens left, the short one still does
    picked = select_comments([first, second, short], NOW, token_budget=100, target_comments=2)

    assert [s.candidate.author_id for s in picked.items] == ["u1", "u3"]
    assert picked.tokens <= 100


def test_tier3_ranks_by_likes_and_recency() -> None:
    old_plain = cand(1, NEUTRAL, likes=0, days=300)
    liked = cand(2, NEUTRAL, likes=50, days=300)
    fresh = cand(3, NEUTRAL, likes=0, days=1)

    picked = select_comments([old_plain, fresh, liked], NOW)

    assert [s.candidate.author_id for s in picked.items] == ["u2", "u3", "u1"]


def test_suspect_copies_go_last_and_are_not_counted_as_people() -> None:
    picked = select_comments([cand(1, NEUTRAL, suspect=True), cand(2, NEUTRAL)], NOW)

    assert [s.candidate.author_id for s in picked.items] == ["u2", "u1"]
    assert picked.people == 1


def test_same_input_in_any_order_gives_same_selection() -> None:
    cands = [cand(i, text) for i, text in enumerate([NEUTRAL, COMPLAINT, FIRST_HAND] * 4)]

    a = select_comments(cands, NOW)
    b = select_comments(list(reversed(cands)), NOW)

    assert [s.candidate.comment_ids for s in a.items] == [s.candidate.comment_ids for s in b.items]


def test_summary_status_gates_the_llm_call() -> None:
    enough = select_comments([cand(i, NEUTRAL) for i in range(MIN_PEOPLE)], NOW)
    too_few = select_comments([cand(i, NEUTRAL) for i in range(MIN_PEOPLE - 1)], NOW)

    assert summary_status(0, too_few) == "no_comments"
    assert summary_status(10, too_few) == "insufficient_data"
    assert summary_status(10, enough) == "ready"


def test_questions_rank_after_statements_in_their_tier() -> None:
    question = "Ở đây có cho mang chó mèo theo không ạ"
    picked = select_comments([cand(1, question, likes=50), cand(2, NEUTRAL)], NOW)

    assert [s.candidate.author_id for s in picked.items] == ["u2", "u1"]  # kept, not dropped


def test_reply_context_is_paid_from_the_same_token_budget() -> None:
    reply = replace(cand(1, NEUTRAL), contexts=("Giá phòng bao nhiêu vậy mọi người?",))

    [picked] = select_comments([reply], NOW).items

    assert picked.tokens == estimate_tokens(NEUTRAL) + estimate_tokens(reply.contexts[0])


LONG_REVIEW = (
    "Khách sạn nằm gần trung tâm, đi bộ ra chợ đêm tầm 10 phút. "
    "Mình ở đây 3 đêm cùng gia đình hồi tháng trước. "
    "Sảnh trang trí đẹp, nhiều góc chụp hình. "
    "Tối thứ hai cả nhà ăn buffet xong bị ngộ độc, phải đi viện. "
    "Hồ bơi hơi nhỏ so với hình quảng cáo. "
    "Nói chung thì cũng tạm ổn với mức giá này."
)


def test_short_comment_is_sent_whole() -> None:
    assert fit_to_share(NEUTRAL, MIN_SHARE_TOKENS) == NEUTRAL


def test_long_comment_keeps_its_most_relevant_sentences_in_order() -> None:
    """Pre-extraction (Bhaskar et al. 2023): safety first, then complaints, then the rest."""
    short = fit_to_share(LONG_REVIEW, 40)

    assert "ngộ độc" in short
    assert estimate_tokens(short) <= 40
    assert short.startswith(GAP.strip())  # dropped sentences are marked, not hidden
    assert all(part.strip() in LONG_REVIEW for part in short.split(GAP.strip()) if part.strip())


def test_one_long_sentence_is_cut_at_a_word_boundary() -> None:
    sentence = "phòng rộng " * 100

    short = fit_to_share(sentence, MIN_SHARE_TOKENS)

    assert estimate_tokens(short) <= MIN_SHARE_TOKENS
    assert short.endswith(GAP.strip())
    assert short.removesuffix(GAP.rstrip()).split()[-1] in {"phòng", "rộng"}


def test_fair_share_lets_more_voices_in_and_keeps_flags_from_the_whole_comment() -> None:
    reviews = [cand(i, LONG_REVIEW + f" Lần thứ {i}.") for i in range(40)]
    budget = estimate_tokens(LONG_REVIEW) * 10

    whole = select_comments(reviews, NOW, token_budget=budget, target_comments=1)
    shared = select_comments(reviews, NOW, token_budget=budget, target_comments=30)

    assert len(shared.items) > len(whole.items)
    # "Mình ở đây 3 đêm..." may be dropped from the text; the tier was set before that
    assert all(s.first_hand and s.tier == 1 for s in shared.items)
    assert all(s.text != s.candidate.text for s in shared.items)


def test_over_budget_pick_keeps_the_complaint_share(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stratified pick (Marozzo 2025): 30 % complaints in, about 30 % complaints out,
    even though every praise is first-hand (tier 1) and no complaint is."""
    praise = [cand(i, f"Mình ở đây tháng trước, phòng đẹp lắm số {i}") for i in range(70)]
    complaints = [cand(100 + i, f"Phòng bẩn quá trời số {i}") for i in range(30)]
    monkeypatch.setattr(
        "app.services.summary.selection.complaint_model.is_complaint",
        lambda text: text.startswith("Phòng bẩn"),
    )
    budget = sum(estimate_tokens(c.text) for c in praise[:20])  # room for about 20 of 100

    picked = select_comments([*praise, *complaints], NOW, token_budget=budget)
    share = sum(s.complaint for s in picked.items) / len(picked.items)

    assert 0.25 <= share <= 0.35
    assert all(s.tier == 1 for s in picked.items if not s.complaint)  # tier order inside


def test_everything_is_sent_when_it_fits() -> None:
    cands = [cand(i, text) for i, text in enumerate([NEUTRAL, COMPLAINT, FIRST_HAND] * 30)]

    picked = select_comments(cands, NOW)

    assert len(picked.items) == 90 and picked.skipped == 0


def test_a_question_is_never_counted_as_a_complaint() -> None:
    """The review-trained model scores many questions as complaints; questions state no view."""
    [picked] = select_comments([cand(1, "Trẻ em dưới 6 tuổi có tính tiền không ạ")], NOW).items

    assert picked.complaint is False
