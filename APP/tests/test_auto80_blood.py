"""AUTO80: the Blood sphere lines that used to be GM reminders and now run at the table.

Owner 2026-09-29: "i want everything we can automated, keep going until its only the non-combat ones left".
This lane (auto/blood, int/r25x2-fix) adds:

* Scarlet Mist Form's two movement clauses -- "move through occupied spaces as difficult
  terrain" and "apply Blood Thread automatically to one creature whose space you move
  through, once per turn" (combat/ext/blood_scarlet_mist.py, on the engine's own
  pass_through / pass_through_entered seams).
* Physician's Pulse's examination: it reads the examined creature's live conditions and
  names what it found (combat/ext/blood_diagnosis.py).
* Vital Transfusion's printed limitation, which the effect itself already enforces, moved
  out of the fight's GM reminders.

Every test below presses a printed button on a real compiled character and reads the engine's
own state, events or reload; none of them calls a plug-in function directly. The Scarlet Mist
Form crossings go through the real table's preview/question/commit/reload boundary
(``_mist_fight`` below), so the question, the rollback and the saved state are all exercised.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import pytest

import combat.factory_compiler as compiler
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, Position
from tests import test_auto_lane4 as L4
from tests import test_riders_c5 as C

t = L4.t
ME = L1_ME = "actor:factory.lane1"
ALLY = "actor:factory.lane1_ally"
BL = "tianxia.talent.blood."
SPHERE = "tianxia.sphere.blood"
QI = "resource:core.qi"
STAMINA = "resource:core.stamina"
MIST = "condition:typed.scarlet_mist_form"
THREAD_USE = "typed_once_turn:scarlet_mist_form:blood_thread"
CROSSING = "scarlet_mist_thread"
WILLING = "crimson_mark_willing"


def _authority() -> dict:
    return json.loads(Path(compiler.TYPED_AUTHORITY).read_text(encoding="utf-8"))["mechanics"]


def _misty(talents, cl=12, dc=16, qi=40):
    """ME (a Blood cultivator with ``talents``) beside an ally; the foe adjacent and big enough to bleed."""
    from tests import test_auto_lane1 as L1

    sheet = L1._sheet("BLOOD_BASE_BLOOD_THREAD", cl=cl, dc=dc)
    sheet["spheres_and_talents"]["learned_talent_record_ids"] = [BL + name for name in talents]
    engine = L1._engine(compile_character(sheet, actor_id=L1.ME),
                        allies=(compile_character(t._sheet(None, [], {}), actor_id=ALLY),))
    me, ally, foe = engine.state.actors[ME], engine.state.actors[ALLY], engine.state.actors[AN]
    me.resource_maximums[QI] = me.resources[QI] = qi
    foe.maximum_hp = foe.current_hp = 500
    return L1, engine, me, ally, foe


def _use(L1, engine, name, target=None, *, me=ME):
    L1._ready(engine)
    found = [c for c in engine.legal_candidates() if c.display_name == name and c.actor_id == me
             and (target is None or tuple(c.target_ids or ()) == (target,))]
    assert found, f"{name!r} on {target} is not legal; legal: {sorted({c.display_name for c in engine.legal_candidates()})}"
    candidate = found[0]
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"i-{name}-{engine.state.event_sequence}", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=me,
                                       target_ids=candidate.target_ids, destination=candidate.destination, option_ids=candidate.option_ids))
    return engine.events[before:]


def _threaded(owner, creature) -> bool:
    from combat.typed_executor import mark_condition_id

    return any(c.condition_id == mark_condition_id("Blood Thread", owner.entity_id) for c in creature.conditions.values())


def _mist_form(actor) -> bool:
    return any(c.condition_id == MIST for c in actor.conditions.values())


def _thread_mark(creature, owner_id):
    from combat.typed_executor import mark_condition_id

    return next(c for c in creature.conditions.values() if c.condition_id == mark_condition_id("Blood Thread", owner_id))


def _logs(events) -> list[str]:
    return [str(e.payload.get("log") or "") for e in events if str(e.payload.get("log") or "")]


def _said(engine, *, kinds=("PASSIVE_TRIGGERED",)) -> str:
    return " ".join(str(e.payload.get("text") or e.payload.get("trigger") or e.payload.get("log") or "")
                    for e in engine.events if e.event_type in kinds)


def _gm_lines(name: str) -> list[str]:
    """The GM reminder lines the compiled action for ``name`` would print in a fight."""
    from tests import test_auto_lane1 as L1

    sheet = L1._sheet("BLOOD_BASE_BLOOD_THREAD", cl=18, dc=16)
    sheet["spheres_and_talents"]["learned_talent_record_ids"] = [BL + name]
    bundle = compile_character(sheet, actor_id=ME)
    row = next(r for r in bundle["action_catalog"]
               if ((r.get("parameters") or {}).get("typed") or {}).get("source") == BL + name)
    return list(((row.get("parameters") or {}).get("typed") or {}).get("riders") or [])


@contextmanager
def _saves(*, fail: bool, engine_checks_pass: bool | None = None):
    """Force every printed saving throw in the block to fail (or to succeed).

    A temporary replacement of the roll authority's d20, restored in ``finally``: the printed
    "An unwilling creature makes a Constitution saving throw" is the dice, so a regression about
    whether that save is asked at all has to be able to say which way it went. A saving throw
    succeeds when the total reaches the DC, so a failure is the thousand taken away.

    The engine's own ``SAVE:system:`` checks (a Concentration damage check, say) are left alone unless
    ``engine_checks_pass`` says otherwise: a caster that walks past an enemy can be hit on the way, and
    this helper must not decide that fight by accident.
    """
    from combat.gate2_rolls import DeterministicRollAuthority

    raw = DeterministicRollAuthority.raw_d20

    def forced(roller, *, modifier, actor_id, reason, mode="NORMAL"):
        text = str(reason)
        shift = 0
        if text.startswith("SAVE:"):
            system = text.startswith("SAVE:system:")
            if system and engine_checks_pass is not None:
                shift = 1000 if engine_checks_pass else -1000
            elif not system:
                shift = -1000 if fail else 1000
        return raw(roller, modifier=modifier + shift, actor_id=actor_id, reason=reason, mode=mode)

    DeterministicRollAuthority.raw_d20 = forced
    try:
        yield
    finally:
        DeterministicRollAuthority.raw_d20 = raw


def _saves_by(engine, entity_id) -> list:
    """The saving throws ``entity_id`` itself made, oldest first."""
    return [e for e in engine.events if e.event_type == "SAVE_ROLLED" and e.actor_id == entity_id]


# ------------------------------------------------------------------------------------------------ the table harness
def _mist_fight(tmp_path, talents=("scarlet_mist_form",), *, cl=12, mode="MANUAL", allies=(),
                foes=(("Foe", (6, 5)),), hp=900, seed="AUTO80-MIST", asking=False, large_foes=False):
    """A real table fight in a one-square-wide corridor, because "move through a creature's space" needs one.

    Every square except the row y=5 is a wall, so there is no way round a creature standing in the
    corridor: pressing "Move to 9,5" is the printed crossing, and the movement the fight records is
    difficult terrain (10 feet for the creature's square, 5 for an open one). ``allies`` and ``foes``
    are (display name, square) pairs placed in that row. ``asking`` gives those other creatures an
    "Ask me" reaction plan, so they are manually played players whose own questions -- including a
    crossed creature's decision about Crimson Mark's paid hour -- are put to their controller.
    """
    from combat.canonical import canonical_sha256
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService

    sheet = C._sheet([BL + name for name in talents], spheres=(SPHERE,), cl=cl)
    sheet["identity"]["display_name"] = "Mistweaver"
    mine = C.compile_character(sheet, actor_id=C.ME, reaction_plan={"ask": True})
    for resource in mine["actor_template"]["resources"]:
        if resource["resource_id"] == STAMINA:
            resource["maximum"] = 60
            resource["initial"] = 60
    mine["actor_template"].update(armor_class=0, maximum_hp=hp, initiative_bonus=1000)
    mine.pop("bundle_sha256", None)
    mine["bundle_sha256"] = canonical_sha256(mine)
    bundles, teams, positions = [mine], {C.ME: "team:a"}, {C.ME: {"x": 3, "y": 5}}
    for side, rows in (("team:a", allies), ("team:b", foes)):
        for name, (x, y) in rows:
            actor_id = f"actor:factory.mist{len(teams)}"
            other = C.t._sheet(None, [], {})
            other["identity"]["display_name"] = name
            bundle = (C.compile_character(other, actor_id=actor_id, reaction_plan={"ask": True}) if asking
                      else C.compile_character(other, actor_id=actor_id))
            bundle["actor_template"].update(armor_class=0, maximum_hp=hp, initiative_bonus=-1000)
            if large_foes and side == "team:b":
                from tests.cw2_service_support import add_action, seal
                add_action(bundle, "Prepare Large hostile", [{"type": "size_change", "size": "Large",
                    "applies_to": "self", "expires_on": "UNTIL_REMOVED"}], target="SELF")
                seal(bundle)
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)
            bundles.append(bundle)
            teams[actor_id] = side
            positions[actor_id] = {"x": x, "y": y}
    combat = CombatService(C.ROOT, tmp_path)
    corridor = {"width_squares": 12, "height_squares": 8,
                "walls": [{"shape": "rect", "points": [[0, 0], [12, 5]], "filled": True},
                          {"shape": "rect", "points": [[0, 6], [12, 8]], "filled": True}]}
    if large_foes:
        corridor = {"width_squares": 12, "height_squares": 8,
                    "walls": [{"shape": "rect", "points": [[0, 0], [12, 5]], "filled": True},
                              {"shape": "rect", "points": [[0, 7], [12, 8]], "filled": True}]}
    saved = combat.tabletop_maps.save({"display_name": "Mist corridor", **corridor,
                                       "starts": {"team1": [[3, 5]], "team2": [[9, 5]]}})
    arena = combat.factory_arenas()["battlefield:map." + saved["map_id"]]
    match = combat._finish_factory_match(bundles, list(teams), teams, positions, arena, [C.ME],
                                         [actor for actor, side in teams.items() if side == "team:b"],
                                         control_modes={actor: (mode if actor == C.ME else "MANUAL") for actor in teams},
                                         match_seed=seed, display_name="Mist corridor", maximum_rounds=20)
    table = TabletopService(combat, tmp_path)
    mid = match["match_id"]
    if large_foes:
        foe_id = next(actor for actor, side in teams.items() if side == "team:b")
        _grow_foe(combat, table, mid, foe_id)
    return combat, table, mid


def _grow_foe(combat, table, mid, foe_id):
    """The hostile prepares its Large form through the real table, so it really occupies a 2x2 footprint."""
    from tests.worker2_support import candidate, settle, turn
    turn(table, mid, foe_id)
    settle(table, mid, candidate(combat, mid, "Prepare Large hostile").candidate_id)
    turn(table, mid, C.ME)


def _reloaded(combat, match_id):
    """The fight as it comes back off disk, which is the only persistence evidence that counts."""
    from combat.gate5_service import CombatService

    return CombatService(C.ROOT, combat.userdata_root)._load_session(match_id).engine


def _act(combat, table, match_id, name, *, choose=None, target=None, asked=None):
    """Press the printed button and answer whatever it asks, through the real table.

    ``choose(prompt)`` returns the option ids to take for the Mistweaver's own questions; the default takes the
    first one. ``asked(prompt)`` answers another creature's own question about itself -- a crossed ally deciding
    whether it will bear Crimson Mark's paid hour -- which that creature's controller is asked and the default
    declines, so a refusal is what happens when a test says nothing. Any other creature's reaction (an Opportunity
    Attack on the way past, say) is declined too: these tests are not about that creature. The engine state must be
    untouched while a question is outstanding -- that is the rollback -- and the answer resumes the same action.
    """
    menu = table.state(match_id)["menu"]
    candidates = [c for c in combat.decision(match_id)["context"]["legal_candidates"]
                  if c["display_name"] == name and (target is None or not c["target_ids"] or target in c["target_ids"])]
    assert candidates, f"{name!r} is not on offer: {sorted({c['display_name'] for c in combat.decision(match_id)['context']['legal_candidates']})}"
    candidate = candidates[0]
    before = combat._load_session(match_id).engine.state.model_dump(mode="json")
    answers, prompts = [], []
    for _ in range(12):
        result = table.act(match_id, candidate["candidate_id"], menu["decision_id"], menu["state_version"], 0, answers)
        if result["status"] == "COMMITTED":
            engine = _reloaded(combat, match_id)
            assert engine.state.model_dump(mode="json") == combat._load_session(match_id).engine.state.model_dump(mode="json")
            return engine, prompts
        assert result["status"] == "REACTION_REQUIRED", result
        assert combat._load_session(match_id).engine.state.model_dump(mode="json") == before, "the question rolled the action back"
        prompt = result["reaction"]
        prompts.append(prompt)
        options = [option["id"] for option in prompt.get("choice", {}).get("options", [])]
        if prompt["context"].get("reactor_id") in (None, C.ME):
            chosen = (choose(prompt) if choose else options[:1]) or []
        elif asked is not None and str(prompt["context"].get("reaction_source_id") or "").endswith(WILLING):
            chosen = asked(prompt) or []
        else:
            chosen = []
        answers.append({**prompt["context"], "selection": "USE" if chosen else "DECLINE", "option_ids": chosen})
    raise AssertionError(f"the table never finished its questions for {name!r}")


def _squares(combat, match_id):
    """The walking Move buttons on offer, by square (the "Jump to x,y at 5 ft." variant of the same square
    is left out: this is about ground movement through a creature)."""
    return {(c["destination"]["x"], c["destination"]["y"]): c for c in combat.decision(match_id)["context"]["legal_candidates"]
            if c["kind"] == "MOVE" and not (c["destination"].get("z") or 0)}


def _move(combat, table, match_id, x, y, *, choose=None, asked=None):
    """Press the printed Move button that walks to (x, y), answering whatever the crossing asks."""
    offered = _squares(combat, match_id)
    assert (x, y) in offered, f"no Move to {x},{y}; offered {sorted(offered)}"
    return _act(combat, table, match_id, offered[(x, y)]["display_name"], choose=choose, asked=asked)


def _last_move(engine, actor_id=C.ME):
    """The voluntary movement the fight recorded last (a landing or a fall is not the move)."""
    event = next(e for e in reversed(engine.events)
                 if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == actor_id
                 and e.source_definition_id == "system:combat.movement")
    return event.payload["cost_ft"], [(step["x"], step["y"]) for step in event.payload["path"]]


# =========================================================================================== Scarlet Mist Form
def test_scarlet_mist_form_moves_through_a_creatures_space_as_difficult_terrain():
    """"ability to move through occupied spaces as difficult terrain" -- the engine's own creature-passage answer, so
    crossing a creature is legal but costs twice the movement, and no other creature gets the same permission."""
    from combat import creature_passage

    L1, engine, me, ally, foe = _misty(["scarlet_mist_form"])
    engine.state.actors[ME].position = type(me.position)(x=5, y=5)
    engine.state.actors[AN].position = type(me.position)(x=6, y=5)
    assert creature_passage.permission(engine, me, foe) is None  # before the form

    _use(L1, engine, "Scarlet Mist Form")
    assert _mist_form(me)
    assert creature_passage.permission(engine, me, foe) == "difficult"

    # It is difficult terrain, not free: combat/creature_passage.py keeps the occupied cell out of
    # the free path and doubles its cost, and the same creature still blocks the ally without the form.
    assert creature_passage.permission(engine, ally, foe) is None


def test_scarlet_mist_form_walks_through_a_creature_at_the_table_and_asks_whether_to_thread_it(tmp_path):
    """"ability to apply Blood Thread automatically to one creature whose space you move through, once per turn":
    a real Move through a creature in a corridor it cannot walk around, and the question the crossing asks."""
    combat, table, mid = _mist_fight(tmp_path)
    _act(combat, table, mid, "Scarlet Mist Form")

    offered = _squares(combat, mid)
    assert {y for _x, y in offered} == {5}, "a one-square corridor: there is no way round"
    assert (6, 5) not in offered, "the occupied square is never a destination"
    assert offered[(4, 5)]["movement_cost_ft"] == 5, "open ground is 5 feet a square"

    engine, prompts = _move(combat, table, mid, 9, 5)
    me = engine.state.actors[C.ME]
    foe = next(a for a in engine.state.actors.values() if a.team_id == "team:b")
    cost, path = _last_move(engine)
    assert path == [(3, 5), (4, 5), (5, 5), (6, 5), (7, 5), (8, 5), (9, 5)], path  # through the creature
    assert cost == 35, "difficult terrain: 10 feet for the creature's square, 5 for the five open ones"
    (prompt,) = prompts
    assert prompt["context"]["reaction_source_id"].endswith(CROSSING)
    assert "Scarlet Mist Form" in prompt["trigger"] and foe.display_name in prompt["trigger"]
    assert _threaded(me, foe) and _mist_form(me)
    assert me.turn_flags[THREAD_USE] is True
    assert f"passes through {foe.display_name}" in _said(engine), _said(engine)


def test_scarlet_mist_form_spends_the_turns_use_only_on_the_creature_the_player_chose(tmp_path):
    """The printed line is the user's to spend: declining the first creature crossed leaves the use for the
    next one the same move passes through."""
    combat, table, mid = _mist_fight(tmp_path, foes=(("First Foe", (5, 5)), ("Second Foe", (6, 5))))
    _act(combat, table, mid, "Scarlet Mist Form")
    engine, prompts = _move(combat, table, mid, 9, 5,
                            choose=lambda prompt: [] if "First Foe" in prompt["trigger"] else ["thread"])
    me = engine.state.actors[C.ME]
    threaded = sorted(a.display_name for a in engine.state.actors.values() if _threaded(me, a))
    assert threaded == ["Second Foe"], threaded
    assert [p["context"]["reaction_source_id"].split(".")[-1] for p in prompts] == [CROSSING, CROSSING]
    said = _said(engine)
    assert "moves through First Foe's space without applying your Blood Thread" in said, said
    assert f"passes through Second Foe" in said, said
    assert me.turn_flags[THREAD_USE] is True


def test_scarlet_mist_form_declining_the_only_crossing_keeps_the_turns_use(tmp_path):
    combat, table, mid = _mist_fight(tmp_path)
    _act(combat, table, mid, "Scarlet Mist Form")
    engine, prompts = _move(combat, table, mid, 9, 5, choose=lambda prompt: [])
    me = engine.state.actors[C.ME]
    foe = next(a for a in engine.state.actors.values() if a.team_id == "team:b")
    assert [p["context"]["reaction_source_id"].split(".")[-1] for p in prompts] == [CROSSING]
    assert not _threaded(me, foe) and THREAD_USE not in me.turn_flags
    assert "without applying your Blood Thread, so this turn's use is still available" in _said(engine)


def test_declined_large_creature_crossing_is_not_asked_again_on_interior_steps(tmp_path, monkeypatch):
    """One declined entry notice covers every occupied voxel crossed inside a Large creature."""
    from combat import ext

    entered_by_foe = set()

    def observe_cells(_engine, _mover, occupant, entered, _intent):
        if occupant.team_id == "team:b":
            entered_by_foe.update(entered)

    monkeypatch.setitem(ext._HOOKS, "pass_through_entered_cells",
                        [*ext._HOOKS.get("pass_through_entered_cells", ()), observe_cells])
    combat, table, mid = _mist_fight(tmp_path, large_foes=True, seed="AUTO80-MIST-LARGE-DECLINE")
    _act(combat, table, mid, "Scarlet Mist Form")
    engine, prompts = _move(combat, table, mid, 9, 5, choose=lambda _prompt: [])
    mistweaver = engine.state.actors[C.ME]
    foe = next(a for a in engine.state.actors.values() if a.team_id == "team:b")
    assert len(engine._actor_volume(foe)) > 1
    assert len(entered_by_foe) > 1, "the general crossing notice reports the actual Large-footprint voxels entered"
    assert len(prompts) == 1, [p["trigger"] for p in prompts]
    assert not _threaded(mistweaver, foe)
    assert THREAD_USE not in mistweaver.turn_flags
    assert _reloaded(combat, mid).state.actors[C.ME].turn_flags.get(THREAD_USE) is None


def test_scarlet_mist_form_threads_any_creature_it_crosses_including_an_ally(tmp_path):
    """"one creature" is not "one enemy": an ally's square works too, which is how a Blood Mending or Coagulate
    target gets a Thread without spending an Action on it."""
    combat, table, mid = _mist_fight(tmp_path, allies=(("Ally", (6, 5)),), foes=(("Foe", (10, 5)),))
    _act(combat, table, mid, "Scarlet Mist Form")
    engine, prompts = _move(combat, table, mid, 8, 5)
    me = engine.state.actors[C.ME]
    ally = next(a for a in engine.state.actors.values() if a.display_name == "Ally")
    assert [p["context"]["reaction_source_id"].split(".")[-1] for p in prompts] == [CROSSING]
    assert "Ally" in prompts[0]["trigger"]
    assert _threaded(me, ally), "the ally bears the Thread, so Blood Mending and Coagulate can reach it"


def test_scarlet_mist_form_refreshes_a_creature_that_already_bears_the_thread():
    """A creature that already bears the Thread is asked about again and threaded again -- the ordinary mark row
    refreshes it, instead of the use being spent on nothing. (At the table the plain Thread always ends at the
    start of its owner's next turn, so the creature that still bears one when the crossing happens is threaded
    during the same turn, by Blood Thread's own attack.)

    The evidence is read from the event stream by the offset taken immediately before the move: a filtered
    list of old events is not an index into the whole stream, and slicing by its length can reach back into the
    Thread's first application and call that a refresh."""
    from tests.test_lock9_granted_paths import request

    L1, engine, me, ally, foe = _misty(["scarlet_mist_form"])
    _use(L1, engine, "Scarlet Mist Form")
    me.position, foe.position, ally.position = Position(x=3, y=6), Position(x=4, y=6), Position(x=6, y=6)
    _use(L1, engine, "Blood Thread", AN)  # the foe's own square, threaded by the printed attack
    thread_id = _thread_mark(foe, me.entity_id).condition_id
    assert len([e for e in engine.events if e.event_type == "CONDITION_APPLIED"
                and e.payload.get("condition_id") == thread_id]) == 1, "one Thread so far"

    asked = C._answers(engine, {CROSSING: lambda options: ["thread"]})
    offset = len(engine.events)  # the stream position the crossing starts from
    engine.move_path(me, (me.position, Position(x=4, y=6), Position(x=5, y=6)), "test:mist-refresh",
                     kind="willing", intent=request(engine))
    assert len(asked) == 1, "the already-threaded creature is asked about, not skipped"
    assert len([c for c in foe.conditions.values() if c.condition_id == thread_id]) == 1, "a refresh, not a second Thread"
    refreshed = [e for e in engine.events[offset:] if e.event_type == "CONDITION_APPLIED"
                 and e.payload.get("condition_id") == thread_id and foe.entity_id in (e.target_ids or ())]
    assert refreshed, "the mark row ran again on the creature that already bore it"
    mark = _thread_mark(foe, me.entity_id)
    assert mark.expires_on == "START_OF_MARKER_NEXT_TURN" == refreshed[-1].payload.get("expires_on"), \
        "the crossing's own Thread, not a longer deadline it did not buy"
    said = _said(engine, kinds=("PASSIVE_TRIGGERED",))
    assert "already bears" not in said and "earlier creature" not in said, said
    assert said.count(foe.display_name) == 1 and f"passes through {foe.display_name}" in said, said


def test_scarlet_mist_form_threads_one_creature_per_turn_and_again_on_the_next_creatures_turn():
    """The printed "once per turn" never says "on your turn", so the use is the engine's shared per-turn clock
    (combat/turn_uses.py): a second creature crossed in the same turn is not threaded, and once another
    creature's turn starts the use is there again.

    No printed Blood talent moves its user on another creature's turn, so the off-turn crossing is executed
    through the engine's own chosen-path seam (``engine.move_path``), the same native movement transaction
    the Move button runs."""
    from tests.test_lock9_granted_paths import request

    L1, engine, me, ally, foe = _misty(["scarlet_mist_form"])
    _use(L1, engine, "Scarlet Mist Form")
    C._answers(engine, {CROSSING: lambda options: ["thread"]})
    me.position, foe.position, ally.position = Position(x=3, y=6), Position(x=4, y=6), Position(x=6, y=6)

    assert engine.move_path(me, (me.position, Position(x=4, y=6), Position(x=5, y=6)), "test:mist-first",
                            kind="willing", intent=request(engine)) == 15
    assert _threaded(me, foe) and me.turn_flags[THREAD_USE] is True

    asked = C._answers(engine, {CROSSING: lambda options: ["thread"]})
    engine.move_path(me, (me.position, Position(x=6, y=6), Position(x=7, y=6)), "test:mist-second",
                     kind="willing", intent=request(engine))
    assert not _threaded(me, ally) and asked == [], "the turn's use is spent: no second question, no second Thread"

    L1._ready(engine)
    while engine.state.current_actor_id != AN:
        engine.end_turn()
    reset = [e for e in engine.events if e.event_type == "PER_TURN_USES_RESET" and e.actor_id == me.entity_id]
    assert reset and reset[-1].payload["keys"] == [THREAD_USE]
    assert THREAD_USE not in me.turn_flags

    asked = C._answers(engine, {CROSSING: lambda options: ["thread"]})
    engine.move_path(me, (me.position, Position(x=6, y=6), Position(x=5, y=6)), "test:mist-third",
                     kind="willing", intent=request(engine))
    assert _threaded(me, ally) and len(asked) == 1, "the next creature's turn made the use available again"


def test_scarlet_mist_form_ends_with_its_own_minute_and_with_concentration():
    """"Duration: Concentration, up to 1 minute": the marker ends at whichever comes first, and both of those
    are the engine's own expiry sweeps rather than something the plug-in remembers to remove."""
    from combat.creature_passage import permission
    from combat.gate2_rolls import DeterministicRollAuthority

    L1, engine, me, ally, foe = _misty(["scarlet_mist_form"])
    _use(L1, engine, "Scarlet Mist Form")
    assert next(c for c in me.conditions.values() if c.condition_id == MIST).expires_on == "CONCENTRATION_END"

    raw = DeterministicRollAuthority.raw_d20

    def failing(roller, *, modifier, actor_id, reason, mode="NORMAL"):  # the damage check fails, every other roll stands
        return raw(roller, modifier=modifier - (1000 if reason.startswith("SAVE:") else 0),
                   actor_id=actor_id, reason=reason, mode=mode)

    DeterministicRollAuthority.raw_d20 = failing
    try:
        with engine._transaction("system:test.concentration_damage", "damage", ME):
            engine._commit_damage(me, 20, "TEST", "system:test.concentration_damage", AN, None, reaction_depth=0)
    finally:
        DeterministicRollAuthority.raw_d20 = raw
    assert not _mist_form(me), "damage that breaks Concentration ends the form"
    assert permission(engine, me, foe) is None
    assert any(e.event_type == "CONCENTRATION_ENDED" and e.payload.get("reason") == "FAILED_DAMAGE_CHECK"
               for e in engine.events)

    L1, engine, me, ally, foe = _misty(["scarlet_mist_form"])
    _use(L1, engine, "Scarlet Mist Form")
    for _ in range(45):
        engine.end_turn()
        if not _mist_form(me):
            break
    assert not _mist_form(me), "its minute ran out on the tenth round"
    assert any(e.event_type == "CONDITION_REMOVED" and e.payload.get("reason") == "DURATION_ENDED"
               for e in engine.events)


def test_scarlet_mist_form_state_survives_the_table_boundary_and_keeps_its_clocks_after_a_reload(tmp_path):
    """Commit, reload from disk: the form, its Blood Thread, the spent use and the stretched Bloodsense are all
    still there, and the reloaded fight still runs the per-turn clock."""
    from combat import senses
    from combat.ext.effect_durations import round_token

    combat, table, mid = _mist_fight(tmp_path, talents=("scarlet_mist_form", "blood_emperor_incarnation", "crimson_mark"),
                                     cl=16)
    assert senses.of(_reloaded(combat, mid), _reloaded(combat, mid).state.actors[C.ME])["bloodsense"]["range_ft"] == 60
    _act(combat, table, mid, "Blood Emperor Incarnation")
    _act(combat, table, mid, "End turn")
    _act(combat, table, mid, "End turn")
    _act(combat, table, mid, "Scarlet Mist Form")
    with _saves(fail=True, engine_checks_pass=True):  # the crossed foe is an unwilling creature: the paid hour needs its save failed
        _move(combat, table, mid, 9, 5)

    engine = _reloaded(combat, mid)
    me = engine.state.actors[C.ME]
    foe = next(a for a in engine.state.actors.values() if a.team_id == "team:b")
    assert _mist_form(me) and me.turn_flags[THREAD_USE] is True
    assert _thread_mark(foe, C.ME).expires_on == round_token(engine, 600), "the Thread, and the paid hour, are saved state too"
    assert senses.of(engine, me)["bloodsense"]["range_ft"] == 5280, "the Incarnation's stretched Bloodsense survived"

    _act(combat, table, mid, "End turn")
    _act(combat, table, mid, "End turn")
    engine = _reloaded(combat, mid)
    me = engine.state.actors[C.ME]
    assert _mist_form(me) and THREAD_USE not in me.turn_flags, "the reloaded fight still runs the per-turn clock"


def test_scarlet_mist_form_leaves_everyone_else_alone():
    """A character without the talent keeps the ordinary passage rules: no permission, and no marker."""
    from combat import creature_passage

    L1, engine, me, ally, foe = _misty([])
    assert not _mist_form(me)
    assert creature_passage.permission(engine, me, foe) is None


def test_scarlet_mist_forms_printed_movement_clauses_are_no_longer_gm_reminders():
    """"move through occupied spaces as difficult terrain" and the automatic Blood Thread both run, so neither reaches the
    fight as a rule the GM has to apply. The one line left is the printed clause this table cannot judge."""
    gm = _gm_lines("scarlet_mist_form")
    assert [line for line in gm if "occupied spaces" in line or "Blood Thread" in line] == []
    assert gm == ["ability to pass through openings as narrow as 1 inch"]


@pytest.mark.parametrize("followup,save_fails,expectation", [
    ("take", True, "hour"),
    ("take", False, "thread"),
    ("decline", True, "thread"),
])
def test_crimson_mark_is_offered_for_a_blood_thread_the_mist_applies(tmp_path, followup, save_fails, expectation):
    """Crimson Mark prints "When you apply Blood Thread", and the mist applies one, so the paid extension is
    offered for it too.

    The save follows the creature, not the application. "An unwilling creature makes a Constitution
    saving throw", and the foe the mist crosses is asked whether it will bear the hour and says no -- the
    ordinary Thread (which this mist line prints "automatically", save or no save) is placed either way, and
    only the hour is contested. A success defeats only the hour and leaves the ordinary Thread standing,
    and the printed cost is already paid either way.
    """
    from combat.ext.effect_durations import round_token

    combat, table, mid = _mist_fight(tmp_path, talents=("scarlet_mist_form", "crimson_mark"))
    _act(combat, table, mid, "Scarlet Mist Form")

    def answer(prompt):
        if prompt["context"]["reaction_source_id"].endswith(CROSSING):
            return ["thread"]
        return ["skip"] if followup == "decline" else ["crimson_mark"]

    with _saves(fail=save_fails):
        engine, prompts = _move(combat, table, mid, 7, 5, choose=answer, asked=lambda prompt: ["refuse"])
    me = engine.state.actors[C.ME]
    foe = next(a for a in engine.state.actors.values() if a.team_id == "team:b")
    asked = [p["context"]["reaction_source_id"].split(".")[-1] for p in prompts]
    if followup == "decline":
        assert asked == [CROSSING, "crimson_mark"], asked
    else:
        assert asked == [CROSSING, "crimson_mark", WILLING], asked
        (consent,) = [p for p in prompts if p["context"]["reaction_source_id"].endswith(WILLING)]
        assert consent["context"]["reactor_id"] == foe.entity_id, "the crossed creature is asked about itself"
    extension = next(p for p in prompts if p["context"]["reaction_source_id"].endswith("crimson_mark"))
    assert "Scarlet Mist Form applied your Blood Thread" in extension["trigger"], extension["trigger"]
    assert "resists it with a Constitution saving throw" in json.dumps(extension), "the offer says the hour is contested"
    saves = _saves_by(engine, foe.entity_id)
    if followup == "decline":
        assert not saves, "no hour was bought, so there is nothing to save against"
    else:
        assert saves, "a creature that refused the hour is asked to save against it"
    if expectation == "hour":
        assert _thread_mark(foe, C.ME).expires_on == round_token(engine, 600), "the paid hour, not the plain Thread"
        assert me.resources[STAMINA] == 60 - 6 - 1
    else:
        assert _thread_mark(foe, C.ME).expires_on == "START_OF_MARKER_NEXT_TURN"
        assert me.resources[STAMINA] == (60 - 6 - 1 if followup == "take" else 60 - 6), "declining the hour costs no CP"


def test_crimson_marks_hour_needs_no_save_from_a_creature_that_agrees_to_it(tmp_path):
    """The other half of the same rule: the mist crosses any creature, and one on the Mistweaver's own side can be
    asked and can agree to bear the longer Thread. "An unwilling creature makes a Constitution saving throw"
    applies to the creature that refused, not to everyone the Thread reaches, so an acceptance takes the hour
    outright."""
    from combat.ext.effect_durations import round_token

    combat, table, mid = _mist_fight(tmp_path, talents=("scarlet_mist_form", "crimson_mark"),
                                     allies=(("Ally", (6, 5)),), foes=(("Foe", (10, 5)),))
    _act(combat, table, mid, "Scarlet Mist Form")

    def answer(prompt):
        return ["thread"] if prompt["context"]["reaction_source_id"].endswith(CROSSING) else ["crimson_mark"]

    engine, prompts = _move(combat, table, mid, 8, 5, choose=answer, asked=lambda prompt: ["accept"])
    ally = next(a for a in engine.state.actors.values() if a.display_name == "Ally")
    assert [p["context"]["reaction_source_id"].split(".")[-1] for p in prompts] == [CROSSING, "crimson_mark", WILLING]
    consent = next(p for p in prompts if p["context"]["reaction_source_id"].endswith(WILLING))
    assert consent["context"]["reactor_id"] == ally.entity_id, "the crossed ally is asked about itself"
    assert "Crimson Mark" in consent["trigger"], "the question names the ability"
    assert "Scarlet Mist Form" in consent["trigger"], "and the action that applied the Thread"
    assert "refuse and make a Constitution saving throw" in consent["trigger"], \
        "and says what refusing costs the creature: the printed saving throw"
    assert _thread_mark(ally, C.ME).expires_on == round_token(engine, 600), "a consenting bearer's hour needs no save"
    assert not _saves_by(engine, ally.entity_id), "nothing was forced on the ally"
    assert not any(e.event_type == "SAVE_ROLLED" for e in engine.events), "the crossed foe was not reached"


def test_an_ally_the_mist_crosses_can_refuse_the_paid_hour_and_has_to_save_for_it(tmp_path):
    """Side membership is not consent. A creature on the Thread owner's own side can still refuse to bear the
    paid hour, and the printed rule for a creature that will not is that it makes a Constitution saving throw:
    a failure leaves the hour on it anyway. This is the reverse of the test above and the same printed sentence."""
    from combat.ext.effect_durations import round_token

    combat, table, mid = _mist_fight(tmp_path, talents=("scarlet_mist_form", "crimson_mark"),
                                     allies=(("Ally", (6, 5)),), foes=(("Foe", (10, 5)),))
    _act(combat, table, mid, "Scarlet Mist Form")

    def answer(prompt):
        return ["thread"] if prompt["context"]["reaction_source_id"].endswith(CROSSING) else ["crimson_mark"]

    with _saves(fail=True):
        engine, prompts = _move(combat, table, mid, 8, 5, choose=answer, asked=lambda prompt: ["refuse"])
    ally = next(a for a in engine.state.actors.values() if a.display_name == "Ally")
    assert [p["context"]["reaction_source_id"].split(".")[-1] for p in prompts] == [CROSSING, "crimson_mark", WILLING]
    assert _saves_by(engine, ally.entity_id), "an allied creature that refused the hour is still asked to save"
    assert _thread_mark(ally, C.ME).expires_on == round_token(engine, 600), \
        "a failed save defeats nothing: the hour it refused still sticks"


def test_an_enemy_that_agrees_to_bear_the_paid_hour_never_has_to_save(tmp_path):
    """The other direction, and the one side membership got wrong: an enemy has no automatic right to the hour,
    but it is not automatically unwilling either. Asked, it can agree, and then the printed saving throw is not
    for it -- the hour is taken on its acceptance."""
    from combat.ext.effect_durations import round_token

    combat, table, mid = _mist_fight(tmp_path, talents=("scarlet_mist_form", "crimson_mark"))
    _act(combat, table, mid, "Scarlet Mist Form")

    def answer(prompt):
        return ["thread"] if prompt["context"]["reaction_source_id"].endswith(CROSSING) else ["crimson_mark"]

    engine, prompts = _move(combat, table, mid, 7, 5, choose=answer, asked=lambda prompt: ["accept"])
    foe = next(a for a in engine.state.actors.values() if a.team_id == "team:b")
    assert [p["context"]["reaction_source_id"].split(".")[-1] for p in prompts] == [CROSSING, "crimson_mark", WILLING]
    consent = next(p for p in prompts if p["context"]["reaction_source_id"].endswith(WILLING))
    assert consent["context"]["reactor_id"] == foe.entity_id, "even an enemy is asked about itself"
    assert _thread_mark(foe, C.ME).expires_on == round_token(engine, 600), "an accepting enemy's hour needs no save"
    assert not _saves_by(engine, foe.entity_id), "nothing was forced on a creature that agreed"


def test_the_mist_crossing_announces_the_paid_hour_it_actually_left_on_the_creature(tmp_path):
    """The crossing's line is the last word on what the Thread now is, so it reads the mark back: the paid
    Crimson Mark hour it just bought is not "until the start of your next turn"."""
    from combat.ext.effect_durations import round_token

    combat, table, mid = _mist_fight(tmp_path, talents=("scarlet_mist_form", "crimson_mark"))
    _act(combat, table, mid, "Scarlet Mist Form")

    def answer(prompt):
        if prompt["context"]["reaction_source_id"].endswith(CROSSING):
            return ["thread"]
        return ["crimson_mark"]

    with _saves(fail=True):
        engine, prompts = _move(combat, table, mid, 7, 5, choose=answer, asked=lambda prompt: ["refuse"])
    me = engine.state.actors[C.ME]
    foe = next(a for a in engine.state.actors.values() if a.team_id == "team:b")
    assert _thread_mark(foe, C.ME).expires_on == round_token(engine, 600), "the foe refused and failed the save, so it wears the paid hour"
    said = _said(engine)
    assert f"passes through {foe.display_name}" in said, said
    assert "start of your next turn" not in said, said
    assert "next turn starts" not in said, "the ordinary Thread's deadline is not the one it wears now"
    _, paid_round, paid_turn = round_token(engine, 600).split(":")
    assert f"until round {paid_round}, turn {int(paid_turn) + 1} starts" in said, \
        "the hour it does wear is stated as that exact deadline, not merely as a word"


def test_the_mist_crossing_announces_the_hour_it_retains_and_keeps_it_across_a_reload(tmp_path):
    """The retained hour, end to end: the creature already wears a paid hour from an earlier crossing, and the
    next ordinary Thread the mist applies must neither shorten that deadline nor be announced as "until the start
    of your next turn".

    This is the path that keeps a paid hour rather than buying a new one (blood_riders.preserve_extended_thread
    intercepts the ordinary mark and fires the extension hook from there), so it is a different code path from the
    announcement test above and it is the one a player reads on the second crossing. The deadline is read from the
    reloaded fight and compared with the exact token bought in the earlier round -- a fresh hour would carry the
    later round's number -- and the crossing's own line is read from the event stream after the offset taken just
    before the move, so the first crossing's announcement cannot answer for the second."""
    from combat.ext.effect_durations import round_token

    combat, table, mid = _mist_fight(tmp_path, talents=("scarlet_mist_form", "crimson_mark"))
    _act(combat, table, mid, "Scarlet Mist Form")

    def buy(prompt):  # take the crossing, then buy the hour; the crossed foe refuses it and fails the save
        return ["thread"] if prompt["context"]["reaction_source_id"].endswith(CROSSING) else ["crimson_mark"]

    with _saves(fail=True):
        _move(combat, table, mid, 7, 5, choose=buy, asked=lambda prompt: ["refuse"])
    engine = _reloaded(combat, mid)
    me, foe = engine.state.actors[C.ME], next(a for a in engine.state.actors.values() if a.team_id == "team:b")
    bought = _thread_mark(foe, C.ME).expires_on
    assert bought == round_token(engine, 600), "the first crossing bought the printed hour"

    _act(combat, table, mid, "End turn")
    _act(combat, table, mid, "End turn")
    engine = _reloaded(combat, mid)
    assert engine.state.round_number > 1, "a later round, so a fresh hour would carry a different deadline"
    offset = len(engine.events)  # the stream position the second crossing starts from

    # The second crossing: the Thread is applied again, the paid hour is declined this time, and the retained
    # hour is what the creature is left wearing.
    engine, prompts = _move(combat, table, mid, 5, 5, choose=lambda prompt: ["skip"]
                            if prompt["context"]["reaction_source_id"].endswith("crimson_mark") else ["thread"])
    me, foe = engine.state.actors[C.ME], next(a for a in engine.state.actors.values() if a.team_id == "team:b")
    assert [p["context"]["reaction_source_id"].split(".")[-1] for p in prompts] == [CROSSING, "crimson_mark"], \
        "the second crossing applies the Thread and offers the hour again; declining it is the owner's choice alone"
    assert _thread_mark(foe, C.ME).expires_on == bought, \
        "the retained hour keeps the deadline it was bought with, not a new one and not the plain Thread"
    assert _thread_mark(foe, C.ME).expires_on != round_token(engine, 600), \
        "which is not the deadline a fresh hour bought in this round would carry"
    said = " ".join(str(e.payload.get("text") or e.payload.get("trigger") or "") for e in engine.events[offset:])
    assert f"passes through {foe.display_name}" in said, said
    assert "next turn starts" not in said, "the plain Thread's deadline is not what this creature wears"
    _, paid_round, paid_turn = bought.split(":")
    assert f"until round {paid_round}, turn {int(paid_turn) + 1} starts" in said, \
        "the crossing names the retained hour's own deadline, in the table's own words"

    reloaded = _reloaded(combat, mid)  # and it is saved state, not just fight memory
    assert _thread_mark(reloaded.state.actors[foe.entity_id], C.ME).expires_on == bought


def test_the_mist_crossing_announces_the_ordinary_thread_when_no_hour_is_bought(tmp_path):
    """A character without Crimson Mark has only the ordinary Thread to announce, and that deadline is the
    printed one: until the start of the mover's next turn."""
    combat, table, mid = _mist_fight(tmp_path)
    _act(combat, table, mid, "Scarlet Mist Form")
    engine, _ = _move(combat, table, mid, 7, 5, choose=lambda prompt: ["thread"])
    me = engine.state.actors[C.ME]
    foe = next(a for a in engine.state.actors.values() if a.team_id == "team:b")
    assert _thread_mark(foe, C.ME).expires_on == "START_OF_MARKER_NEXT_TURN"
    said = _said(engine)
    assert f"passes through {foe.display_name}" in said and "next turn starts" in said, said
    assert me.turn_flags[THREAD_USE] is True


def test_an_ai_mistweaver_threads_the_creature_it_crosses_and_pays_for_the_hour(tmp_path):
    """The AI is asked the same question and answers it: the printed automatic application, and Crimson Mark's
    paid hour, both taken by the real LocalDeterministicController rather than by the test. The creature it
    crossed is an enemy, so it is asked about the hour and refuses it -- an AI recipient answers the same question
    a player does, with the side-based answer it would have chosen anyway -- and the printed Constitution saving
    throw decides the hour here. The dice are forced to fail so the assertion is about who answered, not about
    the roll."""
    from combat.ext.effect_durations import round_token
    from combat.gate4_adapters import ManualControllerAdapter

    combat, table, mid = _mist_fight(tmp_path, talents=("scarlet_mist_form", "crimson_mark"), mode="LOCAL_AUTO")

    def choose(context):  # pick the two printed buttons and let the real AI answer everything they raise
        by_name = {c.display_name: c for c in context.legal_candidates}
        pick = by_name.get("Scarlet Mist Form") or by_name["Move to 9,5"]
        return ManualControllerAdapter(lambda context: (pick.candidate_id, ())).choose_primary_action(context)

    with pytest.MonkeyPatch.context() as patch, _saves(fail=True):
        patch.setattr(combat.controller, "choose_primary_action", choose)
        assert table.auto_step(mid, 0, [])["status"] == "COMMITTED"  # Scarlet Mist Form, the Bonus Action
        assert table.auto_step(mid, 0, [])["status"] == "COMMITTED"  # the crossing move
    engine = _reloaded(combat, mid)
    me = engine.state.actors[C.ME]
    foe = next(a for a in engine.state.actors.values() if a.team_id == "team:b")
    assert _threaded(me, foe), "the AI took the printed automatic application"
    assert _thread_mark(foe, C.ME).expires_on == round_token(engine, 600), "and the AI paid for Crimson Mark's hour"
    assert me.resources[STAMINA] == 60 - 6 - 1
    assert _saves_by(engine, foe.entity_id), "the unwilling foe answered the printed save"


def test_a_manual_recipient_is_asked_while_the_ai_is_the_one_crossing_it(tmp_path):
    """The consent question belongs to the crossed creature whoever is driving: here the Mistweaver is under AI
    control (its action is chosen by the real LocalDeterministicController, not by this test) and the creature it
    walks through is a manually played ally, so the hour is still put to that ally's own controller instead of
    being taken on a default. An ally that refuses still faces the printed saving throw, so the AI gets no free
    extension of its own."""
    from combat.ext.effect_durations import round_token
    from combat.gate4_adapters import ManualControllerAdapter

    combat, table, mid = _mist_fight(tmp_path, talents=("scarlet_mist_form", "crimson_mark"), mode="LOCAL_AUTO",
                                     allies=(("Ally", (6, 5)),), foes=(("Foe", (10, 5)),), asking=True)

    def choose(context):  # the AI picks the printed bonus action, then the crossing move; questions are answered below
        by_name = {c.display_name: c for c in context.legal_candidates}
        pick = by_name.get("Scarlet Mist Form") or by_name["Move to 9,5"]
        return ManualControllerAdapter(lambda context: (pick.candidate_id, ())).choose_primary_action(context)

    ally_id = next(a.entity_id for a in combat._load_session(mid).engine.state.actors.values()
                   if a.display_name == "Ally")
    reactions, prompts = [], []
    with pytest.MonkeyPatch.context() as patch, _saves(fail=True):
        patch.setattr(combat.controller, "choose_primary_action", choose)
        for _ in range(12):
            result = table.auto_step(mid, 0, reactions)
            if result["status"] == "REACTION_REQUIRED":
                prompt = result["reaction"]
                prompts.append(prompt)
                options = [option["id"] for option in prompt.get("choice", {}).get("options", [])]
                if prompt["context"].get("reactor_id") in (None, C.ME):
                    chosen = options[:1]  # the AI's own questions take their printed default
                elif str(prompt["context"].get("reaction_source_id") or "").endswith(WILLING):
                    chosen = ["refuse"]  # the manual recipient's own controller: it will not bear the hour
                else:
                    chosen = []
                reactions.append({**prompt["context"], "selection": "USE" if chosen else "DECLINE",
                                  "option_ids": chosen})
                continue
            if result["status"] != "COMMITTED" or _threaded_in(combat, mid, ally_id, C.ME):
                break  # the crossing has happened; the AI action is over
            reactions = []  # the bonus action committed; step on into the crossing move
        else:
            raise AssertionError("the AI action never finished its questions")

    engine = _reloaded(combat, mid)
    ally = next(a for a in engine.state.actors.values() if a.display_name == "Ally")
    consent = [p for p in prompts if str(p["context"].get("reaction_source_id") or "").endswith(WILLING)]
    assert consent, [p["context"]["reaction_source_id"] for p in prompts]
    assert consent[0]["context"]["reactor_id"] == ally.entity_id, "the manually played ally is asked, not the AI's owner"
    assert _saves_by(engine, ally.entity_id), "an ally that refused the hour during an AI action still saves for it"
    assert _thread_mark(ally, C.ME).expires_on == round_token(engine, 600), "a failed save leaves the hour on it anyway"


def _threaded_in(combat, match_id, creature_id, owner_id) -> bool:
    """Whether the fight already saved on disk has ``owner_id``'s Blood Thread on that creature."""
    from combat.typed_executor import mark_condition_id

    actors = combat._load_session(match_id).engine.state.actors
    creature = actors.get(creature_id)
    return bool(creature is not None and owner_id in actors
                and any(c.condition_id == mark_condition_id("Blood Thread", owner_id)
                        for c in creature.conditions.values()))


def test_crimson_aura_makes_its_bloodied_enemy_save_before_a_paid_hour_can_stick():
    """"Crimson Aura: When a Bloodied enemy starts its turn within 20 feet" threads a creature that never chose
    to bear the Thread, so it is unwilling and Crimson Mark's paid hour is behind the printed Constitution
    saving throw. The aura is not a way around that save -- the enemy the aura reaches has to fail it, exactly
    as the enemy Blood Thread's own attack reaches does.

    The aura's trigger fires at another creature's turn start, where this table has no player question to put
    to the Thread's owner, so the paid hour is taken on the printed default rather than asked about; what this
    asserts is the printed outcome of that default either way. The aura's own printed damage save is rolled too
    and is not what is counted here."""

    def aura_fight(*, save_fails: bool):
        L1, engine, me, ally, foe = _misty(["blood_emperor_incarnation", "crimson_mark"], cl=16, qi=99)
        _use(L1, engine, "Blood Emperor Incarnation")
        qi_before = me.resources[QI]
        foe.current_hp = foe.maximum_hp // 2  # "a Bloodied enemy", at or below half its Hit Points
        with _saves(fail=save_fails):
            while engine.state.current_actor_id != AN:
                engine.end_turn()
        return engine, me, foe, qi_before

    from combat.ext.effect_durations import round_token

    engine, me, foe, qi_before = aura_fight(save_fails=True)
    assert _threaded(me, foe), "the aura's printed automatic application threads the Bloodied enemy"
    assert _saves_by(engine, foe.entity_id), "the enemy the aura reached answers a Constitution saving throw"
    assert me.resources[QI] == qi_before - 1, "the paid hour costs its printed 1 CP"
    assert _thread_mark(foe, me.entity_id).expires_on == round_token(engine, 600), "the failed save leaves the hour"

    engine, me, foe, _ = aura_fight(save_fails=False)
    assert _threaded(me, foe)
    assert _saves_by(engine, foe.entity_id), "the save is asked either way; only its outcome differs"
    assert _thread_mark(foe, me.entity_id).expires_on == "START_OF_MARKER_NEXT_TURN", \
        "a save the enemy passes defeats only the paid hour; the Thread the aura applied stands"


# =========================================================================================== Physician's Pulse
def test_physicians_pulse_reports_the_ailments_it_finds_and_finds_none_on_a_healthy_creature():
    """"Examine one willing living creature. Learn whether it is affected by: ordinary bleeding; poison; disease; ...;
    ordinary exhaustion" -- one readable line, naming what the table can see."""
    from combat.ext import forged_exhaustion

    L1, engine, me, ally, foe = _misty(["physician_s_pulse"])
    events = _use(L1, engine, "Physician’s Pulse", ALLY)
    said = " ".join(_logs(events))
    assert "Physician's Pulse" in said and "none of the ailments" in said

    engine._apply_condition(ally, "condition:typed.bleeding", "test", me.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": "Bleeding"})
    engine._apply_condition(ally, "condition:typed.poisoned", "test", me.entity_id, expires_on="UNTIL_REMOVED")
    forged_exhaustion.add(engine, ally, 2, "test")
    events = _use(L1, engine, "Physician’s Pulse", ALLY)
    said = _logs(events)[-1]
    assert "ordinary bleeding" in said and "poison" in said and "exhaustion (level 2)" in said, said
    # It diagnoses: nothing it found was removed.
    assert any(c.condition_id == "condition:typed.bleeding" for c in ally.conditions.values())
    assert ally.current_hp == ally.maximum_hp


def test_physicians_pulse_is_inert_for_a_character_without_it():
    L1, engine, me, ally, foe = _misty([])
    assert "Physician’s Pulse" not in {c.display_name for c in engine.legal_candidates()}


def test_physicians_pulse_still_asks_the_gm_about_what_the_table_cannot_see():
    gm = _gm_lines("physician_s_pulse")
    assert [line for line in gm if "bleeding" in line or "diagnosis" in line] == []
    assert len(gm) == 1 and "internal injury" in gm[0]
    assert "unusual blood loss" in gm[0], "the printed category nothing tracks stays a GM line"


# =========================================================================================== Blood Emperor Incarnation
def test_blood_emperor_incarnation_stretches_bloodsense_to_a_mile_for_its_minute():
    """"Bloodsense range becomes 1 mile" -- the printed range is the table's own Bloodsense sense, widened by the
    ordinary gain_sense row for the Incarnation's duration, and gone again when the Incarnation ends."""
    from combat import senses

    L1, engine, me, ally, foe = _misty(["blood_emperor_incarnation"], cl=16, qi=99)
    assert senses.of(engine, me)["bloodsense"]["range_ft"] == 60

    _use(L1, engine, "Blood Emperor Incarnation")
    assert senses.of(engine, me)["bloodsense"]["range_ft"] == 5280

    for instance_id, condition in list(me.conditions.items()):
        if condition.condition_id == senses.SENSE:
            me.conditions.pop(instance_id)
    assert senses.of(engine, me)["bloodsense"]["range_ft"] == 60


def test_blood_emperor_incarnations_range_clause_is_no_longer_a_gm_reminder():
    assert _gm_lines("blood_emperor_incarnation") == []
    assert _authority()[BL + "blood_emperor_incarnation"]["coverage"] == "FULL"


# =========================================================================================== Vital Transfusion
def test_vital_transfusion_s_limitation_is_the_ability_s_own_text_not_a_fight_reminder():
    """Vital Transfusion only ever moves Hit Points, so "does not restore missing limbs or remove major injuries" is a
    limitation the table enforces; it stays printed, but not as a rule the GM must apply."""
    mechanic = _authority()[BL + "vital_transfusion"]
    assert mechanic["coverage"] == "FULL"
    assert mechanic["riders"] == []
    assert any("missing limbs" in line for line in mechanic["description"])
