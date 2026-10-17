from __future__ import annotations

from typing import Any

from app.core import Database, FoundryError, utcnow


class CharacterLibraryArchiveService:
    """Own the reversible user-facing archive marker for character projects."""

    def __init__(self, db: Database):
        self.db = db
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS character_library_archives(
                   project_id TEXT PRIMARY KEY,
                   archived_at TEXT NOT NULL,
                   FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
                )"""
            )
            conn.execute(
                """CREATE INDEX IF NOT EXISTS idx_character_library_archives_archived_at
                   ON character_library_archives(archived_at, project_id)"""
            )

    @staticmethod
    def _project_not_found(project_id: str) -> FoundryError:
        return FoundryError(
            "CHARACTER_LIBRARY_PROJECT_NOT_FOUND",
            "No character project has that ID.",
            details={"project_id": project_id},
            status_code=404,
        )

    def _require_project(self, conn: Any, project_id: str) -> None:
        exists = conn.execute(
            "SELECT 1 FROM projects WHERE project_id=?",
            (project_id,),
        ).fetchone()
        if exists is None:
            raise self._project_not_found(project_id)

    def archive(self, project_id: str) -> dict[str, Any]:
        with self.db.transaction() as conn:
            self._require_project(conn, project_id)
            existing = conn.execute(
                "SELECT archived_at FROM character_library_archives WHERE project_id=?",
                (project_id,),
            ).fetchone()
            if existing is not None:
                return {
                    "project_id": project_id,
                    "archived": True,
                    "archived_at": existing["archived_at"],
                    "changed": False,
                }
            archived_at = utcnow()
            conn.execute(
                "INSERT INTO character_library_archives(project_id,archived_at) VALUES(?,?)",
                (project_id, archived_at),
            )
            return {
                "project_id": project_id,
                "archived": True,
                "archived_at": archived_at,
                "changed": True,
            }

    def restore(self, project_id: str) -> dict[str, Any]:
        with self.db.transaction() as conn:
            self._require_project(conn, project_id)
            existing = conn.execute(
                "SELECT 1 FROM character_library_archives WHERE project_id=?",
                (project_id,),
            ).fetchone()
            changed = existing is not None
            if changed:
                conn.execute(
                    "DELETE FROM character_library_archives WHERE project_id=?",
                    (project_id,),
                )
            return {
                "project_id": project_id,
                "archived": False,
                "changed": changed,
            }

    def archived_project_ids(self) -> set[str]:
        with self.db.connection() as conn:
            return {
                str(row["project_id"])
                for row in conn.execute(
                    "SELECT project_id FROM character_library_archives"
                )
            }

    def list_archived(self) -> list[dict[str, Any]]:
        with self.db.connection() as conn:
            return [
                {"project_id": str(row["project_id"]), "archived_at": row["archived_at"]}
                for row in conn.execute(
                    """SELECT project_id,archived_at FROM character_library_archives
                       ORDER BY archived_at DESC, project_id"""
                )
            ]
