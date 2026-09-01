"""Unit tests for src/state.py in local-file mode (no S3, no network)."""

from src.state import StateStore, empty_doc, open_stints


def test_open_stints_creates_nested_maps():
    doc = empty_doc()
    m = open_stints(doc, "pl1")
    m["trk1"] = {"start": "2026-09-01", "last_seen": "2026-09-01"}
    assert doc["playlists"]["pl1"]["trk1"]["start"] == "2026-09-01"
    # same call returns the same dict
    assert open_stints(doc, "pl1") is m


def test_load_returns_none_when_absent(tmp_path, monkeypatch):
    monkeypatch.delenv("S3_BUCKET_NAME", raising=False)
    monkeypatch.setenv("EDITORIAL_STATE_LOCAL_PATH", str(tmp_path / "state.json"))
    assert StateStore().load() is None


def test_save_then_load_round_trips(tmp_path, monkeypatch):
    monkeypatch.delenv("S3_BUCKET_NAME", raising=False)
    monkeypatch.setenv("EDITORIAL_STATE_LOCAL_PATH", str(tmp_path / "state.json"))

    doc = empty_doc()
    open_stints(doc, "pl1")["trk1"] = {"start": "2026-08-15", "last_seen": "2026-09-01"}
    StateStore().save(doc)

    loaded = StateStore().load()
    assert loaded["playlists"]["pl1"]["trk1"] == {
        "start": "2026-08-15",
        "last_seen": "2026-09-01",
    }
    assert "updated_at" in loaded  # stamped on save
