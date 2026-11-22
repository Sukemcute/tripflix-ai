"""Download the comment classifier bundle from this repo's GitHub Release and verify it.

The bundle is not in git (about 100 MB, DeepResearch_Luu_tru_model_phan_loai_khi_deploy.md).
Needs the GitHub CLI logged in with access to the private repo (locally `gh auth login`;
in CI the job's GITHUB_TOKEN). Without the bundle the worker runs on rules.

    uv run python -m scripts.fetch_classifier --tag comment-classifier-v1
"""

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.services.summary.comment_classifier import BUNDLE_FILES, MANIFEST_FILE, verify_bundle
from scripts.package_classifier import OUT


def fetch(tag: str, out: Path) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        names = [*BUNDLE_FILES, MANIFEST_FILE]
        patterns = [arg for name in names for arg in ("--pattern", name)]
        subprocess.run(["gh", "release", "download", tag, "--dir", tmp, *patterns], check=True)
        manifest = verify_bundle(Path(tmp))  # nothing replaces a working bundle unless it checks
        if manifest["version"] != tag:
            raise ValueError(f"release {tag} holds bundle {manifest['version']}")
        out.mkdir(parents=True, exist_ok=True)
        for name in names:
            shutil.copyfile(Path(tmp) / name, out / name)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True, help="release tag = bundle version")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    manifest = fetch(args.tag, args.out)
    print(f"{manifest['version']} from run {manifest['source_run']} -> {args.out}")


if __name__ == "__main__":
    main()
