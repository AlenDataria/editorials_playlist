"""Database engine factory and the generic retry decorator.

Both are copied (not imported) from song_resolver_tracker/src/utils.py so this
repo stays standalone. Same behaviour: one shared SQLAlchemy Engine built from
DB_* env vars, and an exponential-backoff decorator for outbound calls.
"""

import logging
import os
import time
from functools import wraps
from typing import Any, Callable

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL

logger = logging.getLogger(__name__)


def retry_on_error(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
) -> Callable:
    """Retry a function on error with exponential backoff.

    Args:
        max_retries: number of retries after the first attempt.
        delay: initial wait between retries, seconds.
        backoff: multiplier applied to `delay` after each retry.
        exceptions: exception types that trigger a retry.
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            retry_delay = delay
            last_exception: Exception | None = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:  # noqa: BLE001 - caller picks the types
                    last_exception = e
                    if attempt < max_retries:
                        logger.warning(
                            "Attempt %d/%d failed for %s: %s. Retrying in %.1fs...",
                            attempt + 1,
                            max_retries + 1,
                            func.__name__,
                            e,
                            retry_delay,
                        )
                        time.sleep(retry_delay)
                        retry_delay *= backoff
                    else:
                        logger.error(
                            "All %d attempts failed for %s. Last error: %s",
                            max_retries + 1,
                            func.__name__,
                            e,
                        )

            assert last_exception is not None
            raise last_exception

        return wrapper

    return decorator


def db_config_from_env() -> dict[str, str]:
    """Read the DB_* connection settings from the environment.

    DB_HOST / DB_NAME / DB_USER / DB_PASSWORD are required; DB_PORT defaults to
    5432. Same variable names as ASP and song_resolver_tracker.
    """
    return {
        "host": os.environ["DB_HOST"],
        "port": os.environ.get("DB_PORT", "5432"),
        "name": os.environ["DB_NAME"],
        "user": os.environ["DB_USER"],
        "password": os.environ["DB_PASSWORD"],
    }


def create_db_engine(db_config: dict[str, Any]) -> Engine:
    """Build the shared SQLAlchemy Engine (a lazy connection pool).

    No connection is opened here; connections are taken from the pool when a
    Session actually runs a query. RDS requires TLS, so `sslmode` defaults to
    `require` and is overridable via env.
    """
    url = URL.create(
        drivername=os.environ.get("DATABASE_DRIVER", "postgresql+psycopg2"),
        username=db_config["user"],
        password=db_config["password"],
        host=db_config["host"],
        port=int(db_config["port"]),
        database=db_config["name"],
    )
    sslmode = os.environ.get("DATABASE_SSLMODE", "require")
    return create_engine(url, pool_pre_ping=True, connect_args={"sslmode": sslmode})
