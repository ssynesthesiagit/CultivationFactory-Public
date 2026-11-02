"""SOL157: actual table batches, custody boundaries and project sheet defaults."""
import json

import pytest

from combat.canonical import canonical_sha256
from combat.gate2_runtime_models import ActionIntent
from combat.gate3_storage import Gate3InjectedCrash
from combat.gate3_reducer import canonical_state_sha256
from combat.gate5_service import CombatService
from combat.tabletop import TabletopError
from combat.tabletop_service import TabletopService
from combat.ext.attack_modifiers import chosen
from combat.ext.setting_choices import BATCH_KIND
from tests.hunt36_support import LEFT, RIGHT, ROOT, fight, turn
from tests.test_ocf7_nullifying_toggle import rolls

NULL = "TAL_VOID_NULLIFYING_STRIKE"
NEEDLE = "TAL_VOID_VOID_NEEDLE"


def sources(engine, count=9):
    rows = [a for a in engine.action_catalog.values() if (a.parameters.get("attack_modifier_setting") or {}).get("modifier") == NULL]
    groups = {}
    for action in rows:
        spec = action.parameters["attack_modifier_setting"]
        if spec["field"] != "on" and spec["value"] != "ask":
            groups[(spec["family"], spec["modifier"], spec["field"])] = action.source_definition_id
    return list(groups.values())[:count]


def test_non_rider_setting_commits_reloads_and_renders_project_and_match_receipts(tmp_path, monkeypatch):
    """A hook-approved preference never needs attack-modifier parameters."""
    from copy import deepcopy
    from combat import ext, factory_compiler
    from tests import hunt36_support
    source = "action:test.generic.preference"
    effect = {"type": "b3f4_test_preference", "value": "quiet"}
    original = factory_compiler.compile_character

    def compile_generic(*args, **kwargs):
        bundle = original(*args, **kwargs)
        if bundle["actor_id"] == LEFT:
            action = deepcopy(next(row for row in bundle["action_catalog"] if row["resolution_kind"] == "TYPED"))
            action.update(source_definition_id=source, display_name="Quiet preference", economy="NONE", target_kind="SELF", costs=[])
            action["parameters"] = {"setting_only": True, "typed": {"effects": [effect], "numbers": {}, "riders": []}}
            bundle["action_catalog"].append(action)
            bundle["actor_template"]["action_ids"].append(source)
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)
        return bundle

    ext.effects()  # Load production plug-ins before isolating the test registry.
    hooks = {key: list(rows) for key, rows in ext._HOOKS.items()}
    monkeypatch.setattr(ext, "_HOOKS", hooks)
    monkeypatch.setattr(ext, "_HOOK_PRIORITIES", dict(ext._HOOK_PRIORITIES))
    @ext.hook("settings_batch_key")
    def approve(action):
        return ("test", "preference") if action.source_definition_id == source and action.parameters["typed"]["effects"] == [effect] else None

    effects = dict(ext._EFFECTS)
    monkeypatch.setattr(ext, "_EFFECTS", effects)
    monkeypatch.setattr(ext, "_EFFECT_HARM", dict(ext._EFFECT_HARM))
    @ext.effect("b3f4_test_preference")
    def apply(ctx, row):
        ctx.engine._apply_condition(ctx.actor, "condition:test.preference", ctx.source,
                                    ctx.actor.entity_id, expires_on="UNTIL_REMOVED", data={"value": row["value"]})

    monkeypatch.setattr(hunt36_support, "compile_character", compile_generic)
    monkeypatch.setattr(factory_compiler, "compile_character", compile_generic)
    combat, table, mid = fight(tmp_path, [NULL], seed="B3F4-generic", primary="Stamina", cl=5)
    turn(combat, table, mid)
    reply = table.save_settings(mid, LEFT, [source], "generic")
    assert reply["rows"][0]["source"] == source and reply["modifier_rows"] == []
    loaded = CombatService(ROOT, combat.userdata_root)._load_session(mid)
    assert any(row.data == {"value": "quiet"} for row in loaded.engine.state.actors[LEFT].conditions.values())
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"
    assert table.save_settings(mid, LEFT, [source], "generic")["modifier_rows"] == []
    project = LEFT.removeprefix("actor:factory.")
    reply = table.save_project_settings(project, [source])
    assert reply["rows"][0]["source"] == source and reply["modifier_rows"] == []
    assert isinstance(table.sheet(project)["attack_modifier_rows"], list)


@pytest.fixture
def table_fight(tmp_path):
    combat, table, mid = fight(tmp_path, [NULL, NEEDLE], primary="Stamina", cl=5, seed="SOL157")
    turn(combat, table, mid)
    return combat, table, mid


def test_nine_changes_one_commit_reload_reexecution_and_retry(table_fight):
    combat, table, mid = table_fight
    before = combat._load_session(mid)
    actions = sources(before.engine)
    assert len(actions) == 9
    state = before.engine.state.model_copy(deep=True)
    reply = table.save_settings(mid, LEFT, actions, "nine")
    assert len(reply["rows"]) == 9 and "state" not in reply
    assert len(reply["modifier_rows"]) == 3
    loaded = CombatService(ROOT, combat.userdata_root)._load_session(mid)
    assert loaded.engine.state.state_version == state.state_version + 1
    assert loaded.engine.state.current_actor_id == state.current_actor_id
    for field in ("action_available", "bonus_action_available", "reaction_available", "movement_remaining_ft", "turn_flags"):
        assert getattr(loaded.engine.state.actors[LEFT], field) == getattr(state.actors[LEFT], field)
    assert loaded.engine.state.actors[LEFT].resources == state.actors[LEFT].resources
    assert loaded.engine.state.roll_counter == state.roll_counter
    for source in actions:
        spec = loaded.engine.action_catalog[source].parameters["attack_modifier_setting"]
        assert chosen(loaded.engine.state.actors[LEFT], spec["family"], spec["modifier"])[spec["field"]] == spec["value"]
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"
    assert loaded.verify()["controller_open_transactions"] == []
    journal = loaded.store.journal_path.read_bytes()
    table.save_settings(mid, LEFT, actions, "nine")
    assert loaded.store.journal_path.read_bytes() == journal
    with pytest.raises(TabletopError, match="different settings"):
        table.save_settings(mid, LEFT, actions[:1], "nine")


def test_rejects_wrong_owner_arbitrary_free_actions_and_pending_choices(table_fight):
    combat, table, mid = table_fight
    session = combat._load_session(mid)
    action = sources(session.engine, 1)[0]
    before = session.store.journal_path.read_bytes()
    with pytest.raises(TabletopError):
        table.save_settings(mid, RIGHT, [action], "wrong-owner")
    toggle = next(a.source_definition_id for a in session.engine.action_catalog.values()
                  if (a.parameters.get("attack_modifier_setting") or {}).get("field") == "on")
    with pytest.raises(TabletopError):
        table.save_settings(mid, LEFT, [toggle], "toggle")
    with pytest.raises(TabletopError):
        table.save_settings(mid, LEFT, ["turn:end"], "not-settings")
    table._pending_action_path(mid).write_text('{}')
    with pytest.raises(TabletopError, match="open combat question"):
        table.save_settings(mid, LEFT, [action], "pending")
    assert session.store.journal_path.read_bytes() == before


def test_setting_is_available_off_turn_and_cache_invalidates_control_change(table_fight):
    combat, table, mid = table_fight
    action = sources(combat._load_session(mid).engine, 1)[0]
    table.save_settings(mid, LEFT, [action], "first")
    turn(combat, table, mid, RIGHT)
    table.save_settings(mid, LEFT, [action], "off-turn")
    path = combat._metadata_path(mid)
    doc = json.loads(path.read_text())
    doc["participant_control_modes"][LEFT] = "LOCAL_AUTO"
    path.write_text(json.dumps(doc))
    with pytest.raises(TabletopError, match="player-controlled"):
        table.save_settings(mid, LEFT, [action], "ai")


@pytest.mark.parametrize("stage", ["after_prepare_flush", "during_resolution", "after_commit_flush_before_manifest"])
def test_batch_crash_recovers_exactly_once(table_fight, stage):
    combat, table, mid = table_fight
    session = combat._load_session(mid)
    actions = sources(session.engine, 3)
    binding = {"kind": BATCH_KIND, "sources": actions}
    intent = ActionIntent(intent_id="settings:crash", decision_id="settings:v1", candidate_id=canonical_sha256(binding),
                          state_version=session.engine.state.state_version, actor_id=LEFT, target_ids=(LEFT,))
    before = session.engine.state.state_version
    def crash(point, _context):
        if point == stage:
            raise Gate3InjectedCrash(stage)
    with pytest.raises(Gate3InjectedCrash):
        session.submit_intent(intent, primary_decision_record=None, reaction_provider=None,
                              settings_binding=binding, failure_injector=crash)
    loaded = CombatService(ROOT, combat.userdata_root)._load_session(mid)
    assert loaded.engine.state.state_version == before + 1
    assert loaded.verify()["controller_open_transactions"] == []
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"
    assert sum(r["record_type"] == "COMMIT" and r["intent"]["intent_id"] == intent.intent_id
               for r in loaded.mechanical._records) == 1


def test_ordinary_resolution_error_restores_entire_batch(table_fight, monkeypatch):
    combat, table, mid = table_fight
    session = combat._load_session(mid)
    actions = sources(session.engine, 3)
    from combat import typed_executor
    real = typed_executor.run_effects
    calls = []
    def failed(ctx, effects):
        calls.append(ctx)
        if len(calls) == 2:
            raise ValueError("injected setting failure")
        return real(ctx, effects)
    monkeypatch.setattr(typed_executor, "run_effects", failed)
    binding = {"kind": BATCH_KIND, "sources": actions}
    intent = ActionIntent(intent_id="settings:abort", decision_id="settings:v1", candidate_id=canonical_sha256(binding),
                          state_version=session.engine.state.state_version, actor_id=LEFT, target_ids=(LEFT,))
    before = canonical_state_sha256(session.engine.state)
    with pytest.raises(ValueError, match="injected"):
        session.submit_intent(intent, primary_decision_record=None, reaction_provider=None, settings_binding=binding)
    assert canonical_state_sha256(session.engine.state) == before
    loaded = CombatService(ROOT, combat.userdata_root)._load_session(mid)
    assert canonical_state_sha256(loaded.engine.state) == before
    assert loaded.verify()["controller_open_transactions"] == []


def test_controller_gap_after_durable_commit_is_reconciled(table_fight):
    from combat.diagnostics import CombatGate1Error
    from combat.gate3_storage import LocalMatchWriterLock
    combat, table, mid = table_fight
    actions = sources(combat._load_session(mid).engine, 1)
    table.save_settings(mid, LEFT, actions, "gap")
    path = combat._match_dir(mid) / "ControllerJournal.ndjson"
    rows = path.read_bytes().splitlines(keepends=True)
    path.write_bytes(b''.join(rows[:-1]))  # exact crash gap: controller COMMIT never flushed
    before = path.read_bytes()
    with LocalMatchWriterLock(combat._match_dir(mid) / '.settings_audit.lock', mid):
        with pytest.raises(CombatGate1Error) as busy:
            combat.persistence.load_match(mid)
        assert busy.value.diagnostic.code == 'MATCH_STORAGE_LOCKED'
        assert path.read_bytes() == before
    loaded = CombatService(ROOT, combat.userdata_root)._load_session(mid)
    assert loaded.verify()["controller_open_transactions"] == []
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


def test_outside_combat_sheet_defaults_freeze_in_next_fight(table_fight):
    combat, table, mid = table_fight
    project = LEFT.removeprefix("actor:factory.")
    actions = sources(combat._load_session(mid).engine, 3)
    reply = table.save_project_settings(project, actions)
    assert len(reply["rows"]) == 3
    sheet = table.sheet(project)
    assert sheet["attack_modifier_rows"]
    new = combat.create_factory_match(project_ids=[project], control_modes={LEFT: "MANUAL"}, match_seed="SOL157-defaults")
    loaded = combat._load_session(new["match_id"])
    for source in actions:
        spec = loaded.engine.action_catalog[source].parameters["attack_modifier_setting"]
        assert chosen(loaded.engine.state.actors[LEFT], spec["family"], spec["modifier"])[spec["field"]] == spec["value"]
    before = canonical_state_sha256(loaded.engine.state)
    table.save_project_settings(project, [actions[0]])
    assert canonical_state_sha256(CombatService(ROOT, combat.userdata_root)._load_session(new["match_id"]).engine.state) == before
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


def test_sheet_cache_accepts_decimal_authoring_metadata_and_invalidates(table_fight, monkeypatch):
    """A purchase budget is authoring data; opening its public sheet must work."""
    from copy import deepcopy
    from combat import factory_compiler

    combat, table, _mid = table_fight
    project = LEFT.removeprefix("actor:factory.")
    original_sheet = combat._factory_owner_sheet
    sheet = deepcopy(original_sheet(project))
    equipment = sheet.setdefault("equipment", [])
    kit = next((row["starting_kit"] for row in equipment
                if isinstance(row, dict) and row.get("starting_kit")), None)
    if kit is None:
        kit = {}
        equipment.append({"starting_kit": kit})
    plan = kit.setdefault("resolved_treasure_purchases", {}).setdefault("plan", {})
    plan["budget_gt"] = 0.5
    monkeypatch.setattr(combat, "_factory_owner_sheet", lambda _project: deepcopy(sheet))
    compile_character = factory_compiler.compile_character
    calls = []

    def compile_once(*args, **kwargs):
        calls.append(1)
        return compile_character(*args, **kwargs)

    monkeypatch.setattr(factory_compiler, "compile_character", compile_once)
    first = table.sheet(project)
    second = table.sheet(project)
    assert first["buttons"] == second["buttons"]
    assert len(calls) == 1
    plan["budget_gt"] = 0.75
    table.sheet(project)
    assert len(calls) == 2


def test_the_next_attack_uses_the_accepted_batch(table_fight, rolls):
    from tests.test_ocf7_nullifying_toggle import setting, strike, HIT_THEN_FAILED_SAVE
    rolls(HIT_THEN_FAILED_SAVE)
    combat, table, mid = table_fight
    engine = combat._load_session(mid).engine
    attack = "Void Needle: Unsettle Invisibility"
    family = next(a.source_definition_id for a in engine.action_catalog.values() if a.display_name == attack)
    setting(combat, table, mid, family, "on", "toggle")
    picks = {"payment": "0", "option": "0", "damage": "necrotic"}
    actions = [a.source_definition_id for a in engine.action_catalog.values()
               if (spec := a.parameters.get("attack_modifier_setting")) and spec["family"] == family
               and spec["modifier"] == NULL and picks.get(spec["field"]) == spec["value"]]
    before = combat._load_session(mid).engine.state.actors[LEFT].resources["resource:core.stamina"]
    table.save_settings(mid, LEFT, actions, "before-hit")
    strike(combat, table, mid, attack)
    loaded = combat._load_session(mid)
    assert loaded.engine.state.actors[LEFT].resources["resource:core.stamina"] == before - 2
    assert any(e.event_type == "DAMAGE_COMMITTED" and e.payload.get("damage_type") == "NECROTIC"
               and e.payload.get("display_source_id") == f"passive:{NULL}" for e in loaded.engine.events)
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


def test_settings_api_requires_token_and_returns_compact_rows(table_fight):
    from app.api import create_app
    from app.core import Settings
    from fastapi.testclient import TestClient
    combat, table, mid = table_fight
    actions = sources(combat._load_session(mid).engine, 3)
    with TestClient(create_app(Settings.from_env(ROOT, combat.userdata_root))) as client:
        payload = {"actor_id": LEFT, "sources": actions, "request_id": "api-batch"}
        url = f"/api/tabletop/matches/{mid}/settings"
        assert client.post(url, json=payload).status_code == 403
        headers = {"X-Foundry-Token": client.get('/api/session').json()['token']}
        reply = client.post(url, json=payload, headers=headers)
        assert reply.status_code == 200, reply.text
        assert len(reply.json()['rows']) == 3 and reply.json()['modifier_rows'] and 'state' not in reply.json()
        before = combat._match_dir(mid).joinpath('Journal.ndjson').read_bytes()
        assert client.post(url, json=payload, headers=headers).status_code == 200
        assert combat._match_dir(mid).joinpath('Journal.ndjson').read_bytes() == before
        outside = f"/api/tabletop/characters/{LEFT.removeprefix('actor:factory.')}/settings"
        assert client.post(outside, json=payload, headers=headers).status_code == 200


def test_project_settings_translate_another_writers_lock_to_a_plain_error(table_fight, monkeypatch):
    from combat.gate3_storage import LocalMatchWriterLock
    import combat.tabletop_service as service
    combat, table, mid = table_fight
    actions = sources(combat._load_session(mid).engine, 1)
    root = combat.userdata_root / 'tabletop_presets'
    root.mkdir()
    monkeypatch.setattr(service, 'TABLE_BUSY_WAIT_S', 0)
    with LocalMatchWriterLock(root / '.tabletop_action.lock', 'presets'):
        with pytest.raises(TabletopError, match='still finishing'):
            table.save_project_settings(LEFT.removeprefix('actor:factory.'), actions)


def test_warm_cache_rechecks_saved_genesis_integrity(table_fight, monkeypatch):
    from combat.gate5_service import CombatServiceError
    combat, table, mid = table_fight
    actions = sources(combat._load_session(mid).engine, 1)
    table.save_settings(mid, LEFT, actions, 'prime-genesis')
    path = combat._match_dir(mid) / 'GenesisState.json'
    genesis = json.loads(path.read_text())
    genesis['state']['actors'][LEFT]['current_hp'] -= 1
    path.write_text(json.dumps(genesis))
    corrupted = path.read_bytes()
    original = combat._load_session
    reloaded = []
    def load(mid):
        reloaded.append(mid)
        return original(mid)
    monkeypatch.setattr(combat, '_load_session', load)
    with pytest.raises(CombatServiceError):
        table.save_settings(mid, LEFT, actions, 'changed-genesis')
    assert reloaded == [mid]
    assert path.read_bytes() == corrupted


def test_warm_cache_ignores_retired_controller_metadata(table_fight, monkeypatch):
    combat, table, mid = table_fight
    actions = sources(combat._load_session(mid).engine, 1)
    table.save_settings(mid, LEFT, actions, 'prime-current-cache')
    path = combat._match_dir(mid) / 'ControllerLock.json'
    path.write_bytes(b'retired controller source pins\n')
    original = combat._load_session
    reloaded = []
    def load(mid):
        reloaded.append(mid)
        return original(mid)
    monkeypatch.setattr(combat, '_load_session', load)

    reply = table.save_settings(mid, LEFT, actions, 'same-current-cache')
    assert reply['rows'] and reloaded == []
    assert path.read_bytes() == b'retired controller source pins\n'


def test_warm_cache_cannot_append_after_an_earlier_journal_record_changes(table_fight):
    from combat.gate5_service import CombatServiceError
    combat, table, mid = table_fight
    actions = sources(combat._load_session(mid).engine, 1)
    table.save_settings(mid, LEFT, actions, 'prime-journal')
    path = combat._match_dir(mid) / 'Journal.ndjson'
    before = path.read_bytes()
    corrupt = before.replace(b'SETTINGS_BATCH_V1', b'SETTINGS_BATCH_V0', 1)
    assert corrupt != before and len(corrupt) == len(before) and corrupt[-512:] == before[-512:]
    path.write_bytes(corrupt)
    with pytest.raises(CombatServiceError):
        table.save_settings(mid, LEFT, actions, 'changed-journal')
    assert path.read_bytes() == corrupt
