"""Print the track order the embed endpoint gives us, for manual comparison
against what Spotify shows in the app / web player.

The embed `trackList` has NO position field - `src/embed.py` numbers tracks by
their order in that array. This script just dumps that order, numbered, so you
can eyeball it next to the real playlist.

    uv run python scripts/dump_editorial_order.py                 # all editorials
    uv run python scripts/dump_editorial_order.py "RADAR"         # name substring
    uv run python scripts/dump_editorial_order.py 37i9dQZF1DWVjDgOMO8jZl
    uv run python scripts/dump_editorial_order.py RADAR --limit 30
"""

import argparse
import logging
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.consts import EDITORIALS, HTTP_HEADERS, REQUEST_DELAY

# Quiet the embed's truncation/retry logging so it doesn't interleave with the
# printed track lists - this script is for reading by eye.
logging.disable(logging.WARNING)
from src.embed import PlaylistUnavailable, fetch_playlist_tracklist


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("selector", nargs="?", help="playlist id, or a substring of the name")
    ap.add_argument("--limit", type=int, default=25, help="max tracks to print per playlist (default 25)")
    args = ap.parse_args(argv)

    if args.selector:
        sel = args.selector.lower()
        chosen = [e for e in EDITORIALS if sel in e.playlist_id.lower() or sel in e.name.lower()]
        if not chosen:
            print(f"no editorial matches {args.selector!r}", file=sys.stderr)
            return 2
    else:
        chosen = list(EDITORIALS)

    session = requests.Session()
    session.headers.update(HTTP_HEADERS)

    for ed in chosen:
        print(f"\n=== {ed.name}  ({ed.playlist_id}) ===")
        try:
            tracks = fetch_playlist_tracklist(ed.playlist_id, session)
        except PlaylistUnavailable:
            print("  not served via embed (404)")
            continue
        except Exception as e:  # noqa: BLE001
            print(f"  ERROR: {type(e).__name__}: {e}")
            continue

        shown = tracks[: args.limit]
        for t in shown:
            print(f"  {t.position:3d}. {t.title}  —  {t.artists}")
        if len(tracks) > len(shown):
            print(f"  ... (+{len(tracks) - len(shown)} more, {len(tracks)} total)")
        time.sleep(REQUEST_DELAY)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
