"""Scoped canonical nested-consumer tests; deferred-damage expectations promoted."""
from pathlib import Path
import pytest
from combat import typed_executor as te
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, ConcentrationState
from combat.gate4_engine import Gate4ControllerEngine
from tests import test_auto_lane1 as L
ROOT = Path(__file__).resolve().parents[1]
ME = L.ME
F1, F2, F3, F4 = 'actor:riders.f1', 'actor:riders.f2', 'actor:riders.f3', 'actor:riders.f4'
PB = 4
LASH, GATHER = 'TAL_LIGHTNING_LIGHTNING_LASH', 'TAL_LIGHTNING_GATHER_CHARGE'
BLACK_SUN = 'TAL_DAEMONIC_CULTIVATION_BLACK_SUN_OVER_THE_DANTIAN'


def _rider_engine(mid, *, dc=50, cl=17, foes=None, talents=()):
    sheet = L._sheet(mid, dc=dc, cl=cl)
    sheet["spheres_and_talents"]["learned_talent_record_ids"].extend(talents)
    return _engine(compile_character(sheet, actor_id=ME), foes or {F1: (7, 6), F2: (8, 7)})


def _rider_action(engine, mid):
    return next(action for action in engine.action_catalog.values()
                if (action.parameters.get("typed") or {}).get("source") == mid
                and not action.parameters.get("player_only"))


def _rider_use(engine, mid, *, aim=None):
    action = _rider_action(engine, mid)
    return _rider_use_action(engine, action, aim=aim)


def _rider_use_action(engine, action, *, aim=None):
    candidates = [c for c in engine.legal_candidates() if c.source_definition_id == action.source_definition_id]
    candidate = next((c for c in candidates if (aim is None or c.destination == aim)
                      and (not c.target_ids or AN in c.target_ids or tuple(c.target_ids) == (ME,))), None)
    assert candidate is not None, (action.display_name, [(c.target_ids, c.destination) for c in candidates[:8]])
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id="rider-use", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=tuple(candidate.target_ids or ()),
                                       destination=candidate.destination))
    return engine.events[before:]


@pytest.mark.parametrize("dc,resource", [(50, "resource:an_eui.stamina"),
                                          (50, "resource:core.qi"), (50, "resource:core.resonance"),
                                          (-40, "resource:core.qi")])
def test_black_sun_waits_for_one_positive_cp_or_stamina_spend(dc, resource):
    from combat.ext.daemonic_riders import BLACK_SUN_STATE

    engine = _rider_engine(BLACK_SUN, dc=dc)
    foe = engine.state.actors[AN]
    foe.maximum_hp = 200
    foe.current_hp = 200
    foe.resources[resource] = foe.resource_maximums[resource] = 10
    seen = _answers(engine, {"black_sun_damage": ["necrotic"]})
    hp = foe.current_hp
    _rider_use(engine, BLACK_SUN)
    assert foe.current_hp == hp  # a save arms the consequence; it does not deal it
    assert any(c.condition_id == BLACK_SUN_STATE for c in foe.conditions.values())
    assert any("Black Sun Over the Dantian" in str(r) and foe.display_name in str(r) for r in seen)
    engine._spend_resource(foe, resource, 0, "test:zero")
    foe.resources["resource:core.martial_focus"] = foe.resource_maximums["resource:core.martial_focus"] = 1
    engine._spend_resource(foe, "resource:core.martial_focus", 1, "test:focus")
    assert foe.current_hp == hp
    engine._spend_resource(foe, resource, 1, "test:spend")
    # The native nested dispatcher now commits the chosen damage once.
    damage = hp - foe.current_hp
    assert (4 <= damage <= 32) if dc == 50 else damage == PB
    assert not any(c.condition_id == BLACK_SUN_STATE for c in foe.conditions.values())
    notices = [e for e in engine.events if e.event_type == "GM_RIDER" and AN in e.target_ids]
    assert not any("nested-event" in e.payload["rider"] for e in notices)
    engine._spend_resource(foe, resource, 1, "test:second")
    assert hp - foe.current_hp == damage


@pytest.mark.parametrize("dc", [50, -40])
def test_black_sun_unspent_consequence_expires_on_the_casters_printed_edge(dc):
    from combat.ext.daemonic_riders import BLACK_SUN_STATE

    engine = _rider_engine(BLACK_SUN, dc=dc)
    foe = engine.state.actors[AN]
    _rider_use(engine, BLACK_SUN)
    engine.state.current_actor_id = AN
    engine._system_start_turn()
    assert any(c.condition_id == BLACK_SUN_STATE for c in foe.conditions.values())
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    assert any(c.condition_id == BLACK_SUN_STATE for c in foe.conditions.values()) == (dc == 50)
    if dc == 50:
        engine.end_turn()
    assert not any(c.condition_id == BLACK_SUN_STATE for c in foe.conditions.values())


@pytest.mark.parametrize("foe_hp", [60, 1])
def test_black_sun_state_survives_a_persistent_commit_reload_and_spend(tmp_path, foe_hp):
    from combat.ext.daemonic_riders import BLACK_SUN_STATE
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    foe_sheet = L._sheet(BLACK_SUN, cl=17, dc=50)
    foe_sheet["ability_scores_and_statistics"]["hit_points"]["maximum"] = foe_hp
    session = persistence.create_match(match_seed="BLACK-SUN-SAVED",
        typed_bundles=(compile_character(L._sheet(BLACK_SUN, cl=17, dc=50), actor_id=ME),
                       compile_character(foe_sheet, actor_id=F1)),
        roster_setup={"primary_actor_ids": [ME, F1], "team_by_actor": {ME: "team:a", F1: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, F1: {"x": 4, "y": 6}}})

    def submit(predicate):
        e = session.engine
        c = next(c for c in e.legal_candidates() if predicate(c))
        session.submit_intent(ActionIntent(intent_id=f"sun:{e.state.state_version}", decision_id=c.decision_id,
            candidate_id=c.candidate_id, state_version=c.state_version, actor_id=c.actor_id,
            target_ids=c.target_ids, destination=c.destination), primary_decision_record=None, reaction_provider=None)

    while session.engine.state.current_actor_id != ME:
        submit(lambda c: c.kind == "END_TURN")
    action_id = _rider_action(session.engine, BLACK_SUN).source_definition_id
    submit(lambda c: c.source_definition_id == action_id and F1 in c.target_ids)
    saved = [c.model_dump(mode="json") for c in session.engine.state.actors[F1].conditions.values()
             if c.condition_id == BLACK_SUN_STATE]
    assert saved
    session = persistence.load_match(session.match_id)
    assert saved == [c.model_dump(mode="json") for c in session.engine.state.actors[F1].conditions.values()
                     if c.condition_id == BLACK_SUN_STATE]
    while session.engine.state.current_actor_id != F1:
        submit(lambda c: c.kind == "END_TURN")
    hp = session.engine.state.actors[F1].current_hp
    submit(lambda c: c.source_definition_id in session.engine.action_catalog and
           (session.engine.action_catalog[c.source_definition_id].parameters.get("typed") or {}).get("source") == BLACK_SUN)
    assert session.engine.state.actors[F1].current_hp < hp
    assert not any(e.event_type == "GM_RIDER" and F1 in e.target_ids and "nested-event" in e.payload.get("rider", "")
               for e in session.engine.events)
    session = persistence.load_match(session.match_id)
    assert not any(c.condition_id == BLACK_SUN_STATE for c in session.engine.state.actors[F1].conditions.values())
    assert session.verify()["status"] == "PASS"


def _rider_strike(engine, attacker, target, *, kind="unarmed", friendly=False, bonus=100):
    """A controlled engine attack checkpoint, after compiling the real rider owner."""
    from tests.test_reaction_effects_r6 import _typed_action, _use
    action = _typed_action(engine, attacker, [{"type": "attack", "attack_kind": kind, "on_hit": [
        {"type": "damage", "applies_to": "target", "flat": 1, "damage_types": ["bludgeoning"]}]}])
    action.parameters["typed"]["numbers"]["attack_bonus"] = bonus
    if friendly:
        action = action.model_copy(update={"target_kind": "ALLY_OR_SELF"})
        engine.action_catalog[action.source_definition_id] = action
    engine.state.actors[attacker].action_available = True
    before = len(engine.events)
    _use(engine, attacker, action, target)
    return engine.events[before:]


@pytest.mark.parametrize("attacker", ["caster", "ally"])
@pytest.mark.parametrize("temporary_hp", [0, 100])
def test_beast_tamer_ends_on_caster_or_ally_damage_including_temporary_hp(attacker, temporary_hp):
    mid = "TAL_BEASTMASTERY_BEAST_TAMER"
    engine = _rider_engine(mid)
    foe = engine.state.actors[AN]
    _rider_use(engine, mid)
    source = _rider_action(engine, mid).source_definition_id
    assert any(c.source_definition_id == source and c.condition_id == te.CONDITION_PREFIX + "charmed"
               for c in foe.conditions.values())
    engine._apply_condition(foe, te.CONDITION_PREFIX + "poisoned", "test:unrelated", F1,
                            expires_on="UNTIL_REMOVED")
    foe.temporary_hp = temporary_hp
    hp = foe.current_hp
    ally = next(a.entity_id for a in engine.state.actors.values()
                if (a.summon or {}).get("owner") == ME and a.summon.get("source") == "tamer")
    # Move the existing ally into legal melee reach, then run an ordinary typed hit.
    engine.state.actors[ally].position = foe.position.model_copy(update={"x": 5})
    _rider_strike(engine, ME if attacker == "caster" else ally, AN)
    assert not any(c.source_definition_id == source for c in foe.conditions.values())
    assert any(c.source_definition_id == "test:unrelated" for c in foe.conditions.values())
    if temporary_hp:
        assert foe.current_hp == hp and foe.temporary_hp < temporary_hp
    else:
        assert foe.current_hp < hp


def test_beast_tamer_ignores_damage_by_an_enemy_and_creates_no_ending_ledger_on_a_successful_save():
    mid = "TAL_BEASTMASTERY_BEAST_TAMER"
    engine = _rider_engine(mid)
    _rider_use(engine, mid)
    engine.state.actors[F1].position = engine.state.actors[AN].position.model_copy(update={"x": 5})
    _rider_strike(engine, F1, AN, friendly=True)
    assert any(c.condition_id == te.CONDITION_PREFIX + "charmed" for c in engine.state.actors[AN].conditions.values())
    engine = _rider_engine(mid, dc=-40)
    _rider_use(engine, mid)
    assert not any(c.condition_id.startswith("condition:typed.rider_break_on_allied_damage.")
                   for c in engine.state.actors[AN].conditions.values())


def _sheet(talents, *, cl=10, dc=16, kit=None):
    sheet = L._sheet(LASH, cl=cl, dc=dc)
    sheet["spheres_and_talents"]["learned_talent_record_ids"] = list(talents)
    if kit:
        sheet["equipment"] = [kit]
    return sheet


def _bundle(*talents, cl=10, dc=16, kit=None):
    return compile_character(_sheet(talents, cl=cl, dc=dc, kit=kit), actor_id=ME)


def _dummy(actor_id):
    sheet = L._sheet(GATHER)
    sheet.pop("spheres_and_talents")
    return compile_character(sheet, actor_id=actor_id)


def _engine(bundle, foes=None):
    """ME at (3,6) and the stock foe AN at (4,6); ``foes`` maps extra hostile actors to squares (5 feet each)."""
    foes = foes or {}
    positions = {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}, **{who: {"x": x, "y": y} for who, (x, y) in foes.items()}}
    engine = Gate4ControllerEngine(
        ROOT, match_seed="RIDERS1", typed_bundles=(bundle, *(_dummy(who) for who in foes)),
        roster_setup={"primary_actor_ids": [ME, *foes, AN], "team_by_actor": {ME: "team:a", AN: "team:b", **{who: "team:b" for who in foes}},
                      "starting_positions": positions})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    for who in (AN, *foes):
        engine.state.actors[who].armor_class = -50
    roller = engine.roller
    original = roller._die

    def _die(sides):  # a natural 1 always misses: keep the technique's attack out of the dice
        value, counter = original(sides)
        return (max(2, value) if sides == 20 else value), counter

    roller._die = _die
    L._ready(engine)
    return engine


def _mark(engine, who, name):
    action = next(iter(engine.action_catalog.values()))
    me, target = engine.state.actors[ME], engine.state.actors[who]
    ctx = te.Context(engine, me, action, None, {"numbers": {"pb": PB}}, [target], target, {})
    te.run_effects(ctx, [{"type": "mark", "mark": name, "applies_to": "target", "duration": {"kind": "until_start_of_your_next_turn"}}])


def _use_on(engine, name, target):
    candidate = next(c for c in engine.legal_candidates() if c.display_name == name and tuple(c.target_ids or ()) == (target,))
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"i-{name}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=(target,), destination=candidate.destination))
    return engine.events[before:]


def _committed(events):
    """{creature: lightning damage committed to it} for the events of one action."""
    out = {}
    for event in events:
        if event.event_type == "DAMAGE_COMMITTED":
            for who in event.target_ids or ():
                out[who] = out.get(who, 0) + int((event.payload or {}).get("rolled_or_pending_damage") or 0)
    return out


def _move(engine, who, destination):
    """The creature's own willing move (its turn, one of its own Move candidates)."""
    engine.state.current_actor_id = who
    actor = engine.state.actors[who]
    actor.action_available = actor.bonus_action_available = actor.reaction_available = True
    actor.movement_remaining_ft = 30
    candidate = next(c for c in engine.legal_candidates() if c.destination and (c.destination.x, c.destination.y) == destination)
    engine.execute_intent(ActionIntent(intent_id=f"move-{who}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=who, target_ids=(), destination=candidate.destination))


def _linked(engine, who):
    return any(c.condition_id == "condition:typed.link.lightning" for c in engine.state.actors[who].conditions.values())


def test_lightning_chains_links_the_hit_creature_to_a_second_one_that_fails_its_save():
    """"You may spend 1 CP to create a short-lived lightning link between it and one creature within 15 feet. ... Failed Save: It
    takes lightning damage ... and both targets are linked": the old typing carried the whole talent as a GM line."""
    engine = _engine(_bundle("TAL_LIGHTNING_LIGHTNING_CHAINS", cl=10, dc=50), {F1: (5, 6)})
    _mark(engine, AN, "Charged")
    damage = _committed(_use_on(engine, "Lightning Lash: Jolt + Lightning Chains", AN))
    assert damage[F1] > 0 and _linked(engine, AN) and _linked(engine, F1)


def test_lightning_chains_needs_a_charged_target_and_a_failed_save_to_link():
    engine = _engine(_bundle("TAL_LIGHTNING_LIGHTNING_CHAINS", cl=10, dc=50), {F1: (5, 6)})
    _use_on(engine, "Lightning Lash: Jolt + Lightning Chains", AN)  # AN is not Charged
    assert not _linked(engine, F1) and not _linked(engine, AN)
    engine = _engine(_bundle("TAL_LIGHTNING_LIGHTNING_CHAINS", cl=10, dc=-40), {F1: (5, 6)})
    _mark(engine, AN, "Charged")
    damage = _committed(_use_on(engine, "Lightning Lash: Jolt + Lightning Chains", AN))
    assert damage[F1] > 0 and not _linked(engine, F1)  # "half damage and no link forms"


def test_lightning_chains_link_snaps_when_a_linked_creature_walks_more_than_10_feet_away():
    """"While linked, if either target willingly moves more than 10 feet away from the other, it takes lightning damage equal
    to your Proficiency Bonus and the link ends"""
    engine = _engine(_bundle("TAL_LIGHTNING_LIGHTNING_CHAINS", cl=10, dc=50), {F1: (5, 6)})
    _mark(engine, AN, "Charged")
    _use_on(engine, "Lightning Lash: Jolt + Lightning Chains", AN)
    before = engine.state.actors[F1].current_hp
    _move(engine, F1, (8, 6))  # 20 feet from AN
    assert before - engine.state.actors[F1].current_hp == PB
    assert not any(e.event_type == "GM_RIDER" and F1 in e.target_ids and "snapped link" in e.payload.get("rider", "")
               for e in engine.events)
    assert not _linked(engine, F1) and not _linked(engine, AN)


def test_lightning_chains_link_holds_for_a_short_step():
    engine = _engine(_bundle("TAL_LIGHTNING_LIGHTNING_CHAINS", cl=10, dc=50), {F1: (5, 6)})
    _mark(engine, AN, "Charged")
    _use_on(engine, "Lightning Lash: Jolt + Lightning Chains", AN)
    before = engine.state.actors[F1].current_hp
    _move(engine, F1, (6, 6))  # 10 feet from AN: not more than 10
    assert engine.state.actors[F1].current_hp == before and _linked(engine, F1)


def _answers(engine, table):
    """A player answering the choices: ``table`` maps the suffix after "choice:needle." to the option ids to pick."""
    from combat.gate2_runtime_models import ReactionDecision

    seen = []

    def provider(request):
        base = dict(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"], reaction_source_id=request["reaction_source_id"])
        if "extension_choice" not in request:  # an ordinary reaction window: nobody reacts
            return ReactionDecision(**base, selection="DECLINE", option_ids=()), None
        seen.append(request)
        key = request["reaction_source_id"].split("choice:needle.")[-1]
        spec = request["extension_choice"]
        pick = table.get(key) or (spec.get("preferred_option_ids") or spec["option_ids"])[:spec["maximum_selections"]]
        return ReactionDecision(**base, selection="USE", option_ids=tuple(pick)), None

    engine.set_reaction_provider(provider)
    return seen
