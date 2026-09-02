"""Command-line argument parsing for the editorials_playlist pipeline."""

import argparse


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Track every track in the tracked Italian editorial playlists as "
            "stints (start_date / end_date) in social_golden_data."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch and log what would be written, without touching the DB",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="logging level (default: INFO)",
    )
    return parser.parse_args(argv)
