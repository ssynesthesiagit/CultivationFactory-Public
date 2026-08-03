from __future__ import annotations

import json
import re
from pathlib import Path

from app.api import create_app
from app.core import APP_STATUS, APP_VERSION, Settings

ROOT = Path(__file__).resolve().parents[1]


def test_combined_api_exposes_character_and_polished_combat_authority(tmp_path):
    app = create_app(settings=Settings.from_env(ROOT, tmp_path / "data"))
    paths = {route.path for route in app.routes}
    required = {
        "/api/characters",
        "/api/characters/{project_id}/sheet",
        "/api/characters/{project_id}/gm-export/status",
        "/api/characters/{project_id}/gm-export",
        "/api/character-builder/options",
        "/api/stage1/prompts/{prompt_id}/responses/load-zip",
        "/api/combat/catalog",
        "/api/combat/matches",
        "/api/combat/matches/{match_id}/presentation",
        "/api/combat/matches/{match_id}/preview",
        "/api/combat/matches/{match_id}/intent",
    }
    assert required <= paths
    assert app.state.combat.ai_provider is app.state.ai_provider


def test_combined_owner_ui_preserves_character_workflow_and_exact_combat_workspace():
    html = (ROOT / "static/index.html").read_text(encoding="utf-8")
    js = (ROOT / "static/app.js").read_text(encoding="utf-8")
    assert "Character Sheets" in html
    assert "TIANXIA COMBAT" in html
    assert "Save ChatGPT Request ZIP" in html
    assert "Export Character ZIP for GM Screen" in html
    assert 'schema_version: "TianxiaFoundry.Stage2AdvancementProposal.v2"' in js
    ids = re.findall(r'id="([^"]+)"', html)
    assert len(ids) == len(set(ids))


def test_successor_identity_preserves_both_authoritative_parents():
    assert APP_VERSION == "0.6.6.9.2-CAT2-CANONICAL-CATALOG"
    assert APP_STATUS == "CANONICAL_CATALOG_PRODUCT_INTEGRATION_READY_COMBATANT_LIBRARY_PRE_ENCOUNTER"
    version = json.loads((ROOT / "packaging/windows_portable/VERSION.json").read_text(encoding="utf-8"))
    assert version["authoritative_polished_combat_parent_sha256"] == "1896ea1d5ec61f0f8cfc42282bd84f4369ce5605cfb777d5a553efc24dea79ce"
    assert version["character_factory_feature_parent_sha256"] == "e1a42986475354c78f858698a227bbd0959f386a6c4fa965969c0b6aa8b5e495"
