"""Brute Maneuvers delivered by real equipment, table choices and cold replay."""
import pytest

from combat.ext.brute_shove import MANEUVERS
from combat.ext.scoundrel_riders import held_possessions
from tests.worker2_support import OWNER, FOE, fixture, reload, settle, turn
from tests.cw2_service_support import seal
from tests.r1i_service_support import force_ai_candidate

KIT = {"starting_kit": {"items": [
    {"item_id": "tianxia.mortal.weapon.bi_shou", "name": "Bi Shou (Dagger)", "quantity": 1},
    {"item_id": "tianxia.mortal.weapon.dao", "name": "Dao", "quantity": 1}]}}
BOW = "tianxia.mortal.weapon.gong_jian"
ARROWS = "tianxia.mortal.gear.arrows_20"
RANGED = {"starting_kit": {"items": [
    {"item_id": BOW, "quantity": 1}, {"item_id": ARROWS, "quantity": 1}]}}


def prepare(success):
    def transform(bundles):
        bundles[2]["skills"] = {"Athletics": -100 if success else 100,
                                 "Acrobatics": -100 if success else 100}
        for bundle in bundles:
            seal(bundle)
    return transform


def disarms(engine):
    return [c for c in engine.legal_candidates() if c.actor_id == OWNER
            and engine.action_catalog.get(c.source_definition_id) is not None
            and any(row.get("type") == "brute_disarm" for row in
                    ((engine.action_catalog.get(c.source_definition_id).parameters.get("typed") or {}).get("effects") or []))]


def pick(engine, weapon=None):
    offered = [c for c in disarms(engine) if c.target_ids == (FOE,)
               and (weapon is None or weapon in c.source_definition_id)]
    assert offered, "Brute Maneuvers must offer a real weapon Disarm against a held item"
    return offered[0].candidate_id


def contest(engine):
    return next(e.payload for e in reversed(engine.events)
                if e.event_type == "CHECK_ROLLED" and e.payload.get("contest") == "disarm")


@pytest.mark.parametrize("success", [False, True])
@pytest.mark.parametrize("automatic", [False, True])
def test_native_disarm_exact_item_defender_choice_no_damage_reload(tmp_path, success, automatic):
    from tests.h1_support import mechanics
    assert mechanics()[MANEUVERS]["riders"] == []
    assert mechanics()[MANEUVERS]["coverage"] == "FULL"
    combat, table, mid = fixture(tmp_path, [MANEUVERS], owner_kit=KIT, foe_kit=KIT,
        foe_position={"x": 4, "y": 5}, named=True, bundle_transform=prepare(success))
    # Starting loadout deliberately stows the spare dagger. The player must
    # actually draw it before it can be chosen as a second held item.
    turn(table, mid, FOE)
    on_turn = reload(tmp_path, mid)
    draw = next(c for c in on_turn.legal_candidates()
                if (grip := (on_turn.action_catalog.get(c.source_definition_id).parameters.get("equipment_grip")
                             if on_turn.action_catalog.get(c.source_definition_id) else None))
                and grip.get("held") and "bi_shou" in grip.get("weapon", ""))
    settle(table, mid, draw.candidate_id)
    turn(table, mid, OWNER)
    before = reload(tmp_path, mid)
    items = held_possessions(before, before.state.actors[FOE])
    assert len(items) == 2
    chosen = items[-1]
    cid = pick(before)
    if automatic:
        force_ai_candidate(combat, mid, OWNER, cid)
    prompts = settle(table, mid, cid, {"choice:needle.brute_disarm_item": chosen["object"],
        "choice:needle.brute_disarm_skill": "Acrobatics"}, auto=automatic)
    cold = reload(tmp_path, mid)
    event = contest(cold)
    assert event["success"] is success
    assert event["actor"]["reason"].startswith("ATTACK:")
    assert event["target"]["reason"].startswith("CHECK:")
    assert event["target_skill"] == "Acrobatics"
    assert cold.state.actors[FOE].current_hp == before.state.actors[FOE].current_hp
    assert not cold.state.actors[OWNER].action_available
    remaining = held_possessions(cold, cold.state.actors[FOE])
    assert len(remaining) == 2 - int(success)
    ids = {p["context"]["reaction_source_id"] for p in prompts}
    assert "choice:needle.brute_disarm_skill" in ids  # manual defender on either actor's turn
    assert ("choice:needle.brute_disarm_item" in ids) is (not automatic)
    if not automatic:
        assert (chosen["object"] in {i["object"] for i in remaining}) is (not success)
    assert all("Disarm" in str(p) for p in prompts if p["context"]["reaction_source_id"] in ids
               and p["context"]["reaction_source_id"].startswith("choice:needle.brute_disarm"))
    assert not any(e.event_type == "DAMAGE_COMMITTED" for e in cold.events[len(before.events):])


@pytest.mark.parametrize("gate", ["immunity", "attempt"])
def test_disarm_condition_gates_prevent_physical_drop(tmp_path, monkeypatch, gate):
    from combat import typed_executor, ext
    combat, table, mid = fixture(tmp_path, [MANEUVERS], owner_kit=KIT, foe_kit=KIT,
        foe_position={"x": 4, "y": 5}, bundle_transform=prepare(True))
    before = reload(tmp_path, mid)
    items = held_possessions(before, before.state.actors[FOE])
    if gate == "immunity":
        original = typed_executor.condition_immune
        monkeypatch.setattr(typed_executor, "condition_immune", lambda e, t, n:
            (t.entity_id == FOE and n == "disarmed") or original(e, t, n))
    else:
        original = ext.iter_strict
        def veto(name, *args, **kwargs):
            if name == "condition_attempt" and args[1].entity_id == FOE and args[2].get("condition") == "disarmed":
                yield False
            else:
                yield from original(name, *args, **kwargs)
        monkeypatch.setattr(ext, "iter_strict", veto)
    settle(table, mid, pick(before))
    cold = reload(tmp_path, mid)
    assert contest(cold)["success"] is True
    assert {i["object"] for i in held_possessions(cold, cold.state.actors[FOE])} == {i["object"] for i in items}


def test_disarm_ownership_and_real_held_item_admission(tmp_path):
    for name, talents, foe_kit in (("plain", [], KIT), ("empty", [MANEUVERS], None)):
        root = tmp_path / name
        _, _, mid = fixture(root, talents, owner_kit=KIT, foe_kit=foe_kit,
            foe_position={"x": 4, "y": 5})
        assert not disarms(reload(root, mid))


@pytest.mark.parametrize("ordinary", [False, True])
def test_disarm_replaces_one_attack_and_preserves_remaining_legal_weapons(tmp_path, ordinary):
    from combat.ext.special_attacks import attacks_of
    combat, table, mid = fixture(tmp_path, [MANEUVERS], owner_kit=KIT, foe_kit=KIT,
        foe_position={"x": 4, "y": 5}, bundle_transform=prepare(False),
        owner_features=("tianxia.path.body_refining.feature.extra_attack",))
    e = reload(tmp_path, mid)
    count = attacks_of(e, e.state.actors[OWNER])
    assert count > 1
    settle(table, mid, pick(e))
    e = reload(tmp_path, mid)
    assert e.state.actors[OWNER].turn_flags["special_attack_rest"] == count - 1
    weapons = [c for c in e.legal_candidates() if (a := e.action_catalog.get(c.source_definition_id))
               and a.parameters.get("attack_action_rest") and a.parameters.get("typed", {}).get("weapon")
               and any(row.get("type") == "attack" for row in a.parameters["typed"].get("effects") or [])]
    assert weapons, [c.display_name for c in e.legal_candidates()]
    settle(table, mid, weapons[0].candidate_id if ordinary else pick(e))
    assert reload(tmp_path, mid).state.actors[OWNER].turn_flags["special_attack_rest"] == count - 2


def test_ranged_disarm_spends_ammunition_and_hides_exhausted_shots(tmp_path, monkeypatch):
    import combat.ext.ammunition as ammunition
    monkeypatch.setitem(ammunition._PIECES_PER_UNIT, ARROWS, 1)
    combat, table, mid = fixture(tmp_path, [MANEUVERS], owner_kit=RANGED, foe_kit=KIT,
        foe_position={"x": 4, "y": 5}, bundle_transform=prepare(False),
        owner_features=("tianxia.path.body_refining.feature.extra_attack",))
    before = reload(tmp_path, mid)
    settle(table, mid, pick(before, "gong_jian"))
    cold = reload(tmp_path, mid)
    events = [e for e in cold.events if e.event_type == "ATTACK_ROLLED"
              and e.actor_id == OWNER and e.payload.get("contest") == "disarm"]
    assert len(events) == 1 and events[0].payload["roll_id"]
    assert events[0].payload["mode"] == "DISADVANTAGE"  # a visible hostile is within 5 feet of the bow
    assert [v for k, v in cold.state.actors[OWNER].turn_flags.items()
            if k.startswith("_round_ammunition_spent:")] == [1]
    assert not any("gong_jian" in c.source_definition_id for c in disarms(cold))


def test_automatic_defender_chooses_best_skill_without_human_prompt(tmp_path):
    def setup(bundles):
        bundles[2]["skills"] = {"Athletics": 100, "Acrobatics": 110}
        seal(bundles[2])
    combat, table, mid = fixture(tmp_path, [MANEUVERS], owner_kit=KIT, foe_kit=KIT,
        foe_position={"x": 4, "y": 5}, ask=False, bundle_transform=setup)
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode="LOCAL_AUTO")
    prompts = settle(table, mid, pick(reload(tmp_path, mid)))
    assert not any(p["context"]["reaction_source_id"] == "choice:needle.brute_disarm_skill" for p in prompts)
    assert contest(reload(tmp_path, mid))["target_skill"] == "Acrobatics"


def test_weapon_tag_disarm_is_rebuilt_in_place_for_brute_owner(tmp_path):
    weapon = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.zi_wu", "quantity": 1}]}}
    combat, table, mid = fixture(tmp_path, [MANEUVERS], owner_kit=weapon, foe_kit=KIT,
        foe_position={"x": 4, "y": 5}, bundle_transform=prepare(False))
    e = reload(tmp_path, mid)
    cid = pick(e, "zi_wu")
    action = e.action_catalog[next(c.source_definition_id for c in disarms(e) if c.candidate_id == cid)]
    assert action.source_definition_id.endswith("#disarm")
    assert not any(row.get("type") == "attack" for row in action.parameters["typed"]["effects"])
    hp = e.state.actors[FOE].current_hp
    settle(table, mid, cid)
    assert reload(tmp_path, mid).state.actors[FOE].current_hp == hp


def test_disarm_untrained_defense_uses_ability_score_not_save_proficiency(tmp_path):
    def setup(bundles):
        bundles[2]["skills"] = {}
        bundles[2]["actor_template"]["skills"] = {}
        bundles[2]["actor_template"]["saving_throws"]["STR"] = 100
        seal(bundles[2])
    combat, table, mid = fixture(tmp_path, [MANEUVERS], owner_kit=KIT, foe_kit=KIT,
        foe_position={"x": 4, "y": 5}, bundle_transform=setup)
    settle(table, mid, pick(reload(tmp_path, mid)), {"choice:needle.brute_disarm_skill": "Athletics"})
    result = contest(reload(tmp_path, mid))
    assert result["target_skill"] == "Athletics"
    assert result["target"]["modifier"] == 2
