"""Knot the Knee and Threaded Step Formation answer their printed movement rules at the table.

Both abilities only mean something while a creature is walking, so every case moves a real
creature through a real table turn, answers the owner's question, and reads the state the fight
keeps afterwards: how far the creature stopped, whether it fell Prone, whether the mark was
spent and whether the owner's Reaction was used.  Each case commits through TabletopService and
is re-read through a fresh CombatService with a mechanical replay (``reload``).

The fixture seals independent portable sheets before the match exists: the owner (LEFT), a
hostile creature that carries the owner's Tension Mark (RIGHT) and, when a case needs one, a
willing ally (OTHER).  ``Prepare`` is a real typed action the owner uses to place the mark, so
no test reaches into fight state to set one up.
"""
import json
import zipfile

import pytest

from combat.canonical import canonical_sha256
from combat.ext import placed
from tests.auto28_puppetry_support import resolve
from tests.auto_worker1_support import LEFT, RIGHT

SPHERE = "tianxia.sphere.puppetry"
KNEE = "tianxia.talent.puppetry.knot_the_knee"
STEP = "tianxia.talent.puppetry.threaded_step_formation"
OWNED = ["PUPPETRY_BASE_RAISE_THE_VESSEL", "PUPPETRY_BASE_PUPPET_STRIKE"]
MARK_ACTION = "action:test.auto105.mark"
MARK_EFFECTS = [{"type": "mark", "mark": "Tension Mark", "applies_to": "target",
                 "duration": {"kind": "until_end_of_your_next_turn"}}]


def _bundle(tmp_path, actor_id, talents, *, spheres, ally=False, mark=False, legacy=False, test_effects=()):
    from combat.factory_compiler import compile_character
    from tests.h1_support import ROOT, sheet
    from tests.test_carry import KIT

    doc = sheet(list(talents), cl=15, dc=100, kit={"starting_kit": KIT}, score=14)
    doc.setdefault("spheres_and_talents", {})["sphere_record_ids"] = list(spheres)
    doc["spheres_and_talents"]["automatic_sphere_component_record_ids"] = []
    stats = doc["ability_scores_and_statistics"]
    stats["primary_resource"]["maximum"] = 100
    stats["hit_points"]["maximum"] = 1000
    stats["armor_class"]["base_value"] = 1
    doc["identity"]["display_name"] = {LEFT: "Keeper", RIGHT: "Visitor"}.get(actor_id, "Ally")
    folder = tmp_path / "portable_characters" / actor_id.removeprefix("actor:factory.")
    folder.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    bundle = compile_character(doc, actor_id=actor_id, reaction_plan={"ask": True})
    if mark:
        mark_action = MARK_ACTION + "." + actor_id.removeprefix("actor:factory.")
        bundle["actor_template"]["action_ids"].append(mark_action)
        bundle["action_catalog"].append({
            "source_definition_id": mark_action, "display_name": "Thread the Mark", "owner_id": actor_id,
            "economy": "NONE", "resolution_kind": "TYPED", "target_kind": "HOSTILE_ENTITY", "range_ft": 60, "costs": [],
            "parameters": {"typed": {"effects": MARK_EFFECTS, "numbers": {"cl": 15, "pb": 4, "key_mod": 3},
                                     "duration": {"kind": "instant"}, "riders": []}}})
        if ally:
            bundle["action_catalog"][-1]["parameters"]["typed"]["effects"] = [
                {**MARK_EFFECTS[0], "duration": {"kind": "one_minute"}}]
    if legacy:
        for action in bundle["action_catalog"]:
            if action.get("parameters", {}).get("vessel_kit"):
                action["parameters"]["vessel_native"] = False
    if test_effects:
        action_id = "action:test.auto105.walks." + actor_id.removeprefix("actor:factory.")
        bundle["actor_template"]["action_ids"].append(action_id)
        bundle["action_catalog"].append({"source_definition_id": action_id, "owner_id": actor_id,
            "display_name": "Two Walks", "economy": "NONE", "resolution_kind": "TYPED", "target_kind": "SELF",
            "range_ft": 0, "costs": [], "parameters": {"description": "Take two separate ten-foot walks for this test.",
            "typed": {"effects": list(test_effects), "numbers": {}, "duration": {"kind": "instant"}, "riders": []}}})
    bundle.pop("bundle_sha256", None)
    bundle["bundle_sha256"] = canonical_sha256(bundle)
    return bundle


def scene(tmp_path, talents, *, ally=False, left_kit=None, marked=True, second_puppeteer=False, legacy=False, extra_enemy=False, right_effects=(), left_effects=()):
    """Owner with a raised vessel and a marked hostile creature; ``ally`` adds a willing team mate."""
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.auto28_puppetry_support import turn as turn_to
    from tests.auto_worker1_support import act, reload
    from tests.h1_support import ROOT

    ally_id = "actor:factory.auto105-ally"
    enemy_id = "actor:factory.auto105-enemy2"
    bundles = [_bundle(tmp_path, LEFT, talents, spheres=[SPHERE], mark=True, legacy=legacy, ally=second_puppeteer,
                       test_effects=left_effects)]
    for actor_id in ([RIGHT] + ([ally_id] if ally else []) + ([enemy_id] if extra_enemy else [])):
        other_owner = second_puppeteer and actor_id == ally_id
        bundles.append(_bundle(tmp_path, actor_id, [*OWNED, KNEE] if other_owner else [],
                               spheres=[SPHERE] if other_owner else [], mark=other_owner, ally=other_owner,
                               test_effects=right_effects if actor_id == RIGHT else ()))
    combat = CombatService(ROOT, tmp_path)
    teams = {LEFT: "team:a", RIGHT: "team:b", ally_id: "team:a", enemy_id: "team:b"}
    positions = {LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 4, "y": 6}, ally_id: {"x": 3, "y": 7}, enemy_id: {"x": 4, "y": 8}}
    roster = [LEFT] + ([ally_id] if ally else []) + [RIGHT] + ([enemy_id] if extra_enemy else [])
    mid = combat._finish_factory_match(
        bundles, roster, teams, positions, combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"],
        [a for a in roster if teams[a] == "team:a"], [a for a in roster if teams[a] == "team:b"],
        control_modes={a: "MANUAL" for a in roster}, match_seed="auto105",
        display_name="Puppetry movement regression", maximum_rounds=10)["match_id"]
    table = TabletopService(combat, tmp_path)
    turn_to(table, mid, LEFT)
    _raise(table, combat, mid, 5, 6)
    if marked:
        assert act(table, mid, "Thread the Mark", target_id=RIGHT)["status"] == "COMMITTED"
    return combat, table, mid, (ally_id if ally else None)


def _raise(table, combat, mid, x, y):
    """Raise the printed vessel through the owner's real activation (its optional move is declined)."""
    from tests.auto28_puppetry_support import resolve
    from tests.auto_worker1_support import reload

    state = table.state(mid)
    engine = combat._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates()
                     if c.display_name.startswith("Raise the Vessel (1 CP)") and (c.destination.x, c.destination.y) == (x, y))
    resolve(lambda answers: table.act(mid, candidate.candidate_id, state["menu"]["decision_id"],
                                      state["menu"]["state_version"], state["last_sequence"], answers),
            {"choice:needle.vessel_raise_move": []})
    zone = next(z for z in placed.of(reload(combat, mid), "vessel", owner_id=candidate.actor_id)
                if placed.data(z).get("state") == "active" and (z.center.x, z.center.y) == (x, y))
    assert (zone.center.x, zone.center.y) == (x, y)
    return zone


def turn_to(table, mid, actor_id):
    from tests.auto28_puppetry_support import turn

    turn(table, mid, actor_id)


NO_OA = {"reaction:typed.opportunity_attack": []}
KNEE_ASK = "choice:needle.knot_the_knee"
STEP_ASK = "choice:needle.threaded_step"
STEP_SQUARE = "choice:needle.threaded_step_move"


def far_move(engine, actor, feet, *, longest=True):
    """The table's own movement candidate for ``actor`` that walks at least ``feet``.

    ``longest=False`` asks for the shortest qualifying walk instead, so a case can prove the
    printed "at least 10 feet" limit is real rather than merely unmet by an unlucky roll.
    """
    options = [c for c in engine.legal_candidates()
               if c.source_definition_id == "system:combat.movement" and c.destination
               and engine.grid.distance_ft(actor.position, c.destination) >= feet]
    assert options, "this creature has no movement candidate that far"
    return (max if longest else min)(options, key=lambda c: (engine.grid.distance_ft(actor.position, c.destination), c.candidate_id))


def move_sender(table, mid, candidate, *, ai=False):
    if ai:
        from combat.gate4_adapters import ManualControllerAdapter
        combat = table.combat
        real = combat.controller
        class Controller:
            def choose_primary_action(self, context):
                matches = [c for c in context.legal_candidates
                           if c.source_definition_id == candidate.source_definition_id
                           and c.destination == candidate.destination and c.target_ids == candidate.target_ids]
                assert matches, "the requested fixture action must belong to the actual AI menu"
                selected = matches[0]
                return ManualControllerAdapter(lambda _: (selected.candidate_id, ())).choose_primary_action(context)
            def __getattr__(self, name):
                return getattr(real, name)
        combat.controller = Controller()
        combat.set_controller_mode(mid, actor_id=candidate.actor_id, controller_mode="LOCAL_AUTO")
        return lambda answers: table.auto_step(mid, table.state(mid)["last_sequence"], answers)
    state = table.state(mid)
    menu = state["menu"]
    return lambda answers: table.act(mid, candidate.candidate_id, menu["decision_id"],
                                     menu["state_version"], state["last_sequence"], answers)


def mark_id(owner_id):
    return f"condition:typed.mark.tension_mark.{owner_id}"


def has_mark(actor, owner_id):
    return any(c.condition_id == mark_id(owner_id) for c in actor.conditions.values())


def is_prone(actor):
    return any(c.condition_id == "condition:typed.prone" for c in actor.conditions.values())


def first_step_cell(engine, actor_id):
    """One legal five-foot step for the ally, as the printed grant allows."""
    actor = engine.state.actors[actor_id]
    from combat.ext.granted_movement import choices

    options = sorted((c.destination.x, c.destination.y) for c in choices(engine, actor, 5)
                     if (c.destination.x, c.destination.y) != (actor.position.x, actor.position.y))
    assert options, "the ally has no five-foot step to take"
    return f"cell:{options[0][0]},{options[0][1]}"


def asked_about(prompts, choice_id):
    """Prompts answered by one named choice, read from the reaction's own identity."""
    return [p for p in prompts if str(p.get("context", {}).get("reaction_source_id")) == choice_id]


@pytest.mark.parametrize("save_bonus,fails", [(0, True), (200, False)])
@pytest.mark.parametrize("ai", [False, True])
def test_knot_the_knee_answers_while_the_marked_creature_is_still_walking(tmp_path, monkeypatch, save_bonus, fails, ai):
    """The printed save is answered on the first step, so a failure stops the walk after 5 feet."""
    from tests.test_lock_choices import install
    from tests.auto_worker1_support import reload

    if save_bonus:
        install(monkeypatch, "d20_bonus", lambda *a: {"source_id": "test:auto105.knee", "bonus": save_bonus})
    combat, table, mid, _ally = scene(tmp_path, [*OWNED, KNEE])
    turn_to(table, mid, RIGHT)
    engine = reload(combat, mid)
    assert has_mark(engine.state.actors[RIGHT], LEFT)
    start = engine.state.actors[RIGHT].position
    speed, budget = engine._effective_speed(engine.state.actors[RIGHT]), engine.state.actors[RIGHT].movement_remaining_ft
    _result, prompts = resolve(move_sender(table, mid, far_move(engine, engine.state.actors[RIGHT], 10), ai=ai), NO_OA)
    asked = asked_about(prompts, KNEE_ASK)
    assert len(asked) == 1, prompts
    said = str(asked[0])
    assert RIGHT in said and "Tension Mark" in said and "Reaction" in said and "10 feet" in said
    after = reload(combat, mid)
    walker = after.state.actors[RIGHT]
    assert not has_mark(walker, LEFT), "the printed reaction spends the mark"
    assert not after.state.actors[LEFT].reaction_available
    saves = [r for r in after.events if r.event_type == "SAVE_ROLLED"
             and r.actor_id == RIGHT and r.source_definition_id == KNEE]
    assert len(saves) == 1, [(r.event_type, r.source_definition_id) for r in after.events[-10:]]
    assert bool(saves[0].payload["success"]) is not fails
    if fails:
        # "It falls Prone after moving 5 feet": one step of walking, then the fall.
        assert is_prone(walker), "a failed Dexterity save must leave it Prone"
        assert after.grid.distance_ft(start, walker.position) == 5
    else:
        # "Its Speed is reduced by 10 feet until the end of the current turn".
        assert not is_prone(walker)
        assert after.grid.distance_ft(start, walker.position) > 5
        assert after._effective_speed(walker) == speed - 10
        movement = next(e for e in reversed(after.events) if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == RIGHT)
        assert walker.movement_remaining_ft == budget - 10 - movement.payload["cost_ft"]


def test_knot_the_knee_declining_keeps_the_mark_and_the_walk(tmp_path):
    from tests.auto_worker1_support import reload

    combat, table, mid, _ally = scene(tmp_path, [*OWNED, KNEE])
    turn_to(table, mid, RIGHT)
    engine = reload(combat, mid)
    start = engine.state.actors[RIGHT].position
    _result, prompts = resolve(move_sender(table, mid, far_move(engine, engine.state.actors[RIGHT], 10)),
                               dict(NO_OA, **{"choice:needle.knot_the_knee": []}))
    assert asked_about(prompts, KNEE_ASK)
    after = reload(combat, mid)
    assert has_mark(after.state.actors[RIGHT], LEFT), "declining must not spend the mark"
    assert not is_prone(after.state.actors[RIGHT])
    assert after.grid.distance_ft(start, after.state.actors[RIGHT].position) > 5
    # One opportunity per movement: the end of the walk must not hand the same mark back.
    assert len(asked_about(prompts, KNEE_ASK)) == 1, prompts


def test_knot_the_knee_needs_ten_feet_of_planned_movement(tmp_path):
    from tests.auto_worker1_support import reload

    combat, table, mid, _ally = scene(tmp_path, [*OWNED, KNEE])
    turn_to(table, mid, RIGHT)
    engine = reload(combat, mid)
    short = [c for c in engine.legal_candidates()
             if c.source_definition_id == "system:combat.movement" and c.destination
             and 0 < int(c.movement_cost_ft or 0) < 10]
    assert short, "this creature has no walk of fewer than 10 feet to offer"
    _result, prompts = resolve(move_sender(table, mid, min(short, key=lambda c: c.candidate_id)), NO_OA)
    assert not asked_about(prompts, KNEE_ASK), "a walk of fewer than 10 feet is not the printed trigger"
    after = reload(combat, mid)
    assert has_mark(after.state.actors[RIGHT], LEFT)


def test_knot_the_knee_is_inert_without_the_talent(tmp_path):
    from tests.auto_worker1_support import reload

    combat, table, mid, _ally = scene(tmp_path, list(OWNED))
    turn_to(table, mid, RIGHT)
    engine = reload(combat, mid)
    start = engine.state.actors[RIGHT].position
    _result, prompts = resolve(move_sender(table, mid, far_move(engine, engine.state.actors[RIGHT], 10)), NO_OA)
    assert not asked_about(prompts, KNEE_ASK), "a puppeteer without Knot the Knee is never asked"
    after = reload(combat, mid)
    assert has_mark(after.state.actors[RIGHT], LEFT)
    assert after.grid.distance_ft(start, after.state.actors[RIGHT].position) > 5


def test_threaded_step_formation_lets_the_willing_ally_step_without_provoking(tmp_path):
    """The ally moves the printed 5 feet through the ordinary step rules, once per owner turn."""
    from tests.auto_worker1_support import act, reload

    combat, table, mid, ally = scene(tmp_path, [*OWNED, STEP], ally=True)
    engine = reload(combat, mid)
    assert ally is not None and has_mark(engine.state.actors[RIGHT], LEFT)
    before = engine.state.actors[ally].position
    state = table.state(mid)
    candidate = next(c for c in engine.legal_candidates()
                     if c.source_definition_id.endswith("vessel.move") and c.destination
                     and engine.grid.distance_ft(placed.of(engine, "vessel")[0].center, c.destination) > 0
                     and engine.grid.distance_ft(engine.state.actors[ally].position, c.destination) <= 5)
    _result, prompts = resolve(move_sender(table, mid, candidate), {
        STEP_ASK: [ally],
        "choice:needle.threaded_step_exempt": [RIGHT],
        STEP_SQUARE: [first_step_cell(engine, ally)],
    })
    asked = asked_about(prompts, STEP_ASK)
    assert asked, prompts
    said = str(asked[0])
    assert ally in said and "willing ally" in said and "5 feet" in said and "Tension Mark" in said
    assert asked_about(prompts, STEP_SQUARE), prompts
    after = reload(combat, mid)
    assert after.grid.distance_ft(before, after.state.actors[ally].position) == 5
    assert not any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id == "system:combat.opportunity_attack"
                   and e.actor_id == RIGHT and ally in (e.target_ids or ())
                   for e in after.events), "the marked creature must not get an Opportunity Attack at it"
    assert act(table, mid, "end")["status"] == "COMMITTED"
    assert table.state(mid)["menu"]["actor_id"] in (RIGHT, ally)


def test_threaded_step_formation_is_inert_without_the_talent(tmp_path):
    from tests.auto_worker1_support import reload

    combat, table, mid, ally = scene(tmp_path, list(OWNED), ally=True)
    engine = reload(combat, mid)
    before = engine.state.actors[ally].position
    candidate = next(c for c in engine.legal_candidates()
                     if c.source_definition_id.endswith("vessel.move") and c.destination
                     and engine.grid.distance_ft(placed.of(engine, "vessel")[0].center, c.destination) > 0
                     and engine.grid.distance_ft(engine.state.actors[ally].position, c.destination) <= 5)
    _result, prompts = resolve(move_sender(table, mid, candidate))
    assert not asked_about(prompts, STEP_ASK)
    after = reload(combat, mid)
    assert after.state.actors[ally].position == before
