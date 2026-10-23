"""MMX86 continuation (owner playtest, the Stamina-paid variant of Empty Step): the way a player pays for a
teleport must not change where they are asked to land.

The owner's fight journal (round 24) shows the owner using "Empty Step (1 Stamina)" --
``action:typed.5803e87d88.TAL_VOID_EMPTY_STEP#pay1``, a *paid variant* row built by
``combat/factory_compiler.py`` ``_add_ways`` for the printed "Cost: 1 CP or 1 Stamina". That journal does not
establish a missing destination: the ordinary paid menu already offers bound squares on the base commit.
The unbound fallback tests deliberately set a zero-size area in their compiled fixture to exercise that shape.

Pinned here, at the level the bug showed (a real table, a real menu, the real paid-variant row):

- the Stamina-paid variant offers the same destination squares as the Qi-paid base, one per legal square,
  and the player lands on the one they picked;
- it spends what the printed cost says (1 Stamina, the Bonus Action) and no more;
- a paid variant whose square is *not* bound still asks the player instead of letting the engine pick,
  which is the general rule: no ability id decides this, the printed teleport effect does;
- an AI combatant is never asked, so AI fights are untouched.
"""
from __future__ import annotations

import json
import zipfile

import pytest

from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionDefinition, ActionIntent, EconomyKind, Position, ReactionDecision
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate5_service import FACTORY_ACTOR_PREFIX, CombatService
from combat.tabletop_service import TabletopService
from combat.tabletop import ButtonStore
from tests.h1_support import ROOT, sheet

OWNER = "actor:factory.mmx86pay-owner"
FOE = "actor:factory.00000000-0000-0000-0000-000000000086"
PAY = "(1 Stamina)"  # the printed alternative the owner used
EMPTY_STEP = "TAL_VOID_EMPTY_STEP"
SMOTHER = "TAL_SMOKE_SMOTHER_THE_BREATH"
GRAVE = "TAL_EARTH_THE_GRAVE_REFUSES_THE_STEP"
MOUNTAIN = "TAL_EARTH_INCARNATION_OF_THE_PATIENT_MOUNTAIN"
SHADOW_STEP = "tianxia.subpath.qi.ninpo_adept.feature.shadow_step"

# This fixture compiles Grave's passive response from the dynamically loaded
# split rules. Keep its real input literal so the public test exporter follows
# it through consumers of _table, rather than silently omitting the response.
GRAVE_RULES_INPUT = "combat/rules/feature_blocks.d/riders_lane9.json"


def _owner_sheet(talents=(EMPTY_STEP,)):
    """An owner who can pay Empty Step either way, so the compiler builds the Stamina-paid variant row too."""
    doc = sheet(list(talents), cl=17, dc=50)
    # A second Path pool. Without it the printed "Cost: 1 CP or 1 Stamina" has only one way this character
    # can pay, and no "#pay1" row exists to test.
    doc["ability_scores_and_statistics"]["primary_resource"]["definitions"] = [{"name": "Stamina", "max": 30}]
    return doc


def _write(doc, aid, tmp_path):
    doc["identity"]["display_name"] = aid.removeprefix(FACTORY_ACTOR_PREFIX)
    doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = 500
    doc["ability_scores_and_statistics"]["technique_attack_bonus"] = 100
    folder = tmp_path / "portable_characters" / aid.removeprefix(FACTORY_ACTOR_PREFIX)
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))


def _act(table, mid, candidate_id, answer):
    """Commit one table action; ``answer(prompt)`` returns the option ids for each prompt (None declines)."""
    answers, prompts = [], []
    for _ in range(12):
        result = table.act(mid, candidate_id, table.state(mid)["menu"]["decision_id"],
                           table.state(mid)["menu"]["state_version"], 0, answers)
        if result["status"] != "REACTION_REQUIRED":
            assert result["status"] == "COMMITTED", result
            return prompts
        prompt = result["reaction"]
        prompts.append(prompt)
        picked = answer(prompt)
        answers.append({**prompt["context"], "selection": "DECLINE" if picked is None else "USE",
                        "option_ids": list(picked or [])})
    raise AssertionError("more prompts than one action can ask")


def _unbind(bundle, suffix):
    """Leave a compiled action's square unbound: the same shape a zero-size area gives it at the table.

    combat/gate4_engine.py _action_candidates binds one square per legal square for a self-teleport
    (combat/typed_executor.py teleport_reach); an action that declares a zero-size area is declined by that helper and
    its single candidate carries no destination. Nothing else about the row changes, so the payment still pays.
    """
    for action in bundle.get("action_catalog") or []:
        if str(action.get("source_definition_id") or "").endswith(suffix):
            action["parameters"]["typed"]["area"] = {"size_ft": 0}
            return action["source_definition_id"]
    raise AssertionError(f"no compiled action ends with {suffix!r}")


def _table(tmp_path, unbind_paid=False, smother=False, grave=False, owner_talents=(EMPTY_STEP,), unbind=None, cha_save=None,
           explicit_duplicates=True):
    """A real duel on the pillar arena with the owner in manual control, as the owner's playtest was."""
    docs = {OWNER: _owner_sheet(owner_talents), FOE: sheet([], cl=17, score=14)}
    if cha_save is not None:
        docs[OWNER]["ability_scores_and_statistics"]["saving_throws"] = {"CHA": cha_save}
    if grave:
        docs[FOE] = sheet([GRAVE, MOUNTAIN], cl=17, dc=50)
    if smother:
        docs[FOE] = sheet(["SMOKE_BASE_SMOKE_TRACE", "SMOKE_BASE_SMOKE_VEIL", "TAL_SMOKE_CINDER_WISP", SMOTHER],
                          cl=17, dc=50)
        ButtonStore(tmp_path / "tabletop_buttons").save_reactions(
            FOE.removeprefix(FACTORY_ACTOR_PREFIX), {"mode": "ask"}, {SMOTHER})
    for aid, doc in docs.items():
        _write(doc, aid, tmp_path)
    bundles = [compile_character(
        docs[aid], actor_id=aid,
        reaction_plan=(ButtonStore(tmp_path / "tabletop_buttons").get(
            FOE.removeprefix(FACTORY_ACTOR_PREFIX))["reactions"] if smother and aid == FOE else None))
        for aid in (OWNER, FOE)]
    if unbind_paid:
        _unbind(bundles[0], f"{EMPTY_STEP}#pay1")
        if grave and explicit_duplicates:
            # Reproduce Sand Burrow/Fold Step's duplicate rows with equal explicit reach.
            # The actual null-distance Empty Step shape is exercised separately.
            paid = next(a for a in bundles[0]["action_catalog"]
                        if a["source_definition_id"].endswith(f"{EMPTY_STEP}#pay1"))
            paid["parameters"]["typed"]["effects"] = [
                {"type": "teleport", "applies_to": "self", "distance_ft": 20},
                {"type": "movement", "mode": "teleport", "distance_ft": 20}]
    if unbind:
        _unbind(bundles[0], unbind)
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    arena = combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"]
    mid = combat._finish_factory_match(
        bundles, [OWNER, FOE], {OWNER: "team:a", FOE: "team:b"},
        {OWNER: {"x": 3, "y": 6}, FOE: {"x": 5 if smother or grave else 14, "y": 6}}, arena, [OWNER], [FOE],
        control_modes={OWNER: "MANUAL", FOE: "MANUAL"}, match_seed="MMX86PAY",
        display_name="MMX86 Pay", maximum_rounds=6)["match_id"]
    return combat, table, mid


def _send(table, mid, candidate_id, answers=()):
    menu = table.state(mid)["menu"]
    return table.act(mid, candidate_id, menu["decision_id"], menu["state_version"], 0, list(answers))


def _owners_turn(table, mid):
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        _send(table, mid, table.state(mid)["menu"]["end_turn"])
    return table.state(mid)


def _group(state, label):
    return next((g for g in state["menu"]["actions"] if g["label"].startswith(label)), None)


def _place_smoke(table, mid, state):
    """Cast the fixture's smoke at 4,6 through the table's native square picker."""
    from combat.choice_presentation import option_cell
    from combat.placement_menu import CHOICE

    smoke = _group(state, "Smoke Veil")
    assert smoke is not None
    wanted = {"x": 4, "y": 6}
    # Also accept concrete rows when the caller uses an exhaustive menu.
    option = next((o for o in smoke["options"] if o.get("destination") == wanted),
                  smoke["options"][0])

    def answer(prompt):
        if prompt["context"]["reaction_source_id"] != CHOICE:
            return None
        square = next(o for o in prompt["choice"]["options"]
                      if option_cell(o["id"]) == {**wanted, "z": 0})
        return [square["id"]]

    return _act(table, mid, option["candidate_id"], answer)


def _destinations(group):
    return {json.dumps(o["destination"], sort_keys=True) for o in group["options"] if o.get("destination")}


def _events(combat, mid):
    """Every committed event of the fight, de-duplicated.

    history carries each event both in the raw journal and in the rendered projection, so the same event
    appears twice unless it is collapsed. (history also renders plain presentation lines that carry an
    event_type and no payload; those are not events.)
    """
    out: list[dict] = []
    seen: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            if isinstance(node.get("event_type"), str) and isinstance(node.get("payload"), dict):
                key = json.dumps(node, sort_keys=True, default=str)
                if key not in seen:
                    seen.add(key)
                    out.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(combat.history(mid))
    return out


# ------------------------------------------------------------------ the paid variant is offered the same squares
def test_the_paid_variant_offers_the_same_destination_squares_as_the_base(tmp_path):
    combat, table, mid = _table(tmp_path)
    state = _owners_turn(table, mid)
    base, paid = _group(state, "Empty Step"), _group(state, f"Empty Step {PAY}")
    assert paid is not None, f"the Stamina-paid variant is missing from the menu: {[g['label'] for g in state['menu']['actions']]}"
    assert len(paid["options"]) == len(base["options"])
    assert _destinations(paid) == _destinations(base), "the paid variant must offer the same squares as the base"
    assert len(paid["options"]) > 1, "one destination-less candidate is the bug this pins"
    for option in paid["options"]:
        assert option["destination"], f"{option['label']!r} carries no square to land on"


def test_the_player_chooses_where_the_paid_teleport_lands(tmp_path):
    combat, table, mid = _table(tmp_path)
    state = _owners_turn(table, mid)
    paid = _group(state, f"Empty Step {PAY}")
    wanted = {"x": 5, "y": 8}
    chosen = next(o for o in paid["options"] if o["destination"] == wanted)
    prompts = _act(table, mid, chosen["candidate_id"], lambda prompt: ["cell:5,8"])
    assert len(prompts) == 1
    assert prompts[0]["choice"]["map_pick"]
    events = _events(combat, mid)
    moved = [e for e in events if e.get("event_type") == "MOVEMENT_COMMITTED"]
    assert moved, "the paid teleport never committed"
    assert moved[-1]["payload"]["destination"] == wanted, (
        f"the creature landed on {moved[-1]['payload']['destination']}, not the square the player chose")


def test_the_paid_variant_costs_what_the_printed_alternative_says_and_nothing_else(tmp_path):
    """\"Cost: 1 CP or 1 Stamina\" as a Bonus Action: one Stamina and the Bonus Action, and the Action stays."""
    combat, table, mid = _table(tmp_path)
    state = _owners_turn(table, mid)
    paid = _group(state, f"Empty Step {PAY}")
    chosen = paid["options"][0]
    cell = chosen["destination"]
    prompts = _act(table, mid, chosen["candidate_id"], lambda prompt: [f"cell:{cell['x']},{cell['y']}"])
    assert len(prompts) == 1
    events = _events(combat, mid)
    spent = [e for e in events if e.get("event_type") == "RESOURCE_SPENT"
             and e.get("source_definition_id", "").endswith(f"{EMPTY_STEP}#pay1")]
    assert [e["payload"]["resource_id"] for e in spent] == ["resource:core.stamina"]
    assert [e["payload"]["amount"] for e in spent] == [1], "the Stamina-paid variant spends exactly 1 Stamina"
    qi = [e for e in events if e.get("event_type") == "RESOURCE_SPENT" and e["payload"]["resource_id"] == "resource:core.qi"]
    assert not qi, "the Stamina-paid variant must not also spend Qi"
    actor = CombatService(ROOT, tmp_path)._load_session(mid).engine.state.actors[OWNER]
    assert actor.resources["resource:core.stamina"] == 29
    assert not actor.bonus_action_available and actor.action_available and actor.reaction_available


# ------------------------------------------------- the general rule: an unbound square is asked, whoever the payer
UNBOUND = "action:typed.mmx86pay.paid_step#pay1"


def _engine(mode="MANUAL", unbind_paid=False):
    bundle = compile_character(_owner_sheet(), actor_id=OWNER)
    if unbind_paid:
        _unbind(bundle, f"{EMPTY_STEP}#pay1")
    engine = Gate4ControllerEngine(ROOT, match_seed="MMX86PAY", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [OWNER, AN],
                                                 "team_by_actor": {OWNER: "team:a", AN: "team:b"},
                                                 "starting_positions": {OWNER: {"x": 3, "y": 6}, AN: {"x": 14, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(OWNER)
    engine.state.current_actor_id = OWNER
    engine._system_start_turn()
    engine.typed_control_modes = {OWNER: mode}
    return engine


def _unbound_paid_variant(engine):
    """A paid variant of a self-teleport whose action binds no square.

    combat/gate4_engine.py _action_candidates expands a self-teleport into one candidate per legal square, but it
    declines one that declares a size (combat/typed_executor.py teleport_reach), leaving a single candidate with
    destination=None. The id deliberately reads like a paid variant: nothing keys on it.
    """
    action = ActionDefinition(source_definition_id=UNBOUND, display_name="Paid Step", owner_id=OWNER,
                              economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="SELF", range_ft=20,
                              parameters={"options": ("SELF",),
                                          "typed": {"effects": [{"type": "teleport", "applies_to": "self", "distance_ft": 20,
                                                                 "evidence": "Teleport to an unoccupied space you can see."}],
                                                   "area": {"size_ft": 0},
                                                   "numbers": {"pb": 4, "cl": 17, "save_dc": 15, "attack_bonus": 9},
                                                   "duration": {"kind": "instant"}, "weapon": None, "riders": []}})
    engine.action_catalog[UNBOUND] = action
    actor = engine.state.actors[OWNER]
    actor.action_ids = (*actor.action_ids, UNBOUND)
    return action


def _use(engine, action):
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == action.source_definition_id)
    engine.execute_intent(ActionIntent(intent_id="mmx86pay", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=OWNER, target_ids=candidate.target_ids, option_ids=candidate.option_ids))
    return candidate


def test_a_paid_variant_with_no_bound_square_is_asked_where_to_land():
    engine = _engine()
    action = _unbound_paid_variant(engine)
    asked = []

    def choose(request):
        asked.append(request["legal_option_ids"])
        wanted = next(o for o in request["legal_option_ids"] if o.endswith("5,6"))
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="USE",
                                option_ids=(wanted,)), None

    engine.set_reaction_provider(choose)
    _use(engine, action)
    assert asked, "nobody was asked where a paid teleport lands"
    actor = engine.state.actors[OWNER]
    assert (actor.position.x, actor.position.y) == (5, 6), "the engine chose the square instead of the player"
    for option in asked[0]:
        x, y = (int(part) for part in option.removeprefix("cell:").split(","))
        assert engine.grid.distance_ft(Position(x=3, y=6), Position(x=x, y=y)) <= 20


# ------------------------------------------------- the table: an unbound paid step, asked, answered, reloaded
def test_the_table_asks_where_an_unbound_paid_step_lands_and_the_square_survives_a_reload(tmp_path):
    """The whole round trip on a real table, on the Stamina-paid row: the fight pauses, the player answers, the
    commit moves it, and a reloaded fight still stands on the chosen square."""
    combat, table, mid = _table(tmp_path, unbind_paid=True)
    state = _owners_turn(table, mid)
    paid = _group(state, f"Empty Step {PAY}")
    assert paid is not None, "the Stamina-paid variant is missing from the menu"
    assert len(paid["options"]) == 1 and not paid["options"][0].get("destination"), (
        f"the paid variant still binds its own squares here: {paid['options'][:2]}")
    wanted = "cell:5,6"

    prompts = _act(table, mid, paid["options"][0]["candidate_id"],
                   lambda prompt: [wanted] if wanted in [row["id"] for row in prompt["choice"]["options"]] else None)
    assert len(prompts) == 1, f"one action asked {len(prompts)} times"
    prompt = prompts[0]["choice"]
    assert "Empty Step" in str(prompts[0].get("reaction") or ""), (
        f"the question does not name the ability: {prompts[0].get('reaction')!r}")
    assert str(prompts[0].get("reactor") or ""), "the question does not name the creature choosing"
    labels = " ".join(str(row.get("label") or "") for row in prompt["options"])
    assert "Teleport to 5,6" in labels, f"the picked square is not offered as a button: {labels[:120]}"
    words = str(prompts[0].get("trigger") or "")
    assert "Empty Step" in words, "the question must say which ability it is about"
    assert "stays where it is" in words, "the question must offer staying put in plain words"
    assert "spent either way" in words, "the question must say the cost is spent either way"

    moved = [e for e in _events(combat, mid) if e.get("event_type") == "MOVEMENT_COMMITTED"]
    assert moved and moved[-1]["payload"]["destination"] == {"x": 5, "y": 6}, (
        f"the paid teleport committed {moved[-1]['payload']['destination'] if moved else None}")
    # A fresh load of the fight: the chosen square is saved, not just held in memory.
    reloaded = CombatService(ROOT, tmp_path)._load_session(mid).engine.state.actors[OWNER]
    assert (reloaded.position.x, reloaded.position.y) == (5, 6), "the chosen square did not survive the reload"
    assert len([e for e in moved if e["payload"].get("teleport")]) == 1, "one payment must buy one hop"
    _assert_no_placement_instruction(combat, mid)


def test_the_paid_economy_of_an_unbound_paid_step_is_paid_once(tmp_path):
    """\"Cost: 1 CP or 1 Stamina\" as a Bonus Action: one Stamina and the Bonus Action, the Action still available --
    on the unbound path, and after a reload, and not again for the second row of the same hop."""
    combat, table, mid = _table(tmp_path, unbind_paid=True)
    state = _owners_turn(table, mid)
    paid = _group(state, f"Empty Step {PAY}")
    before = combat._load_session(mid).engine.state.actors[OWNER]
    assert before.resources["resource:core.stamina"] == 30 and before.bonus_action_available
    _act(table, mid, paid["options"][0]["candidate_id"], lambda prompt: None)  # decline: stays put, still pays
    actor = CombatService(ROOT, tmp_path)._load_session(mid).engine.state.actors[OWNER]
    assert (actor.position.x, actor.position.y) == (3, 6), "declining a paid step must not move the creature"
    assert actor.resources["resource:core.stamina"] == 29, "a declined paid step still spends what it costs"
    assert actor.resources.get("resource:core.qi") == 30, "the Stamina-paid variant must not also spend Qi"
    assert actor.bonus_action_available is False, "a Bonus Action ability must spend the Bonus Action"
    assert actor.action_available is True, "a Bonus Action ability must not also spend the Action"
    declined = [e["payload"].get("rider", "") for e in _events(combat, mid) if e["event_type"] == "GM_RIDER"
                and "stays where it is" in e["payload"].get("rider", "")]
    assert len(declined) == 1 and "the Bonus Action and 1 Stamina from its resource pool" in declined[0]
    spent = [e for e in _events(combat, mid) if e.get("event_type") == "RESOURCE_SPENT"
             and e["payload"]["resource_id"] == "resource:core.stamina"]
    assert [e["payload"]["amount"] for e in spent] == [1], f"the Stamina was spent {spent} instead of once"
    _assert_no_placement_instruction(combat, mid)


def _assert_no_placement_instruction(combat, mid):
    assert not any("place the creature on the map" in e["payload"].get("rider", "")
                   for e in _events(combat, mid) if e["event_type"] == "GM_RIDER")


def _paid_candidate(engine):
    return next(c for c in engine.legal_candidates() if c.source_definition_id.endswith(f"{EMPTY_STEP}#pay1"))


@pytest.mark.parametrize("blocked", [True, False])
@pytest.mark.parametrize("explicit_duplicates", [True, False])
def test_destination_then_grave_reaction_resumes_and_reloads(tmp_path, blocked, explicit_duplicates):
    """A selected destination survives a later real teleport gate and fresh table transactions.

    Explicit duplicate teleport/movement rows must not retry a blocked gate for the same payment.
    The successful case also proves the recorded square is used after the gate resumes.
    """
    combat, table, mid = _table(tmp_path, unbind_paid=True, grave=True, cha_save=-100 if blocked else 100,
                              explicit_duplicates=explicit_duplicates)
    if table.state(mid)["menu"]["actor_id"] != FOE:
        assert _send(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    mountain = _group(table.state(mid), "Incarnation of the Patient Mountain")
    assert mountain is not None
    _act(table, mid, mountain["options"][0]["candidate_id"], lambda prompt: None)
    state = _owners_turn(table, mid)
    paid = _group(state, f"Empty Step {PAY}")
    candidate_id = paid["options"][0]["candidate_id"]
    before = combat._load_session(mid).engine
    if not explicit_duplicates:
        paid_action = next(a for a in before.action_catalog.values()
                           if a.source_definition_id.endswith(f"{EMPTY_STEP}#pay1"))
        rows = paid_action.parameters["typed"]["effects"]
        assert any(r.get("type") == "teleport" and r.get("distance_ft") == 20 for r in rows)
        assert any(r.get("mode") == "teleport" and r.get("distance_ft") is None and r.get("within_range") for r in rows)
    stamina = before.state.actors[OWNER].resources["resource:core.stamina"]
    foe_qi = before.state.actors[FOE].resources["resource:core.qi"]
    result = _send(table, mid, candidate_id)
    assert result["status"] == "REACTION_REQUIRED", result
    prompt = result["reaction"]
    assert prompt["context"]["reaction_source_id"] == "choice:needle.teleport_destination"
    assert "Bonus Action" in prompt["trigger"] and "1 Stamina from its resource pool" in prompt["trigger"]
    answers = [{**prompt["context"], "selection": "USE", "option_ids": ["cell:4,6"]}]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    result = _send(table, mid, candidate_id, answers)
    assert result["status"] == "REACTION_REQUIRED", result
    prompt = result["reaction"]
    assert prompt["context"]["reaction_source_id"] == "choice:needle.grave_refuses"
    assert "The Grave Refuses the Step" in str(prompt)
    # Both pauses rolled back the attempt; destination answer is resubmitted with the gate answer.
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    actor = combat._load_session(mid).engine.state.actors[OWNER]
    assert actor.position == Position(x=3, y=6)
    assert actor.resources["resource:core.stamina"] == stamina and actor.bonus_action_available
    answers.append({**prompt["context"], "selection": "USE", "option_ids": ["use"]})
    result = _send(table, mid, candidate_id, answers)
    for _ in range(3):
        if result["status"] != "REACTION_REQUIRED":
            break
        # A successful save can ask whether to place the resulting Burden Mark.
        assert not blocked
        prompt = result["reaction"]
        assert prompt["context"]["reaction_source_id"] not in {
            "choice:needle.teleport_destination", "choice:needle.grave_refuses"}
        answers.append({**prompt["context"], "selection": "DECLINE", "option_ids": []})
        combat = CombatService(ROOT, tmp_path)
        table = TabletopService(combat, tmp_path)
        result = _send(table, mid, candidate_id, answers)
    assert result["status"] == "COMMITTED", result
    combat = CombatService(ROOT, tmp_path)
    engine = combat._load_session(mid).engine
    actor, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    assert actor.position == Position(x=3 if blocked else 4, y=6)
    assert actor.resources["resource:core.stamina"] == stamina - 1
    assert not actor.bonus_action_available and actor.action_available
    assert foe.resources["resource:core.qi"] == foe_qi - 2 and not foe.reaction_available
    events = _events(combat, mid)
    assert len([e for e in events if e["event_type"] == "SAVE_ROLLED" and e["source_definition_id"] == GRAVE]) == 1
    assert len([e for e in events if e["event_type"] == "REACTION_WINDOW_OPENED" and e["source_definition_id"] == GRAVE]) == 1
    spent = [e for e in events if e["event_type"] == "RESOURCE_SPENT"
             and e["source_definition_id"].endswith(f"{EMPTY_STEP}#pay1")]
    assert [(e["payload"]["resource_id"], e["payload"]["amount"]) for e in spent] == [("resource:core.stamina", 1)]
    hops = [e for e in events if e["event_type"] == "MOVEMENT_COMMITTED" and e["payload"].get("teleport")]
    assert len(hops) == (0 if blocked else 1)
    _assert_no_placement_instruction(combat, mid)


@pytest.mark.parametrize("full_speed", [False, True])
@pytest.mark.parametrize("concealed_start", [False, True])
def test_unbound_step_through_darkness_honors_both_endpoints_and_augment(tmp_path, full_speed, concealed_start):
    from combat import motion

    suffix = "granted.tal_dark_step_through_darkness" + ("+full" if full_speed else "")
    combat, table, mid = _table(
        tmp_path, owner_talents=("TAL_DARK_STEP_THROUGH_DARKNESS", "tianxia.subpath.qi.ninpo_adept.feature.smoke_veil"),
        unbind=suffix)
    state = _owners_turn(table, mid)
    if concealed_start:
        _place_smoke(table, mid, state)
        assert _send(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
        state = _owners_turn(table, mid)
    preview = combat._load_session(mid).engine
    actor = preview.state.actors[OWNER]
    assert motion.obscured(preview, actor) == concealed_start
    action = next(a for a in preview.action_catalog.values() if a.source_definition_id.endswith(suffix))
    assert action.parameters["typed"]["teleport_where"] == "darkness"
    assert all(not r.get("where") for r in action.parameters["typed"]["effects"])
    reach = preview._effective_speed(actor) // (1 if full_speed else 2)
    qi = actor.resources["resource:core.qi"]
    step = next(g for g in state["menu"]["actions"] if g["label"] == action.display_name)
    prompts = _act(table, mid, step["options"][0]["candidate_id"], lambda prompt: ["cell:4,6"])
    assert len(prompts) == (1 if concealed_start else 0)
    if concealed_start:
        offered = [row["id"] for row in prompts[0]["choice"]["options"]]
        from combat.ext.teleport_steps import destinations
        lit = [f"cell:{cell.x},{cell.y}" for cell in destinations(preview, actor, reach)
               if not motion.obscured_at(preview, cell)]
        assert "cell:4,6" in offered and lit and not set(lit).intersection(offered)
        for option in offered:
            x, y = map(int, option.removeprefix("cell:").split(","))
            cell = Position(x=x, y=y)
            assert motion.obscured_at(preview, cell)
            assert preview.grid.distance_ft(actor.position, cell) <= reach
        assert f"up to {reach} feet" in prompts[0]["trigger"]
    reloaded = CombatService(ROOT, tmp_path)._load_session(mid).engine.state.actors[OWNER]
    assert reloaded.position == Position(x=4 if concealed_start else 3, y=6)
    assert reloaded.resources["resource:core.qi"] == qi - int(full_speed)


@pytest.mark.parametrize("unbound", [False, True])
def test_shadow_step_player_selects_destination_at_the_table(tmp_path, unbound):
    """Ninpo Shadow Step (Bonus Action, 1 Qi, 15 feet) uses the player's selected square."""
    combat, table, mid = _table(tmp_path, owner_talents=(SHADOW_STEP, "tianxia.subpath.qi.ninpo_adept.feature.smoke_veil"),
                              unbind=SHADOW_STEP if unbound else None)
    state = _owners_turn(table, mid)
    _place_smoke(table, mid, state)
    assert _send(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    state = _owners_turn(table, mid)
    qi = combat._load_session(mid).engine.state.actors[OWNER].resources["resource:core.qi"]
    step = _group(state, "Shadow Step")
    assert step is not None
    wanted = {"x": 4, "y": 6}
    candidate = step["options"][0] if unbound else next(o for o in step["options"] if o.get("destination") == wanted)
    prompts = _act(table, mid, candidate["candidate_id"], lambda prompt: ["cell:4,6"])
    if unbound:
        assert len(prompts) == 1
        assert prompts[0]["context"]["reaction_source_id"] == "choice:needle.teleport_destination"
        assert "Bonus Action" in prompts[0]["trigger"] and "1 Qi from its resource pool" in prompts[0]["trigger"]
        from combat import motion
        preview = combat._load_session(mid).engine
        for option in prompts[0]["choice"]["options"]:
            x, y = map(int, option["id"].removeprefix("cell:").split(","))
            assert motion.obscured_at(preview, Position(x=x, y=y))
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    actor = engine.state.actors[OWNER]
    assert actor.position == Position(**wanted)
    assert actor.resources["resource:core.qi"] == qi - 1
    assert not actor.bonus_action_available and actor.action_available
    assert len([e for e in _events(combat, mid) if e["event_type"] == "MOVEMENT_COMMITTED" and e["payload"].get("teleport")]) == 1


def test_marked_paid_step_interrupts_then_chooses_commits_and_reloads(tmp_path):
    """Real Smoke Trace + Smother the Breath, then an unbound paid teleport destination.

    Smother interrupts technique start, before the destination is asked. Both answers are resubmitted across
    real table transactions; a fresh service loads the persisted fight at each pause and after commit.
    """
    from combat.typed_executor import bears_mark

    combat, table, mid = _table(tmp_path, unbind_paid=True, smother=True)
    if table.state(mid)["menu"]["actor_id"] != FOE:
        assert _send(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    trace = _group(table.state(mid), "Cinder Wisp")
    assert trace is not None
    candidate = next(o for o in trace["options"] if OWNER in o["target_ids"])
    _act(table, mid, candidate["candidate_id"], lambda prompt: None)
    state = _owners_turn(table, mid)
    assert bears_mark(combat._load_session(mid).engine.state.actors[OWNER], FOE, "Smoke Trace")
    paid = _group(state, f"Empty Step {PAY}")
    candidate_id = paid["options"][0]["candidate_id"]
    assert not paid["options"][0].get("destination")
    before = combat._load_session(mid).engine.state.actors[OWNER]
    stamina, qi = before.resources["resource:core.stamina"], before.resources["resource:core.qi"]
    answers, prompts = [], []
    result = _send(table, mid, candidate_id)
    for _ in range(4):
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        source = prompt["context"]["reaction_source_id"]
        prompts.append(source)
        # Pauses roll back movement/payment; inspect through an entirely fresh service.
        combat = CombatService(ROOT, tmp_path)
        table = TabletopService(combat, tmp_path)
        actor = combat._load_session(mid).engine.state.actors[OWNER]
        assert actor.position == Position(x=3, y=6)
        assert actor.resources["resource:core.stamina"] == stamina
        assert actor.bonus_action_available and actor.action_available
        if source == "reaction:typed." + SMOTHER:
            option_ids = []
        else:
            assert source == "choice:needle.teleport_destination"
            assert any(o["id"] == "cell:4,6" for o in prompt["choice"]["options"])
            option_ids = ["cell:4,6"]
        answers.append({**prompt["context"], "selection": "USE", "option_ids": option_ids})
        result = _send(table, mid, candidate_id, answers)
    assert result["status"] == "COMMITTED", result
    assert prompts == ["reaction:typed." + SMOTHER, "choice:needle.teleport_destination"]
    combat = CombatService(ROOT, tmp_path)
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[OWNER]
    assert actor.position == Position(x=4, y=6)
    assert actor.resources["resource:core.stamina"] == stamina - 1
    assert actor.resources["resource:core.qi"] == qi
    assert not actor.bonus_action_available and actor.action_available
    assert not engine.state.actors[FOE].reaction_available
    assert not bears_mark(actor, FOE, "Smoke Trace")
    events = _events(combat, mid)
    assert len([e for e in events if e["event_type"] == "REACTION_RESOLVED"
                and e["source_definition_id"] == SMOTHER]) == 1
    assert len([e for e in events if e["event_type"] == "SAVE_ROLLED"
                and e["source_definition_id"] == SMOTHER]) == 1
    spent = [e for e in events if e["event_type"] == "RESOURCE_SPENT"
             and e["source_definition_id"].endswith(f"{EMPTY_STEP}#pay1")]
    assert [(e["payload"]["resource_id"], e["payload"]["amount"]) for e in spent] == [
        ("resource:core.stamina", 1)]
    hops = [e for e in events if e["event_type"] == "MOVEMENT_COMMITTED" and e["payload"].get("teleport")]
    assert len(hops) == 1 and hops[0]["payload"]["destination"] == {"x": 4, "y": 6}


def _paid_intent(candidate, decisions=()):
    return ActionIntent(intent_id="mmx86pay", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                        state_version=candidate.state_version, actor_id=OWNER, target_ids=candidate.target_ids,
                        option_ids=candidate.option_ids, reaction_decisions=tuple(decisions))


def test_a_recorded_destination_replays_in_an_equivalent_fresh_engine():
    """Recorded-answer unit coverage only; the second engine is newly built, not a persisted reload.

    The table tests separately cover actual interruption, transaction rollback, commit and reload.
    """
    answered_engine = _engine(unbind_paid=True)
    asked = []

    def choose(request):
        asked.append(request)
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="USE",
                                option_ids=("cell:5,6",)), None

    answered_engine.set_reaction_provider(choose)
    answered_engine.execute_intent(_paid_intent(_paid_candidate(answered_engine)))
    assert asked, "the player was never asked where the paid step lands"
    actor = answered_engine.state.actors[OWNER]
    assert (actor.position.x, actor.position.y) == (5, 6), "the engine chose the square instead of the player"
    assert actor.resources["resource:core.stamina"] == 29, "the Stamina-paid variant spends exactly 1 Stamina"
    assert actor.bonus_action_available is False and actor.action_available is True

    request = asked[0]
    recorded = ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="USE",
                                option_ids=("cell:5,6",))
    reloaded = _engine(unbind_paid=True)  # equivalent starting state, not a saved fight reload
    asked_again = []

    def refusing(request):
        asked_again.append(request["legal_option_ids"])
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="USE",
                                option_ids=(request["legal_option_ids"][-1],)), None

    reloaded.set_reaction_provider(refusing)
    reloaded.execute_intent(_paid_intent(_paid_candidate(reloaded), [recorded]))
    assert not asked_again, "the recorded answer was dropped and the player was asked a second time"
    actor = reloaded.state.actors[OWNER]
    assert (actor.position.x, actor.position.y) == (5, 6), "the replay landed somewhere the player never chose"
    assert actor.resources["resource:core.stamina"] == 29, "the fresh engine replay must spend Stamina once"
    assert actor.bonus_action_available is False and actor.action_available is True


@pytest.mark.parametrize("mode", ["LOCAL_AUTO", "API_AUTO", None])
def test_an_ai_combatant_is_never_asked_where_a_paid_teleport_lands(mode):
    """Owner ruling: an AI combatant keeps its existing automatic choice, so AI fights still replay unchanged."""
    engine = _engine(mode=mode) if mode else _engine()
    if mode is None:
        engine.typed_control_modes = {}
    action = _unbound_paid_variant(engine)
    asked = []

    def choose(request):
        asked.append(request["legal_option_ids"])
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="USE"), None

    engine.set_reaction_provider(choose)
    _use(engine, action)
    assert not asked, "an AI combatant must never be asked a player-owned question"
    assert (engine.state.actors[OWNER].position.x, engine.state.actors[OWNER].position.y) == (3, 6)
