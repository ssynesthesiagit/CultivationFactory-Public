"""Plague Cloud (Disease): the three printed effects that never ran.

The talent (authority/typed_mechanics/rules_text.json tianxia.talent.disease.plague_cloud) offers 2 extra CP when you Raise the
Quarantine Veil in Outbreak Mode, and its reviewed modifier (reviewed_final.d/martial.json) carries nothing but a bare "rider"
effect, so at runtime the table printed the line for the GM to resolve and did none of it. This drives a real fight through
TabletopService and proves the printed line, at the table, across table commits and reloads: the veil's area becomes lightly
obscured, an enemy that fails the veil's saving throw gains exactly one Contagion Token, and at Core Formation that enemy
regains only half the Hit Points it would normally regain from healing, ending at the start of the veil-maker's next turn.

Two things make the healing half readable rather than merely asserted. The enemy cultivates Plague-Bearing Body first (printed
immunity to Sickened), so the veil's own Sickened never lands and nothing but Plague Cloud can halve healing on that creature.
And the seed-pinned initiative puts one Life cultivator's mend inside the window and another's after it, in the same round on
the same wounded enemy: half its roll, then all of it. The veil is saved against at Technique save DC 50, which no d20 plus a
low-Constitution enemy can answer.
"""

from __future__ import annotations

import json

import pytest

from combat import zones
from combat.ext.disease import tokens
from combat.factory_compiler import compile_character
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

CLOUD = "tianxia.talent.disease.plague_cloud"
BODY = "tianxia.talent.disease.plague_bearing_body"
SOW = "DISEASE_BASE_SOW_THE_FEVER_SEED"
MEND = "LIFE_BASE_MEND_THE_PULSE"
MEND_AT = "Mend the Pulse"  # the same ability as the decision menu prints it
VEIL = "Raise the Quarantine Veil: Outbreak Mode + Plague Cloud"
NO_BASE_ABILITIES = "automatic_sphere_component_record_ids"
SEED = "PGC-PLAGUE-CLOUD-7-21"
PLACEMENT_SQUARE = "choice:placement_menu.square"

PLAGUE, EARLY, LATE, FOE = ("actor:factory.pgc-" + name for name in ("plague", "early", "late", "foe"))
TEAMS = {PLAGUE: "team:factory", FOE: "team:pestilence", EARLY: "team:pestilence", LATE: "team:pestilence"}
PLACES = {PLAGUE: {"x": 2, "y": 6}, EARLY: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}, LATE: {"x": 5, "y": 6}}
ROUND = (FOE, EARLY, PLAGUE, LATE)  # the initiative this seed pins


def mechanics():
    from combat import factory_compiler

    return json.loads(factory_compiler.TYPED_AUTHORITY.read_bytes())["mechanics"]


def _hp(doc, hp=200):
    doc["ability_scores_and_statistics"]["hit_points"] = {"maximum": hp}
    return doc


def bundles(cl):
    """PLAGUE raises the veil (Disease, the veil-maker); EARLY and LATE mend it (Life); FOE owns Plague-Bearing Body alone.
    The two menders stand on FOE's side: Mend the Pulse is a friendly mend, and the enemy it heals is the one the veil caught.

    FOE takes that talent without its sphere's base abilities: it is a creature that is hard to sicken, not a second
    veil-maker, and every ability it could otherwise raise would blur what this fight is about.
    """
    mechs = mechanics()
    sphere = mechs[SOW]["sphere_id"]
    bases = [k for k, m in mechs.items() if m.get("sphere_id") == sphere and m.get("kind") == "base_ability"]
    carrier = _hp(sheet([BODY], cl=cl, dc=50))
    carrier["spheres_and_talents"].pop(NO_BASE_ABILITIES, None)
    return [compile_character(_hp(sheet(list(dict.fromkeys([*bases, SOW, CLOUD])), cl=cl, dc=50)), actor_id=PLAGUE),
            compile_character(_hp(sheet([MEND], cl=cl, dc=16)), actor_id=EARLY),
            compile_character(_hp(sheet([MEND], cl=cl, dc=16)), actor_id=LATE),
            compile_character(carrier, actor_id=FOE)]


def fight(tmp_path, *, cl=12):
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        bundles(cl), list(TEAMS), TEAMS, PLACES, combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"],
        [PLAGUE], [FOE, EARLY, LATE], control_modes={aid: "MANUAL" for aid in TEAMS}, match_seed=SEED,
        display_name="Plague Cloud regression", maximum_rounds=20)["match_id"]
    engine = Gate4ControllerEngine(ROOT, match_seed=SEED, typed_bundles=tuple(bundles(cl)),
                                   roster_setup={"primary_actor_ids": list(TEAMS), "team_by_actor": TEAMS,
                                                 "starting_positions": PLACES})
    assert tuple(engine.state.initiative_order) == ROUND, list(engine.state.initiative_order)
    return combat, table, mid


def fresh(combat, mid):
    """A second service reading the same table: the fight as it stands after the last commit was stored."""
    return CombatService(ROOT, combat.userdata_root)._load_session(mid)


def turn_of(table, mid, actor):
    """End turns (declining every prompt) until ``actor`` is up, and hand back its menu."""
    for _ in range(2 * len(TEAMS)):
        state = table.state(mid)
        if state["menu"]["actor_id"] == actor:
            return state
        end_turn(table, mid, state)
    pytest.fail(f"{actor} never came up")


def _act(table, mid, state, entry, answers=(), centre_on=None):
    menu = state["menu"]
    answers = list(answers)
    result = table.act(mid, entry, menu["decision_id"], menu["state_version"], state["last_sequence"], list(answers))
    while result["status"] == "REACTION_REQUIRED":
        prompt = result["reaction"]
        context = prompt["context"]
        if context["reaction_source_id"] == PLACEMENT_SQUARE:
            # Placement menus are lazy since 0b7a87b0: the action commits through an ordinary
            # square choice, so bind the cell nearest the one the old eager menu offered.
            cells = prompt["choice"]["options"]
            assert cells, prompt
            if centre_on is None:
                picked = cells[0]
            else:
                picked = min(cells, key=lambda o: (abs(o["cell"]["x"] - centre_on["x"])
                                                  + abs(o["cell"]["y"] - centre_on["y"]), o["cell"]["z"]))
            answers = [*answers, {**context, "selection": "USE", "option_ids": [picked["id"]]}]
        else:
            answers = [*answers, {**context, "selection": "DECLINE"}]
        result = table.act(mid, entry, menu["decision_id"], menu["state_version"], state["last_sequence"],
                           list(answers))
    return result


def end_turn(table, mid, state):
    result = _act(table, mid, state, state["menu"]["end_turn"])
    assert result["status"] == "COMMITTED", result
    return result["state"]


def use_ability(table, mid, state, label, *, target=None, centre_on=None):
    """Take one named action out of ``state``'s menu and assert it committed."""
    menu = state["menu"]
    group = next((g for g in menu["actions"] if label in g["label"]), None)
    assert group is not None, (label, [g["label"] for g in menu["actions"]])
    options = group["options"]
    if target is not None:
        options = [o for o in options if target in (o.get("target_ids") or [])]
    assert options, (label, target, group["options"])
    placed = [o for o in options if o.get("destination")]
    if centre_on is not None and placed:  # an eager menu names its cells; keep the nearest one
        options = [min(placed, key=lambda o: abs(o["destination"]["x"] - centre_on["x"])
                       + abs(o["destination"]["y"] - centre_on["y"]))]
    result = _act(table, mid, state, options[0]["candidate_id"], centre_on=centre_on)
    assert result["status"] == "COMMITTED", result
    return result["state"]


def mend(engine):
    """What the last mend rolled and how much of it the engine credited the creature with.

    ``offered`` is the mend after the healing reductions and before the "you cannot regain more Hit Points than you are
    missing" ceiling, so it reads the rule rather than the enemy's accident of Hit Points.
    """
    roll = next((r for r in reversed(engine.rolls) if str(r.reason or "").startswith("HEALING")), None)
    applied = next((e for e in reversed(engine.events) if e.event_type == "HEALING_APPLIED"), None)
    assert roll is not None and applied is not None, "no mend was resolved"
    return int(roll.total), int(applied.payload["offered"]), int(applied.payload["before"]), int(applied.payload["after"])


def hp_of(engine, actor_id):
    return engine.state.actors[actor_id].current_hp


def cap_on(engine, actor_id):
    """Whatever is halving this creature's healing right now, read the way the healing rules read it."""
    from combat.typed_executor import condition_rules

    rows = [row for row in condition_rules(engine.state.actors[actor_id]) if row.get("healing_halved")]
    assert len(rows) <= 1, "one creature cannot be halving its healing twice over"
    return next((c for c in engine.state.actors[actor_id].conditions.values()
                 if (c.data or {}).get("rule", {}).get("healing_halved")), None) if rows else None


def holds(engine, actor_id, condition_id):
    return any(c.condition_id == condition_id for c in engine.state.actors[actor_id].conditions.values())


@pytest.mark.parametrize("cl,capped", [(12, True), (15, True), (9, False)], ids=["core-formation", "nascent-soul", "foundation"])
def test_plague_cloud_obscures_the_veil_and_a_failed_save_gains_a_token_and_halves_healing_to_the_next_turn(tmp_path, cl, capped):
    combat, table, mid = fight(tmp_path, cl=cl)

    # The enemy arms itself against Sickened first, so nothing but Plague Cloud can halve healing on it below.
    use_ability(table, mid, turn_of(table, mid, FOE), "Plague-Bearing Body")
    engine = fresh(combat, mid).engine
    assert holds(engine, FOE, "condition:typed.plague_body_immunity")

    # The printed talent: Raise the Quarantine Veil in Outbreak Mode, paying the 2 extra CP.
    use_ability(table, mid, turn_of(table, mid, PLAGUE), VEIL, centre_on=PLACES[FOE])
    veil = zones.typed_zones(fresh(combat, mid).engine)[0]
    assert veil.active and veil.trigger_profile.get("obscured") == "light"

    # The veil's own save (Technique save DC 50) fails at the enemy's turn start: exactly one Contagion Token, and the cap.
    turn_of(table, mid, FOE)
    engine = fresh(combat, mid).engine
    foe = engine.state.actors[FOE]
    assert tokens(engine, engine.state.actors[PLAGUE], foe) == 1
    assert not holds(engine, FOE, "condition:typed.sickened")
    assert foe.current_hp < foe.maximum_hp  # the veil's own 3d6 necrotic damage landed, so a mend has room to heal
    assert (cap_on(engine, FOE) is not None) is capped
    if capped:
        assert cap_on(engine, FOE).expires_on == "START_OF_SOURCE_NEXT_TURN"  # until the veil-maker's next turn
        assert cap_on(engine, FOE).source_actor_id == PLAGUE

    # EARLY mends inside the window (before the veil-maker's next turn), LATE mends after it: half the roll, then all of it.
    wounded = hp_of(engine, FOE)
    use_ability(table, mid, turn_of(table, mid, EARLY), MEND_AT, target=FOE)
    engine = fresh(combat, mid).engine
    rolled, offered, before, after = mend(engine)
    assert offered == (rolled // 2 if capped else rolled), (cl, capped, rolled, offered)
    assert (before, after - before) == (wounded, min(offered, foe.maximum_hp - wounded))

    end_turn(table, mid, turn_of(table, mid, PLAGUE))  # the start of the veil-maker's next turn ends the cap
    engine = fresh(combat, mid).engine
    assert cap_on(engine, FOE) is None
    wounded = hp_of(engine, FOE)
    use_ability(table, mid, turn_of(table, mid, LATE), MEND_AT, target=FOE)
    engine = fresh(combat, mid).engine
    rolled, offered, before, after = mend(engine)
    assert offered == rolled and (before, after - before) == (wounded, min(offered, foe.maximum_hp - wounded)), (cl, rolled, offered)
    assert fresh(combat, mid).mechanical.replay()["status"] == "PASS"
