"""The open-stint state document.

One JSON file records which (playlist, track) stints are currently open, so a
run can tell new tracks from tracks it has already recorded without inferring it
from the history table. Shape:

    {
      "updated_at": "2026-09-01T00:00:00+00:00",
      "playlists": {
        "<playlist_id>": {
          "<track_id>": {"start": "2026-08-15", "last_seen": "2026-09-01"}
        }
      }
    }

Stored on S3 when `S3_BUCKET_NAME` is set (key `STATE_S3_KEY`, region
`AWS_REGION`), otherwise on a local file (`STATE_LOCAL_PATH`) for dev and
`--dry-run`.
"""

import json
import logging
import os
from datetime import datetime, timezone

from src.consts import STATE_LOCAL_PATH, STATE_S3_KEY

logger = logging.getLogger(__name__)


def empty_doc() -> dict:
    """A fresh state document with no open stints."""
    return {"playlists": {}}


def open_stints(doc: dict, playlist_id: str) -> dict[str, dict]:
    """The `{track_id: {start, last_seen}}` map for one playlist (created if new)."""
    return doc.setdefault("playlists", {}).setdefault(playlist_id, {})


class StateStore:
    """Load / save the state document, on S3 or a local file."""

    def __init__(self) -> None:
        self.bucket = os.environ.get("S3_BUCKET_NAME") or None
        self.key = os.environ.get("EDITORIAL_STATE_S3_KEY", STATE_S3_KEY)
        self.local_path = os.environ.get("EDITORIAL_STATE_LOCAL_PATH", STATE_LOCAL_PATH)
        self._s3 = None
        if self.bucket:
            import boto3

            self._s3 = boto3.client(
                "s3", region_name=os.environ.get("AWS_REGION", "eu-west-1")
            )

    @property
    def location(self) -> str:
        return f"s3://{self.bucket}/{self.key}" if self.bucket else self.local_path

    def load(self) -> dict | None:
        """Return the state document, or None if it does not exist yet."""
        raw = self._read()
        if raw is None:
            return None
        doc = json.loads(raw)
        doc.setdefault("playlists", {})
        return doc

    def save(self, doc: dict) -> None:
        doc["updated_at"] = datetime.now(timezone.utc).isoformat()
        body = json.dumps(doc, indent=2, sort_keys=True).encode("utf-8")
        if self._s3 is not None:
            self._s3.put_object(
                Bucket=self.bucket,
                Key=self.key,
                Body=body,
                ContentType="application/json",
            )
        else:
            parent = os.path.dirname(self.local_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(self.local_path, "wb") as fh:
                fh.write(body)
        logger.debug("state saved to %s", self.location)

    # ------------------------------------------------------------------ #
    def _read(self) -> str | None:
        if self._s3 is not None:
            try:
                obj = self._s3.get_object(Bucket=self.bucket, Key=self.key)
            except self._s3.exceptions.NoSuchKey:
                return None
            return obj["Body"].read().decode("utf-8")
        if not os.path.exists(self.local_path):
            return None
        with open(self.local_path, encoding="utf-8") as fh:
            return fh.read()
