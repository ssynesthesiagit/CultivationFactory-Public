"""Serve the unmodified production static owner application for UX1 rendering.

The browser campaign owns a fresh data root and uses the real FastAPI routes.
No prototype source or visual asset is served by this module.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api import create_app
from app.core import Settings
from catalog.service import CatalogService
from vendor_adapter.service import FactoryAdapter

FACTORY = ROOT / "BundledContent" / "Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip"


def build_application(data_root: Path):
    settings = Settings.from_env(ROOT, data_root)
    app = create_app(settings)
    configured = FactoryAdapter(app.state.db).configure(FACTORY)
    CatalogService(app.state.db).rebuild_core(Path(configured["factory_root"]))
    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    app = build_application(args.data_root)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
