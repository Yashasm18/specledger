"""Persistence store for catalogue batches, rows, and evaluation runs.

Supports both PostgreSQL (for production / migration 007 schema)
and an in-memory store (for testing and local dev).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass
class PersistedBatch:
    batch_id: str
    organization_id: str
    source_name: str
    source_fingerprint: str
    column_list: list[str]
    row_count: int
    verified_rate: float
    rows: list[dict[str, Any]]
    ingested_at: str | None = None


def _escape_like(term: str) -> str:
    """Escape LIKE wildcards so a part number containing % or _ is matched
    literally rather than as a pattern."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _row_matches_search(row: dict[str, Any], search: str) -> bool:
    """Case-insensitive substring match over a row's raw values.

    Values only, never keys: matching keys would make a search for "desc"
    return every row in any dataset with a "part_desc" column.
    """
    needle = search.strip().lower()
    if not needle:
        return True
    for value in (row.get("raw_values") or {}).values():
        if value is not None and needle in str(value).lower():
            return True
    return False


class CatalogueStore:
    """Abstract interface for catalogue batch and row persistence."""

    def save_batch(self, batch_data: dict[str, Any]) -> str:
        raise NotImplementedError

    def get_batch(
        self, organization_id: str, batch_id: str,
        row_limit: int | None = None, row_offset: int = 0,
        search: str | None = None,
    ) -> dict[str, Any] | None:
        """Fetch a batch. `row_limit=None` returns every row.

        Callers that only render a page must pass row_limit so the rows are
        never materialised in full — at catalogue scale, loading every row to
        then slice it in Python is the actual bottleneck, not the response
        size. "row_count" stays the true batch total either way.

        `search` filters across the whole batch before paging, and is matched
        against every raw value rather than a fixed set of column names — the
        uploaded dataset decides its own columns, so hardcoding "part_desc"
        here would only work for one supplier's file. When it is set, the
        result carries "matched_rows": the batch-wide number of matches, which
        is what pagination and any "N of M" label must be computed from.
        """
        raise NotImplementedError

    def get_batch_row(self, organization_id: str, batch_id: str, row_number: int) -> dict[str, Any] | None:
        raise NotImplementedError

    def list_batches(self, organization_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    def update_row_review_state(
        self, organization_id: str, batch_id: str, row_number: int,
        review_state: str, reviewed_by: str | None = None,
        corrections: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        raise NotImplementedError


class InMemoryCatalogueStore(CatalogueStore):
    """In-memory catalogue store for testing and fallback."""

    def __init__(self) -> None:
        # (org_id, batch_id) -> batch_dict
        self._batches: dict[tuple[str, str], dict[str, Any]] = {}

    def save_batch(self, batch_data: dict[str, Any]) -> str:
        org_id = batch_data.get("organization_id", "default")
        batch_id = batch_data["batch_id"]
        # PostgresCatalogueStore derives raw_values/enriched_values from the
        # row's "fields" array on write and returns them on read. Readers
        # (e.g. the review-queue rebuild) rely on that shape, so derive them
        # here too rather than storing the input dict verbatim — otherwise
        # the same code path works against Postgres and KeyErrors locally.
        for row in batch_data.get("rows", []):
            fields = row.get("fields", [])
            row.setdefault("raw_values", {f["column"]: f["raw_value"] for f in fields})
            row.setdefault(
                "enriched_values", {f["column"]: f["canonical_value"] for f in fields}
            )
            row.setdefault("review_state", None)
        self._batches[(org_id, batch_id)] = batch_data
        return batch_id

    def get_batch(
        self, organization_id: str, batch_id: str,
        row_limit: int | None = None, row_offset: int = 0,
        search: str | None = None,
    ) -> dict[str, Any] | None:
        batch = self._batches.get((organization_id, batch_id))
        if batch is None:
            return batch
        if row_limit is None and not search:
            return batch

        rows = batch.get("rows", [])
        # Shallow-copy so filtering/slicing never mutates the stored batch.
        paged = dict(batch)
        if search:
            rows = [r for r in rows if _row_matches_search(r, search)]
            paged["matched_rows"] = len(rows)
        if row_limit is not None:
            rows = rows[row_offset:row_offset + row_limit]
        paged["rows"] = rows
        return paged

    def get_batch_row(self, organization_id: str, batch_id: str, row_number: int) -> dict[str, Any] | None:
        batch = self.get_batch(organization_id, batch_id)
        if not batch:
            return None
        for row in batch.get("rows", []):
            if row.get("row_number") == row_number:
                return row
        return None

    def list_batches(self, organization_id: str) -> list[dict[str, Any]]:
        # Postgres orders by ingested_at DESC on write; match that here too
        # (most-recently-ingested first) — dict insertion order alone would
        # put the oldest batch first, which is the opposite of "latest".
        return [
            {
                "batch_id": b["batch_id"],
                "source_name": b["source_name"],
                "row_count": b["row_count"],
                "verified_rate": b["verified_rate"],
            }
            for (org_id, _), b in reversed(list(self._batches.items()))
            if org_id == organization_id
        ]

    def update_row_review_state(
        self, organization_id: str, batch_id: str, row_number: int,
        review_state: str, reviewed_by: str | None = None,
        corrections: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        batch = self.get_batch(organization_id, batch_id)
        if not batch:
            return None
        for row in batch.get("rows", []):
            if row.get("row_number") == row_number:
                row["review_state"] = review_state
                row["reviewed_by"] = reviewed_by
                # Postgres stamps reviewed_at = NOW() on this same write.
                # Recording it here too keeps the two stores interchangeable —
                # the queue rebuild reads reviewed_at to date the restored
                # audit event, and would otherwise report the decision time as
                # unknown everywhere except production.
                row["reviewed_at"] = datetime.now(timezone.utc).isoformat()
                if corrections:
                    row["corrections"] = corrections
                return row
        return None


class PostgresCatalogueStore(CatalogueStore):
    """PostgreSQL catalogue store using psycopg (v3) and migration 007 schema."""

    def __init__(self, connection_url: str) -> None:
        self.connection_url = connection_url
        self._pool: Any = None

    def _get_pool(self) -> Any:
        """Lazily open a shared connection pool.

        Every call used to open its own connection. Against a managed
        Postgres in another region that is a TLS handshake per query, and a
        single dashboard load makes several — measured at roughly 1 second
        of pure connection setup each, dominating request time regardless of
        how many rows were actually fetched.
        """
        if self._pool is None:
            from psycopg_pool import ConnectionPool
            self._pool = ConnectionPool(
                self.connection_url, min_size=1, max_size=10, open=True,
            )
        return self._pool

    def _get_connection(self) -> Any:
        return self._get_pool().getconn()

    def _release(self, conn: Any) -> None:
        """Return a connection to the pool instead of closing it."""
        self._get_pool().putconn(conn)

    def save_batch(self, batch_data: dict[str, Any]) -> str:
        org_id = batch_data.get("organization_id", "default")
        batch_id = batch_data["batch_id"]

        conn = self._get_connection()
        try:
            with conn:
                with conn.cursor() as cur:
                    # Ensure org exists
                    cur.execute(
                        "INSERT INTO organizations (organization_id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                        (org_id, org_id.capitalize()),
                    )
                    # Insert batch
                    cur.execute(
                        """
                        INSERT INTO catalogue_batches
                            (organization_id, batch_id, source_name, source_fingerprint, column_list, row_count, verified_rate, llm_usage)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (organization_id, batch_id) DO UPDATE SET
                            verified_rate = EXCLUDED.verified_rate,
                            row_count = EXCLUDED.row_count,
                            llm_usage = EXCLUDED.llm_usage
                        """,
                        (
                            org_id,
                            batch_id,
                            batch_data["source_name"],
                            batch_data.get("source_fingerprint", batch_id),
                            json.dumps(batch_data.get("columns", [])),
                            batch_data["row_count"],
                            batch_data.get("verified_rate", 0.0),
                            json.dumps(batch_data["llm_usage"]) if batch_data.get("llm_usage") else None,
                        ),
                    )

                    # Insert rows
                    for row in batch_data.get("rows", []):
                        raw_values = {f["column"]: f["raw_value"] for f in row.get("fields", [])}
                        enriched_values = {f["column"]: f["canonical_value"] for f in row.get("fields", [])}
                        cur.execute(
                            """
                            INSERT INTO catalogue_rows
                                (organization_id, batch_id, row_number, source_fingerprint, raw_values, enriched_values, overall_status, overall_confidence, review_state, llm_suggestion)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (organization_id, batch_id, row_number) DO UPDATE SET
                                enriched_values = EXCLUDED.enriched_values,
                                overall_status = EXCLUDED.overall_status,
                                overall_confidence = EXCLUDED.overall_confidence,
                                review_state = EXCLUDED.review_state,
                                llm_suggestion = EXCLUDED.llm_suggestion
                            """,
                            (
                                org_id,
                                batch_id,
                                row["row_number"],
                                row.get("source_fingerprint", f"{batch_id}-{row['row_number']}"),
                                json.dumps(raw_values),
                                json.dumps(enriched_values),
                                row.get("overall_status", "review_required"),
                                row.get("overall_confidence", 0.0),
                                row.get("review_state", "pending_review"),
                                json.dumps(row["llm_suggestion"]) if row.get("llm_suggestion") else None,
                            ),
                        )
            return batch_id
        finally:
            self._release(conn)

    def get_batch(
        self, organization_id: str, batch_id: str,
        row_limit: int | None = None, row_offset: int = 0,
        search: str | None = None,
    ) -> dict[str, Any] | None:
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT batch_id, source_name, column_list, row_count, verified_rate, ingested_at, llm_usage
                    FROM catalogue_batches
                    WHERE organization_id = %s AND batch_id = %s
                    """,
                    (organization_id, batch_id),
                )
                batch_row = cur.fetchone()
                if not batch_row:
                    return None

                where_sql = "WHERE organization_id = %s AND batch_id = %s"
                where_params: list[Any] = [organization_id, batch_id]

                # Search runs in SQL against the whole batch. Doing it in
                # Python would mean loading every row to filter it, which is
                # exactly the cost pagination exists to avoid. jsonb_each_text
                # walks the row's values whatever the uploaded columns are
                # called, and never matches on key names.
                matched_rows: int | None = None
                if search and search.strip():
                    where_sql += """
                     AND EXISTS (
                        SELECT 1 FROM jsonb_each_text(raw_values) AS kv(k, v)
                        WHERE kv.v ILIKE %s
                     )"""
                    where_params.append(f"%{_escape_like(search.strip())}%")
                    cur.execute(
                        f"SELECT COUNT(*) FROM catalogue_rows {where_sql}",
                        tuple(where_params),
                    )
                    matched_rows = cur.fetchone()[0]

                # Page in SQL rather than fetching every row and slicing in
                # Python — the point of pagination is not transferring less,
                # it is not loading the whole catalogue per request.
                row_sql = f"""
                    SELECT row_number, source_fingerprint, raw_values, enriched_values, overall_status, overall_confidence, review_state, reviewed_by, reviewed_at, llm_suggestion
                    FROM catalogue_rows
                    {where_sql}
                    ORDER BY row_number
                """
                params: list[Any] = list(where_params)
                if row_limit is not None:
                    row_sql += " LIMIT %s OFFSET %s"
                    params.extend([row_limit, row_offset])
                cur.execute(row_sql, tuple(params))
                rows = cur.fetchall()

                def _json(value: Any) -> Any:
                    """psycopg returns JSONB already decoded on some paths and
                    as text on others; accept either, and pass None through."""
                    if value is None or isinstance(value, (dict, list)):
                        return value
                    return json.loads(value)

                result: dict[str, Any] = {
                    "batch_id": batch_row[0],
                    "organization_id": organization_id,
                    "source_name": batch_row[1],
                    "columns": batch_row[2] if isinstance(batch_row[2], list) else json.loads(batch_row[2]),
                    "row_count": batch_row[3],
                    "verified_rate": batch_row[4],
                    "ingested_at": str(batch_row[5]),
                    "rows": [
                        {
                            "row_number": r[0],
                            "source_fingerprint": r[1],
                            "raw_values": _json(r[2]) or {},
                            "enriched_values": _json(r[3]) or {},
                            "overall_status": r[4],
                            "overall_confidence": r[5],
                            "review_state": r[6],
                            "reviewed_by": r[7],
                            "reviewed_at": str(r[8]) if r[8] else None,
                            **({"llm_suggestion": _json(r[9])} if r[9] is not None else {}),
                        }
                        for r in rows
                    ],
                }
                if matched_rows is not None:
                    result["matched_rows"] = matched_rows
                batch_llm_usage = _json(batch_row[6])
                if batch_llm_usage is not None:
                    result["llm_usage"] = batch_llm_usage
                return result
        finally:
            self._release(conn)

    def get_batch_row(self, organization_id: str, batch_id: str, row_number: int) -> dict[str, Any] | None:
        batch = self.get_batch(organization_id, batch_id)
        if not batch:
            return None
        for row in batch.get("rows", []):
            if row.get("row_number") == row_number:
                return row
        return None

    def list_batches(self, organization_id: str) -> list[dict[str, Any]]:
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT batch_id, source_name, row_count, verified_rate
                    FROM catalogue_batches
                    WHERE organization_id = %s
                    ORDER BY ingested_at DESC
                    """,
                    (organization_id,),
                )
                rows = cur.fetchall()
                return [
                    {
                        "batch_id": r[0],
                        "source_name": r[1],
                        "row_count": r[2],
                        "verified_rate": r[3],
                    }
                    for r in rows
                ]
        finally:
            self._release(conn)

    def update_row_review_state(
        self, organization_id: str, batch_id: str, row_number: int,
        review_state: str, reviewed_by: str | None = None,
        corrections: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        conn = self._get_connection()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE catalogue_rows
                        SET review_state = %s, reviewed_by = %s, reviewed_at = NOW()
                        WHERE organization_id = %s AND batch_id = %s AND row_number = %s
                        RETURNING row_number, review_state, reviewed_by
                        """,
                        (review_state, reviewed_by, organization_id, batch_id, row_number),
                    )
                    res = cur.fetchone()
                    if res:
                        return {
                            "row_number": res[0],
                            "review_state": res[1],
                            "reviewed_by": res[2],
                            "corrections": corrections,
                        }
                    return None
        finally:
            self._release(conn)
