from mahogany.state import dedup
from mahogany.state.dedup import _title_key, is_seen, mark_seen


def test_title_key_stable():
    a = _title_key("Mahogany Lake Path Opens")
    b = _title_key("mahogany lake path opens")
    assert a == b


def test_mark_and_seen(tmp_path, monkeypatch):
    monkeypatch.setattr(dedup, "STORE_FILE", tmp_path / "seen.json")
    monkeypatch.setattr(dedup, "BOT_RUN_FILE", tmp_path / "bots.json")
    url = "https://example.com/a"
    assert not is_seen(url, "Hello Mahogany")
    mark_seen(url, "Hello Mahogany")
    assert is_seen(url, "Hello Mahogany")
