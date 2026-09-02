"""Split the embed's joined artist string into individual names.

The embed's per-track `subtitle` is a comma-joined artist string ("Angelina
Mango, Marco Mengoni"). We store one history row per credited artist name.
"""


def split_artist_names(subtitle: str | None) -> list[str]:
    """Individual artist names from the embed's joined string.

    The embed joins credited artists with ", "; splitting on comma is right for
    the overwhelming majority (a name that itself contains a comma, e.g. "Tyler,
    The Creator", is the rare exception and would be split — accepted).
    """
    if not subtitle:
        return []
    return [part.strip() for part in subtitle.split(",") if part.strip()]
