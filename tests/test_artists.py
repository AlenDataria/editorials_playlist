"""Unit tests for src/artists.py — name normalization, splitting, resolution.

No DB and no network: `ArtistResolver` is built with a dummy engine and its
lookup maps are populated directly.
"""

from src.artists import ArtistResolver, normalize, split_artist_names


def test_normalize_lowercases_and_strips():
    assert normalize("  Marco Mengoni ") == "marco mengoni"
    assert normalize(None) == ""


def test_split_artist_names_single_and_multi():
    assert split_artist_names("Bresh") == ["Bresh"]
    assert split_artist_names("Angelina Mango, Marco Mengoni") == [
        "Angelina Mango",
        "Marco Mengoni",
    ]
    assert split_artist_names(" Samurai Jay ,Vito Salamanca ") == [
        "Samurai Jay",
        "Vito Salamanca",
    ]
    assert split_artist_names(None) == []
    assert split_artist_names("") == []


def _resolver() -> ArtistResolver:
    return ArtistResolver.__new__(ArtistResolver)  # skip __init__ (no engine)


def test_resolve_prefers_per_track_apify_credits():
    r = _resolver()
    r._db_map = {"marco mengoni": "db-wrong"}
    r._apify_by_track = {"t1": {"marco mengoni": "apify-right"}}
    r._apify_name_map = {}
    assert r.resolve("t1", "Marco Mengoni") == "apify-right"


def test_resolve_falls_back_to_our_data():
    r = _resolver()
    r._db_map = {"bresh": "artist-bresh"}
    r._apify_by_track = {}
    r._apify_name_map = {}
    assert r.resolve("whatever", "Bresh") == "artist-bresh"


def test_resolve_loose_match_within_track_credits():
    r = _resolver()
    r._db_map = {}
    r._apify_by_track = {"t2": {"lil pump feat. x": "apify-id"}}
    r._apify_name_map = {}
    assert r.resolve("t2", "Lil Pump") == "apify-id"


def test_resolve_returns_none_when_unknown():
    r = _resolver()
    r._db_map = {}
    r._apify_by_track = {}
    r._apify_name_map = {}
    assert r.resolve("t3", "Nobody Known") is None
    assert r.resolve("t3", "") is None


def test_is_known_checks_both_maps():
    r = _resolver()
    r._db_map = {"a": "1"}
    r._apify_by_track = {}
    r._apify_name_map = {"b": "2"}
    assert r.is_known("A") is True
    assert r.is_known("B") is True
    assert r.is_known("c") is False
