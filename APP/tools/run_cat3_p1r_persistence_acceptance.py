from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from app.core import Database, Settings
from catalog.service import CatalogService
from tests.test_cat3_p1r_persistence import run_cat3_p1r_persistence_acceptance
from vendor_adapter.service import FactoryAdapter

ROOT = Path(__file__).resolve().parents[1]
FACTORY = ROOT / "BundledContent" / "Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    data_root = args.data_root.resolve()
    if data_root.exists():
        shutil.rmtree(data_root)
    source_settings = Settings.from_env(ROOT, data_root / "source")
    source_db = Database(source_settings)
    source_db.migrate()
    configured = FactoryAdapter(source_db).configure(FACTORY)
    CatalogService(source_db).rebuild_core(Path(configured["factory_root"]))

    report = run_cat3_p1r_persistence_acceptance(
        source_db,
        target_settings=Settings.from_env(ROOT, data_root / "clean-import-target"),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
