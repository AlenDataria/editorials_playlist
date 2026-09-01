"""Command-line argument parsing for the editorials_playlist pipeline."""

import argparse


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Snapshot every track and artist in the tracked Italian editorial "
            "playlists, one row per (playlist, track, artist) per day."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch and log what would be written, without touching the DB",
    )
    parser.add_argument(
        "--no-apify",
        action="store_true",
        help=(
            "skip the Apify fallback for artist ids; artist_id stays NULL "
            "wherever our own data has no match"
        ),
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="logging level (default: INFO)",
    )
    return parser.parse_args(argv)
