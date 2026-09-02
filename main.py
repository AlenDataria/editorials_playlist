"""Entry point: load env, parse args, run the editorials snapshot."""

import logging

from dotenv import load_dotenv

from src.cli import parse_args
from src.processor import EditorialsTracker

logger = logging.getLogger(__name__)


def main() -> None:
    # Load .env so DB_* settings are on os.environ before create_db_engine reads them.
    load_dotenv()

    args = parse_args()
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    logger.info("starting editorials_playlist run (dry_run=%s)", args.dry_run)
    EditorialsTracker().run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
