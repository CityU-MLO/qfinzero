"""Documentation that is generated from code, or points at code, stays in sync."""

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_mcp_reference_is_current():
    r = subprocess.run([sys.executable, "scripts/gen_mcp_reference.py", "--check"], cwd=REPO,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_relative_links_resolve():
    """Every relative markdown link in README and docs/en|cn points at a file."""
    files = [REPO / "README.md", REPO / "CHANGELOG.md", *(REPO / "docs" / "en").glob("*.md"),
             *(REPO / "docs" / "cn").glob("*.md")]
    broken = []
    for f in files:
        for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", f.read_text()):
            if re.match(r"[a-z]+:", target):
                continue
            if not (f.parent / target).exists():
                broken.append(f"{f.relative_to(REPO)} -> {target}")
    assert not broken, "\n".join(broken)


def test_doc_hub_index_points_at_files():
    import json
    index = json.loads((REPO / "docs" / "index.json").read_text())
    slugs = [p["slug"] for s in index["sections"] for p in s["pages"]]
    assert len(slugs) == len(set(slugs))
    for s in index["sections"]:
        assert set(s["title"]) == {"en", "zh"}
        for p in s["pages"]:
            assert set(p["title"]) == {"en", "zh"}
            for lang in ("en", "zh"):
                if lang in p:
                    assert (REPO / p[lang]).is_file(), f"{p['slug']}: {p[lang]} missing"
