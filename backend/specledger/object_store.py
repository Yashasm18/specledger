"""Object-storage boundary used by document workers.

Uses Supabase Storage in production when SUPABASE_URL and
SUPABASE_SERVICE_ROLE_KEY are set. Falls back to local disk otherwise, which
is fine for local dev but not durable on hosts (e.g. Render's free tier)
that wipe local disk on every restart/redeploy.
"""

from __future__ import annotations

from pathlib import Path
import json
import os


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

    def put_json(self, object_key: str, payload: dict) -> str:
        return self.put(object_key, json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"))


class SupabaseObjectStore:
    """Object store backed by the Supabase Storage REST API."""

    def __init__(self, url: str, service_key: str, bucket: str = "specledger-artifacts") -> None:
        import requests

        self._requests = requests
        self.base_url = url.rstrip("/")
        self.bucket = bucket
        self.headers = {"Authorization": f"Bearer {service_key}", "apikey": service_key}
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        response = self._requests.post(
            f"{self.base_url}/storage/v1/bucket",
            headers=self.headers,
            json={"id": self.bucket, "name": self.bucket, "public": False},
            timeout=10,
        )
        if response.status_code not in (200, 201) and "already exists" not in response.text.lower():
            raise RuntimeError(f"Could not create Supabase bucket '{self.bucket}': {response.status_code} {response.text}")

    def put(self, object_key: str, content: bytes) -> str:
        response = self._requests.post(
            f"{self.base_url}/storage/v1/object/{self.bucket}/{object_key}",
            headers={**self.headers, "x-upsert": "true", "Content-Type": "application/octet-stream"},
            data=content,
            timeout=30,
        )
        if response.status_code not in (200, 201):
            raise RuntimeError(f"Supabase upload failed for '{object_key}': {response.status_code} {response.text}")
        return f"{self.bucket}/{object_key}"

    def get(self, object_key: str) -> bytes:
        response = self._requests.get(
            f"{self.base_url}/storage/v1/object/{self.bucket}/{object_key}",
            headers=self.headers,
            timeout=30,
        )
        response.raise_for_status()
        return response.content

    def exists(self, object_key: str) -> bool:
        response = self._requests.get(
            f"{self.base_url}/storage/v1/object/info/{self.bucket}/{object_key}",
            headers=self.headers,
            timeout=10,
        )
        return response.status_code == 200

    def put_json(self, object_key: str, payload: dict) -> str:
        return self.put(object_key, json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"))


def build_object_store():
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if supabase_url and supabase_key:
        bucket = os.getenv("SUPABASE_STORAGE_BUCKET", "specledger-artifacts")
        return SupabaseObjectStore(supabase_url, supabase_key, bucket)
    return LocalObjectStore(os.getenv("SPECLEDGER_OBJECT_STORE", "object-data"))
