from qfinzero.server.app import _supervision_enabled
from qfinzero.server import supervisor


def test_legacy_supervise_alias(monkeypatch):
    monkeypatch.delenv("QFZ_SUPERVISE", raising=False)
    monkeypatch.setenv("QFZ_LITE_SUPERVISE", "0")
    assert _supervision_enabled() is False


def test_current_supervise_setting_wins(monkeypatch):
    monkeypatch.setenv("QFZ_SUPERVISE", "1")
    monkeypatch.setenv("QFZ_LITE_SUPERVISE", "0")
    assert _supervision_enabled() is True


def test_installed_wheel_skips_source_only_children(monkeypatch, tmp_path):
    monkeypatch.setattr(supervisor, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(supervisor, "LOG_DIR", tmp_path / "logs")

    children = supervisor._default_children()

    assert children
    assert not any(child.enabled for child in children)
