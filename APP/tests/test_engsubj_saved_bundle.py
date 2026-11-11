"""Saved fights require the same recipient seal as newly built effects."""
import json

import pytest

from combat.gate3_storage import TYPED_BUNDLES_FILE, load_typed_bundles
from combat.saved_fight_format import UnsupportedSavedFight
from factory_authoring.effect_subjects import derive_effect_subjects


@pytest.mark.parametrize("location", ["action", "nested", "option", "rider"])
@pytest.mark.parametrize("kind", ["other", "save", "ally"])
def test_saved_effect_requires_complete_subjects(tmp_path, location, kind):
    effect = {
        "other": {"type": "condition", "condition": "prone"},
        "save": {"type": "save", "ability": "dex"},
        "ally": {"type": "speed", "applies_to": "ally"},
    }[kind]
    typed = {"source": "synthetic.source", "effects": []}
    if location == "action":
        typed["effects"] = [effect]
    elif location == "nested":
        typed["effects"] = [{"type": "attack", "on_hit": [{"type": "save", "on_fail": [effect]}]}]
    elif location == "option":
        typed["options"] = [{"effects": [effect]}]
    else:
        typed["riders"] = [{"effects": [effect]}]
    derive_effect_subjects(typed)
    bundle = {
        "actor_id": "actor:synthetic.source",
        "actor_template": {
            "entity_id": "actor:synthetic.source", "display_name": "Test", "team_id": "team:test",
            "primary_combatant": True, "armor_class": 10, "maximum_hp": 10,
            "speed_ft": 30, "initiative_bonus": 0, "dexterity_score": 10,
            "proficiency_bonus": 2, "saving_throws": {}, "resources": [],
            "action_ids": ["action:test"], "reaction_ids": [],
        },
        "action_catalog": [{
            "source_definition_id": "action:test", "display_name": "Test",
            "owner_id": "actor:synthetic.source", "economy": "ACTION", "resolution_kind": "TYPED",
            "target_kind": "SELF", "parameters": {"typed": typed},
        }],
    }
    path = tmp_path / TYPED_BUNDLES_FILE
    sealed = effect.pop("subjects")
    path.write_text(json.dumps([bundle]))
    if kind == "other":
        # Non-recipient effects are not read by either subject selector.
        assert load_typed_bundles(tmp_path) == (bundle,)
    else:
        with pytest.raises(UnsupportedSavedFight) as caught:
            load_typed_bundles(tmp_path)
        assert isinstance(caught.value.__cause__, ValueError)
        assert "subjects" in str(caught.value.__cause__)
        assert effect["type"] in str(caught.value.__cause__)
        assert "synthetic.source" in str(caught.value.__cause__)

        effect["subjects"] = {**sealed}
        del effect["subjects"]["exclude_self" if kind == "save" else "or_self"]
        path.write_text(json.dumps([bundle]))
        with pytest.raises(UnsupportedSavedFight) as partial:
            load_typed_bundles(tmp_path)
        assert isinstance(partial.value.__cause__, ValueError)
        assert "subjects" in str(partial.value.__cause__)

    effect["subjects"] = sealed
    path.write_text(json.dumps([bundle]))
    assert load_typed_bundles(tmp_path) == (bundle,)


@pytest.mark.parametrize("version", ["v1", "missing", "current"])
def test_state_carried_zone_save_is_safe_across_format_boundary(tmp_path, monkeypatch, version):
    from combat.gate2_runtime_models import Position, ZoneState
    from combat.gate3_models import STORAGE_SCHEMA_VERSION
    from combat.gate3_storage import Gate3MatchStore, _match_lock_deterministic_hash
    from combat.gate5_service import CombatService, CombatServiceError
    from combat.saved_fight_format import UNSUPPORTED_CODE, UNSUPPORTED_MESSAGE
    from tests import test_tabletop_hunt6 as H
    from tests.h1_support import ROOT
    from tests.persistence_support import inventory
    from tests.test_lock2_persistence import act

    combat, table, mid = H.table_fight(tmp_path, [])
    save = {"type": "save", "ability": "dex", "applies_to": "target",
            "on_fail": [], "on_success": []}
    if version == "current":
        derive_effect_subjects(save)

    def place_zone(engine):
        zone = ZoneState(
            zone_id="zone:recipient-seal", source_definition_id="synthetic.zone",
            owner_id=H.LEFT, center=Position(x=6, y=4), radius_cells=0,
            affected_cells=(Position(x=6, y=4),), concentration_link=False,
            created_round=engine.state.round_number,
            trigger_profile={"kind": "TYPED", "numbers": {"save_dc": 10}, "triggers": [{
                "id": "test:entry", "on": ["enter"], "who": "hostile", "effects": [save],
            }]},
        )
        engine.state.zones[zone.zone_id] = zone
        engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=H.LEFT,
                             payload={"zone": zone.model_dump(mode="json")})

    H.on_hold(monkeypatch, place_zone)
    assert act(table, mid, H.HOLD)["status"] == "COMMITTED"
    store = Gate3MatchStore(tmp_path, mid)
    lock = json.loads(store.match_lock_path.read_text(encoding="utf-8"))
    assert lock["storage_schema_version"] == STORAGE_SCHEMA_VERSION
    if version == "current":
        session = CombatService(ROOT, tmp_path)._load_session(mid)
        assert session.engine.state.zones["zone:recipient-seal"].trigger_profile["triggers"][0]["effects"][0] == save
        assert session.mechanical.replay()["status"] == "PASS"
        return

    if version == "v1":
        lock["storage_schema_version"] = "TianxiaCombatMatchStorage.v1"
    else:
        del lock["storage_schema_version"]
    lock["deterministic_payload_sha256"] = _match_lock_deterministic_hash(lock)
    store.match_lock_path.write_text(json.dumps(lock) + "\n", encoding="utf-8")
    assert '"zone:recipient-seal"' in store.journal_path.read_text(encoding="utf-8")
    before = inventory(store.match_dir)
    for open_fight in (combat.get_match, table.state):
        with pytest.raises(CombatServiceError) as caught:
            open_fight(mid)
        assert caught.value.status_code == 409
        assert caught.value.diagnostic.code == UNSUPPORTED_CODE
        assert caught.value.diagnostic.message == UNSUPPORTED_MESSAGE
        assert inventory(store.match_dir) == before
    assert next(row for row in combat.list_matches() if row["match_id"] == mid)["status"] == "UNSUPPORTED"
    assert inventory(store.match_dir) == before
    table.delete_match(mid)
    assert not store.match_dir.exists()
