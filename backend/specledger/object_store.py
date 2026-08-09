"""Object-storage boundary used by document workers.

The local implementation stores bytes on disk. Production can replace it with
S3, GCS, or Azure Blob without changing worker logic.
"""

from __future__ import annotations

from pathlib import Path


class LocalObjectStore:
    def __init__(self, root: str | Path = "object-data") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, object_key: str, content: bytes) -> str:
        target = self.root / object_key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return str(target)

    def get(self, object_key: str) -> bytes:
        return (self.root / object_key).read_bytes()

    def exists(self, object_key: str) -> bool:
        return (self.root / object_key).exists()

