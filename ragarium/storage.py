from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


def utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = value.strip("_")
    return value or "item"


class ProductStore:
    """
    SQLite-backed local product state.

    The vector index and uploaded files remain on disk; SQLite stores the
    durable product metadata needed by the API and UI.
    """

    def __init__(self, db_path: str | Path = "var/app/state.sqlite") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS knowledge_bases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    collection_name TEXT NOT NULL UNIQUE,
                    index_status TEXT NOT NULL DEFAULT 'not_indexed',
                    indexed_at TEXT,
                    index_error TEXT,
                    chunk_config_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    knowledge_base_id INTEGER NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
                    source_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    uri TEXT,
                    stored_path TEXT,
                    status TEXT NOT NULL,
                    error TEXT,
                    error_code TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    knowledge_base_id INTEGER NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
                    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS workflows (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    graph_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS query_sets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    knowledge_base_id INTEGER NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    examples_json TEXT NOT NULL,
                    target_count INTEGER NOT NULL,
                    queries_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS eval_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query_set_id INTEGER NOT NULL REFERENCES query_sets(id) ON DELETE CASCADE,
                    workflow_id INTEGER REFERENCES workflows(id) ON DELETE SET NULL,
                    status TEXT NOT NULL,
                    metrics_json TEXT NOT NULL,
                    samples_json TEXT NOT NULL DEFAULT '[]',
                    output_csv TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )
            self._ensure_knowledge_base_columns(conn)
            self._ensure_source_columns(conn)
            self._ensure_eval_run_columns(conn)

    def _ensure_knowledge_base_columns(self, conn: sqlite3.Connection) -> None:
        existing = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(knowledge_bases)").fetchall()
        }
        columns = {
            "index_status": "TEXT NOT NULL DEFAULT 'not_indexed'",
            "indexed_at": "TEXT",
            "index_error": "TEXT",
            "chunk_config_json": "TEXT NOT NULL DEFAULT '{}'",
        }
        for name, definition in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE knowledge_bases ADD COLUMN {name} {definition}")

    def _ensure_source_columns(self, conn: sqlite3.Connection) -> None:
        existing = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(sources)").fetchall()
        }
        columns = {
            "error_code": "TEXT",
        }
        for name, definition in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE sources ADD COLUMN {name} {definition}")

    def _ensure_eval_run_columns(self, conn: sqlite3.Connection) -> None:
        existing = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(eval_runs)").fetchall()
        }
        columns = {
            "samples_json": "TEXT NOT NULL DEFAULT '[]'",
        }
        for name, definition in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE eval_runs ADD COLUMN {name} {definition}")

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        return {key: row[key] for key in row.keys()}

    @staticmethod
    def _decode_json_fields(row: Dict[str, Any], fields: Iterable[str]) -> Dict[str, Any]:
        for field in fields:
            if field in row and isinstance(row[field], str):
                row[field] = json.loads(row[field])
        return row

    @classmethod
    def _hydrate_knowledge_base(cls, row: sqlite3.Row) -> Dict[str, Any]:
        item = cls._row_to_dict(row)
        chunk_config = item.pop("chunk_config_json", "{}")
        try:
            item["chunk_config"] = json.loads(chunk_config) if chunk_config else {}
        except json.JSONDecodeError:
            item["chunk_config"] = {}
        item["index_status"] = item.get("index_status") or "not_indexed"
        return item

    def create_knowledge_base(self, name: str) -> Dict[str, Any]:
        now = utc_now()
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO knowledge_bases (name, collection_name, created_at) VALUES (?, ?, ?)",
                (name, f"pending_{slugify(name)}", now),
            )
            kb_id = int(cur.lastrowid)
            collection = f"kb_{kb_id}_{slugify(name)}"
            conn.execute(
                "UPDATE knowledge_bases SET collection_name = ? WHERE id = ?",
                (collection, kb_id),
            )
        return self.get_knowledge_base(kb_id)

    def list_knowledge_bases(self) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT kb.*,
                       COUNT(DISTINCT s.id) AS source_count,
                       COUNT(c.id) AS chunk_count
                FROM knowledge_bases kb
                LEFT JOIN sources s ON s.knowledge_base_id = kb.id
                LEFT JOIN chunks c ON c.knowledge_base_id = kb.id
                GROUP BY kb.id
                ORDER BY kb.id DESC
                """
            ).fetchall()
        return [self._hydrate_knowledge_base(row) for row in rows]

    def get_knowledge_base(self, kb_id: int) -> Dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM knowledge_bases WHERE id = ?",
                (kb_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"knowledge base not found: {kb_id}")
        return self._hydrate_knowledge_base(row)

    def update_knowledge_base_index_status(
        self,
        kb_id: int,
        *,
        status: str,
        error: Optional[str] = None,
        chunk_config: Optional[Dict[str, Any]] = None,
        indexed_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        self.get_knowledge_base(kb_id)
        if status == "ready" and indexed_at is None:
            indexed_at = utc_now()
        chunk_config_json = None
        if chunk_config is not None:
            chunk_config_json = json.dumps(chunk_config, ensure_ascii=False)
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE knowledge_bases
                SET index_status = ?,
                    index_error = ?,
                    indexed_at = COALESCE(?, indexed_at),
                    chunk_config_json = COALESCE(?, chunk_config_json)
                WHERE id = ?
                """,
                (status, error, indexed_at, chunk_config_json, kb_id),
            )
        return self.get_knowledge_base(kb_id)

    def create_source(
        self,
        knowledge_base_id: int,
        *,
        source_type: str,
        name: str,
        uri: Optional[str] = None,
        stored_path: Optional[str] = None,
        status: str = "processing",
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        self.get_knowledge_base(knowledge_base_id)
        now = utc_now()
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO sources (
                    knowledge_base_id, source_type, name, uri, stored_path, status, error, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (knowledge_base_id, source_type, name, uri, stored_path, status, error, now),
            )
            source_id = int(cur.lastrowid)
        return self.get_source(source_id)

    def update_source_status(
        self,
        source_id: int,
        *,
        status: str,
        error: Optional[str] = None,
        error_code: Optional[str] = None,
        stored_path: Optional[str] = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE sources
                SET status = ?,
                    error = ?,
                    error_code = ?,
                    stored_path = COALESCE(?, stored_path)
                WHERE id = ?
                """,
                (status, error, error_code, stored_path, source_id),
            )

    def get_source(self, source_id: int) -> Dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        if row is None:
            raise KeyError(f"source not found: {source_id}")
        return self._row_to_dict(row)

    def list_sources(self, knowledge_base_id: int) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sources WHERE knowledge_base_id = ? ORDER BY id DESC",
                (knowledge_base_id,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def delete_source(self, knowledge_base_id: int, source_id: int) -> Dict[str, Any]:
        source = self.get_source(source_id)
        if int(source["knowledge_base_id"]) != int(knowledge_base_id):
            raise KeyError(f"source not found: {source_id}")
        with self.connect() as conn:
            conn.execute(
                "DELETE FROM sources WHERE id = ? AND knowledge_base_id = ?",
                (source_id, knowledge_base_id),
            )
        return source

    def replace_source_chunks(
        self,
        knowledge_base_id: int,
        source_id: int,
        chunks: List[Dict[str, Any]],
    ) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute("DELETE FROM chunks WHERE source_id = ?", (source_id,))
            conn.executemany(
                """
                INSERT INTO chunks (
                    knowledge_base_id, source_id, chunk_index, content, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        knowledge_base_id,
                        source_id,
                        int(chunk["chunk_index"]),
                        chunk["content"],
                        json.dumps(chunk["metadata"], ensure_ascii=False),
                        now,
                    )
                    for chunk in chunks
                ],
            )

    def list_chunks(self, knowledge_base_id: int, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM chunks WHERE knowledge_base_id = ? ORDER BY source_id, chunk_index"
        params: List[Any] = [knowledge_base_id]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            self._decode_json_fields(self._row_to_dict(row), ["metadata_json"])
            for row in rows
        ]

    def upsert_workflow(self, name: str, graph: Dict[str, Any], workflow_id: Optional[int] = None) -> Dict[str, Any]:
        now = utc_now()
        graph_json = json.dumps(graph, ensure_ascii=False)
        with self.connect() as conn:
            if workflow_id is None:
                cur = conn.execute(
                    "INSERT INTO workflows (name, graph_json, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    (name, graph_json, now, now),
                )
                workflow_id = int(cur.lastrowid)
            else:
                conn.execute(
                    "UPDATE workflows SET name = ?, graph_json = ?, updated_at = ? WHERE id = ?",
                    (name, graph_json, now, workflow_id),
                )
        return self.get_workflow(int(workflow_id))

    def get_workflow(self, workflow_id: int) -> Dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
        if row is None:
            raise KeyError(f"workflow not found: {workflow_id}")
        data = self._row_to_dict(row)
        data["graph"] = json.loads(data.pop("graph_json"))
        return data

    def list_workflows(self) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM workflows ORDER BY id DESC").fetchall()
        items = []
        for row in rows:
            item = self._row_to_dict(row)
            item["graph"] = json.loads(item.pop("graph_json"))
            items.append(item)
        return items

    def create_query_set(
        self,
        knowledge_base_id: int,
        *,
        name: str,
        examples: List[str],
        target_count: int,
        queries: List[str],
    ) -> Dict[str, Any]:
        self.get_knowledge_base(knowledge_base_id)
        now = utc_now()
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO query_sets (
                    knowledge_base_id, name, examples_json, target_count, queries_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    knowledge_base_id,
                    name,
                    json.dumps(examples, ensure_ascii=False),
                    int(target_count),
                    json.dumps(queries, ensure_ascii=False),
                    now,
                ),
            )
            query_set_id = int(cur.lastrowid)
        return self.get_query_set(query_set_id)

    def get_query_set(self, query_set_id: int) -> Dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM query_sets WHERE id = ?", (query_set_id,)).fetchone()
        if row is None:
            raise KeyError(f"query set not found: {query_set_id}")
        item = self._row_to_dict(row)
        item["examples"] = json.loads(item.pop("examples_json"))
        item["queries"] = json.loads(item.pop("queries_json"))
        return item

    def list_query_sets(self, knowledge_base_id: Optional[int] = None) -> List[Dict[str, Any]]:
        if knowledge_base_id is None:
            sql = "SELECT * FROM query_sets ORDER BY id DESC"
            params: List[Any] = []
        else:
            sql = "SELECT * FROM query_sets WHERE knowledge_base_id = ? ORDER BY id DESC"
            params = [knowledge_base_id]
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        items = []
        for row in rows:
            item = self._row_to_dict(row)
            item["examples"] = json.loads(item.pop("examples_json"))
            item["queries"] = json.loads(item.pop("queries_json"))
            items.append(item)
        return items

    def create_eval_run(
        self,
        *,
        query_set_id: int,
        workflow_id: Optional[int],
        status: str,
        metrics: Dict[str, Any],
        samples: Optional[List[Dict[str, Any]]] = None,
        output_csv: Optional[str] = None,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = utc_now()
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO eval_runs (
                    query_set_id, workflow_id, status, metrics_json, samples_json, output_csv, error, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    query_set_id,
                    workflow_id,
                    status,
                    json.dumps(metrics, ensure_ascii=False),
                    json.dumps(samples or [], ensure_ascii=False),
                    output_csv,
                    error,
                    now,
                ),
            )
            eval_run_id = int(cur.lastrowid)
        return self.get_eval_run(eval_run_id)

    def get_eval_run(self, eval_run_id: int) -> Dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM eval_runs WHERE id = ?", (eval_run_id,)).fetchone()
        if row is None:
            raise KeyError(f"eval run not found: {eval_run_id}")
        item = self._row_to_dict(row)
        item["metrics"] = json.loads(item.pop("metrics_json"))
        item["samples"] = json.loads(item.pop("samples_json", "[]") or "[]")
        item["sample_count"] = len(item["samples"])
        return item

    def list_eval_runs(self) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM eval_runs ORDER BY id DESC").fetchall()
        items = []
        for row in rows:
            item = self._row_to_dict(row)
            item["metrics"] = json.loads(item.pop("metrics_json"))
            item["samples"] = json.loads(item.pop("samples_json", "[]") or "[]")
            item["sample_count"] = len(item["samples"])
            items.append(item)
        return items
