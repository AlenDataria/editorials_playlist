from src.matching import (
    clean_title,
    is_artist_match,
    is_title_match,
    is_track_match,
    normalize,
)


def test_normalize():
    assert normalize("  Ciao MONDO ") == "ciao mondo"
    assert normalize(None) == ""


def test_clean_title_strips_whitelisted_variants():
    assert clean_title("Sally - Vasco Live 2025") == "Sally"
    assert clean_title("Libera Le Ali (Demo)") == "Libera Le Ali"
    assert clean_title("Canto d'amore (con Marco Mengoni)") == "Canto d'amore"


def test_clean_title_keeps_remix_and_real_parentheses():
    assert clean_title("OCEANICA - Botteghi Remix") == "OCEANICA - Botteghi Remix"
    assert clean_title("Song (Part 2)") == "Song (Part 2)"


def test_is_title_match_containment_both_ways():
    # playlist side carries a "(con ...)" suffix that clean_title strips, then
    # the bare titles match by containment
    assert is_title_match("Canto d'amore", "Canto d'amore (con Marco Mengoni)")
    assert is_title_match("Da Dio", "da dio")
    assert not is_title_match("Da Dio", "Buon Vento")
    assert not is_title_match("", "anything")


def test_is_artist_match_any_of_our_artists_in_playlist_string():
    assert is_artist_match(["Angelina Mango"], "Angelina Mango, Marco Mengoni")
    assert is_artist_match(["Marco Mengoni"], "Angelina Mango, Marco Mengoni")
    assert not is_artist_match(["Bresh"], "Angelina Mango, Marco Mengoni")
    assert not is_artist_match([], "Angelina Mango")


def test_is_track_match_requires_title_and_artist():
    assert is_track_match(
        "Canto d'amore", ["Angelina Mango"],
        "Canto d'amore (con Marco Mengoni)", "Angelina Mango, Marco Mengoni",
    )
    # right title, wrong artist
    assert not is_track_match(
        "Canto d'amore", ["Someone Else"],
        "Canto d'amore (con Marco Mengoni)", "Angelina Mango, Marco Mengoni",
    )
