"""api/db.py — SQLite persistence for conversations and messages."""
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "conversations.db"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id         TEXT PRIMARY KEY,
                title      TEXT,
                status     TEXT DEFAULT 'active',
                created_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS messages (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT REFERENCES conversations(id),
                role            TEXT,
                content         TEXT,
                message_type    TEXT DEFAULT 'answer',
                metadata        TEXT,
                created_at      TEXT
            );
        """)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_conversation(title: str) -> dict:
    cid = str(uuid.uuid4())
    ts = now()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO conversations VALUES (?,?,?,?,?)",
            (cid, title, "active", ts, ts),
        )
    return {"id": cid, "title": title, "status": "active", "created_at": ts}


def list_conversations() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, title, status, created_at, updated_at "
            "FROM conversations ORDER BY updated_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_conversation(cid: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM conversations WHERE id=?", (cid,)
        ).fetchone()
    return dict(row) if row else None


def set_conversation_status(cid: str, status: str) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE conversations SET status=?, updated_at=? WHERE id=?",
            (status, now(), cid),
        )


def set_conversation_title(cid: str, title: str) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE conversations SET title=?, updated_at=? WHERE id=?",
            (title, now(), cid),
        )


def add_message(cid: str, role: str, content: str,
                message_type: str = "answer", metadata: dict | None = None) -> dict:
    ts = now()
    meta_str = json.dumps(metadata) if metadata else None
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO messages (conversation_id,role,content,message_type,metadata,created_at)"
            " VALUES (?,?,?,?,?,?)",
            (cid, role, content, message_type, meta_str, ts),
        )
        mid = cur.lastrowid
    with _conn() as conn:
        conn.execute(
            "UPDATE conversations SET updated_at=? WHERE id=?", (now(), cid)
        )
    return {"id": mid, "conversation_id": cid, "role": role, "content": content,
            "message_type": message_type, "metadata": metadata, "created_at": ts}


def delete_conversation(cid: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM messages WHERE conversation_id=?", (cid,))
        conn.execute("DELETE FROM conversations WHERE id=?", (cid,))


def list_messages(cid: str) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id,conversation_id,role,content,message_type,metadata,created_at "
            "FROM messages WHERE conversation_id=? ORDER BY id ASC",
            (cid,),
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        if d["metadata"]:
            d["metadata"] = json.loads(d["metadata"])
        result.append(d)
    return result
