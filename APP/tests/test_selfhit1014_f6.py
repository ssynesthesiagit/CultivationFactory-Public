"""Mixed packet permissions and preview parity at the table/reload boundary."""
import pytest

from combat.area_recipients import scoped_area, harmful_effect_scope
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests.test_friendly_fire_area_table import _commit_area_action
from tests.test_lock_choices import install
from tests.test_tabletop_hunt6 import LEFT, ALLY, RIGHT, table_fight


@pytest.mark.parametrize("amount,printed", [
    ({"dice": {"count": 1, "sides": 6}}, "1d6"),
    ({"dice": "1d6"}, "1d6"),
    ({"dice": {"count": 1, "sides": 6, "bonus": 2}}, "1d6 + 2"),
    ({"dice": {"count": 1, "sides": 6}, "flat": 2}, "1d6+2"),
])
def test_matching_dice_fallback_preserves_legal_inclusive_packet(amount, printed):
    effect = {"type": "damage", **amount, "damage_types": ["fire"], "applies_to": "enemies_in_area"}
    area = scoped_area({"shape": "sphere", "size_ft": 15}, [effect],
                       f"Each creature takes {printed} fire damage.")
    assert harmful_effect_scope(area, effect) == "all"


def test_formula_own_inclusive_evidence_remains_authoritative():
    effect = {"type": "damage", "formula": "pb", "damage_types": ["fire"],
              "evidence": "Each creature takes your Proficiency Bonus in fire damage."}
    area = scoped_area({"shape": "sphere", "size_ft": 15}, [effect])
    assert harmful_effect_scope(area, effect) == "all"


@pytest.mark.parametrize("shape", ["sphere", "cone", "line"])
@pytest.mark.parametrize("amount,printed", [
    ({"dice": {"count": 1, "sides": 6}}, "1d6"),
    ({"dice": {"count": 1, "sides": 6, "bonus": 2}}, "1d6 + 2"),
    ({"formula": "pb"}, "your Proficiency Bonus"),
], ids=["dice", "dice-bonus", "formula"])
def test_dice_formula_sibling_cannot_borrow_inclusive_scope(tmp_path, monkeypatch, shape, amount, printed):
    source, name = "test:selfhit-f6-dice", "Mixed fire burst"
    def compile_area(info):
        if info["actor_id"] != LEFT:
            return []
        effects = [
            {"type": "damage", "flat": 5, "damage_types": ["fire"],
             "applies_to": "creatures_in_area", "evidence": "Each creature in the area takes 5 fire damage."},
            {"type": "damage", **amount, "damage_types": ["fire"], "applies_to": "enemies_in_area",
             "evidence": f"Creatures in the area take {printed} fire damage."}]
        area = {"shape": shape, "size_ft": 30, "include_origin": True}
        if shape == "sphere":
            area["centered_on_self"] = True
        typed = {"numbers": info["numbers"], "effects": effects}
        typed["area"] = scoped_area(area, effects, " ".join(e["evidence"] for e in effects), typed=typed)
        return [ActionDefinition(source_definition_id=source, display_name=name, owner_id=LEFT,
            economy=EconomyKind.ACTION, resolution_kind="TYPED",
            target_kind="SELF" if shape == "sphere" else "CELL", range_ft=30, radius_ft=30,
            parameters={"typed": typed})]
    install(monkeypatch, "compile_actions", compile_area)
    combat, table, mid = table_fight(tmp_path, [], ally_talents=[],
        starts={"team1": [[3, 4], [4, 4]], "team2": [[5, 4]]})
    result, _ = _commit_area_action(table, mid, name, None if shape == "sphere" else {"x": 5, "y": 4})
    assert result["status"] == "COMMITTED", result
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[ALLY].current_hp == 55
    assert loaded.engine.state.actors[LEFT].current_hp == (55 if shape == "sphere" else 60)
    assert loaded.engine.state.actors[RIGHT].current_hp < 55
    typed = loaded.engine.action_catalog[source].parameters["typed"]
    assert [harmful_effect_scope(typed["area"], e) for e in typed["effects"]] == ["all", "hostile"]
    assert "harmful_recipient_override" not in typed["area"]
    packets = [e for e in loaded.engine.events if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == source]
    assert sum(ALLY in e.target_ids for e in packets) == 1
    assert sum(RIGHT in e.target_ids for e in packets) == 2
    assert sum(LEFT in e.target_ids for e in packets) == int(shape == "sphere")
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("chosen", [False, True], ids=["mandatory", "chosen"])
def test_mixed_save_preview_matches_execution_after_reload(tmp_path, monkeypatch, chosen):
    from combat.area_safety import preview, harmful_recipients, _risk
    from combat.typed_executor import Context, _area_targets
    source, name = "test:selfhit-f6-preview", "Mixed saving throw burst"
    def compile_area(info):
        if info["actor_id"] != LEFT:
            return []
        effects = ([{"type": "rider_choose_area_recipients"}] if chosen else []) + [
            {"type": "save", "ability": "dex", "applies_to": "enemies_in_area",
             "recipient_text": ("Creatures of your choice" if chosen else "Each creature") + " make a Dexterity saving throw.",
             "on_fail": [{"type": "damage", "flat": 5, "damage_types": ["force"], "applies_to": "enemies_in_area"}]},
            {"type": "save", "ability": "dex", "applies_to": "enemies_in_area",
             "recipient_text": "Each hostile creature makes a Dexterity saving throw.",
             "on_fail": [{"type": "damage", "flat": 3, "damage_types": ["force"], "applies_to": "enemies_in_area"}]}]
        typed = {"numbers": {**info["numbers"], "save_dc": 99}, "effects": effects}
        typed["area"] = scoped_area({"shape": "sphere", "size_ft": 15, "centered_on_self": True}, effects, typed=typed)
        return [ActionDefinition(source_definition_id=source, display_name=name, owner_id=LEFT,
            economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="SELF", radius_ft=15,
            parameters={"typed": typed})]
    install(monkeypatch, "compile_actions", compile_area)
    combat, table, mid = table_fight(tmp_path, [], ally_talents=[])
    engine = combat._load_session(mid).engine
    actor, action = engine.state.actors[LEFT], engine.action_catalog[source]
    typed = action.parameters["typed"]
    targets = _area_targets(engine, actor, actor.position, typed["area"], typed=typed)
    ctx = Context(engine, actor, action, None, typed, targets, None)
    assert harmful_recipients(ctx, typed["effects"]) == {LEFT, ALLY, RIGHT}
    assert _risk(ctx, typed["effects"])[(ALLY, False)] == 5
    _, metadata, label = preview(engine, actor, action, actor.position)
    assert "Ally" in label
    # The inclusive sphere exposes both its user and the allied creature.
    assert metadata["allies_in_area"] == 2
    assert metadata["ally_expected_damage"] == (0 if chosen else 10)
    assert metadata["unavoidable_allies_in_area"] == (0 if chosen else 2)
    if not chosen:
        assert label.startswith("Hits allies too:")
    result, option = _commit_area_action(table, mid, name, None)
    if chosen:
        assert result["status"] == "REACTION_REQUIRED", result
        answer = {**result["reaction"]["context"], "selection": "USE", "option_ids": [ALLY, RIGHT]}
        table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
        state = table.state(mid)
        result = table.act(mid, option["candidate_id"], state["menu"]["decision_id"],
                           state["menu"]["state_version"], state["last_sequence"], [answer])
    assert result["status"] == "COMMITTED", result
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[ALLY].current_hp == 55
    assert loaded.engine.state.actors[RIGHT].current_hp == 52
    assert loaded.engine.state.actors[LEFT].current_hp == (60 if chosen else 55)
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"
