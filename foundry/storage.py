"""Versioned local state. A failed commit leaves the previous pointer readable."""

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import gzip
import json
import os
from pathlib import Path
import tempfile
import uuid
import zlib

from .validation import Invalid, MAX_BYTES, _pairs, digest, read_json, require, validate_state


COMPRESSION_THRESHOLD = 1_000_000


def encoded(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_compressed(path, max_bytes):
    """Read only a bounded amount of expanded JSON before parsing it."""
    try:
        with gzip.open(path, "rb") as handle:
            raw = handle.read(max_bytes + 1)
    except (OSError, EOFError, zlib.error) as exc:
        raise Invalid("invalid compressed state revision") from exc
    require(len(raw) <= max_bytes, f"input exceeds {max_bytes} bytes after decompression")
    try:
        return json.loads(raw, object_pairs_hook=_pairs,
                          parse_constant=lambda value: require(False, f"non-finite JSON: {value}"))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise Invalid(f"invalid JSON in {path.name}: {exc}") from exc


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
        sync_directory(path.parent)
    finally:
        Path(name).unlink(missing_ok=True)


class Store:
    def __init__(self, path, validator=validate_state, max_bytes=MAX_BYTES, *, compress=False):
        self.path = Path(path)
        self.validator = validator
        self.max_bytes = max_bytes
        self.compress = compress

    @contextmanager
    def locked(self):
        self.path.mkdir(parents=True, exist_ok=True)
        with (self.path / ".lock").open("a", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield

    def load(self):
        pointer = read_json(self.path / "current.json")
        revision = pointer["revision"]
        require(isinstance(revision, str) and len(revision) == 32
                and all(c in "0123456789abcdef" for c in revision), "invalid revision pointer")
        compression = pointer.get("compression")
        require(compression in (None, "gzip"), "unsupported state compression")
        path = self.path / "history" / (revision + (".json.gz" if compression else ".json"))
        record = _read_compressed(path, self.max_bytes) if compression else read_json(path, max_bytes=self.max_bytes)
        require(digest(encoded(record)) == pointer["sha256"], "state revision hash mismatch")
        self.validator(record["state"])
        return record["state"]

    def _commit(self, state, reason):
        self.validator(state)
        current = self.path / "current.json"
        previous = read_json(current)["revision"] if current.exists() else None
        record = {
            "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "previous": previous, "reason": reason, "state": state,
        }
        payload = encoded(record)
        raw = payload.encode("utf-8")
        require(len(raw) <= self.max_bytes, "state budget exceeded")
        compressed = self.compress and len(raw) >= COMPRESSION_THRESHOLD
        data = gzip.compress(raw, compresslevel=3, mtime=0) if compressed else raw
        revision = uuid.uuid4().hex
        history = self.path / "history"
        history.mkdir(exist_ok=True)
        # Exclusive creation protects history; a crash can leave an unreferenced
        # revision, but cannot make half a revision the current state.
        suffix = ".json.gz" if compressed else ".json"
        with (history / (revision + suffix)).open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        sync_directory(history)
        pointer = {"revision": revision, "sha256": digest(payload)}
        if compressed:
            pointer["compression"] = "gzip"
        atomic_text(current, encoded(pointer))

    def initialize(self, state):
        with self.locked():
            require(not (self.path / "current.json").exists(), "store already initialized; use a new directory")
            self._commit(state, "initial reviewed-source bundle; claims still require human review")

    def update(self, transform, reason):
        with self.locked():
            state = self.load()
            transform(state)
            self._commit(state, reason)
        return state
