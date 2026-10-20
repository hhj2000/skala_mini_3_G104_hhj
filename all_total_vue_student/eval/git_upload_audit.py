"""Read-only GitHub size/secret audit. Does not stage, commit, push or print secrets."""

import json
from pathlib import Path
import re
import subprocess

root = Path(
    subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()
)


def git(*args, input=None):
    return subprocess.check_output(["git", "-C", str(root), *args], input=input)


files = sorted(
    set(
        p.decode()
        for p in git(
            "ls-files", "--cached", "--others", "--exclude-standard", "-z"
        ).split(b"\0")
        if p
    )
)
rows = [
    {"path": name, "bytes": (root / name).stat().st_size}
    for name in files
    if (root / name).is_file()
]
secret_paths = []
for row in rows:
    path = root / row["path"]
    if row["bytes"] > 5 * 1024 * 1024:
        continue
    data = path.read_bytes()
    # Values never leave the process; .env.example placeholders are shorter.
    if re.search(rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{30,}", data):
        secret_paths.append(row["path"])
objects = git("rev-list", "--objects", "--all")
history = (
    git("cat-file", "--batch-check=%(objecttype) %(objectsize) %(rest)", input=objects)
    .decode()
    .splitlines()
    if objects
    else []
)
large_history = []
for line in history:
    kind, size, *name = line.split(" ", 2)
    if kind == "blob" and int(size) > 100 * 1024 * 1024:
        large_history.append({"path": name[0] if name else "", "bytes": int(size)})
report = {
    "repository": str(root),
    "branch": git("branch", "--show-current").decode().strip(),
    "candidate_count": len(rows),
    "candidate_bytes": sum(r["bytes"] for r in rows),
    "largest_files": sorted(rows, key=lambda r: r["bytes"], reverse=True)[:8],
    "over_50_mib": [r for r in rows if r["bytes"] > 50 * 1024 * 1024],
    "over_100_mib": [r for r in rows if r["bytes"] > 100 * 1024 * 1024],
    "history_over_100_mib": large_history,
    "possible_key_paths": secret_paths,
    "note": "작업 파일 합계입니다. 압축된 push 크기나 GitHub 접근 권한을 보장하지 않습니다.",
}
print(json.dumps(report, ensure_ascii=False, indent=2))
if report["over_100_mib"] or report["history_over_100_mib"] or secret_paths:
    raise SystemExit(1)
