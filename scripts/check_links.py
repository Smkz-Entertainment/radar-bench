"""Check local Markdown links without making network requests."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse


LINK_RE = re.compile(r"\[[^\]]+\]\(([^)\s]+)(?:\s+[^)]*)?\)")


def _markdown_paths(root: Path) -> list[Path]:
    return sorted(
        path
        for path in (list(root.glob("*.md")) + list((root / "docs").glob("*.md")) + list((root / ".github").glob("*.md")))
        if path.is_file()
    )


def check(root: Path) -> dict[str, object]:
    findings: list[dict[str, object]] = []
    checked = 0
    for source in _markdown_paths(root):
        text = source.read_text(encoding="utf-8")
        for target in LINK_RE.findall(text):
            parsed = urlparse(target)
            if parsed.scheme in {"http", "https", "mailto"}:
                if parsed.scheme in {"http", "https"} and not parsed.netloc:
                    findings.append({"path": source.relative_to(root).as_posix(), "target": target, "reason": "URL has no host"})
                continue
            checked += 1
            relative = target.split("#", 1)[0]
            if not relative:
                continue
            candidate = (source.parent / relative).resolve()
            try:
                candidate.relative_to(root.resolve())
            except ValueError:
                findings.append({"path": source.relative_to(root).as_posix(), "target": target, "reason": "link escapes repository"})
                continue
            if not candidate.exists():
                findings.append({"path": source.relative_to(root).as_posix(), "target": target, "reason": "target does not exist"})
    return {"status": "PASS" if not findings else "FAIL", "local_links_checked": checked, "findings": findings}


def main(argv: list[str] | None = None) -> int:
    arguments = argv if argv is not None else sys.argv[1:]
    root = Path(arguments[0]).resolve() if arguments else Path(__file__).resolve().parents[1]
    result = check(root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
