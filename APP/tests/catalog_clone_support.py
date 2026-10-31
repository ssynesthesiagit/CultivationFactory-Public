"""Shared helper: copy the session catalog database and security folder into a fresh data directory."""
from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from app.core import Database, Settings

ROOT = Path(__file__).resolve().parents[1]


def _clone_catalog_db(catalog_environment: dict, data_dir: Path) -> tuple[Settings, Database]:
    settings = Settings.from_env(ROOT, data_dir)
    settings.ensure_dirs()
    source = sqlite3.connect(catalog_environment["settings"].db_path)
    target = sqlite3.connect(settings.db_path)
    source.backup(target)
    target.close()
    source.close()
    source_security = catalog_environment["settings"].data_dir / "security"
    target_security = settings.data_dir / "security"
    if source_security.is_dir():
        shutil.copytree(source_security, target_security, dirs_exist_ok=True, copy_function=shutil.copy2)
    db = Database(settings)
    db.migrate()
    return settings, db
