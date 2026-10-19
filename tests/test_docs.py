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


def test_api_reference_is_current():
    """docs/api/reference.json (the hub's API and MCP reference) matches the services."""
    r = subprocess.run([sys.executable, "-m", "qfinzero.docsgen", "--check"], cwd=REPO,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_api_reference_shape():
    import json
    ref = json.loads((REPO / "docs" / "api" / "reference.json").read_text())
    assert [s["id"] for s in ref["services"]] == ["upq", "esp", "pmb"]
    for s in ref["services"]:
        ids = [e["id"] for e in s["endpoints"]]
        assert len(ids) == len(set(ids)) and s["base"].startswith("/svc/")
        for e in s["endpoints"]:
            assert e["method"] in ("GET", "POST", "PUT", "PATCH", "DELETE") and e["summary"]
    upq = {e["path"] for e in ref["services"][0]["endpoints"]}
    assert {"/stock/daily", "/dividends/query", "/future/quote"} <= upq
    assert len({t["name"] for t in ref["mcp"]}) == len(ref["mcp"]) > 40


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
