"""Dọn phiên bản image cũ trên GHCR của repo này (workflow ghcr-cleanup).

Giữ: tag không bắt đầu bằng sha- (develop, main, tag phát hành), tag trong KEEP_TAGS (bản
server đang ghim), KEEP_RECENT bản có tag mới nhất, và mọi manifest con mà các bản giữ lại
trỏ tới (image thật, attestation của buildx), để không làm hỏng image còn giữ.
Mặc định chỉ liệt kê; DRY_RUN=false mới xoá. Bản đã xoá khôi phục được trong 30 ngày.

Biến môi trường: GITHUB_TOKEN, OWNER, PACKAGES (tên cách nhau bởi dấu cách, ví dụ
"tripflix-be/core-api"), KEEP_TAGS (tag không bao giờ xoá, cách nhau bởi dấu cách hoặc dấu phẩy),
KEEP_RECENT (mặc định 5), DRY_RUN (mặc định true).
"""

import base64
import json
import os
import urllib.parse
import urllib.request

TOKEN = os.environ["GITHUB_TOKEN"]
OWNER = os.environ["OWNER"].lower()
PACKAGES = os.environ["PACKAGES"].split()
KEEP_TAGS = set(os.environ.get("KEEP_TAGS", "").replace(",", " ").split())
KEEP_RECENT = int(os.environ.get("KEEP_RECENT", "5"))
DRY_RUN = os.environ.get("DRY_RUN", "true") != "false"
ACCEPT = ", ".join(
    [
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ]
)


def github(method, path):
    req = urllib.request.Request(f"https://api.github.com/{path}", method=method)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Accept", "application/vnd.github+json")
    with urllib.request.urlopen(req) as res:
        body = res.read()
        return json.loads(body) if body else None


def versions_path(package):
    return f"users/{OWNER}/packages/container/{urllib.parse.quote(package, safe='')}/versions"


def list_versions(package):
    versions, page = [], 1
    while True:
        batch = github("GET", f"{versions_path(package)}?per_page=100&page={page}")
        versions += batch
        if len(batch) < 100:
            return versions
        page += 1


def registry_token(repo):
    url = f"https://ghcr.io/token?scope=repository:{repo}:pull&service=ghcr.io"
    req = urllib.request.Request(url)
    basic = base64.b64encode(f"{OWNER}:{TOKEN}".encode()).decode()
    req.add_header("Authorization", f"Basic {basic}")
    with urllib.request.urlopen(req) as res:
        return json.load(res)["token"]


def child_digests(repo, digest, bearer):
    req = urllib.request.Request(f"https://ghcr.io/v2/{repo}/manifests/{digest}")
    req.add_header("Authorization", f"Bearer {bearer}")
    req.add_header("Accept", ACCEPT)
    with urllib.request.urlopen(req) as res:
        return [c["digest"] for c in json.load(res).get("manifests", [])]


def tags_of(version):
    return version["metadata"]["container"]["tags"]


def is_protected(version):
    return any(not tag.startswith("sha-") or tag in KEEP_TAGS for tag in tags_of(version))


for package in PACKAGES:
    repo = f"{OWNER}/{package}"
    versions = list_versions(package)
    bearer = registry_token(repo)
    tagged = [v for v in versions if tags_of(v)]
    tagged.sort(key=lambda v: v["created_at"], reverse=True)
    roots = [v for v in tagged if is_protected(v)] + tagged[:KEEP_RECENT]
    keep = set()
    for v in roots:
        keep.add(v["name"])
        keep.update(child_digests(repo, v["name"], bearer))
    stale = [v for v in versions if v["name"] not in keep]
    kept_tags = sorted({t for v in versions if v["name"] in keep for t in tags_of(v)})
    action = "sẽ xoá" if DRY_RUN else "xoá"
    print(f"{package}: giữ {len(versions) - len(stale)}, {action} {len(stale)} / {len(versions)}")
    print(f"  tag giữ lại: {', '.join(kept_tags)}")
    if DRY_RUN:
        continue
    for v in stale:
        github("DELETE", f"{versions_path(package)}/{v['id']}")
    print(f"  đã xoá {len(stale)} phiên bản")

if DRY_RUN:
    print("Chế độ thử: chưa xoá gì. Đặt biến repo GHCR_CLEANUP_ENABLED=true để lịch hằng tuần xoá.")
