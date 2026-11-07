"""Batch 3 integration seams: DC providers coexist and proof regeneration fails closed."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from combat import ext, typed_executor
from tools import automation_truth_pins as pins


def test_native_condition_catalog_explains_flight_grappling_and_aim():
    """Public sheet/area help explains new condition pills without raw keys."""
    from combat.condition_text import condition_reading

    phrases = {
        "aimed_line": "total cover",
        "brute_court_grapple_size": "grapple",
        "brute_muscular_surge_grapple_size": "grapple",
        "brute_sovereign_grapple_size": "grapple",
        "daemonic_emperor_flight": "fly speed",
        "daemonic_inner_flight": "fly speed",
        "drunken_sovereign_flight": "fly speed",
        "radiance_heavenly_flight": "fly speed",
        "shadow_sovereign_flight": "fly speed",
        "void_sovereign_flight": "fly speed",
    }
    for key, phrase in phrases.items():
        reading = condition_reading(key)
        assert reading is not None, key
        text = reading[1]
        assert phrase in text.lower(), (key, text)
        assert key not in text and "combat/" not in text, (key, text)


def test_lightning_manual_hit_help_explains_cost_save_and_expiry():
    """Unsupported hit deliveries retain a usable player-facing GM fallback."""
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    document = json.loads((root / "authority/typed_mechanics/reviewed_final.d/elements.json").read_text())
    row = document.get("mechanics", document).get("TAL_LIGHTNING_MERIDIAN_STOPPING_SPARK")
    text = " ".join(row["riders"])
    for phrase in ("Charged Needle", "Conductive Strike", "Game Master", "1 CP",
                   "Constitution", "end of its next turn", "start of its next turn",
                   "cannot take Reactions", "CP it already holds is unchanged"):
        assert phrase in text
    assert "combat/" not in text and ".py" not in text


def test_yin_healing_compiler_registration_remains_statically_enumerable():
    import ast
    from combat.ext import healing_interception
    from tools.automation_truth_plugins import _assignments, _block_guards

    tree = ast.parse(Path(healing_interception.__file__).read_text())
    assignments, _ = _assignments(tree)
    compiler = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_compile")
    assert set(_block_guards(compiler, assignments)) == {
        "reversing_pulse", "diminish_recovery", "wound_that_refuses_dawn",
        "yin_stillness_has_teeth", "yin_borrowed_consequence",
        "yin_return_overextension", "yin_still_bright_strike",
    }


def test_targeting_occluder_and_settings_provenance_coexist_after_table_reload(tmp_path):
    import json
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from combat.ext.attack_modifiers import chosen
    from combat.ext.setting_choices import BATCH_KIND
    from combat.terrain_occlusion import CROSS_POLICY
    from tests.hunt36_support import LEFT, RIGHT, ROOT, fight
    from tests.test_sol157_presets import NULL, NEEDLE, sources

    combat, table, first = fight(tmp_path, [NULL, NEEDLE], primary="Stamina", cl=5, seed="SOL158-PRESETS")
    selected = sources(combat._load_session(first).engine, 3)
    project = LEFT.removeprefix("actor:factory.")
    table.save_project_settings(project, selected)
    bamboo = json.loads((ROOT / "combat/maps/builtin-bamboo-forest-ravine.json").read_text())
    mid = combat.create_factory_match(project_ids=[project], opponent_actor_ids=[RIGHT],
        control_modes={LEFT: "MANUAL", RIGHT: "MANUAL"},
        arena_id="battlefield:map." + bamboo["map_id"], match_seed="SOL158-POLICIES")["match_id"]
    session = combat._load_session(mid)
    genesis = next(e.payload for e in session.engine.events if e.event_type == "MATCH_CREATED")
    expected_targeting = {"concealment_miss_percent": 0, "total_concealment_miss_percent": 0}
    assert genesis["targeting_policy"] == expected_targeting
    assert genesis["terrain_occlusion_policy"] == CROSS_POLICY
    for source in selected:
        spec = session.engine.action_catalog[source].parameters["attack_modifier_setting"]
        assert chosen(session.engine.state.actors[LEFT], spec["family"], spec["modifier"])[spec["field"]] == spec["value"]
    table.save_settings(mid, LEFT, selected, "SOL158-BATCH")
    state = table.state(mid)
    menu = state["menu"]
    assert table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], state["last_sequence"], [])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, combat.userdata_root)._load_session(mid)
    fresh = next(e.payload for e in loaded.engine.events if e.event_type == "MATCH_CREATED")
    assert fresh["targeting_policy"] == expected_targeting
    assert fresh["terrain_occlusion_policy"] == CROSS_POLICY
    assert loaded.engine.grid.occluder_policy == CROSS_POLICY
    journal = [json.loads(line) for line in loaded.controller_journal_path.read_text().splitlines()]
    assert any((row.get("settings_policy") or {}).get("kind") == BATCH_KIND for row in journal)
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


def test_poison_check_penalty_retains_meridian_save_dc_through_table_reload(tmp_path):
    import copy
    import json
    from combat.ext import qi_path
    from combat.ext.poison import NEXT_CHECK
    from combat.gate5_service import CombatService
    from tests import auto_worker1_support as H
    from tests.test_auto2_paths_b import DOSE, MERIDIAN

    authority = json.loads((H.ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())["mechanics"]
    delivery = next(fx for fx in authority[DOSE]["effects"][0]["on_hit"] if fx["type"] == "poison_delivery_save")
    penalty = copy.deepcopy(next(fx for fx in delivery["effects"][0]["on_fail"] if fx["type"] == "poison_next_check"))

    def source_provenance(bundle):
        if bundle["actor_id"] == H.RIGHT:
            setup = next(a for a in bundle["action_catalog"] if a["display_name"] == "Cause")
            setup["parameters"]["typed"]["source"] = DOSE

    # A committed synthetic save supplies the printed failure's real effect row.
    # DC 100 makes the fixture outcome certain; the production effect supplies
    # the condition and provenance, with no hand-written stored condition.
    combat, table, mid = H.fight(tmp_path, [MERIDIAN], right_talents=[DOSE],
        cause=[{"type": "save", "ability": "con", "applies_to": "target", "on_fail": [penalty]}],
        cause_save_dc=100, bundle_edit=source_provenance)
    H.turn(table, mid, H.RIGHT)
    H.settle(lambda answers: H.act(table, mid, "Cause", answers, target_id=H.LEFT))
    H.settle(lambda answers: H.act(table, mid, "end", answers))
    loaded = CombatService(H.ROOT, combat.userdata_root)._load_session(mid)
    target = loaded.engine.state.actors[H.LEFT]
    condition = next(c for c in target.conditions.values() if c.condition_id == NEXT_CHECK)
    assert condition.data["origin_save"] == {"ability": "CON", "dc": 100}
    assert any(row[1].instance_id == condition.instance_id and row[2:] == ("Disadvantage on ability checks", 100)
               for row in qi_path._suppressible(loaded.engine, target))
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


def test_meridian_generic_check_reader_does_not_remove_unrelated_composite_effects():
    from combat.ext import qi_path
    condition = SimpleNamespace(condition_id="condition:typed.custom_composite", data={
        "rule": {"check_mode": {"ALL": "DISADVANTAGE"}, "no_reactions": True}})
    assert qi_path._condition_penalty(condition) == ""


def test_suppressed_poison_one_check_is_consumed_when_the_check_happens():
    from combat.ext.benefit_suppression import SUPPRESSED, suppress
    from combat.ext.poison import NEXT_CHECK
    from tests.test_auto2_paths_b import ALLY, ME, DOSE, _meridian_engine, _typed_action, _fail_a_printed_save

    engine = _meridian_engine(talents=(DOSE,))
    target = engine.state.actors[ALLY]
    _fail_a_printed_save(engine, DOSE, target, {"ability": "CON", "dc": 14})
    held = next(c for c in target.conditions.values() if c.condition_id == NEXT_CHECK)
    assert suppress(engine, engine.state.actors[ME], target, "condition:" + held.instance_id,
                    "holder_turn_end", "test:suppression")
    engine._apply_condition(target, "condition:typed.invisible", "test:unrelated", ME,
                            expires_on="END_OF_SOURCE_NEXT_TURN")
    unrelated = next(c for c in target.conditions.values() if c.condition_id == "condition:typed.invisible")
    assert suppress(engine, engine.state.actors[ME], target, "condition:" + unrelated.instance_id,
                    "holder_turn_end", "test:unrelated-suppression")
    _, action, typed = _typed_action(engine, DOSE)
    ctx = typed_executor.Context(engine, target, action, None, typed, [], None)
    typed_executor.resolve_opposed_check(ctx, target, {"skill": "Perception", "ability": "wis", "bonus": 0},
                                        {"kind": "dc", "dc": 10})
    assert any(e.event_type == "CHECK_ROLLED" and e.actor_id == ALLY for e in engine.events)
    assert not any(c.condition_id == NEXT_CHECK or (c.condition_id == SUPPRESSED and
                   (c.data.get("model") or {}).get("condition_id") == NEXT_CHECK) for c in target.conditions.values())
    assert any(c.condition_id == SUPPRESSED and (c.data.get("model") or {}).get("instance_id") == unrelated.instance_id
               for c in target.conditions.values())


def test_dc_lookup_keeps_literal_basis_and_named_provider_contracts(monkeypatch):
    ctx = SimpleNamespace(engine=object())
    target = SimpleNamespace(entity_id="actor:target")
    monkeypatch.setattr("combat.save_dcs.save_dc", lambda engine, actor, basis: {"cultivation_save_dc": 18}[basis])
    monkeypatch.setattr(ext, "run", lambda hook, *args: [23] if hook == "check_dc" else [])
    assert typed_executor.dc_of(ctx, target, {"dc": 15}) == 15
    assert typed_executor.dc_of(ctx, target, {"basis": "cultivation_save_dc"}) == 18
    assert typed_executor.dc_of(ctx, target, {"of": "binder"}) == 23


def test_proof_pin_builder_rejects_unreviewed_dependency_bytes(tmp_path, monkeypatch):
    source = tmp_path / "proof.py"
    dependency = tmp_path / "runtime.py"
    dependency.write_bytes(b"changed")
    source.write_text('_REVIEWED_REF = "old"\n_REVIEWED_SHA256 = {"runtime.py": "old digest"}\n')
    monkeypatch.setattr(pins, "ROOT", tmp_path)
    before = source.read_bytes()
    with pytest.raises(ValueError, match="Unreviewed working-copy drift"):
        pins.regenerate("proof.py", "reviewed-commit", lambda dependency: b"reviewed")
    assert source.read_bytes() == before


def test_proof_pin_builder_changes_only_existing_digest_and_ref(tmp_path, monkeypatch):
    from tools.automation_truth_digest import dependency_digest

    dependency = tmp_path / "runtime.py"
    dependency.write_bytes(b"reviewed")
    source = tmp_path / "proof.py"
    source.write_text('# Keep this review note.\n_RUNTIME = "runtime.py"\n_REVIEWED_REF = "old"\n_REVIEWED_SHA256 = {_RUNTIME: "old digest"}\n')
    monkeypatch.setattr(pins, "ROOT", tmp_path)
    generated = pins.regenerate("proof.py", "reviewed-commit", lambda path: dependency.read_bytes())
    assert generated == source.read_text().replace('"old"', '"reviewed-commit"').replace('"old digest"', '"' + dependency_digest("runtime.py", b"reviewed") + '"')
