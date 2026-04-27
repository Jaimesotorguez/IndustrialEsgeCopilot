"""
memory/memory_store.py — M12: Persistencia del sistema
=======================================================
Almacena todos los objetos del sistema en SQLite local.
Sin servidor, sin configuración, funciona en Raspberry Pi.

Tablas:
  events      — AnomalyEvents detectados
  diagnoses   — Diagnósticos generados por Claude
  actions     — Comandos recomendados y su estado
  interactions — Preguntas del operario y respuestas
  knowledge   — Fragmentos de conocimiento del proceso

Para búsqueda semántica (RAG) usa ChromaDB en paralelo.
"""

import json
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from backend.core.interfaces import (
    ActionStatus, AnomalyEvent, Diagnosis,
    MemoryStore, RecommendedAction, Severity,
)


class SqliteMemoryStore(MemoryStore):
    """
    Implementación de MemoryStore sobre SQLite.
    Thread-safe gracias al check_same_thread=False + WAL mode.
    """

    def __init__(self, db_path: str = "data/copilot.db"):
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            db_path,
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        self._conn.row_factory = sqlite3.Row
        self._setup_wal()
        self._create_tables()
        print(f"[Memory] SQLite inicializado: {db_path}")

    # ── Setup ─────────────────────────────────────────────────────────────────

    def _setup_wal(self):
        """WAL mode: mejor rendimiento en escrituras concurrentes."""
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA cache_size=10000")

    def _create_tables(self):
        self._conn.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            id          TEXT PRIMARY KEY,
            timestamp   TEXT NOT NULL,
            tag_ids     TEXT NOT NULL,       -- JSON array
            score       REAL NOT NULL,
            severity    TEXT NOT NULL,
            description TEXT NOT NULL,
            raw_values  TEXT,                -- JSON dict
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS diagnoses (
            id                  TEXT PRIMARY KEY,
            timestamp           TEXT NOT NULL,
            probable_cause      TEXT NOT NULL,
            confidence          REAL NOT NULL,
            tags_involved       TEXT NOT NULL,  -- JSON array
            urgency             INTEGER NOT NULL,
            evidence            TEXT,           -- JSON array
            context_tokens      INTEGER DEFAULT 0,
            event_id            TEXT,           -- FK → events.id
            created_at          TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (event_id) REFERENCES events(id)
        );

        CREATE TABLE IF NOT EXISTS actions (
            id                      TEXT PRIMARY KEY,
            timestamp               TEXT NOT NULL,
            machine_id              TEXT NOT NULL,
            action_type             TEXT NOT NULL,
            parameters              TEXT,        -- JSON dict
            reason                  TEXT,
            estimated_impact        TEXT,
            estimated_saving_eur    REAL DEFAULT 0,
            risk_level              TEXT,
            status                  TEXT NOT NULL DEFAULT 'pending',
            approved_by             TEXT,
            approved_at             TEXT,
            diagnosis_id            TEXT,        -- FK → diagnoses.id
            created_at              TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (diagnosis_id) REFERENCES diagnoses(id)
        );

        CREATE TABLE IF NOT EXISTS interactions (
            id          TEXT PRIMARY KEY,
            timestamp   TEXT NOT NULL,
            role        TEXT NOT NULL,           -- user | agent | system
            content     TEXT NOT NULL,
            context     TEXT,                    -- JSON: estado de planta al momento
            tokens_used INTEGER DEFAULT 0,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS knowledge (
            id          TEXT PRIMARY KEY,
            timestamp   TEXT NOT NULL,
            source      TEXT NOT NULL,           -- operator | inference | document
            tag_ids     TEXT,                    -- JSON array de tags relacionados
            content     TEXT NOT NULL,
            confidence  REAL DEFAULT 1.0,
            validated   INTEGER DEFAULT 0,       -- 0=no validado, 1=validado por operario
            created_at  TEXT DEFAULT (datetime('now'))
        );

        -- Índices para queries frecuentes
        CREATE INDEX IF NOT EXISTS idx_events_ts    ON events(timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_events_sev   ON events(severity);
        CREATE INDEX IF NOT EXISTS idx_diag_ts      ON diagnoses(timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_actions_st   ON actions(status);
        CREATE INDEX IF NOT EXISTS idx_actions_ts   ON actions(timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_interact_ts  ON interactions(timestamp DESC);
        """)
        self._conn.commit()

    # ── MemoryStore interface ─────────────────────────────────────────────────

    def save_event(self, event: AnomalyEvent) -> str:
        event_id = str(uuid.uuid4())
        self._conn.execute(
            """INSERT INTO events (id, timestamp, tag_ids, score, severity, description, raw_values)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id,
                event.timestamp.isoformat(),
                json.dumps(event.tag_ids),
                event.anomaly_score,
                event.severity.value,
                event.description,
                json.dumps(event.raw_values),
            )
        )
        self._conn.commit()
        return event_id

    def save_diagnosis(self, diagnosis: Diagnosis, event_id: Optional[str] = None) -> str:
        diag_id = diagnosis.id or str(uuid.uuid4())
        self._conn.execute(
            """INSERT OR REPLACE INTO diagnoses
               (id, timestamp, probable_cause, confidence, tags_involved, urgency, evidence, context_tokens, event_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                diag_id,
                diagnosis.timestamp.isoformat(),
                diagnosis.probable_cause,
                diagnosis.confidence,
                json.dumps(diagnosis.tags_involved),
                diagnosis.urgency,
                json.dumps(diagnosis.evidence),
                diagnosis.context_sent_tokens,
                event_id,
            )
        )
        self._conn.commit()
        return diag_id

    def save_action(self, action: RecommendedAction, diagnosis_id: Optional[str] = None) -> str:
        action_id = action.id or str(uuid.uuid4())
        self._conn.execute(
            """INSERT OR REPLACE INTO actions
               (id, timestamp, machine_id, action_type, parameters, reason,
                estimated_impact, estimated_saving_eur, risk_level, status, diagnosis_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                action_id,
                action.timestamp.isoformat(),
                action.machine_id,
                action.action_type,
                json.dumps(action.parameters),
                action.reason,
                action.estimated_impact,
                action.estimated_saving_eur,
                action.risk_level.value,
                action.status.value,
                diagnosis_id,
            )
        )
        self._conn.commit()
        return action_id

    def update_action_status(
        self,
        action_id: str,
        status: ActionStatus,
        approved_by: str = "",
    ) -> None:
        self._conn.execute(
            """UPDATE actions SET status=?, approved_by=?, approved_at=?
               WHERE id=?""",
            (
                status.value,
                approved_by,
                datetime.now().isoformat() if status == ActionStatus.APPROVED else None,
                action_id,
            )
        )
        self._conn.commit()

    def get_similar_events(
        self,
        tag_ids: list[str],
        limit: int = 5,
    ) -> list[AnomalyEvent]:
        """
        Busca eventos pasados con tags similares.
        Versión simple: búsqueda por overlap de tags.
        (La versión avanzada usa ChromaDB para búsqueda semántica)
        """
        if not tag_ids:
            return []

        # Busca eventos que contengan al menos uno de los tags
        placeholders = ",".join("?" * len(tag_ids))
        rows = self._conn.execute(
            f"""SELECT * FROM events
                WHERE ({' OR '.join([f"tag_ids LIKE ?" for _ in tag_ids])})
                ORDER BY timestamp DESC LIMIT ?""",
            [f"%{tag}%" for tag in tag_ids] + [limit]
        ).fetchall()

        return [self._row_to_event(r) for r in rows]

    def get_recent_diagnoses(self, hours: int = 24) -> list[Diagnosis]:
        since = (datetime.now() - timedelta(hours=hours)).isoformat()
        rows = self._conn.execute(
            "SELECT * FROM diagnoses WHERE timestamp > ? ORDER BY timestamp DESC",
            (since,)
        ).fetchall()
        return [self._row_to_diagnosis(r) for r in rows]

    # ── Métodos adicionales ───────────────────────────────────────────────────

    def save_interaction(
        self,
        role: str,
        content: str,
        context: Optional[dict] = None,
        tokens_used: int = 0,
    ) -> str:
        interaction_id = str(uuid.uuid4())
        self._conn.execute(
            """INSERT INTO interactions (id, timestamp, role, content, context, tokens_used)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                interaction_id,
                datetime.now().isoformat(),
                role,
                content,
                json.dumps(context) if context else None,
                tokens_used,
            )
        )
        self._conn.commit()
        return interaction_id

    def save_knowledge(
        self,
        content: str,
        source: str,
        tag_ids: Optional[list[str]] = None,
        confidence: float = 1.0,
        validated: bool = False,
    ) -> str:
        knowledge_id = str(uuid.uuid4())
        self._conn.execute(
            """INSERT INTO knowledge (id, timestamp, source, tag_ids, content, confidence, validated)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                knowledge_id,
                datetime.now().isoformat(),
                source,
                json.dumps(tag_ids or []),
                content,
                confidence,
                1 if validated else 0,
            )
        )
        self._conn.commit()
        return knowledge_id

    def get_recent_interactions(self, limit: int = 10) -> list[dict]:
        """Recupera el historial reciente de chat para pasarlo al LLM."""
        rows = self._conn.execute(
            """SELECT role, content FROM interactions
               WHERE role IN ('user', 'agent')
               ORDER BY created_at DESC LIMIT ?""",
            (limit,)
        ).fetchall()
        # Devuelve en orden cronológico con roles compatibles con la API de Claude
        result = []
        for row in reversed(rows):
            result.append({
                "role": "assistant" if row["role"] == "agent" else "user",
                "content": row["content"],
            })
        return result

    def get_pending_actions(self) -> list[RecommendedAction]:
        rows = self._conn.execute(
            "SELECT * FROM actions WHERE status=? ORDER BY timestamp DESC",
            (ActionStatus.PENDING.value,)
        ).fetchall()
        return [self._row_to_action(r) for r in rows]

    def get_stats(self) -> dict:
        stats = {}
        for table in ["events", "diagnoses", "actions", "interactions", "knowledge"]:
            row = self._conn.execute(f"SELECT COUNT(*) as n FROM {table}").fetchone()
            stats[f"total_{table}"] = row["n"]

        row = self._conn.execute(
            "SELECT COUNT(*) as n FROM actions WHERE status='pending'"
        ).fetchone()
        stats["pending_actions"] = row["n"]

        row = self._conn.execute(
            "SELECT AVG(confidence) as avg FROM diagnoses WHERE timestamp > ?",
            ((datetime.now() - timedelta(hours=24)).isoformat(),)
        ).fetchone()
        stats["avg_diagnosis_confidence_24h"] = round(row["avg"] or 0, 3)

        return stats

    def get_audit_log(self, limit: int = 100) -> list[dict]:
        """Log de auditoría completo para el historial del dashboard."""
        rows = self._conn.execute("""
            SELECT 'event' as type, id, timestamp, description as content, severity, NULL as machine_id
            FROM events
            UNION ALL
            SELECT 'diagnosis', id, timestamp, probable_cause, CAST(urgency as TEXT), NULL
            FROM diagnoses
            UNION ALL
            SELECT 'action', id, timestamp, action_type || ': ' || reason, status, machine_id
            FROM actions
            ORDER BY timestamp DESC LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]

    # ── Deserialización ───────────────────────────────────────────────────────

    def _row_to_event(self, row) -> AnomalyEvent:
        return AnomalyEvent(
            timestamp=datetime.fromisoformat(row["timestamp"]),
            tag_ids=json.loads(row["tag_ids"]),
            anomaly_score=row["score"],
            severity=Severity(row["severity"]),
            description=row["description"],
            raw_values=json.loads(row["raw_values"] or "{}"),
        )

    def _row_to_diagnosis(self, row) -> Diagnosis:
        return Diagnosis(
            id=row["id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            probable_cause=row["probable_cause"],
            confidence=row["confidence"],
            tags_involved=json.loads(row["tags_involved"]),
            urgency=row["urgency"],
            evidence=json.loads(row["evidence"] or "[]"),
            context_sent_tokens=row["context_tokens"] or 0,
        )

    def _row_to_action(self, row) -> RecommendedAction:
        return RecommendedAction(
            id=row["id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            machine_id=row["machine_id"],
            action_type=row["action_type"],
            parameters=json.loads(row["parameters"] or "{}"),
            reason=row["reason"] or "",
            estimated_impact=row["estimated_impact"] or "",
            estimated_saving_eur=row["estimated_saving_eur"] or 0,
            risk_level=Severity(row["risk_level"] or "low"),
            status=ActionStatus(row["status"]),
            approved_by=row["approved_by"],
            approved_at=datetime.fromisoformat(row["approved_at"]) if row["approved_at"] else None,
        )

    def close(self):
        self._conn.close()
