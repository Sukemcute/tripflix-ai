from pathlib import Path

import pytest

from app.services.summary.lexicon import LEXICON_DIR, LexiconError, load, parse
from app.services.summary.vi_text import to_norm

NAMES = ["safety", "injection", "video_reaction", "first_hand_cues", "complaint", "service_terms"]


def doc(
    version: int = 1,
    patterns: str = "['ngo doc']",
    match: str = "['bi ngo doc']",
    no_match: str = "['an ngon']",
) -> str:
    return (
        f"name: demo\nversion: {version}\ngroups:\n  g:\n"
        f"    patterns: {patterns}\n    match: {match}\n    no_match: {no_match}\n"
    )


def write(path: Path, version: int, pattern: str) -> None:
    body = doc(version=version, patterns=f"['{pattern}']", match=f"['{pattern}']", no_match="['x']")
    path.write_text(body, encoding="utf-8")


@pytest.mark.parametrize("name", NAMES)
def test_every_lexicon_loads_and_passes_its_own_samples(name: str) -> None:
    lexicon = load(name)

    assert lexicon.name == name
    assert lexicon.version >= 1
    assert lexicon.groups


def test_no_lexicon_file_is_left_out_of_the_list() -> None:
    on_disk = {path.name.split(".v")[0] for path in LEXICON_DIR.glob("*.yaml")}

    assert on_disk == set(NAMES)


def test_matches_real_comment_after_normalization() -> None:
    safety = load("safety")

    assert safety.matches(to_norm("Cả nhà bị tào tháo rượt sau buffet 😭")) == ["ngo_doc"]
    assert safety.matches(to_norm("Phòng sạch, nhân viên dễ thương")) == []


def test_latest_version_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write(tmp_path / "demo.v1.yaml", version=1, pattern="cu")
    write(tmp_path / "demo.v2.yaml", version=2, pattern="moi")
    monkeypatch.setattr("app.services.summary.lexicon.LEXICON_DIR", tmp_path)
    load.cache_clear()
    try:
        assert load("demo").version == 2
    finally:
        load.cache_clear()


@pytest.mark.parametrize(
    ("body", "error"),
    [
        (doc(version=2), "'version' must be 1"),
        (doc(patterns="['(a+)+']", match="['aa']"), "nested quantifier"),
        (doc(patterns="['(ab']"), "invalid regex"),
        (doc(patterns="[no]", match="['x']"), "quoted strings"),  # YAML reads no as False
        (doc(no_match="['ngo doc roi']"), "should not match"),
        (doc(match="['an ngon']"), "should match"),
        (doc(patterns=f"['{'a' * 261}']"), "longer than 260"),
    ],
)
def test_bad_lexicon_is_rejected_with_location(tmp_path: Path, body: str, error: str) -> None:
    path = tmp_path / "demo.v1.yaml"
    path.write_text(body, encoding="utf-8")

    with pytest.raises(LexiconError, match=error) as caught:
        parse(path)
    assert "demo.v1.yaml" in str(caught.value)
