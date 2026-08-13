import json
import os
import tempfile
from pathlib import Path
from typing import Callable

from .models import CacheRecord


class AtomicCache:
    def __init__(self, directory: Path):
        self.directory = directory

    def initialize(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)

    def read(self, name: str, validator: Callable[[object], bool] | None = None) -> CacheRecord | None:
        path = self.directory / f"{name}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            record = CacheRecord(float(data["timestamp"]), str(data["source"]), data["payload"], dict(data.get("metadata", {})))
        except (OSError, ValueError, KeyError, TypeError):
            return None
        if validator is not None and not validator(record.payload):
            return None
        return record

    def write(self, name: str, record: CacheRecord) -> None:
        self.initialize()
        destination = self.directory / f"{name}.json"
        payload = {"timestamp": record.timestamp, "source": record.source, "payload": record.payload, "metadata": dict(record.metadata)}
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{name}-", suffix=".tmp", dir=self.directory)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, separators=(",", ":"), sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, destination)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
