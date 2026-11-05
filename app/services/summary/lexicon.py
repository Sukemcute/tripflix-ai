"""Versioned pattern lists (app/lexicons/<name>.v<N>.yaml) compiled into one regex per group.

Patterns match text produced by vi_text.normalize_text. A file never changes once used:
new patterns go into a new version, and the version feeds input_hash.
"""

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

LEXICON_DIR = Path(__file__).resolve().parents[2] / "lexicons"
MAX_PATTERN_LENGTH = 260  # same cap Discord AutoMod puts on one regex
_FILE_NAME = re.compile(r"^(?P<name>[a-z_]+)\.v(?P<version>\d+)\.yaml$")
# shortcut: catches (x+)+ style nested quantifiers, not every ReDoS shape;
# move to RE2 if patterns ever come from moderators or users.
_NESTED_QUANTIFIER = re.compile(r"\((?:[^()\\]|\\.)*[+*]\)[+*{]")


class LexiconError(ValueError):
    pass


@dataclass(frozen=True)
class Lexicon:
    name: str
    version: int
    groups: dict[str, re.Pattern[str]]

    def matches(self, text_norm: str) -> list[str]:
        """Names of the groups whose patterns occur in text_norm."""
        return [group for group, regex in self.groups.items() if regex.search(text_norm)]


@cache
def load(name: str) -> Lexicon:
    """Latest version of a lexicon, validated against its own match/no_match samples."""
    versions = {
        int(m["version"]): path
        for path in LEXICON_DIR.glob(f"{name}.v*.yaml")
        if (m := _FILE_NAME.match(path.name)) and m["name"] == name
    }
    if not versions:
        raise LexiconError(f"no lexicon named {name!r} in {LEXICON_DIR}")
    return parse(versions[max(versions)])


def read_versions() -> dict[str, int]:
    """Version in use of every lexicon; feeds input_hash so a new version re-summarizes."""
    names = {m["name"] for p in LEXICON_DIR.glob("*.yaml") if (m := _FILE_NAME.match(p.name))}
    return {name: load(name).version for name in sorted(names)}


def parse(path: Path) -> Lexicon:
    m = _FILE_NAME.match(path.name)
    if not m:
        raise LexiconError(f"{path.name}: file name must be <name>.v<N>.yaml")
    data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("name") != m["name"]:
        raise LexiconError(f"{path.name}: 'name' must be {m['name']!r}")
    if data.get("version") != int(m["version"]):
        raise LexiconError(f"{path.name}: 'version' must be {int(m['version'])}")
    raw_groups = data.get("groups")
    if not isinstance(raw_groups, dict) or not raw_groups:
        raise LexiconError(f"{path.name}: 'groups' must be a non-empty mapping")

    groups = {str(g): _compile_group(f"{path.name}:{g}", spec) for g, spec in raw_groups.items()}
    return Lexicon(name=m["name"], version=data["version"], groups=groups)


def _compile_group(where: str, spec: Any) -> re.Pattern[str]:
    if not isinstance(spec, dict):
        raise LexiconError(f"{where}: group must have patterns, match, no_match")
    patterns = _strings(where, spec, "patterns")
    samples_match = _strings(where, spec, "match")
    samples_no_match = spec.get("no_match", [])
    for pattern in patterns:
        if len(pattern) > MAX_PATTERN_LENGTH:
            raise LexiconError(f"{where}: pattern longer than {MAX_PATTERN_LENGTH}: {pattern!r}")
        if _NESTED_QUANTIFIER.search(pattern):
            raise LexiconError(f"{where}: nested quantifier can hang the regex: {pattern!r}")
    try:
        regex = re.compile(r"\b(?:" + "|".join(patterns) + r")\b", re.ASCII)
    except re.error as e:
        raise LexiconError(f"{where}: invalid regex: {e}") from e

    for sample in samples_match:
        if not regex.search(sample):
            raise LexiconError(f"{where}: sample should match but does not: {sample!r}")
    for sample in samples_no_match:
        if regex.search(str(sample)):
            raise LexiconError(f"{where}: sample should not match but does: {sample!r}")
    return regex


def _strings(where: str, spec: dict[str, Any], key: str) -> list[str]:
    values = spec.get(key)
    # YAML turns unquoted no/yes/on into booleans; insist on real strings.
    if not isinstance(values, list) or not values or not all(isinstance(v, str) for v in values):
        raise LexiconError(f"{where}: '{key}' must be a non-empty list of quoted strings")
    return values
