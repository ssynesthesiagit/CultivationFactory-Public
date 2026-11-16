"""Named Court choices on actual Counterweave and interception table actions."""
import json
import zipfile

import pytest

from combat.factory_compiler import compile_character
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate2_rolls import DeterministicRollAuthority
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext import fate_riders as F
from tests.h1_support import ROOT, sheet
from tests.test_r9i_choices import action, finish_turn, resolve
from tests.test_r9i_karma_persistence import act
from tests.test_tabletop_hunt6 import LEFT, ALLY, RIGHT, PROJECTS


REACTIONS = {"counter": "TAL_QIWEAVING_COUNTERWEAVE",
             "strike": "TAL_RETRIBUTION_INTERCEPTING_STRIKE",
             "shot": "TAL_SNIPER_INTERCEPTING_SHOT"}
BOW = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.gong_jian"},
                                   {"item_id": "tianxia.mortal.weapon.dao"}]}}


def fixture(tmp_path, kind):
    ids = [LEFT, ALLY, RIGHT]
    # Reviewed hands (c18f4990): a two-handed bow needs both hands. The shot
    # scenario tests the reaction, so give its archers only the intended weapon.
    kit = {"starting_kit": {"items": BOW["starting_kit"]["items"][:1]}} if kind == "shot" else BOW
    docs = [sheet([F.COURT], cl=15), sheet([REACTIONS[kind]], cl=15, kit=kit),
            sheet([F.VIOLENCE_ID] if kind == "counter" else [], cl=15, kit=kit)]
    for name, doc in zip(("left", "ally", "right"), docs):
        doc["identity"]["display_name"] = name.title()
        folder = tmp_path / "portable_characters" / PROJECTS[name]
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    bundles = [compile_character(doc, actor_id=aid, reaction_plan={"ask": True}) for aid, doc in zip(ids, docs)]
    mid = combat._finish_factory_match(
        bundles, ids, {LEFT: "team:factory", ALLY: "team:factory", RIGHT: "team:opponents"},
        {LEFT: {"x": 3, "y": 6}, ALLY: {"x": 4, "y": 6}, RIGHT: {"x": 5, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [LEFT, ALLY], [RIGHT],
        control_modes={aid: "MANUAL" for aid in ids}, match_seed="R9M-COURT", maximum_rounds=10,
        display_name="Court reactions")["match_id"]
    while table.state(mid)["menu"]["actor_id"] != LEFT:
        finish_turn(table, mid)
    resolve(lambda answers: act(table, mid, action(table, mid, "Court of the Heavenly Ledger"), answers), {})
    finish_turn(table, mid)
    while table.state(mid)["menu"]["actor_id"] != RIGHT:
        finish_turn(table, mid)
    return combat, table, mid


@pytest.mark.parametrize("use", [False, True])
@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("kind,direct_target", [("counter", False), ("counter", True),
                                               ("strike", True), ("shot", True)])
def test_named_court_real_reaction_use_decline_reload(tmp_path, monkeypatch, kind, direct_target, auto_turn, use):
    combat, table, mid = fixture(tmp_path, kind)
    trigger = "Violence Word" if kind == "counter" else "Gong Jian" if kind == "shot" else "Dao"
    target = ALLY if direct_target else LEFT
    cid = action(table, mid, trigger, target)
    reaction_id = "reaction:typed." + REACTIONS[kind]
    court_id = "choice:needle.court_bonus"
    if auto_turn:
        real = combat.controller

        class Controller:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)

            def __getattr__(self, name):
                return getattr(real, name)

        combat.controller = Controller()
        combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode="LOCAL_AUTO")
    # Counter: 5 + 8 < DC 16; Strike: 9 + 8 < 17 + 2;
    # Shot uses its proficient weapon bonus: 9 + 6 < 16 + 2.
    # Adding four from Court changes only the chosen reaction's outcome.
    dice = [5] if kind == "counter" else [17 if kind == "strike" else 16, 9]
    original_die = DeterministicRollAuthority._die

    def die(roller, sides):
        if roller.counter < start_counter:
            return original_die(roller, sides)
        index = roller.counter
        roller.counter += 1
        # Retries reconstruct the roller from the same committed counter.
        offset = index - start_counter
        return (dice[offset] if sides == 20 and 0 <= offset < len(dice) else 4), index

    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    start_counter = combat._load_session(mid).engine.roller.counter
    monkeypatch.setattr(DeterministicRollAuthority, "_die", die)
    prompts = []

    def send(answers):
        # Generic Use/Decline reactions have no option IDs; the shared choice
        # resolver's sentinel requests Use, then is removed for this transport.
        answers = [{k: v for k, v in answer.items() if k != "option_ids"}
                   if answer.get("reaction_source_id") == reaction_id else answer for answer in answers]
        result = table.auto_step(mid, 0, answers) if auto_turn else act(table, mid, cid, answers)
        if result["status"] == "REACTION_REQUIRED":
            if (result["reaction"]["context"]["reaction_source_id"] == court_id
                    and "Ally's" in result["reaction"]["moment"]
                    and (kind != "counter" or "Counterweave" in result["reaction"]["moment"])):
                prompts.append(result["reaction"]["moment"])
            assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
        return result

    seen = resolve(send, {reaction_id: ["use"], court_id: ["add"] if use else None})
    assert reaction_id in seen and court_id in seen
    reaction_name = {"counter": "Counterweave", "strike": "Intercepting Strike", "shot": "Intercepting Shot"}[kind]
    assert prompts and all(all(word in p for word in ("Court of the Heavenly Ledger", "Ally", reaction_name,
                                                      "Right", trigger, "before the outcome", "Once per round",
                                                      "no additional Qi")) for p in prompts)
    # The existing player-text transport names this fixture's paying pool (Qi),
    # rather than the rules' CP abbreviation. Keep all contest/reload assertions.
    assert all("REACTION_" not in p and "reaction:typed" not in p for p in prompts)
    assert all(("ability check" if kind == "counter" else "attack roll") in p for p in prompts)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    engine = loaded.engine
    zone = F._zones(engine, F.COURT)[0]
    assert F._once_a_round(engine, ("court", zone.zone_id), consume=False) == (not use)
    rolls = [r for r in engine.rolls if r.actor_id == ALLY and r.reason == ("REACTION_COUNTER" if kind == "counter" else "REACTION_CONTEST")]
    assert len(rolls) == 1
    assert rolls[0].modifier == (6 if kind == "shot" else 8) + (4 if use else 0)
    assert rolls[0].total == rolls[0].natural_result + rolls[0].modifier
    riders = " ".join(str(e.payload.get("rider") or "") for e in engine.events if e.event_type == "GM_RIDER")
    outcome = ("the technique is countered" if use else "not countered") if kind == "counter" else ("is negated" if use else "not negated")
    assert outcome in riders
    if kind != "counter":
        assert any(e.event_type == "ATTACK_ROLLED" and e.actor_id == RIGHT and ALLY in e.target_ids for e in engine.events) == (not use)
    else:
        assert any(c.condition_id == F.VIOLENCE for c in engine.state.actors[target].conditions.values()) == (not use)
        assert engine.state.actors[RIGHT].resources["resource:core.qi"] < before["actors"][RIGHT]["resources"]["resource:core.qi"]
    assert engine.state.actors[ALLY].reaction_available is False
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("auto_turn", [False, True])
def test_direct_target_can_decline_counterweave_without_spending(tmp_path, auto_turn):
    combat, table, mid = fixture(tmp_path, "counter")
    cid = action(table, mid, "Violence Word", ALLY)
    if auto_turn:
        real = combat.controller

        class Controller:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)

            def __getattr__(self, name):
                return getattr(real, name)

        combat.controller = Controller()
        combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode="LOCAL_AUTO")
    before = combat._load_session(mid).engine.state.model_dump(mode="json")

    def send(answers):
        result = table.auto_step(mid, 0, answers) if auto_turn else act(table, mid, cid, answers)
        if result["status"] == "REACTION_REQUIRED":
            assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
        return result

    seen = resolve(send, {})
    assert "reaction:typed." + REACTIONS["counter"] in seen
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    target = loaded.engine.state.actors[ALLY]
    assert target.reaction_available
    assert target.resources == before["actors"][ALLY]["resources"]
    assert any(c.condition_id == F.VIOLENCE for c in target.conditions.values())
    assert not any(r.reason == "REACTION_COUNTER" for r in loaded.engine.rolls)
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_roll_description_is_nested_scoped_and_cleared_on_exception():
    from types import SimpleNamespace
    from combat.ext.roll_context import described_d20, roll_description

    roll = SimpleNamespace(actor_id="ally", reason="REACTION_CONTEST")
    engine = SimpleNamespace()

    def inner(**kwargs):
        assert roll_description(engine, roll) == "inner"
        raise ValueError("preview pause")

    def outer(**kwargs):
        assert roll_description(engine, roll) == "outer"
        assert roll_description(SimpleNamespace(), roll) is None
        assert roll_description(engine, SimpleNamespace(actor_id="foe", reason=roll.reason)) is None
        engine.roller = SimpleNamespace(d20=inner)
        with pytest.raises(ValueError, match="preview pause"):
            described_d20(engine, description="inner", actor_id=roll.actor_id, reason=roll.reason)
        assert roll_description(engine, roll) == "outer"
        return roll

    engine.roller = SimpleNamespace(d20=outer)
    assert described_d20(engine, description="outer", actor_id=roll.actor_id, reason=roll.reason) is roll
    assert roll_description(engine, roll) is None
