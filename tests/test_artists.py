"""Unit tests for src/artists.py."""

from src.artists import split_artist_names


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


def test_split_artist_names_empty():
    assert split_artist_names(None) == []
    assert split_artist_names("") == []
    assert split_artist_names("  ,  ") == []
