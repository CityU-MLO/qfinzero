"""Agent benchmark: task file, scoring, episode checks and the agent loop."""

import json

import pytest

from qfinzero.bench import episodes
from qfinzero.bench.ops import OPS, parse_number
from qfinzero.bench.score import check, extract_answer, markdown_table, summarize
from qfinzero.bench.tasks import build_tasks, load_tasks


def test_shipped_task_file_matches_a_fresh_build(sample_root):
    fresh = [json.loads(t.to_json()) for t in build_tasks(sample_root)]
    shipped = [json.loads(t.to_json()) for t in load_tasks()]
    assert fresh == shipped, "regenerate with: qfz-bench build --data <sample> --out qfinzero/bench/data/tasks-v1.0.jsonl"


def test_task_set_shape():
    tasks = load_tasks()
    assert len({t.id for t in tasks}) == len(tasks)
    cats = {t.category for t in tasks}
    assert cats == {"daily", "intraday", "quotes", "options", "events", "corporate", "time_lock", "trading"}
    for t in tasks:
        assert t.op in OPS or t.episode
        if t.kind == "none":
            assert t.answer is None and t.as_of
        elif not t.episode:
            assert t.answer is not None, t.id


@pytest.mark.parametrize("text,found,value", [
    ("The close was 12.5.\nANSWER: 12.5", True, 12.5),
    ("ANSWER: null", True, None),
    ('thinking...\n**ANSWER:** "O:ACME250404C00185000"', True, "O:ACME250404C00185000"),
    ("answer: true", True, True),
    ("ANSWER: 2025-03-03", True, "2025-03-03"),
    ("no final line", False, None),
    ("ANSWER: 1\nANSWER: 2", True, 2),
])
def test_extract_answer(text, found, value):
    assert extract_answer(text) == (found, value)


@pytest.mark.parametrize("kind,expected,got,tol,ok", [
    ("number", 17.06, 17.06, 0.005, True),
    ("number", 17.06, "17.064", 0.005, True),
    ("number", 17.06, 17.07, 0.005, False),
    ("number", -12.01, "-12.01%", 0.02, True),
    ("integer", 8018657, "8,018,657", 0, True),
    ("integer", 28, 29, 0, False),
    ("none", None, None, 0, True),
    ("none", None, "not yet released", 0, True),
    ("none", None, 1.61, 0, False),
    ("number", 1.61, None, 0.005, False),
    ("bool", False, "no", 0, True),
    ("bool", True, False, 0, False),
    ("date", "2025-03-03", "The ex-date was 2025-03-03.", 0, True),
    ("text", "O:ACME250404C00185000", "acme250404c00185000", 0, True),
    ("text", "ACME", "BOLT", 0, False),
])
def test_check(kind, expected, got, tol, ok):
    assert check(kind, expected, got, tol) is ok


def test_parse_number():
    assert parse_number("256K") == 256 and parse_number("2.9%") == 2.9 and parse_number(None) is None


def test_summary_and_table():
    rows = [{"category": "a", "correct": True, "tool_calls": 2}, {"category": "a", "correct": False, "tool_calls": 4},
            {"category": "b", "correct": True, "error": None}]
    s = summarize(rows)
    assert s["overall"]["accuracy"] == pytest.approx(2 / 3, abs=1e-4)
    assert s["by_category"]["a"]["mean_tool_calls"] == 3
    assert "| **overall** | 3 | 66.7% |" in markdown_table(s)


def test_episode_checks():
    trades = [{"instrument_id": "STOCK:BOLT", "side": "BUY", "qty": 100, "ts": "2025-03-26T19:30:00+00:00"},
              {"instrument_id": "STOCK:BOLT", "side": "SELL", "qty": 100, "ts": "2025-03-26T19:40:00+00:00"},
              {"instrument_id": "OPTION:O:ACME250404C00185000", "side": "BUY", "qty": 2,
               "ts": "2025-03-24T14:00:00+00:00"}]
    positions = [{"instrument_id": "OPTION:O:ACME250404C00185000", "qty": 2}]
    checks = [{"type": "flat_by", "symbol": "BOLT", "ts": "2025-03-27T11:00:00Z"},
              {"type": "filled", "symbol": "BOLT", "side": "BUY", "qty": 100},
              {"type": "position", "symbol": "O:ACME250404C00185000", "qty": 2},
              {"type": "filled", "symbol": "O:ACME250404C00185000", "side": "BUY", "qty": 2,
               "not_before": "2025-03-24T14:01:00Z"},
              {"type": "position", "symbol": "BOLT", "qty": 0}]
    got = [c["ok"] for c in episodes.evaluate(checks, trades, positions)]
    assert got == [True, True, True, False, True]


def test_cli_build_and_score(sample_root, tmp_path, capsys):
    from qfinzero.bench.cli import main
    out = tmp_path / "t.jsonl"
    assert main(["build", "--data", str(sample_root), "--out", str(out)]) == 0
    assert len(out.read_text().splitlines()) == len(load_tasks())
    res = tmp_path / "r.jsonl"
    res.write_text(json.dumps({"id": "x", "category": "daily", "correct": True}) + "\n")
    assert main(["score", str(res)]) == 0
    assert "100.0%" in capsys.readouterr().out
