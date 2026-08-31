from pathlib import Path

import pytest

from src.embed import (
    EmbedParseError,
    PlaylistTrack,
    PlaylistUnavailable,
    parse_tracklist,
)

FIXTURE = Path(__file__).parent / "fixtures" / "embed_playlist.html"


def test_parse_tracklist_extracts_tracks_in_order():
    html = FIXTURE.read_text(encoding="utf-8")
    tracks = parse_tracklist(html)

    # the episode entry is skipped; positions are 1-based over the raw list
    assert tracks == [
        PlaylistTrack(1, "3JjyzXQ07ODREBhJknQgLS", "Canto d’amore (con Marco Mengoni)", "Angelina Mango, Marco Mengoni"),
        PlaylistTrack(2, "7pzx95tPu1njhmM6IoR6Al", "Da Dio", "Bresh"),
        PlaylistTrack(4, "549DrPfwUQuZB3q53WQh1z", "FLAMENCO PARANOIA", "Samurai Jay, Vito Salamanca"),
    ]


def test_parse_tracklist_position_is_raw_index_not_filtered_index():
    tracks = parse_tracklist(FIXTURE.read_text(encoding="utf-8"))
    # 3rd kept track was the 4th entry in the playlist
    assert tracks[-1].position == 4


def test_parse_tracklist_raises_without_next_data():
    with pytest.raises(EmbedParseError):
        parse_tracklist("<html><body>no script here</body></html>")


def test_parse_tracklist_raises_on_unexpected_shape():
    bad = (
        '<script id="__NEXT_DATA__" type="application/json">'
        '{"props":{"pageProps":{"state":{"data":{}}}}}</script>'
    )
    with pytest.raises(EmbedParseError):
        parse_tracklist(bad)


def test_parse_tracklist_raises_playlist_unavailable_on_embed_404():
    # what Spotify returns for "Viral 50 - Italia" via the embed endpoint
    page = (
        '<script id="__NEXT_DATA__" type="application/json">'
        '{"props":{"pageProps":{"status":404,"title":"Page not found"}}}</script>'
    )
    with pytest.raises(PlaylistUnavailable):
        parse_tracklist(page)
