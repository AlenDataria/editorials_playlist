"""Text matching between one of our Spotify tracks and a playlist entry.

Ported from song_resolver_tracker/src/platforms/instagram/utils.py, which solved
the same problem (match a Spotify title that carries "(feat. ...)" / "- Live" /
"(Sped Up)" style qualifiers). Kept side-effect free so it is unit-testable
without a DB or the network.

The primary match in the pipeline is an exact `spotify_id` equality (the embed
exposes `spotify:track:<id>` on every entry); this module is the fuzzy fallback
for when our DB holds the track under a different id than the one Spotify put in
the editorial (single vs album, re-release, regional id).
"""

import re

# Spotify appends variant qualifiers with a spaced dash ("Sally - Vasco Live
# 2025", "Libera Le Ali - Demo") or a parenthetical ("(feat. ...)", "(Live)").
# We strip these before comparing. The strip is a WHITELIST, never "everything
# after the dash": a remix is a distinct recording, so a suffix mentioning
# "remix" is always kept.
_VARIANT_KEYWORDS = (
    "live", "demo", "acoustic", "unplugged", "remaster", "remastered",
    "radio edit", "version", "sped up", "slowed", "edit",
)
_DASH_SUFFIX = re.compile(r"\s+-\s+(?P<suffix>.*)$")
_PAREN = re.compile(r"\s*[\(\[](?P<inner>[^\)\]]*)[\)\]]")
_FEAT_INNER = re.compile(r"\s*(?:feat|ft|with|con)\b", re.I)


def normalize(value: str | None) -> str:
    """Lower-case and strip for case-insensitive comparison."""
    return (value or "").strip().casefold()


def _is_variant_qualifier(text: str) -> bool:
    """True when `text` names a non-distinct variant (Live/Demo/...), not a remix."""
    low = text.casefold()
    if "remix" in low:
        return False
    return any(kw in low for kw in _VARIANT_KEYWORDS)


def clean_title(name: str | None) -> str:
    """Strip non-distinct variant qualifiers from a title for comparison.

    Drops a spaced-dash suffix ("- Vasco Live 2025", "- Acoustic Version") and a
    parenthetical ("(feat. ...)", "(Live)") only when it is a whitelisted variant
    and not a remix; a genuine dash/parenthesis that is part of the real title,
    and any remix suffix, are kept. Falls back to the original when stripping
    would empty it.
    """
    if not name:
        return ""

    cleaned = name
    dash = _DASH_SUFFIX.search(cleaned)
    if dash and _is_variant_qualifier(dash.group("suffix")):
        cleaned = cleaned[: dash.start()]

    def _strip_noise_paren(match: re.Match) -> str:
        inner = match.group("inner")
        if _FEAT_INNER.match(inner) or _is_variant_qualifier(inner):
            return ""
        return match.group(0)

    cleaned = _PAREN.sub(_strip_noise_paren, cleaned).strip()
    return cleaned or name.strip()


def is_title_match(our_title: str | None, playlist_title: str | None) -> bool:
    """Containment either way on the cleaned, normalized titles.

    So "Canto d'amore (con Marco Mengoni)" in the playlist still matches our
    "Canto d'amore". An empty base never matches.
    """
    ours = normalize(clean_title(our_title))
    theirs = normalize(clean_title(playlist_title))
    if not ours or not theirs:
        return False
    return ours in theirs or theirs in ours


def is_artist_match(our_artists: list[str], playlist_artists: str | None) -> bool:
    """True when any of our artist names is a substring of the playlist artist string.

    The embed's `subtitle` concatenates featured artists ("Angelina Mango, Marco
    Mengoni"); matching on ANY of our artists (not just the first) tolerates a
    different primary-artist ordering between the two sides.
    """
    haystack = normalize(playlist_artists)
    if not haystack:
        return False
    needles = [n for n in (normalize(a) for a in our_artists) if n]
    return any(n in haystack for n in needles)


def is_track_match(
    our_title: str | None,
    our_artists: list[str],
    playlist_title: str | None,
    playlist_artists: str | None,
) -> bool:
    """Fuzzy match: title containment AND a shared artist."""
    return is_title_match(our_title, playlist_title) and is_artist_match(
        our_artists, playlist_artists
    )
