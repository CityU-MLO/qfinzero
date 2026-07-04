"""Unit tests for qfinzero.admin — the data-admin control plane.

Pure/injected where possible: the config store writes to a tmp file, scans use an
injected lister / no-credential paths (no network), and the scheduler is exercised
in dry-run so no real crontab is touched.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """A config_store bound to a throwaway JSON file."""
    monkeypatch.setenv("QFZ_CONFIG_FILE", str(tmp_path / "qfz.config.json"))
    # env creds must not leak defaults into assertions
    for k in ("POLYGON_S3_ACCESS_KEY_ID", "POLYGON_S3_SECRET_ACCESS_KEY",
              "MASSIVE_REST_API_KEY", "POLYGON_API_KEY", "TUSHARE_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    from qfinzero.admin import config_store
    importlib.reload(config_store)
    return config_store


# ── config_store ────────────────────────────────────────────────────────────
def test_secret_masked_and_preserved(store):
    store.update({"massive": {"s3_secret_access_key": "abcd1234SECRET"}})
    masked = store.masked()["massive"]["s3_secret_access_key"]
    assert masked == "••••CRET"
    # posting the masked value back must NOT overwrite the stored secret
    store.update({"massive": {"s3_secret_access_key": masked}})
    assert store.massive_s3()["secret_access_key"] == "abcd1234SECRET"


def test_blank_secret_keeps_existing(store):
    store.update({"tushare": {"token": "tok-123456"}})
    store.update({"tushare": {"token": ""}})
    assert store.tushare_token() == "tok-123456"


def test_non_secret_updates_and_apply_to_env(store, monkeypatch):
    store.update({"dirs": {"raw_massive": "/x/massive"},
                  "massive": {"s3_access_key_id": "AKID"}})
    assert store.dirs()["raw_massive"] == "/x/massive"
    store.apply_to_env()
    import os
    assert os.environ["RAW_MASSIVE_DIR"] == "/x/massive"
    assert os.environ["POLYGON_S3_ACCESS_KEY_ID"] == "AKID"


def test_config_file_is_owner_only(store):
    store.update({"tushare": {"token": "t"}})
    import os
    import stat
    mode = stat.S_IMODE(os.stat(store.config_path()).st_mode)
    assert mode == 0o600


# ── scan (injected / no-network) ────────────────────────────────────────────
def test_scan_massive_s3_flags_required(store):
    from qfinzero.admin import scan
    res = scan.scan_massive_s3(
        s3={"access_key_id": "a", "secret_access_key": "b", "bucket": "flatfiles"},
        lister=lambda s3: ["us_stocks_sip", "us_options_opra", "global_crypto"],
    )
    assert res["ok"] and res["count"] == 3 and res["missing_required"] == []
    assert {d["name"] for d in res["datasets"] if d["required"]} == {"us_stocks_sip", "us_options_opra"}


def test_scan_massive_s3_missing_required(store):
    from qfinzero.admin import scan
    res = scan.scan_massive_s3(s3={"access_key_id": "a", "secret_access_key": "b"},
                               lister=lambda s3: ["global_crypto"])
    assert set(res["missing_required"]) == {"us_stocks_sip", "us_options_opra"}


def test_scan_no_credentials(store):
    from qfinzero.admin import scan
    assert scan.scan_massive_s3(s3={"access_key_id": "", "secret_access_key": ""})["ok"] is False
    assert scan.scan_massive_rest(rest={"api_key": "", "base_url": "x"})["ok"] is False
    assert scan.scan_tushare(token="")["ok"] is False
    assert scan.scan("bogus")["ok"] is False


# ── scheduler (dry-run only) ────────────────────────────────────────────────
def test_scheduler_render_only_enabled(store):
    from qfinzero.admin import scheduler
    store.update({"schedule": {"prices": {"enabled": True, "cron": "30 17 * * 1-5"},
                               "news": {"enabled": False, "cron": "0 6 * * *"}}})
    block = scheduler.render()
    assert "30 17 * * 1-5" in block
    assert "0 6 * * *" not in block  # disabled group excluded
    assert scheduler.MANAGED_BEGIN in block and scheduler.MANAGED_END in block


def test_scheduler_strip_is_idempotent(store):
    from qfinzero.admin import scheduler
    text = f"# mine\n{scheduler.MANAGED_BEGIN}\n1 2 3 4 5 x\n{scheduler.MANAGED_END}\n# other\n"
    kept = scheduler._strip_managed(text)
    assert "# mine" in kept and "# other" in kept
    assert all(scheduler.MANAGED_BEGIN not in ln for ln in kept)


def test_scheduler_plan_shape(store):
    from qfinzero.admin import scheduler
    store.update({"schedule": {"prices": {"enabled": True, "cron": "0 1 * * *"}}})
    p = {i["group"]: i for i in scheduler.plan()}
    assert p["prices"]["enabled"] is True
    assert "qfinzero.pipeline.cli" in p["prices"]["command"]


# ── acquire ─────────────────────────────────────────────────────────────────
def test_run_stream_captures_and_reports_exit(store):
    from qfinzero.admin import acquire
    out = []
    res = acquire.run_stream(["bash", "-c", "echo a; echo b; exit 2"], on_line=out.append)
    assert res["lines"] == ["a", "b"] and res["returncode"] == 2 and res["ok"] is False


def test_acquire_unknown_and_missing_binary(store):
    from qfinzero.admin import acquire
    assert acquire.acquire("nope")["ok"] is False
    assert acquire.run_stream(["/definitely/not/here"])["returncode"] == 127


def test_acquire_missing_config(store):
    from qfinzero.admin import acquire
    # us_prices needs S3 creds; with none set it should refuse before launching.
    res = acquire.acquire("us_prices", dry_run=True)
    assert res["ok"] is False and "missing config" in res["error"]


# ── setup-state ─────────────────────────────────────────────────────────────
def test_setup_state_shape(store, monkeypatch):
    from qfinzero.admin import setup
    st = setup.state()
    assert set(st) >= {"configured", "initialized", "show_wizard", "steps"}
    assert {s["id"] for s in st["steps"]} == {"massive", "tushare", "raw", "storage"}
    assert isinstance(st["show_wizard"], bool)
