"""Rider lane 3 of the automation push (owner 2026-09-29: "i want everything we can automated, keep going until its only the
non-combat ones left"): abilities whose core already ran but whose printed lines reached the GM only as riders.  Every line
automated here is compiled on a real character and run through the engine; each test fails on the typing the authority
carried before (the line was a ``rider`` row or a top-level rider, so nothing happened).

Overrides: authority/typed_mechanics/reviewed_final.d/riders_lane3.json plus in-place edits to the owner files that already
hold the entry (martial.json, review_sw-athletics.json, ...).  Plug-ins: combat/ext/outcome_gates.py (if_missed_by, if_failed_by,
if_size_at_most, if_dropped_by_attack), combat/ext/nearby_hostiles.py (hostiles_within), combat/ext/deny_teleport.py.
Saves are forced with the sheet's technique DC (50: the foe fails, -40: the foe succeeds; a margin is set by reading the
foe's roll first -- the dice are deterministic for a given seed and action order) and attacks always hit (foe AC -50) unless a
test sets the AC to a known margin over the attack total.

Axes: Armor Joint Hook, Axe-and-Shield Press, Bearded Hook Method, Cast Axe (Turning Cast), Execution Mark, Headsman's Mandate,
Moon-Cleaver Return, Split the Shield Wall.
"""

import importlib.util
from pathlib import Path

import pytest

from combat import typed_executor
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import Position
from combat.gate4_engine import Gate4ControllerEngine

_spec = importlib.util.spec_from_file_location("_sw_athletics_harness", Path(__file__).with_name("test_review_sw-athletics.py"))
H = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(H)

ME = H.ME
FAIL, PASS = H.FAIL, H.PASS
STRIKE = H.STRIKE
TURNING = "Fu (Short Axe) thrown: Cast Axe: Turning Cast"


def _axes(talents, *, dc=16, cl=10):
    return H._bundle(H.AXES, [H.HEWING, *talents], H.AXE_KIT, dc=dc, cl=cl)


def _conds(actor):
    return {c.condition_id.removeprefix("condition:"): c for c in actor.conditions.values()}


def _at_ac(talents, name, ac, *, dc=16):
    """The action against a foe whose AC is set to ``ac`` (the attack is rolled, not a sure hit)."""
    engine = H._engine(_axes(talents, dc=dc), sure_hit=False)
    H._foe(engine).armor_class = ac
    return engine, H._use(engine, name)


def _attack_total(talents, name):
    _, events = _at_ac(talents, name, -50)
    return H._payloads(events, "ATTACK_ROLLED")[0]["modified_total"]


def _save_total(talents, name):
    _, events = H._axes_cast(talents, name, dc=FAIL)
    return H._payloads(events, "SAVE_ROLLED")[0]["total"]


# ----------------------------------------------------------------------------------------------------------------- Axes


def test_armor_joint_hook_lends_the_next_attack_a_plus_two():
    """"Failed Save: Until the start of your next turn, the next attack roll made against the target by you or an ally gains a
    +2 bonus. Successful Save: Until the end of your current turn, your next attack roll against the target gains a +2 bonus."
    Both were ``rider`` rows the GM applied by hand; now the target holds a next-attack AC penalty of 2 (spent by that roll)."""
    name = STRIKE + "Bite + Armor Joint Hook"
    failed, _ = H._axes_cast(["TAL_AXES_ARMOR_JOINT_HOOK"], name, dc=FAIL, marked=True)
    held = _conds(H._foe(failed))["typed.next_attack_ac"]
    assert held.data["amount"] == -2 and held.expires_on == "START_OF_SOURCE_NEXT_TURN"

    saved, _ = H._axes_cast(["TAL_AXES_ARMOR_JOINT_HOOK"], name, dc=PASS, marked=True)
    held = _conds(H._foe(saved))["typed.next_attack_ac"]
    assert held.data["amount"] == -2 and held.expires_on != "START_OF_SOURCE_NEXT_TURN"  # only to the end of the current turn

    # the next attack roll spends it and lands against an AC two lower
    H._ready(failed)
    events = H._use(failed, STRIKE + "Bite")
    roll = H._payloads(events, "ATTACK_ROLLED")[0]
    assert roll["target_ac"] == H._foe(failed).armor_class - 2
    assert "typed.next_attack_ac" not in _conds(H._foe(failed))


def test_axe_and_shield_press_pushes_only_on_a_failure_by_five_or_more():
    """"If the target fails the save by 5 or more, it is also pushed 5 feet": the push was a GM line at the GM's judgement of
    the margin.  The foe's save total is read first, then the DC is set to fail by 4 (no push) and by 5 (pushed)."""
    talents, name = ["TAL_AXES_AXE_AND_SHIELD_PRESS"], STRIKE + "Bite + Axe-and-Shield Press"
    total = _save_total(talents, name)
    close, _ = H._axes_cast(talents, name, dc=total + 4)
    assert H._foe(close).position == Position(x=4, y=6) and "typed.mark.bite.actor:factory.sweep" in _conds(H._foe(close))
    far, events = H._axes_cast(talents, name, dc=total + 5)
    assert H._foe(far).position == Position(x=5, y=6)  # pushed 5 feet away from the axe
    # "cannot move through your space or the spaces of allies adjacent to you": every creature's space already blocks a walker,
    # so nothing is left for the GM and no line is raised at the table
    assert not [e for e in events if e.event_type == "GM_RIDER" and "cannot move through your space" in str(e.payload)]
    assert [p["reason"] for p in H._payloads(events, "SAVE_ROLLED")]


def test_bearded_hook_method_moves_the_target_to_a_space_within_reach():
    """"When Hewing Strike hits and you choose Bite, move the target up to 5 feet to an unoccupied space within your reach":
    the move was a GM line; it is now Repositioning Strike's ``needle_reposition``, offered as a modifier of Hewing Strike."""
    name = STRIKE + "Bite + Bearded Hook Method"
    engine, events = H._axes_cast(["TAL_AXES_BEARDED_HOOK_METHOD"], name)
    foe = H._foe(engine)
    assert foe.position != Position(x=4, y=6)
    assert engine.grid.distance_ft(H._me(engine).position, foe.position) <= 5  # still within reach
    assert [e for e in events if e.event_type == "MOVEMENT_COMMITTED"]
    plain, _ = H._axes_cast(["TAL_AXES_BEARDED_HOOK_METHOD"], STRIKE + "Bite")
    assert H._foe(plain).position == Position(x=4, y=6)  # the bare option does not move it


def test_turning_cast_pushes_only_a_target_no_more_than_one_size_larger():
    """"If the target is no more than one size larger than you, it must choose either to be pushed 5 feet or ...": the push was
    unconditional, so a Huge creature was shoved as easily as a Medium one."""
    talents = ["TAL_AXES_CAST_AXE"]
    medium, _ = H._axes_cast(talents, TURNING)
    assert H._foe(medium).position == Position(x=5, y=6)

    engine = H._engine(_axes(talents))
    huge = engine._footprint(AN).model_copy(update={"width_cells": 3, "height_cells": 3, "occupied_relative_cells": tuple(
        Position(x=x, y=y) for x in range(3) for y in range(3))})
    engine.actor_footprints[AN] = huge
    start = H._foe(engine).position
    H._use(engine, TURNING)
    assert H._foe(engine).position == start


def test_split_the_shield_wall_and_moon_cleaver_deny_reactions_only_on_a_close_miss():
    """"Miss by 5 or less: ... cannot take Reactions against you until the start of your next turn" (Moon-Cleaver Return adds
    damage equal to your Proficiency Bonus): both applied to every miss, however wide."""
    for talents, name, closes in ((["TAL_AXES_SPLIT_THE_SHIELD_WALL"], "Split the Shield Wall", True),
                                  (["TAL_AXES_MOON_CLEAVER_RETURN"], "Moon-Cleaver Return", True)):
        total = _attack_total(talents, name)
        by_five, _ = _at_ac(talents, name, total + 5)
        by_six, _ = _at_ac(talents, name, total + 6)
        assert "typed.no_reactions_against" in _conds(H._foe(by_five)), name
        assert "typed.no_reactions_against" not in _conds(H._foe(by_six)), name
        if "MOON" in talents[0]:
            assert H._foe(by_five).current_hp == H._foe(by_five).maximum_hp - 4  # Proficiency Bonus damage
            assert H._foe(by_six).current_hp == H._foe(by_six).maximum_hp


def test_execution_mark_lasts_until_the_next_turn_and_counts_as_bite():
    """"The mark lasts until the start of your next turn and counts as Bite for your Axes talents": the mark was left until
    removed and no Bite was placed, so Bite-conditioned talents never saw it."""
    engine, _ = H._axes_cast(["TAL_AXES_EXECUTION_MARK"], STRIKE + "Bite", foe_hp=20)
    held = _conds(H._foe(engine))
    assert held["typed.mark.execution_mark.actor:factory.sweep"].expires_on == "START_OF_MARKER_NEXT_TURN"
    assert held["typed.mark.bite.actor:factory.sweep"].expires_on == "START_OF_MARKER_NEXT_TURN"


# ------------------------------------------------------------------------------------ Headsman's Mandate (three foes)


@pytest.mark.parametrize('consume,destination', [(False, Position(x=3,y=5)), (True, Position(x=3,y=4))])
def test_splitting_step_is_immediate_and_extends_when_the_attack_consumed_bite(consume, destination):
    from combat.gate2_runtime_models import ReactionDecision

    talents = ['TAL_AXES_SPLITTING_STEP', *(['TAL_AXES_RENDING_HEW'] if consume else [])]
    engine = H._engine(_axes(talents, dc=FAIL), foe_hp=500)
    if consume:
        H._bite(engine)
    requests = []

    def answer(request):
        if request['reaction_source_id'] == 'choice:needle.rider_step':
            requests.append(request)
            return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=request['reactor_id'],
                reaction_source_id=request['reaction_source_id'], selection='USE',
                option_ids=(f'cell:{destination.x},{destination.y}',)), None
        return None, None

    engine.set_reaction_provider(answer)
    name = next(c.display_name for c in engine.legal_candidates() if c.display_name.startswith(STRIKE+'Bite')
                and ('Rending Hew' in c.display_name) == consume)
    before = H._me(engine).movement_remaining_ft
    events = H._use(engine, name)
    assert H._me(engine).position == destination
    assert H._me(engine).movement_remaining_ft == before
    assert requests and any(e.event_type == 'MOVEMENT_COMMITTED' for e in events)
    if not consume:
        assert 'cell:3,4' not in requests[0]['extension_choice']['option_ids']


def test_splitting_step_still_moves_after_a_finishing_hit():
    from combat.gate2_runtime_models import ReactionDecision

    engine = _beauty_arena([H.HEWING, 'TAL_AXES_SPLITTING_STEP'], ally=True, extra_spheres=(H.AXES,))
    engine.state.actors[ALLY].team_id = engine.state.actors[H.FOE].team_id
    foe = engine.state.actors[H.FOE]
    foe.current_hp, foe.armor_class = 1, -50

    def answer(request):
        if request['reaction_source_id'] == 'choice:needle.rider_step':
            return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=request['reactor_id'],
                reaction_source_id=request['reaction_source_id'], selection='USE', option_ids=('cell:3,5',)), None
        return None, None

    engine.set_reaction_provider(answer)
    _act(engine, ME, STRIKE+'Bite', H.FOE)
    assert not foe.active
    assert H._me(engine).position == Position(x=3,y=5)


def _alchemy_arena(talents, *, dc=FAIL, cl=10, foe_talents=()):
    sphere = 'tianxia.sphere.alchemy'
    bundles = [compile_character(H._sheet(sphere, talents, H.AXE_KIT, dc=dc, cl=cl), actor_id=ME),
        compile_character(H._sheet(sphere, list(foe_talents), H.AXE_KIT, dc=50, cl=cl), actor_id=H.FOE)]
    engine = Gate4ControllerEngine(H.ROOT, match_seed='a', typed_bundles=tuple(bundles), roster_setup={
        'primary_actor_ids':[ME,H.FOE], 'team_by_actor':{ME:'team:a',H.FOE:'team:b'},
        'starting_positions':{ME:{'x':3,'y':6},H.FOE:{'x':4,'y':6}}})
    _begin_turn(engine, ME)
    # Prepared reagents are a fixture, not a claim that downtime crafting ran.
    engine._gain_resource(engine.state.actors[ME], 'resource:named.reagent_stock', 4, 'test:prepared_reagents')
    return engine


CAULDRON = 'tianxia.talent.alchemy.court_of_the_three_legged_cauldron'
RESTORATION = 'TAL_ALCHEMY_PILL_OF_RESTORATION'
DEVOURING = 'tianxia.talent.alchemy.pill_devouring'
PURIFICATION = 'tianxia.talent.alchemy.purification_formula'
FURNACE = 'tianxia.talent.alchemy.world_within_the_furnace'


HEALING_PILL = 'TAL_ALCHEMY_HEALING_PILL'
HEALING_BENEFITS = 'condition:typed.healing_pill_benefits'


def _healing_benefits(actor):
    return sum(c.data['amount'] for c in actor.conditions.values()
               if c.condition_id == HEALING_BENEFITS)


@pytest.mark.parametrize('pb', [2, 4, 6])
def test_healing_pill_consumer_pb_cap_preserves_actual_healing_and_other_consumers(pb):
    sheets = [H._sheet('tianxia.sphere.alchemy', [HEALING_PILL], H.AXE_KIT) for _ in range(2)]
    sheets[0]['identity']['proficiency_bonus'] = pb
    bundles = tuple(compile_character(sheet, actor_id=key) for sheet, key in zip(sheets, (ME, H.FOE)))
    engine = Gate4ControllerEngine(H.ROOT, match_seed='a', typed_bundles=bundles,
        roster_setup={'primary_actor_ids':[ME,H.FOE], 'team_by_actor':{ME:'team:a',H.FOE:'team:b'},
            'starting_positions':{ME:{'x':3,'y':6},H.FOE:{'x':4,'y':6}}})
    actor = engine.state.actors[ME]
    actor.current_hp = 1  # sufficient injury for every permitted dose
    for n in range(pb):
        before = actor.current_hp
        events = _act(engine, ME, 'Healing Pill')
        assert 4 <= actor.current_hp - before <= 10
        assert _healing_benefits(actor) == n + 1
        assert not actor.bonus_action_available
        assert H._payloads(events, 'HEALING_APPLIED')[0]['after'] == actor.current_hp
        _begin_turn(engine, H.FOE)
        _begin_turn(engine, ME)
        assert _healing_benefits(actor) == n + 1
    before, rolls = actor.current_hp, len(engine.rolls)
    events = _act(engine, ME, 'Healing Pill')
    assert actor.current_hp == before
    assert len(engine.rolls) == rolls
    assert not H._payloads(events, 'HEALING_APPLIED')
    assert _healing_benefits(actor) == pb
    foe = engine.state.actors[H.FOE]
    foe.current_hp = 1
    _act(engine, H.FOE, 'Healing Pill')
    assert foe.current_hp > 1 and _healing_benefits(foe) == 1
    assert _healing_benefits(actor) == pb


def test_healing_pill_full_hp_and_rotting_denial_spend_no_benefit():
    engine = _alchemy_arena([HEALING_PILL, 'TAL_ALCHEMY_POISON_PILL'], foe_talents=[HEALING_PILL])
    actor, foe = engine.state.actors[ME], engine.state.actors[H.FOE]
    _act(engine, ME, 'Healing Pill')
    assert _healing_benefits(actor) == 0
    _act(engine, ME, 'Poison Pill: Rotting Pill', H.FOE)
    before = foe.current_hp
    _act(engine, H.FOE, 'Healing Pill')
    assert foe.current_hp == before and _healing_benefits(foe) == 0
    actor.current_hp = 1
    _act(engine, ME, 'Healing Pill')
    assert _healing_benefits(actor) == 1  # parent typing has no benefit record


def test_healing_pill_table_commit_reload_retains_cap_and_does_not_refresh_at_turn_start(tmp_path):
    from combat.canonical import canonical_sha256
    from combat.gate4_persistence import Gate4Persistence

    sheet = H._sheet('tianxia.sphere.alchemy', [HEALING_PILL], H.AXE_KIT)
    sheet['identity']['proficiency_bonus'] = 2
    bundles = (compile_character(sheet, actor_id=ME),
        compile_character(H._sheet('tianxia.sphere.alchemy', [], H.AXE_KIT, cl=17, dc=50), actor_id=H.FOE))
    persistence = Gate4Persistence(H.ROOT, tmp_path/'healing-pill-table')
    session = persistence.create_match(match_seed='a', typed_bundles=bundles,
        roster_setup={'primary_actor_ids':[ME,H.FOE], 'team_by_actor':{ME:'team:a',H.FOE:'team:b'}},
        genesis_setup={ME:{'placement':{'x':3,'y':6}},
            H.FOE:{'placement':{'x':4,'y':6}, 'resources':{STOCK:4}}})

    def submit(name=None, target=None):
        c = next(c for c in session.engine.legal_candidates() if c.display_name == name
                 and (target is None or target in c.target_ids)) if name else next(
            c for c in session.engine.legal_candidates() if str(getattr(c.kind,'value',c.kind)) == 'END_TURN')
        session.submit_intent(H.ActionIntent(intent_id=f'healing-pill-{session.engine.state.event_sequence}',
            decision_id=c.decision_id, candidate_id=c.candidate_id, state_version=c.state_version,
            actor_id=c.actor_id, target_ids=c.target_ids, destination=c.destination),
            primary_decision_record=None, reaction_provider=None)

    # Injury comes from accepted table actions and is retained in the commit log.
    while session.engine.state.actors[ME].current_hp > session.engine.state.actors[ME].maximum_hp - 21:
        while session.engine.state.current_actor_id != H.FOE:
            submit()
        submit('Field Formula: Corrosive Dregs', ME)
        submit()
    while session.engine.state.current_actor_id != ME:
        submit()
    for n in (1, 2):
        submit('Healing Pill')
        assert _healing_benefits(session.engine.state.actors[ME]) == n
        before = canonical_sha256(session.engine.state.model_dump(mode='json'))
        session = persistence.load_match(session.match_id)
        assert canonical_sha256(session.engine.state.model_dump(mode='json')) == before
        counter = next(c for c in session.engine.state.actors[ME].conditions.values()
                       if c.condition_id == HEALING_BENEFITS)
        assert type(counter.data['amount']) is int and counter.expires_on == 'UNTIL_REMOVED'
        submit()
        while session.engine.state.current_actor_id != ME:
            submit()
    hp = session.engine.state.actors[ME].current_hp
    submit('Healing Pill')
    assert session.engine.state.actors[ME].current_hp == hp
    session = persistence.load_match(session.match_id)
    assert _healing_benefits(session.engine.state.actors[ME]) == 2
    assert session.engine.state.actors[ME].current_hp == hp


@pytest.mark.parametrize('cl,count', [(3, 1), (5, 2), (11, 3), (17, 4)])
@pytest.mark.parametrize('option', ['Medicinal Smoke', 'Numbing Smoke', 'Corrosive Dregs'])
def test_alchemy_scaling_field_formula_runs_without_duplicate_gm_instruction(cl, count, option):
    engine = _alchemy_arena([], cl=cl)
    owner, foe = engine.state.actors[ME], engine.state.actors[H.FOE]
    cp, stock = owner.resources['resource:core.stamina'], owner.resources[STOCK]
    events = _act(engine, ME, 'Field Formula: ' + option,
                  ME if option == 'Medicinal Smoke' else H.FOE if option == 'Corrosive Dregs' else None,
                  destination=foe.position if option == 'Numbing Smoke' else None)
    rolls = H._payloads(events, 'DAMAGE_ROLLED')
    assert rolls[0]['expression'] == f'{count}d6+3'
    if option == 'Medicinal Smoke':
        assert owner.temporary_hp == rolls[0]['total']
    else:
        assert H._payloads(events, 'DAMAGE_COMMITTED')[0]['hp_damage'] == rolls[0]['total']
    assert owner.resources['resource:core.stamina'] == cp - 1
    assert owner.resources[STOCK] == stock - 1
    assert not any(e.event_type == 'GM_RIDER' and 'increases to' in e.payload['rider'] for e in events)


@pytest.mark.parametrize('target', [ME, 'actor:factory.ally'])
def test_alchemy_scaling_medicinal_smoke_grants_only_the_selected_self_or_ally(target):
    engine = _beauty_arena([], ally=True, extra_spheres=('tianxia.sphere.alchemy',))
    owner = engine.state.actors[ME]
    engine._gain_resource(owner, STOCK, 2, 'test:prepared_reagents')
    events = _act(engine, ME, 'Field Formula: Medicinal Smoke', target)
    rolled = H._payloads(events, 'DAMAGE_ROLLED')[0]
    assert engine.state.actors[target].temporary_hp == rolled['total']
    other = 'actor:factory.ally' if target == ME else ME
    assert engine.state.actors[other].temporary_hp == 0
    assert engine.state.actors[H.FOE].temporary_hp == 0
    assert not any(e.event_type == 'GM_RIDER' and 'increases to' in e.payload['rider'] for e in events)


@pytest.mark.parametrize('target', [ME, 'actor:factory.ally'])
def test_alchemy_scaling_medicinal_smoke_table_commit_reload_preserves_selected_benefit(tmp_path, target):
    from combat.canonical import canonical_sha256
    from combat.gate4_persistence import Gate4Persistence

    ally = 'actor:factory.ally'
    bundles = tuple(compile_character(H._sheet('tianxia.sphere.alchemy' if key == ME else None,
        [], H.AXE_KIT, cl=11), actor_id=key) for key in (ME, H.FOE, ally))
    persistence = Gate4Persistence(H.ROOT, tmp_path/'medicinal-table')
    session = persistence.create_match(match_seed='a', typed_bundles=bundles,
        roster_setup={'primary_actor_ids':[ME,H.FOE,ally],
            'team_by_actor':{ME:'team:a',H.FOE:'team:b',ally:'team:a'}},
        genesis_setup={ME:{'placement':{'x':3,'y':6}, 'resources':{STOCK:2}},
            H.FOE:{'placement':{'x':4,'y':6}}, ally:{'placement':{'x':3,'y':7}}})
    def submit(name=None):
        c = next(c for c in session.engine.legal_candidates() if
            c.display_name == name and target in c.target_ids) if name else next(
            c for c in session.engine.legal_candidates() if str(getattr(c.kind,'value',c.kind)) == 'END_TURN')
        session.submit_intent(H.ActionIntent(intent_id=f'medicinal-{session.engine.state.event_sequence}',
            decision_id=c.decision_id, candidate_id=c.candidate_id, state_version=c.state_version,
            actor_id=c.actor_id, target_ids=c.target_ids, destination=c.destination),
            primary_decision_record=None, reaction_provider=None)
    while session.engine.state.current_actor_id != ME:
        submit()
    first = len(session.engine.events)
    submit('Field Formula: Medicinal Smoke')
    events = session.engine.events[first:]
    rolled = H._payloads(events, 'DAMAGE_ROLLED')[0]
    assert rolled['expression'] == '3d6+3'
    assert session.engine.state.actors[target].temporary_hp == rolled['total']
    other = ally if target == ME else ME
    assert session.engine.state.actors[other].temporary_hp == 0
    assert not any(e.event_type == 'GM_RIDER' and 'increases to' in e.payload['rider'] for e in events)
    before = canonical_sha256(session.engine.state.model_dump(mode='json'))
    session = persistence.load_match(session.match_id)
    assert canonical_sha256(session.engine.state.model_dump(mode='json')) == before
    assert session.engine.state.actors[target].temporary_hp == rolled['total']


@pytest.mark.parametrize('talent,name,sides,bonus,tiers', [
    ('TAL_ALCHEMY_FURNACE_VENT', 'Furnace Vent', 8, 3, [(3, 1), (5, 2), (11, 3), (17, 4)]),
    ('TAL_ALCHEMY_NUMBING_POWDER', 'Numbing Powder', 6, 0, [(3, 1), (5, 2), (11, 3), (17, 4)]),
    ('TAL_ALCHEMY_EXPLOSIVE_PILL', 'Explosive Pill', 6, 0, [(5, 4), (10, 4), (11, 6), (17, 8)]),
])
@pytest.mark.parametrize('tier', range(4))
@pytest.mark.parametrize('saved', [False, True])
def test_alchemy_scaling_formula_and_pill_runs_without_duplicate_gm_instruction(
        talent, name, sides, bonus, tiers, tier, saved):
    cl, count = tiers[tier]
    engine = _alchemy_arena([talent], cl=cl, dc=PASS if saved else FAIL)
    foe = engine.state.actors[H.FOE]
    events = _act(engine, ME, name, H.FOE if name == 'Numbing Powder' else None,
                  destination=None if name == 'Numbing Powder' else foe.position)
    rolled = H._payloads(events, 'DAMAGE_ROLLED')[0]
    assert rolled['expression'] == f'{count}d{sides}+{bonus}'
    damage = H._payloads(events, 'DAMAGE_COMMITTED')[0]
    assert damage['hp_damage'] == rolled['total'] // (2 if saved else 1)
    assert not any(e.event_type == 'GM_RIDER' and
                   ('increases to' in e.payload['rider'] or e.payload['rider'].startswith('CL ')) for e in events)
    if name == 'Explosive Pill':
        # Refinement-time element/inventory are still declarations, not a new combat-time choice.
        assert any(e.event_type == 'GM_RIDER' and 'when you refine' in e.payload['rider'] for e in events)


@pytest.mark.parametrize('cl,count', [(10, 3), (16, 3), (17, 5)])
@pytest.mark.parametrize('saved', [False, True])
def test_alchemy_scaling_dregs_zone_runs_and_pays_without_duplicate_gm_instruction(cl, count, saved):
    talent = 'tianxia.talent.alchemy.ten_thousand_dregs_field'
    engine = _alchemy_arena([talent], cl=cl, dc=PASS if saved else FAIL)
    owner, foe = engine.state.actors[ME], engine.state.actors[H.FOE]
    cp, stock = owner.resources['resource:core.stamina'], owner.resources[STOCK]
    events = _act(engine, ME, 'Ten Thousand Dregs Field', destination=foe.position)
    assert not H._payloads(events, 'DAMAGE_ROLLED')
    assert owner.resources['resource:core.stamina'] == cp - 3
    assert owner.resources[STOCK] == stock - 2
    before = len(engine.events)
    _end_turn(engine)
    boundary = engine.events[before:]
    rolled = H._payloads(boundary, 'DAMAGE_ROLLED')[0]
    assert rolled['expression'] == f'{count}d6+0'
    assert H._payloads(boundary, 'DAMAGE_COMMITTED')[0]['hp_damage'] == rolled['total'] // (2 if saved else 1)
    assert not any(e.event_type == 'GM_RIDER' and
                   ('damage becomes' in e.payload['rider'] or e.payload['rider'].startswith('Cost:')) for e in events + boundary)


def _furnace_answers(engine, *, exclude=(), rider='Burn Away Dross'):
    from combat.gate2_runtime_models import ReactionDecision
    requests = []
    def answer(request):
        if request['reaction_source_id'] == 'choice:needle.furnace_rider':
            return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=request['reactor_id'],
                reaction_source_id=request['reaction_source_id'], selection='USE', option_ids=(rider,)), None
        if request['reaction_source_id'] != 'choice:needle.furnace_target':
            return None, None
        requests.append(request)
        target = request['choice_trigger']['target_id']
        return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=request['reactor_id'],
            reaction_source_id=request['reaction_source_id'], selection='USE',
            option_ids=('exclude' if target in exclude else 'include',)), None
    engine.set_reaction_provider(answer)
    return requests


@pytest.mark.parametrize('damage_type', ['acid', 'fire', 'poison'])
@pytest.mark.parametrize('rider', ['Burn Away Dross', 'Numb the Meridians', 'Clog the Breath'])
def test_furnace_creation_selects_damage_and_only_one_failed_save_rider(damage_type, rider):
    engine = _alchemy_arena([FURNACE], cl=15)
    requests = _furnace_answers(engine, rider=rider)
    owner, foe = engine.state.actors[ME], engine.state.actors[H.FOE]
    before_cp, before_stock = owner.resources['resource:core.stamina'], owner.resources[STOCK]
    events = _act(engine, ME, f'World Within the Furnace: {damage_type.title()}', destination=foe.position)
    assert not H._payloads(events, 'SAVE_ROLLED')  # Nothing is applied at creation.
    assert owner.resources['resource:core.stamina'] == before_cp - 8
    assert owner.resources[STOCK] == before_stock - 3
    before = len(engine.events)
    _end_turn(engine)
    assert engine.state.current_actor_id == H.FOE
    events = engine.events[before:]
    assert requests and H._payloads(events, 'SAVE_ROLLED')
    damage = H._payloads(events, 'DAMAGE_COMMITTED')
    assert damage and damage[0]['damage_type'].lower() == damage_type
    reductions = [m for m in foe.modifiers.values() if m.target_field == 'healing_reduction']
    assert bool(reductions) == (rider == 'Burn Away Dross')
    assert ('typed.reaction_denied' in _conds(foe)) == (rider == 'Numb the Meridians')
    assert ('typed.silenced' in _conds(foe)) == (rider == 'Clog the Breath')
    for item in [*reductions, *[c for c in foe.conditions.values() if c.condition_id in
            ('condition:typed.reaction_denied', 'condition:typed.silenced')]]:
        assert item.expires_on in ('START_OF_SELF_NEXT_TURN', f'START_OF_TURN_AT:{H.FOE}:{foe.turns_started + 1}')
    # Leave the area so the next boundary cannot reapply the failed-save effect.
    foe.position = Position(x=19, y=19)
    _begin_turn(engine, H.FOE)
    assert not [m for m in foe.modifiers.values() if m.target_field == 'healing_reduction']
    assert not {'typed.reaction_denied', 'typed.silenced'} & _conds(foe).keys()


def test_furnace_successful_save_halves_damage_without_any_rider():
    engine = _alchemy_arena([FURNACE], cl=15, dc=PASS)
    _furnace_answers(engine, rider='Clog the Breath')
    _act(engine, ME, 'World Within the Furnace: Fire', destination=engine.state.actors[H.FOE].position)
    before = len(engine.events)
    _end_turn(engine)
    events = engine.events[before:]
    damage = H._payloads(events, 'DAMAGE_COMMITTED')[0]
    rolls = H._payloads(events, 'DAMAGE_ROLLED')
    assert damage['hp_damage'] == rolls[0]['total'] // 2
    assert 'typed.silenced' not in _conds(engine.state.actors[H.FOE])


def test_furnace_caster_can_exclude_hostiles_on_their_turn_and_self_from_ally_benefit():
    engine = _alchemy_arena([FURNACE], cl=15)
    requests = _furnace_answers(engine, exclude=(ME, H.FOE), rider='Numb the Meridians')
    _act(engine, ME, 'World Within the Furnace: Poison', destination=engine.state.actors[H.FOE].position)
    before = len(engine.events)
    _end_turn(engine)
    _end_turn(engine)
    assert len(requests) == 2 and all(r['reactor_id'] == ME for r in requests)
    assert not H._payloads(engine.events[before:], 'SAVE_ROLLED')
    assert engine.state.actors[ME].temporary_hp == 0
    assert not {'typed.reaction_denied', 'typed.silenced'} & _conds(engine.state.actors[H.FOE]).keys()


def test_furnace_automatic_caster_applies_printed_ally_temp_hp_and_healing_denial():
    engine = _alchemy_arena([FURNACE], cl=15, foe_talents=['TAL_ALCHEMY_HEALING_PILL'])
    _act(engine, ME, 'World Within the Furnace: Acid', destination=engine.state.actors[H.FOE].position)
    _end_turn(engine)
    foe = engine.state.actors[H.FOE]
    hp = foe.current_hp
    assert hp < foe.maximum_hp
    _act(engine, H.FOE, 'Healing Pill')
    assert foe.current_hp == hp
    _end_turn(engine)
    owner = engine.state.actors[ME]
    zone = next(iter(engine.state.zones.values()))
    numbers = zone.trigger_profile['numbers']
    assert owner.temporary_hp == numbers['pb'] + numbers['key_mod']
    assert not zone.trigger_profile.get('wall') and not zone.trigger_profile.get('difficult')


@pytest.mark.parametrize('rider', ['Numb the Meridians', 'Clog the Breath'])
def test_furnace_failed_save_prevents_actual_reactions_or_voiced_actions(rider):
    engine = _alchemy_arena([FURNACE], cl=15,
        foe_talents=['tianxia.path.body_refining.feature.iron_voice'])
    _furnace_answers(engine, rider=rider)
    _act(engine, ME, 'World Within the Furnace: Poison', destination=engine.state.actors[H.FOE].position)
    _end_turn(engine)
    if rider == 'Numb the Meridians':
        assert engine.state.actors[H.FOE].reaction_available is False
    else:
        assert 'Iron Voice' not in H._legal(engine)
        assert 'Fu (Short Axe) attack' in H._legal(engine)


@pytest.mark.parametrize('mode', ['MANUAL', 'SUGGESTED'])
def test_furnace_creation_rider_choice_pauses_real_service_preview(tmp_path, mode):
    from types import SimpleNamespace
    from combat.canonical import canonical_sha256
    from combat.gate2_runtime_models import ReactionDecision
    from combat.gate5_service import CombatService, _ReactionRequired

    engine = _alchemy_arena([FURNACE], cl=15)
    candidate = next(c for c in engine.legal_candidates() if c.display_name.startswith('World Within the Furnace: Fire')
        and c.destination == engine.state.actors[H.FOE].position)
    intent = H.ActionIntent(intent_id='preview-furnace-create', actor_id=candidate.actor_id,
        decision_id=candidate.decision_id, candidate_id=candidate.candidate_id, state_version=candidate.state_version,
        target_ids=candidate.target_ids, destination=candidate.destination)
    service = CombatService(H.ROOT, tmp_path/'service')
    session = SimpleNamespace(engine=engine, match_id=engine.state.match_id)
    metadata = {'participant_control_modes':{ME:mode, H.FOE:'LOCAL_AUTO'}}
    before = canonical_sha256(engine.state.model_dump(mode='json'))
    with pytest.raises(_ReactionRequired) as paused:
        service._run_preview(session, metadata, intent, ())
    context = paused.value.context
    assert context.reactor_id == ME and context.reaction_source_id == 'choice:needle.furnace_rider'
    assert 'World Within the Furnace' in context.choice_trigger['prompt']
    decision = ReactionDecision(checkpoint=context.checkpoint, reactor_id=ME,
        reaction_source_id=context.reaction_source_id, selection='USE', option_ids=('Clog the Breath',))
    result = service._run_preview(session, metadata, intent, (decision,))
    zones = [e['payload']['zone'] for e in result['events'] if e['event_type'] == 'ZONE_CREATED']
    assert len(zones) == 1
    assert zones[0]['trigger_profile']['triggers'][0]['effects'][0]['effects'][0]['on_fail'][-1]['condition'] == 'silenced'
    assert canonical_sha256(engine.state.model_dump(mode='json')) == before


@pytest.mark.parametrize('mode', ['MANUAL', 'SUGGESTED'])
def test_furnace_off_turn_beneficiary_choice_pauses_real_service_preview(tmp_path, mode):
    from types import SimpleNamespace
    from combat.canonical import canonical_sha256
    from combat.gate2_runtime_models import ReactionDecision
    from combat.gate5_service import CombatService, _ReactionRequired

    engine = _alchemy_arena([FURNACE], cl=15)
    _furnace_answers(engine, rider='Numb the Meridians')
    _act(engine, ME, 'World Within the Furnace: Fire', destination=engine.state.actors[H.FOE].position)
    engine.set_reaction_provider(None)
    candidate = next(c for c in engine.legal_candidates() if str(getattr(c.kind, 'value', c.kind)) == 'END_TURN')
    intent = H.ActionIntent(intent_id='preview-furnace', actor_id=candidate.actor_id,
        decision_id=candidate.decision_id, candidate_id=candidate.candidate_id, state_version=candidate.state_version)
    service = CombatService(H.ROOT, tmp_path/'service')
    # The seam under test is the real service's preview/pause transport (CombatService._run_preview and the
    # reaction decision it raises), not the journal reading. These tests build a bare engine, not a saved
    # match, so the candidate query's verified journal (combat/turn_progress.py) is empty here on purpose;
    # the persisted-session path is covered by the table commit/reload tests in this file.
    session = SimpleNamespace(engine=engine, match_id=engine.state.match_id, mechanical=SimpleNamespace(_records=()))
    metadata = {'participant_control_modes':{ME:mode, H.FOE:'LOCAL_AUTO'}}
    before = canonical_sha256(engine.state.model_dump(mode='json'))
    with pytest.raises(_ReactionRequired) as paused:
        service._run_preview(session, metadata, intent, ())
    context = paused.value.context
    assert context.reactor_id == ME and context.reaction_source_id == 'choice:needle.furnace_target'
    assert 'World Within the Furnace' in context.choice_trigger['prompt']
    assert engine.state.actors[H.FOE].display_name in context.choice_trigger['prompt']
    decision = ReactionDecision(checkpoint=context.checkpoint, reactor_id=ME,
        reaction_source_id=context.reaction_source_id, selection='USE', option_ids=('exclude',))
    result = service._run_preview(session, metadata, intent, (decision,))
    assert not [e for e in result['events'] if e['event_type'] in ('SAVE_ROLLED', 'DAMAGE_COMMITTED')]
    assert canonical_sha256(engine.state.model_dump(mode='json')) == before


@pytest.mark.parametrize('rider', ['Burn Away Dross', 'Numb the Meridians', 'Clog the Breath'])
def test_furnace_creation_choices_and_turn_effects_survive_table_commit_reload(tmp_path, rider):
    from combat.canonical import canonical_sha256
    from combat.gate4_persistence import Gate4Persistence

    bundles = tuple(compile_character(H._sheet('tianxia.sphere.alchemy',
        [FURNACE] if key == ME else [], H.AXE_KIT, cl=15, dc=FAIL), actor_id=key)
        for key in (ME, H.FOE))
    persistence = Gate4Persistence(H.ROOT, tmp_path/'furnace-table')
    session = persistence.create_match(match_seed='a', typed_bundles=bundles,
        roster_setup={'primary_actor_ids':[ME,H.FOE], 'team_by_actor':{ME:'team:a',H.FOE:'team:b'}},
        genesis_setup={ME:{'placement':{'x':3,'y':6}, 'resources':{STOCK:4}},
                       H.FOE:{'placement':{'x':4,'y':6}}})
    def submit(name=None, provider=None):
        candidates = session.engine.legal_candidates()
        c = next(c for c in candidates if (c.display_name == name or c.display_name.startswith(name+' at '))
            and c.destination == Position(x=4,y=6)) if name else next(c for c in candidates
                if str(getattr(c.kind,'value',c.kind)) == 'END_TURN')
        session.submit_intent(H.ActionIntent(intent_id=f'furnace-{session.engine.state.event_sequence}',
            decision_id=c.decision_id, candidate_id=c.candidate_id, state_version=c.state_version,
            actor_id=c.actor_id, target_ids=c.target_ids, destination=c.destination),
            primary_decision_record=None, reaction_provider=provider)
    while session.engine.state.current_actor_id != ME:
        submit()
    _furnace_answers(session.engine, rider=rider)
    provider = session.engine._gate4_reaction_provider
    submit('World Within the Furnace: Poison', provider)
    before = canonical_sha256(session.engine.state.model_dump(mode='json'))
    session = persistence.load_match(session.match_id)
    assert canonical_sha256(session.engine.state.model_dump(mode='json')) == before
    _furnace_answers(session.engine, rider=rider)
    submit(provider=session.engine._gate4_reaction_provider)
    foe = session.engine.state.actors[H.FOE]
    assert foe.current_hp < foe.maximum_hp
    if rider == 'Burn Away Dross':
        assert any(m.target_field == 'healing_reduction' for m in foe.modifiers.values())
    else:
        assert ('typed.reaction_denied' if rider == 'Numb the Meridians' else 'typed.silenced') in _conds(foe)
    before = canonical_sha256(session.engine.state.model_dump(mode='json'))
    session = persistence.load_match(session.match_id)
    assert canonical_sha256(session.engine.state.model_dump(mode='json')) == before


def _end_turn(engine):
    candidate = next(c for c in engine.legal_candidates()
                     if str(getattr(c.kind, 'value', c.kind)) == 'END_TURN')
    engine.execute_intent(H.ActionIntent(intent_id=f'end-pill-{engine.state.event_sequence}',
        actor_id=candidate.actor_id, decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version))


@pytest.mark.parametrize('option,off_turn', [('impurity', False), ('poison', False), ('poison', True)])
def test_devouring_cost_waits_one_minute_then_asks_its_owner(option, off_turn):
    from combat.ext.alchemy_riders import DEVOURING_COST, pill_impurities
    from combat.gate2_runtime_models import ReactionDecision

    engine = _alchemy_arena([DEVOURING], cl=15)
    requests = []

    def answer(request):
        if request['reaction_source_id'] != 'choice:needle.pill_devouring_cost':
            return None, None
        requests.append(request)
        return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=request['reactor_id'],
            reaction_source_id=request['reaction_source_id'], selection='USE', option_ids=(option,)), None

    engine.set_reaction_provider(answer)
    _act(engine, ME, 'Pill Devouring')
    owner = engine.state.actors[ME]
    assert not requests and pill_impurities(owner) == 0 and 'typed.poisoned' not in _conds(owner)
    pending = next(c for c in owner.conditions.values() if c.condition_id == DEVOURING_COST)
    deadline_round = int(pending.data['due'].split(':')[1])
    engine.state.round_number = deadline_round - 1
    _end_turn(engine)
    assert not requests and pending.instance_id in owner.conditions
    engine.state.round_number = deadline_round + (1 if off_turn else 0)
    # A normal END_TURN provides the actual intent for the following boundary.
    # The late-clock case resolves on the foe's turn, with the owner still asked.
    while engine.state.current_actor_id != (ME if off_turn else H.FOE):
        _end_turn(engine)
    _end_turn(engine)
    assert len(requests) == 1 and requests[0]['reactor_id'] == ME
    assert 'Pill Devouring' in requests[0]['choice_trigger']['prompt']
    assert owner.display_name in requests[0]['choice_trigger']['prompt']
    assert pending.instance_id not in owner.conditions
    assert pill_impurities(owner) == (1 if option == 'impurity' else 0)
    if option == 'poison':
        poison = _conds(owner)['typed.poisoned']
        assert poison.expires_on.endswith(':' + str(owner.turns_started + 1))
        rolls = [r for r in engine.rolls if r.reason.startswith('DAMAGE:') and DEVOURING in r.reason]
        assert len(rolls) == 1 and len(rolls[0].dice) == 2
        # The condition survives the owner's current turn and expires after its next.
        before_turn = owner.turns_started
        while owner.turns_started <= before_turn or engine.state.current_actor_id == ME:
            _end_turn(engine)
        assert 'typed.poisoned' not in _conds(owner)
    for _ in range(3):
        _end_turn(engine)
    assert len(requests) == 1


@pytest.mark.parametrize('amount', [0, 1, 8])
def test_purification_removes_rolled_pill_impurities_from_the_target_only(amount):
    from combat.ext.alchemy_riders import PILL_IMPURITIES, pill_impurities

    engine = _alchemy_arena([PURIFICATION], cl=15)
    target, other = engine.state.actors[ME], engine.state.actors[H.FOE]
    # Explicit pre-existing-affliction fixtures; preparation and outside-combat
    # impurity acquisition are not claimed automated by this combat test.
    for subject, count in [(other, 7), (target, amount)]:
        if count:
            engine._apply_condition(subject, PILL_IMPURITIES, 'test:prior_pill_impurities',
                subject.entity_id, expires_on='UNTIL_REMOVED', data={'amount': count})
    target.resource_maximums['resource:named.impurity'] = 6  # unrelated Hunger fixture pool
    target.resources['resource:named.impurity'] = 6
    before_cp = target.resources['resource:core.stamina']
    events = _act(engine, ME, 'Purification Formula: Remove Pill Impurities')
    rolls = [r for r in engine.rolls if r.reason.startswith('PILL_IMPURITIES:')]
    assert len(rolls) == 1 and len(rolls[0].dice) == 1 and 1 <= rolls[0].total <= 4
    assert pill_impurities(target) == max(0, amount - rolls[0].total)
    assert pill_impurities(other) == 7 and target.resources['resource:named.impurity'] == 6
    assert target.resources['resource:core.stamina'] == before_cp  # refinement is preparation
    assert not any(e.event_type == 'GM_RIDER' and 'Spend resource not identified' in str(e.payload) for e in events)


def test_devouring_automatic_cost_is_impurity_and_purification_consumes_it():
    from combat.ext.alchemy_riders import DEVOURING_COST, pill_impurities

    engine = _alchemy_arena([], cl=15, foe_talents=[DEVOURING, PURIFICATION])
    _act(engine, H.FOE, 'Pill Devouring')
    target = engine.state.actors[H.FOE]
    deadline = next(c.data['due'] for c in target.conditions.values() if c.condition_id == DEVOURING_COST)
    engine.state.round_number = int(deadline.split(':')[1]) + 1
    _end_turn(engine)
    assert pill_impurities(target) == 1
    _act(engine, H.FOE, 'Purification Formula: Remove Pill Impurities')
    assert pill_impurities(target) == 0


def test_purification_unrepresented_affliction_choice_stays_gm_qualified():
    from combat.ext.alchemy_riders import PILL_IMPURITIES, pill_impurities

    engine = _alchemy_arena([PURIFICATION], cl=15)
    actor = engine.state.actors[ME]
    engine._apply_condition(actor, PILL_IMPURITIES, 'test:prior_pill_impurities', ME,
        expires_on='UNTIL_REMOVED', data={'amount': 3})
    modifiers = actor.modifiers.copy()
    events = _act(engine, ME, 'Purification Formula: Advantage vs Affliction')
    assert actor.modifiers == modifiers and pill_impurities(actor) == 3
    assert any(e.event_type == 'GM_RIDER' and 'affliction identity and rest boundary' in str(e.payload)
               for e in events)


@pytest.mark.parametrize('mode', ['MANUAL', 'SUGGESTED'])
def test_devouring_expiry_pauses_real_service_preview_for_the_players_choice(tmp_path, mode):
    from types import SimpleNamespace
    from combat.canonical import canonical_sha256
    from combat.ext.alchemy_riders import DEVOURING_COST
    from combat.gate2_runtime_models import ReactionDecision
    from combat.gate5_service import CombatService, _ReactionRequired

    engine = _alchemy_arena([DEVOURING], cl=15)
    _act(engine, ME, 'Pill Devouring')
    pending = next(c for c in engine.state.actors[ME].conditions.values() if c.condition_id == DEVOURING_COST)
    # The table commit/reload test traverses all ten rounds. Here advance only
    # the fixture clock to isolate the real service's preview/pause transport.
    engine.state.round_number = int(pending.data['due'].split(':')[1]) + 1
    candidate = next(c for c in engine.legal_candidates() if str(getattr(c.kind, 'value', c.kind)) == 'END_TURN')
    intent = H.ActionIntent(intent_id='preview-pill-cost', actor_id=candidate.actor_id,
        decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
        state_version=candidate.state_version)
    service = CombatService(H.ROOT, tmp_path/'service')
    # Same seam as the furnace preview test above: preview/pause transport on a bare engine, so the
    # verified-journal tail the candidate query reads is empty by construction.
    session = SimpleNamespace(engine=engine, match_id=engine.state.match_id, mechanical=SimpleNamespace(_records=()))
    metadata = {'participant_control_modes':{ME:mode, H.FOE:'LOCAL_AUTO'}}
    before = canonical_sha256(engine.state.model_dump(mode='json'))
    with pytest.raises(_ReactionRequired) as paused:
        service._run_preview(session, metadata, intent, ())
    context = paused.value.context
    assert context.reactor_id == ME and context.reaction_source_id == 'choice:needle.pill_devouring_cost'
    assert canonical_sha256(engine.state.model_dump(mode='json')) == before
    decision = ReactionDecision(checkpoint=context.checkpoint, reactor_id=ME,
        reaction_source_id=context.reaction_source_id, selection='USE', option_ids=('poison',))
    result = service._run_preview(session, metadata, intent, (decision,))
    assert any(e['event_type'] == 'CONDITION_APPLIED' and
               e['payload'].get('condition_id') == 'condition:typed.poisoned' for e in result['events'])
    assert canonical_sha256(engine.state.model_dump(mode='json')) == before


@pytest.mark.parametrize('option', ['impurity', 'poison'])
def test_devouring_obligation_choice_and_purification_survive_table_reload(tmp_path, option):
    from combat.canonical import canonical_sha256
    from combat.ext.alchemy_riders import DEVOURING_COST, pill_impurities
    from combat.gate2_runtime_models import ReactionDecision
    from combat.gate4_persistence import Gate4Persistence

    bundles = tuple(compile_character(H._sheet('tianxia.sphere.alchemy',
        [DEVOURING, PURIFICATION] if key == ME else [], H.AXE_KIT, cl=15, dc=50), actor_id=key)
        for key in (ME, H.FOE))
    persistence = Gate4Persistence(H.ROOT, tmp_path/'devouring-table')
    session = persistence.create_match(match_seed='a', typed_bundles=bundles,
        roster_setup={'primary_actor_ids':[ME,H.FOE], 'team_by_actor':{ME:'team:a',H.FOE:'team:b'}},
        genesis_setup={ME:{'placement':{'x':3,'y':6}}, H.FOE:{'placement':{'x':4,'y':6}}})
    requests = []

    def answer(request):
        if request['reaction_source_id'] != 'choice:needle.pill_devouring_cost':
            return None, None
        requests.append(request)
        return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=request['reactor_id'],
            reaction_source_id=request['reaction_source_id'], selection='USE', option_ids=(option,)), None

    def submit(name=None):
        candidates = session.engine.legal_candidates()
        c = next(c for c in candidates if c.display_name == name) if name else next(
            c for c in candidates if str(getattr(c.kind, 'value', c.kind)) == 'END_TURN')
        session.submit_intent(H.ActionIntent(intent_id=f'pill-table-{session.engine.state.event_sequence}',
            actor_id=c.actor_id, decision_id=c.decision_id, candidate_id=c.candidate_id,
            state_version=c.state_version, target_ids=c.target_ids),
            primary_decision_record=None, reaction_provider=answer)

    while session.engine.state.current_actor_id != ME:
        submit()
    submit('Pill Devouring')
    actor = session.engine.state.actors[ME]
    assert pill_impurities(actor) == 0 and not requests
    pending = next(c for c in actor.conditions.values() if c.condition_id == DEVOURING_COST)
    deadline = pending.data['due']
    session = persistence.load_match(session.engine.state.match_id)
    actor = session.engine.state.actors[ME]
    assert next(c.data['due'] for c in actor.conditions.values() if c.condition_id == DEVOURING_COST) == deadline
    for _ in range(25):
        if not any(c.condition_id == DEVOURING_COST for c in actor.conditions.values()):
            break
        submit()
    assert len(requests) == 1 and requests[0]['reactor_id'] == ME
    assert not any(c.condition_id == DEVOURING_COST for c in actor.conditions.values())
    assert pill_impurities(actor) == (1 if option == 'impurity' else 0)
    assert ('typed.poisoned' in _conds(actor)) == (option == 'poison')
    state_hash = canonical_sha256(session.engine.state.model_dump(mode='json'))
    session = persistence.load_match(session.engine.state.match_id)
    assert canonical_sha256(session.engine.state.model_dump(mode='json')) == state_hash
    if option == 'impurity':
        while session.engine.state.current_actor_id != ME:
            submit()
        submit('Purification Formula: Remove Pill Impurities')
        assert pill_impurities(session.engine.state.actors[ME]) == 0
        state_hash = canonical_sha256(session.engine.state.model_dump(mode='json'))
        session = persistence.load_match(session.engine.state.match_id)
        assert canonical_sha256(session.engine.state.model_dump(mode='json')) == state_hash


@pytest.mark.parametrize('unqualified_source', ['test:unknown_cause', 'weapon_action'])
def test_restoration_keeps_unqualified_poison_while_ending_real_venom_pill(unqualified_source):
    engine = _alchemy_arena([RESTORATION], foe_talents=['TAL_ALCHEMY_POISON_PILL'])
    engine._gain_resource(engine.state.actors[H.FOE], STOCK, 4, 'test:prepared_reagents')
    _act(engine, H.FOE, 'Poison Pill: Venom Pill', ME)
    actor = engine.state.actors[ME]
    venom = next(c for c in actor.conditions.values() if c.condition_id == 'condition:typed.poisoned')
    if unqualified_source == 'weapon_action':
        # Explicit synthetic condition fixture: a weapon's source alone does not
        # establish poison causation. The Venom Pill condition above is real.
        unqualified_source = next(a.source_definition_id for a in engine.action_catalog.values()
                                  if a.owner_id == H.FOE and a.display_name == 'Fu (Short Axe) attack')
    engine._apply_condition(actor, 'condition:typed.poisoned', unqualified_source, H.FOE,
                            expires_on='UNTIL_REMOVED', data={})
    unknown = next(c for c in actor.conditions.values() if c.source_definition_id == unqualified_source)
    events = _act(engine, ME, 'Pill of Restoration: End Poisoned')
    assert venom.instance_id not in actor.conditions
    assert unknown.instance_id in actor.conditions
    removed = H._payloads(events, 'CONDITION_REMOVED')
    assert [p['instance_id'] for p in removed if p['condition_id'] == 'condition:typed.poisoned'] == [venom.instance_id]
    assert any(e.event_type == 'GM_RIDER' and 'qualify remaining Poisoned' in str(e.payload) for e in events)


def test_restoration_qualifies_reloaded_venom_source_and_preserves_unknown_poison(tmp_path):
    from combat.canonical import canonical_sha256
    from combat.gate4_persistence import Gate4Persistence

    bundles = tuple(compile_character(H._sheet('tianxia.sphere.alchemy',
        [RESTORATION] if key == ME else ['TAL_ALCHEMY_POISON_PILL'], H.AXE_KIT, cl=10, dc=50),
        actor_id=key) for key in (ME, H.FOE))
    # Synthetic source fixture in the sealed bundle: a weapon action applies a
    # self condition with no poison-cause metadata. Every event is committed.
    weapon = next(a for a in bundles[0]['action_catalog'] if a['display_name'] == 'Fu (Short Axe) attack')
    weapon['parameters']['typed']['effects'] = [{'type':'condition', 'condition':'poisoned',
        'applies_to':'self', 'duration':'until_removed'}]
    persistence = Gate4Persistence(H.ROOT, tmp_path/'restoration-table')
    session = persistence.create_match(match_seed='a', typed_bundles=bundles,
        roster_setup={'primary_actor_ids':[ME,H.FOE], 'team_by_actor':{ME:'team:a',H.FOE:'team:b'}},
        genesis_setup={ME:{'placement':{'x':3,'y':6}}, H.FOE:{'placement':{'x':4,'y':6},
            'resources':{STOCK:4}}})
    while session.engine.state.current_actor_id != ME:
        c = next(c for c in session.engine.legal_candidates() if str(getattr(c.kind,'value',c.kind)) == 'END_TURN')
        session.submit_intent(H.ActionIntent(intent_id=f'restoration-wait-{session.engine.state.event_sequence}',
            decision_id=c.decision_id, candidate_id=c.candidate_id, state_version=c.state_version,
            actor_id=c.actor_id), primary_decision_record=None, reaction_provider=None)
    actor = session.engine.state.actors[ME]
    c = next(c for c in session.engine.legal_candidates() if c.display_name == 'Fu (Short Axe) attack')
    session.submit_intent(H.ActionIntent(intent_id='restoration-unknown-cause', decision_id=c.decision_id,
        candidate_id=c.candidate_id, state_version=c.state_version, actor_id=ME, target_ids=c.target_ids),
        primary_decision_record=None, reaction_provider=None)
    unknown = next(c.instance_id for c in actor.conditions.values() if c.condition_id == 'condition:typed.poisoned')
    # End turns normally, retaining the journaled unknown condition for the next
    # Action. This neither changes state out of band nor replaces the reducer.
    while session.engine.state.current_actor_id != ME or not actor.action_available:
        is_venom_turn = session.engine.state.current_actor_id == H.FOE and session.engine.state.actors[H.FOE].action_available
        if is_venom_turn:
            c = next(c for c in session.engine.legal_candidates()
                     if c.display_name == 'Poison Pill: Venom Pill' and ME in c.target_ids)
        else:
            c = next(c for c in session.engine.legal_candidates()
                     if str(getattr(c.kind,'value',c.kind)) == 'END_TURN')
        session.submit_intent(H.ActionIntent(intent_id=f'restoration-next-{session.engine.state.event_sequence}',
            decision_id=c.decision_id, candidate_id=c.candidate_id, state_version=c.state_version,
            actor_id=c.actor_id, target_ids=c.target_ids), primary_decision_record=None, reaction_provider=None)
    venom = next(c.instance_id for c in actor.conditions.values()
                 if c.condition_id == 'condition:typed.poisoned' and c.instance_id != unknown)
    session = persistence.load_match(session.engine.state.match_id)
    actor = session.engine.state.actors[ME]
    assert venom in actor.conditions and unknown in actor.conditions
    c = next(c for c in session.engine.legal_candidates() if c.display_name == 'Pill of Restoration: End Poisoned')
    session.submit_intent(H.ActionIntent(intent_id='restoration-consume', decision_id=c.decision_id,
        candidate_id=c.candidate_id, state_version=c.state_version, actor_id=ME, target_ids=c.target_ids),
        primary_decision_record=None, reaction_provider=None)
    assert unknown in actor.conditions
    assert venom not in actor.conditions
    reloaded = persistence.load_match(session.engine.state.match_id)
    assert canonical_sha256(session.engine.state.model_dump(mode='json')) == canonical_sha256(
        reloaded.engine.state.model_dump(mode='json'))
    assert unknown in reloaded.engine.state.actors[ME].conditions

BITTER = 'TAL_ALCHEMY_BITTER_DREGS'
DREG = 'resource:named.bitter_dreg'
STOCK = 'resource:named.reagent_stock'
INTENSIFY = 'tianxia.talent.alchemy.formula_intensification'


def _intensify_engine(*, dc=FAIL, cl=10, extra=False, talents=()):
    bundles = tuple(compile_character(H._sheet('tianxia.sphere.alchemy',
        [INTENSIFY, *talents] if actor_id == ME else [], H.AXE_KIT, dc=dc, cl=cl), actor_id=actor_id)
        for actor_id in ([ME, H.FOE, F2] if extra else [ME, H.FOE]))
    engine = Gate4ControllerEngine(H.ROOT, match_seed='a', typed_bundles=bundles,
        roster_setup={'primary_actor_ids': [b['actor_id'] for b in bundles],
            'team_by_actor': {ME:'team:a', H.FOE:'team:b', F2:'team:b'},
            'starting_positions': {ME:{'x':3,'y':6}, H.FOE:{'x':4,'y':6}, F2:{'x':4,'y':7}}})
    _begin_turn(engine, ME)
    engine._gain_resource(engine.state.actors[ME], STOCK, 4, 'test:prepared_reagents')
    return engine


def _intensify_name(option, formula='Field Formula: Numbing Smoke'):
    return f'{formula} + Formula Intensification: {option}'


@pytest.mark.parametrize('cl,count', [(10,2), (11,3), (17,4)])
def test_intensification_steps_only_damage_dice_and_pays_one_optional_choice(cl, count):
    engine = _intensify_engine(cl=cl)
    actor, foe = engine.state.actors[ME], engine.state.actors[H.FOE]
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and
        a.display_name == _intensify_name('Larger Damage Dice'))
    assert dict(action.costs) == {'resource:core.stamina':3, STOCK:1}
    assert action.range_ft == 60 and action.parameters['typed']['area']['size_ft'] == 5
    before = dict(actor.resources)
    events = _act(engine, ME, action.display_name, destination=foe.position)
    roll = H._payloads(events, 'DAMAGE_ROLLED')[0]
    assert roll['expression'] == f'{count}d8+3' and len(roll['dice']) == count
    assert actor.position == Position(x=3,y=6) and foe.position == Position(x=4,y=6)
    assert actor.resources['resource:core.stamina'] == before['resource:core.stamina'] - 3
    assert actor.resources[STOCK] == before[STOCK] - 1
    # Optional means the bare formula keeps its original dice, range and cost.
    plain = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.display_name == 'Field Formula: Numbing Smoke')
    assert plain.range_ft == 60 and dict(plain.costs) == {'resource:core.stamina':1, STOCK:1}
    medicine = next(a for a in engine.action_catalog.values() if a.owner_id == ME and
        a.display_name == _intensify_name('Larger Damage Dice', 'Field Formula: Medicinal Smoke'))
    assert medicine.parameters['typed']['effects'][0]['dice']['sides'] == 6
    assert all(a.display_name.count(' + Formula Intensification:') <= 1 for a in engine.action_catalog.values())


def test_intensification_d8_becomes_d10_in_a_real_learned_formula():
    engine = _intensify_engine(talents=['TAL_ALCHEMY_FURNACE_VENT'])
    foe = engine.state.actors[H.FOE]
    events = _act(engine, ME, _intensify_name('Larger Damage Dice', 'Furnace Vent'), destination=foe.position)
    rolls = H._payloads(events, 'DAMAGE_ROLLED')
    assert rolls and all('d10' in p['expression'] for p in rolls)


def test_intensification_range_adds_thirty_feet_without_other_options():
    engine = _intensify_engine()
    actor, foe = engine.state.actors[ME], engine.state.actors[H.FOE]
    foe.position = Position(x=18,y=6)  # 75 feet, beyond ordinary Field Formula.
    name = _intensify_name('Longer Range')
    assert not any(c.display_name.startswith('Field Formula: Numbing Smoke at ') and c.destination == foe.position
                   for c in engine.legal_candidates())
    events = _act(engine, ME, name, destination=foe.position)
    assert 'd6' in H._payloads(events, 'DAMAGE_ROLLED')[0]['expression']
    assert foe.current_hp < foe.maximum_hp and actor.position == Position(x=3,y=6)
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.display_name == name)
    assert action.range_ft == 90 and action.parameters['typed']['area']['size_ft'] == 5
    # The shared +30 range used to leak into every other menu option too.
    push = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.display_name == _intensify_name('Push Creature'))
    assert push.range_ft == 60


def test_intensification_area_grows_existing_radius_and_hits_the_added_ring():
    engine = _intensify_engine(extra=True)
    foe, second = engine.state.actors[H.FOE], engine.state.actors[F2]
    second.position = Position(x=6,y=6)  # 10 feet from the aim.
    events = _act(engine, ME, _intensify_name('Larger Area'), destination=foe.position)
    saves = [p['actor_id'] for p in H._payloads(events, 'SAVE_ROLLED')]
    assert H.FOE in saves and F2 in saves
    assert len(H._payloads(events, 'DAMAGE_ROLLED')) == 1
    plain = _intensify_engine(extra=True)
    plain.state.actors[F2].position = second.position
    _act(plain, ME, 'Field Formula: Numbing Smoke', destination=foe.position)
    assert plain.state.actors[F2].current_hp == plain.state.actors[F2].maximum_hp
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.display_name == _intensify_name('Larger Area'))
    assert action.range_ft == 60 and action.parameters['typed']['area']['size_ft'] == 10


@pytest.mark.parametrize('dc,override', [(FAIL,False), (PASS,False), (FAIL,True)])
def test_intensification_push_selects_one_final_failed_save_only(dc, override):
    from combat.gate2_runtime_models import ReactionDecision

    engine = _intensify_engine(dc=dc, extra=True)
    if override:
        engine._typed_roll_outcome = {H.FOE:'success', F2:'success'}
    requests = []
    def answer(request):
        if request['reaction_source_id'] == 'choice:needle.intensification_push':
            requests.append(request)
            return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=ME,
                reaction_source_id=request['reaction_source_id'], selection='USE', option_ids=(F2,)), None
        return None, None
    engine.set_reaction_provider(answer)
    actor, first, second = (engine.state.actors[key] for key in (ME,H.FOE,F2))
    start = (first.position, second.position)
    events = _act(engine, ME, _intensify_name('Push Creature'), destination=first.position)
    if dc == FAIL and not override:
        assert len(requests) == 1
        assert first.position == start[0] and second.position != start[1]
        assert engine.grid.distance_ft(start[1], second.position) == 10
        assert next(i for i,e in enumerate(events) if e.event_type == 'MOVEMENT_COMMITTED') > max(
            i for i,e in enumerate(events) if e.event_type == 'DAMAGE_COMMITTED')
    else:
        assert not requests and (first.position,second.position) == start
    assert actor.position == Position(x=3,y=6)


@pytest.mark.parametrize('decline', [False,True])
def test_intensification_step_resolves_after_formula_without_oa_or_budget_gain(decline):
    from combat.gate2_runtime_models import ReactionDecision

    engine = _intensify_engine()
    actor, foe = engine.state.actors[ME], engine.state.actors[H.FOE]
    before = actor.movement_remaining_ft
    requests = []
    def answer(request):
        if request['reaction_source_id'] == 'choice:needle.rider_step':
            requests.append(request)
            return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=ME,
                reaction_source_id=request['reaction_source_id'], selection='DECLINE' if decline else 'USE',
                option_ids=() if decline else ('cell:1,6',)), None
        return None, None
    engine.set_reaction_provider(answer)
    events = _act(engine, ME, _intensify_name('Move Self', 'Field Formula: Corrosive Dregs'), H.FOE)
    assert requests and 'Formula Intensification' in str(requests[0])
    assert actor.position == (Position(x=3,y=6) if decline else Position(x=1,y=6))
    assert actor.movement_remaining_ft == before
    assert not actor.turn_flags.get('disengaged') and foe.reaction_available
    assert not [e for e in events if e.actor_id == H.FOE and e.event_type == 'ATTACK_ROLLED']
    if not decline:
        assert next(i for i,e in enumerate(events) if e.event_type == 'MOVEMENT_COMMITTED') > max(
            i for i,e in enumerate(events) if e.event_type == 'DAMAGE_COMMITTED')


def test_intensification_is_unaffordable_without_the_extra_cp():
    engine = _intensify_engine()
    engine.state.actors[ME].resources['resource:core.stamina'] = 1
    actions = [a for a in engine.action_catalog.values() if a.owner_id == ME and 'Formula Intensification:' in a.display_name]
    assert actions and all(dict(a.costs)['resource:core.stamina'] >= 3 for a in actions)
    assert {_intensify_name(option) for option in ('Larger Damage Dice','Longer Range','Larger Area','Move Self','Push Creature')} <= {
        a.display_name for a in actions}
    assert not any('Formula Intensification' in c.display_name for c in engine.legal_candidates())
    assert any(c.display_name.startswith('Field Formula:') for c in engine.legal_candidates())


def test_intensification_step_also_suppresses_legacy_oa_and_restores_the_flag():
    from combat.gate2_runtime_models import ReactionDecision

    bundle = compile_character(H._sheet('tianxia.sphere.alchemy', [INTENSIFY], H.AXE_KIT, dc=FAIL), actor_id=ME)
    engine = H._engine(bundle)
    actor, foe = H._me(engine), H._foe(engine)
    engine._gain_resource(actor, STOCK, 1, 'test:prepared_reagent')
    foe.reaction_available = True
    def answer(request):
        if request['reaction_source_id'] == 'choice:needle.rider_step':
            return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=ME,
                reaction_source_id=request['reaction_source_id'], selection='USE', option_ids=('cell:1,6',)), None
        return None, None
    engine.set_reaction_provider(answer)
    events = H._use(engine, _intensify_name('Move Self', 'Field Formula: Corrosive Dregs'))
    assert actor.position == Position(x=1,y=6) and foe.reaction_available
    assert not actor.turn_flags.get('disengaged')
    assert not [e for e in events if e.actor_id == AN and e.event_type == 'ATTACK_ROLLED']
    assert not [e for e in events if e.event_type == 'REACTION_WINDOW_OPENED' and e.payload.get('checkpoint') == 'LEAVE_REACH']
    # A control using the same real movement resolver does provoke that OA.
    plain = H._engine(bundle)
    H._foe(plain).reaction_available = True
    events = _move_actor(plain, ME, Position(x=1,y=6))
    assert [e for e in events if e.event_type == 'REACTION_WINDOW_OPENED' and e.payload.get('checkpoint') == 'LEAVE_REACH']


@pytest.mark.parametrize('formula,shape,size', [('Furnace Vent','cone',20), ('Choking Smoke Pellet','sphere',15)])
def test_intensification_area_preserves_learned_shape_and_adds_five(formula, shape, size):
    talent = {'Furnace Vent':'TAL_ALCHEMY_FURNACE_VENT', 'Choking Smoke Pellet':'TAL_ALCHEMY_CHOKING_SMOKE_PELLET'}[formula]
    engine = _intensify_engine(talents=[talent])
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.display_name == _intensify_name('Larger Area', formula))
    area = action.parameters['typed']['area']
    assert area['shape'] == shape and area['size_ft'] == size
    events = _act(engine, ME, action.display_name, destination=engine.state.actors[H.FOE].position)
    assert H._payloads(events, 'SAVE_ROLLED')


def test_intensification_single_target_area_choice_does_not_invent_an_area():
    engine = _intensify_engine(extra=True, talents=['TAL_ALCHEMY_BINDING_DREGS'])
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.display_name == _intensify_name('Larger Area', 'Binding Dregs'))
    assert not action.parameters['typed'].get('area')
    events = _act(engine, ME, action.display_name, H.FOE)
    assert [p['actor_id'] for p in H._payloads(events,'SAVE_ROLLED')] == [H.FOE]


def test_intensification_dice_step_preserves_successful_save_half_and_shared_roll():
    engine = _intensify_engine(dc=PASS, extra=True)
    events = _act(engine, ME, _intensify_name('Larger Damage Dice'), destination=engine.state.actors[H.FOE].position)
    rolls = H._payloads(events, 'DAMAGE_ROLLED')
    assert len(rolls) == 1 and rolls[0]['expression'] == '2d8+3'
    assert all(engine.state.actors[key].current_hp == engine.state.actors[key].maximum_hp - rolls[0]['total']//2
               for key in (H.FOE,F2))


@pytest.mark.parametrize('option', ['Move Self', 'Push Creature'])
def test_intensification_table_commit_reload_keeps_resolved_movement_and_costs(tmp_path, option):
    from combat.canonical import canonical_sha256
    from combat.gate4_persistence import Gate4Persistence
    from combat.gate2_runtime_models import ReactionDecision

    bundles = tuple(compile_character(H._sheet('tianxia.sphere.alchemy',
        [INTENSIFY,'TAL_ALCHEMY_BINDING_DREGS'] if key == ME else [], H.AXE_KIT, dc=FAIL, cl=10), actor_id=key)
        for key in (ME,H.FOE))
    persistence = Gate4Persistence(H.ROOT, tmp_path/'intensification-table')
    session = persistence.create_match(match_seed='a', typed_bundles=bundles,
        roster_setup={'primary_actor_ids':[ME,H.FOE], 'team_by_actor':{ME:'team:a',H.FOE:'team:b'}},
        genesis_setup={ME:{'placement':{'x':3,'y':6}, 'resources':{STOCK:2}},
                       H.FOE:{'placement':{'x':4,'y':6}}})
    while session.engine.state.current_actor_id != ME:
        c = next(c for c in session.engine.legal_candidates() if str(getattr(c.kind,'value',c.kind)) == 'END_TURN')
        session.submit_intent(H.ActionIntent(intent_id=f'intensify-wait-{session.engine.state.event_sequence}',
            decision_id=c.decision_id, candidate_id=c.candidate_id, state_version=c.state_version,
            actor_id=c.actor_id, target_ids=c.target_ids, destination=c.destination),
            primary_decision_record=None, reaction_provider=None)
    before_cp = session.engine.state.actors[ME].resources['resource:core.stamina']
    before_move = session.engine.state.actors[ME].movement_remaining_ft
    requests = []
    def answer(request):
        choice = request['reaction_source_id']
        if choice in ('choice:needle.rider_step', 'choice:needle.intensification_push'):
            requests.append(request)
            return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=ME,
                reaction_source_id=choice, selection='USE',
                option_ids=('cell:1,6',) if choice.endswith('rider_step') else (H.FOE,)), None
        return None, None
    c = next(c for c in session.engine.legal_candidates() if c.display_name == _intensify_name(option,'Binding Dregs')
             and H.FOE in c.target_ids)
    session.submit_intent(H.ActionIntent(intent_id='intensify-use', decision_id=c.decision_id,
        candidate_id=c.candidate_id, state_version=c.state_version, actor_id=c.actor_id,
        target_ids=c.target_ids, destination=c.destination), primary_decision_record=None, reaction_provider=answer)
    before = canonical_sha256(session.engine.state.model_dump(mode='json'))
    session = persistence.load_match(session.match_id)
    assert canonical_sha256(session.engine.state.model_dump(mode='json')) == before
    actor, foe = session.engine.state.actors[ME], session.engine.state.actors[H.FOE]
    assert requests and actor.resources[STOCK] == 1 and actor.resources['resource:core.stamina'] == before_cp - 3
    assert actor.movement_remaining_ft == before_move and not actor.turn_flags.get('disengaged')
    assert actor.position == (Position(x=1,y=6) if option == 'Move Self' else Position(x=3,y=6))
    assert foe.position == (Position(x=4,y=6) if option == 'Move Self' else Position(x=6,y=6))


@pytest.mark.parametrize('hit', [True,False])
def test_intensification_attack_vocabulary_push_waits_for_hit_and_only_moves_one(hit):
    """Synthetic attack on a real compiled/costed recipe, not a new printed formula.

    Current printed recipes use saves. This qualifies the existing attack hook
    for the owner's explicit hit alternative without inventing an attack recipe.
    """
    engine = _intensify_engine(talents=['TAL_ALCHEMY_BINDING_DREGS'])
    foe = engine.state.actors[H.FOE]
    foe.armor_class = -50 if hit else 1000
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.display_name == _intensify_name('Push Creature','Binding Dregs'))
    marker = next(row for row in action.parameters['typed']['effects'] if row.get('type') == 'formula_intensification')
    typed = {**action.parameters['typed'], 'effects': [
        {'type':'attack', 'kind':'cultivation_ranged', 'count':1,
         'on_hit':[{'type':'damage','dice':{'count':1,'sides':6},'damage_types':['poison']}]}, marker]}
    engine.action_catalog[action.source_definition_id] = action.model_copy(update={'parameters':{**action.parameters,'typed':typed}})
    events = _act(engine, ME, action.display_name, H.FOE)
    assert H._payloads(events,'ATTACK_ROLLED')
    assert foe.position == (Position(x=6,y=6) if hit else Position(x=4,y=6))
    assert bool([e for e in events if e.event_type == 'MOVEMENT_COMMITTED']) == hit


def _bitter_arena(*, dc=FAIL, extra=False, court=False):
    bundles = tuple(compile_character(H._sheet('tianxia.sphere.alchemy',
        [BITTER, 'TAL_ALCHEMY_BINDING_DREGS', *([CAULDRON] if court else [])] if actor_id == ME else [], H.AXE_KIT, dc=dc, cl=10),
        actor_id=actor_id) for actor_id in ([ME, H.FOE, F2] if extra else [ME, H.FOE]))
    engine = Gate4ControllerEngine(H.ROOT, match_seed='a', typed_bundles=bundles,
        roster_setup={'primary_actor_ids': [b['actor_id'] for b in bundles],
            'team_by_actor': {ME:'team:a', H.FOE:'team:b', F2:'team:b'},
            'starting_positions': {ME:{'x':3,'y':6}, H.FOE:{'x':4,'y':6}, F2:{'x':4,'y':7}}})
    _begin_turn(engine, ME)
    # Prepared inventory is declared, not created by a combat/downtime action.
    engine._gain_resource(engine.state.actors[ME], DREG, 2, 'test:prepared_dregs')
    # Its prepared Reagent Stock is used up (rider lane C10: a fight starts with the Long Rest's prepared uses), so the Dregs
    # variant is shown to need no Reagent Stock.
    engine._spend_resource(engine.state.actors[ME], STOCK, engine.state.actors[ME].resources[STOCK], 'test:stock_used_up')
    return engine


def test_bitter_dregs_substitutes_stock_at_affordability_and_adds_pb_to_one_roll():
    engine = _bitter_arena()
    actor, foe = engine.state.actors[ME], engine.state.actors[H.FOE]
    assert actor.resources[STOCK] == 0
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and
        a.display_name == 'Field Formula: Numbing Smoke + Bitter Dregs')
    assert dict(action.costs) == {'resource:core.stamina':1, DREG:1}
    before = dict(actor.resources)
    events = _act(engine, ME, action.display_name, destination=foe.position)
    damage = H._payloads(events, 'DAMAGE_ROLLED')
    assert len(damage) == 1 and damage[0]['modifier'] == 3 + 4
    assert foe.current_hp == foe.maximum_hp - damage[0]['total']
    assert actor.current_hp == actor.maximum_hp
    assert actor.resources[DREG] == before[DREG] - 1 and actor.resources[STOCK] == 0
    assert actor.resources['resource:core.stamina'] == before['resource:core.stamina'] - 1
    # No Dregs: owning the talent does not make its variant free or give a bonus.
    actor.resources[DREG] = 0
    actor.action_available = True
    assert not any('Bitter Dregs' in c.display_name for c in engine.legal_candidates())
    engine._gain_resource(actor, STOCK, 1, 'test:prepared_reagent')
    events = _act(engine, ME, 'Field Formula: Numbing Smoke', destination=foe.position)
    assert H._payloads(events, 'DAMAGE_ROLLED')[0]['modifier'] == 3


@pytest.mark.parametrize('mixed', [False, True])
def test_bitter_dregs_area_shares_bonus_and_backlashes_only_when_all_final_saves_succeed(mixed):
    engine = _bitter_arena(extra=True, dc=PASS)
    first, second = engine.state.actors[H.FOE], engine.state.actors[F2]
    if mixed:
        second.saving_throws['CON'] = -100
    events = _act(engine, ME, 'Field Formula: Numbing Smoke + Bitter Dregs', destination=first.position)
    saves = H._payloads(events, 'SAVE_ROLLED')
    assert len(saves) == 2 and sum(not s['success'] for s in saves) == int(mixed)
    rolled = H._payloads(events, 'DAMAGE_ROLLED')
    # Both targets use the same 2d6+key_mod+PB roll, including successful halves.
    assert len(rolled) == 1 and rolled[0]['modifier'] == 7
    assert first.current_hp == first.maximum_hp - rolled[0]['total'] // 2
    assert second.current_hp == second.maximum_hp - (rolled[0]['total'] if mixed else rolled[0]['total'] // 2)
    backlash = [e for e in events if e.event_type == 'DAMAGE_COMMITTED' and ME in e.target_ids]
    assert len(backlash) == int(not mixed)
    if backlash:
        assert backlash[0].payload['damage_type'] == 'POISON'
        assert backlash[0].payload['hp_damage'] == 4  # its own bonus never buffs backlash
    assert engine.state.actors[ME].current_hp == 80 - (0 if mixed else 4)


def test_bitter_dregs_uses_final_success_override_for_backlash():
    engine = _bitter_arena()
    engine._typed_roll_outcome = {H.FOE:'success'}
    events = _act(engine, ME, 'Binding Dregs + Bitter Dregs', H.FOE)
    assert engine.state.actors[ME].current_hp == 76
    assert engine.state.actors[ME].resources[DREG] == 1
    assert [e.payload['hp_damage'] for e in events if e.event_type == 'DAMAGE_COMMITTED'] == [4]


def test_bitter_dregs_bonus_belongs_to_formula_roll_and_not_court_extra_damage():
    engine = _bitter_arena(court=True)
    _act(engine, ME, 'Court of the Three-Legged Cauldron')
    foe = engine.state.actors[H.FOE]
    events = _act(engine, ME, 'Field Formula: Numbing Smoke + Bitter Dregs', destination=foe.position)
    assert H._payloads(events, 'DAMAGE_ROLLED')[0]['modifier'] == 7
    assert [e.payload['rolled_or_pending_damage'] for e in events if e.event_type == 'DAMAGE_COMMITTED'][0] == 3


def test_bitter_dregs_empty_area_and_medicine_do_not_trigger_all_success_backlash():
    from combat import ext

    engine = _bitter_arena()
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and
        a.display_name == 'Field Formula: Numbing Smoke + Bitter Dregs')
    # The candidate menu omits empty areas. Qualify the interpreter boundary
    # directly for a target list that became empty before effects resolve.
    ctx = typed_executor.Context(engine, engine.state.actors[ME], action, None, action.parameters['typed'], [], None)
    typed_executor.run_effects(ctx, action.parameters['typed']['effects'])
    engine._run_final_riders('technique_final', ctx)
    assert engine.state.actors[ME].current_hp == 80
    events = _act(engine, ME, 'Field Formula: Medicinal Smoke + Bitter Dregs', ME)
    assert engine.state.actors[ME].current_hp == 80
    assert not [e for e in events if e.event_type == 'DAMAGE_COMMITTED']
    assert H._payloads(events, 'DAMAGE_ROLLED')[0]['modifier'] == 3  # TEMP_HP is not damage


@pytest.mark.parametrize('hit', [False, True])
def test_bitter_dregs_attack_vocabulary_fixture_has_once_roll_bonus_or_poison_backlash(hit):
    """Qualify the printed attack clause using a synthetic attack vocabulary fixture.

    Current printed Field Formula recipes use saves; this does not introduce
    or claim an attack-based recipe. Ownership, variant costs, and the character
    are really compiled; only this engine-seam fixture's resolution is replaced.
    """
    import copy

    engine = _bitter_arena()
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and
        a.display_name == 'Binding Dregs + Bitter Dregs')
    parameters = copy.deepcopy(action.parameters)
    parameters['typed']['effects'] = [{'type':'attack', 'count':2, 'on_hit':[
        {'type':'damage', 'dice':{'count':1,'sides':6}, 'formula':'key_ability_modifier', 'damage_types':['poison']}]}]
    engine.action_catalog[action.source_definition_id] = action.model_copy(update={'parameters':parameters})
    engine.state.actors[H.FOE].armor_class = -50 if hit else 100
    events = _act(engine, ME, action.display_name, H.FOE)
    assert len(H._payloads(events, 'ATTACK_ROLLED')) == 2
    if hit:
        assert [r['modifier'] for r in H._payloads(events, 'DAMAGE_ROLLED')] == [7,3]
        assert engine.state.actors[ME].current_hp == 80
    else:
        assert engine.state.actors[ME].current_hp == 76
        assert [e.payload['hp_damage'] for e in events if e.event_type == 'DAMAGE_COMMITTED'] == [4]


def test_bitter_dregs_prepared_stock_and_resolved_backlash_survive_table_commit_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence
    from combat.canonical import canonical_sha256

    bundles = tuple(compile_character(H._sheet('tianxia.sphere.alchemy',
        [BITTER, 'TAL_ALCHEMY_BINDING_DREGS'] if actor_id == ME else [], H.AXE_KIT, dc=PASS, cl=10),
        actor_id=actor_id) for actor_id in (ME,H.FOE))
    persistence = Gate4Persistence(H.ROOT, tmp_path/'bitter-table')
    session = persistence.create_match(match_seed='a', typed_bundles=bundles,
        roster_setup={'primary_actor_ids':[ME,H.FOE], 'team_by_actor':{ME:'team:a',H.FOE:'team:b'}},
        genesis_setup={ME:{'placement':{'x':3,'y':6}, 'resources':{DREG:2,STOCK:0}},
                       H.FOE:{'placement':{'x':4,'y':6}}})
    while session.engine.state.current_actor_id != ME:
        c = next(c for c in session.engine.legal_candidates() if str(getattr(c.kind,'value',c.kind)) == 'END_TURN')
        session.submit_intent(H.ActionIntent(intent_id=f'bitter-wait-{session.engine.state.event_sequence}',
            decision_id=c.decision_id, candidate_id=c.candidate_id, state_version=c.state_version,
            actor_id=c.actor_id, target_ids=c.target_ids, destination=c.destination),
            primary_decision_record=None, reaction_provider=None)
    c = next(c for c in session.engine.legal_candidates() if c.display_name == 'Binding Dregs + Bitter Dregs' and H.FOE in c.target_ids)
    session.submit_intent(H.ActionIntent(intent_id='bitter-use', decision_id=c.decision_id,
        candidate_id=c.candidate_id, state_version=c.state_version, actor_id=c.actor_id,
        target_ids=c.target_ids, destination=c.destination), primary_decision_record=None, reaction_provider=None)
    before = canonical_sha256(session.engine.state.model_dump(mode='json'))
    session = persistence.load_match(session.match_id)
    assert canonical_sha256(session.engine.state.model_dump(mode='json')) == before
    actor = session.engine.state.actors[ME]
    assert actor.resources[DREG] == 1 and actor.resources[STOCK] == 0 and actor.current_hp == 76
    assert not any('bitter' in c.condition_id for c in actor.conditions.values())


def _cauldron(*, dc=FAIL, damage_type='force'):
    from combat.gate2_runtime_models import ReactionDecision

    engine = _alchemy_arena([CAULDRON, 'TAL_ALCHEMY_BINDING_DREGS'], dc=dc)
    seen = []

    def answer(request):
        if request['reaction_source_id'] != 'choice:needle.cauldron_damage':
            return None, None
        seen.append(request)
        return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=request['reactor_id'],
            reaction_source_id=request['reaction_source_id'], selection='USE', option_ids=(damage_type,)), None

    engine.set_reaction_provider(answer)
    _act(engine, ME, 'Court of the Three-Legged Cauldron')
    assert 'typed.alchemy_court_damage' in _conds(H._me(engine))
    return engine, seen


@pytest.mark.parametrize('damage_type', ['acid', 'fire', 'poison', 'force'])
def test_cauldron_failed_save_chooses_printed_damage_once_per_creature_per_turn(damage_type):
    engine, seen = _cauldron(damage_type=damage_type)
    foe = engine.state.actors[H.FOE]
    before = foe.current_hp
    events = _act(engine, ME, 'Binding Dregs', H.FOE)
    amount = _conds(H._me(engine))['typed.alchemy_court_damage'].data['amount']
    assert amount > 0 and foe.current_hp == before - amount
    assert H._payloads(events, 'DAMAGE_COMMITTED')[0]['damage_type'] == damage_type.upper()
    assert len(seen) == 1 and seen[0]['reactor_id'] == ME
    assert 'Binding Dregs' in str(seen[0]) and foe.display_name in str(seen[0])
    _act(engine, ME, 'Binding Dregs', H.FOE)
    assert foe.current_hp == before - amount and len(seen) == 1
    engine._expire_for_checkpoint('END_OF_TURN', ME)
    _begin_turn(engine, H.FOE)
    # The caster can trigger this on another actor's turn; the marker expires
    # with that actual turn, not with the caster's next turn.
    engine.state.current_actor_id = H.FOE
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.display_name == 'Binding Dregs')
    candidate = engine.legal_candidates()[0]
    off_turn_intent = H.ActionIntent(intent_id='court-off-turn', decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version,
        actor_id=H.FOE, target_ids=candidate.target_ids, destination=candidate.destination)
    ctx = typed_executor.Context(engine, H._me(engine), action, off_turn_intent, action.parameters['typed'], [foe], foe, {})
    typed_executor.run_effects(ctx, action.parameters['typed']['effects'])
    assert foe.current_hp == before - 2 * amount
    assert len(seen) == 2 and seen[-1]['reactor_id'] == ME
    engine._expire_for_checkpoint('END_OF_TURN', H.FOE)
    assert not any('alchemy_court_spent' in c.condition_id for c in foe.conditions.values())


def test_cauldron_damage_requires_final_failure_hostile_inside_and_active_domain():
    engine, seen = _cauldron(dc=PASS)
    foe = engine.state.actors[H.FOE]
    before = foe.current_hp
    _act(engine, ME, 'Binding Dregs', H.FOE)
    assert foe.current_hp == before and not seen
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.display_name == 'Binding Dregs')
    action.parameters['typed']['numbers']['save_dc'] = FAIL
    engine._typed_roll_outcome = {H.FOE: 'success'}
    _act(engine, ME, 'Binding Dregs', H.FOE)
    assert foe.current_hp == before and not seen
    foe.team_id = H._me(engine).team_id
    ctx = typed_executor.Context(engine, H._me(engine), action, None, action.parameters['typed'], [foe], foe, {})
    typed_executor.run_effects(ctx, action.parameters['typed']['effects'])
    assert foe.current_hp == before
    foe.team_id = 'team:b'
    foe.position = Position(x=15, y=6)
    typed_executor.run_effects(ctx, action.parameters['typed']['effects'])
    assert foe.current_hp == before
    foe.position = Position(x=4, y=6)
    engine.state.round_number += 10
    _begin_turn(engine, ME)
    assert 'typed.alchemy_court_damage' not in _conds(H._me(engine))
    _act(engine, ME, 'Binding Dregs', H.FOE)
    assert foe.current_hp == before and not seen


def test_cauldron_damage_gates_each_creature_independently_and_ignores_other_spheres():
    engine, _ = _cauldron()
    foe = engine.state.actors[H.FOE]
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.display_name == 'Binding Dregs')
    ctx = typed_executor.Context(engine, H._me(engine), action, None, action.parameters['typed'], [foe], foe, {})
    before = foe.current_hp
    # An actual non-Alchemy save row using the same hostile/geometry must not
    # gain the Domain rider; source is the real printed Beauty mechanic.
    from dataclasses import replace
    other = replace(ctx, typed={**ctx.typed, 'source': 'tianxia.talent.beauty.tears_like_pearls'})
    typed_executor.run_effects(other, action.parameters['typed']['effects'])
    assert foe.current_hp == before
    # A second real compiled creature in the same domain has its own allowance.
    bundle = compile_character(H._sheet('tianxia.sphere.alchemy', [], H.AXE_KIT, cl=10), actor_id=F2)
    second = Gate4ControllerEngine(H.ROOT, match_seed='a', typed_bundles=(bundle,),
        roster_setup={'primary_actor_ids': [F2, AN]}).state.actors[F2]
    second.team_id, second.position = 'team:b', Position(x=4, y=7)
    engine.state.actors[F2] = second
    for target in (foe, second, foe, second):
        typed_executor.run_effects(replace(ctx, targets=[target], target=target), action.parameters['typed']['effects'])
    amount = _conds(H._me(engine))['typed.alchemy_court_damage'].data['amount']
    assert foe.current_hp == before - amount
    assert second.current_hp == second.maximum_hp - amount


def test_cauldron_domain_and_per_creature_use_survive_table_commit_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence
    from combat.canonical import canonical_sha256

    bundles = tuple(compile_character(H._sheet('tianxia.sphere.alchemy',
        [CAULDRON, 'TAL_ALCHEMY_BINDING_DREGS'] if actor_id == ME else [], H.AXE_KIT, dc=FAIL, cl=10),
        actor_id=actor_id) for actor_id in (ME, H.FOE))
    persistence = Gate4Persistence(H.ROOT, tmp_path / 'court-table')
    session = persistence.create_match(match_seed='a', typed_bundles=bundles,
        roster_setup={'primary_actor_ids': [ME, H.FOE], 'team_by_actor': {ME:'team:a', H.FOE:'team:b'}},
        genesis_setup={ME: {'placement': {'x':3, 'y':6}, 'resources': {'resource:named.reagent_stock':4}},
                       H.FOE: {'placement': {'x':4, 'y':6}}})

    def commit(name=None):
        engine = session.engine
        candidate = next(c for c in engine.legal_candidates() if
            (c.display_name == name if name else str(getattr(c.kind, 'value', c.kind)) == 'END_TURN'))
        session.submit_intent(H.ActionIntent(intent_id=f'court-{engine.state.event_sequence}',
            decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
            state_version=candidate.state_version, actor_id=candidate.actor_id,
            target_ids=candidate.target_ids, destination=candidate.destination),
            primary_decision_record=None, reaction_provider=None)

    while session.engine.state.current_actor_id != ME:
        commit()
    commit('Court of the Three-Legged Cauldron')
    commit('Binding Dregs')
    before = canonical_sha256(session.engine.state.model_dump(mode='json'))
    session = persistence.load_match(session.match_id)
    assert canonical_sha256(session.engine.state.model_dump(mode='json')) == before
    assert 'typed.alchemy_court_damage' in _conds(session.engine.state.actors[ME])
    assert any('alchemy_court_spent' in c.condition_id for c in session.engine.state.actors[H.FOE].conditions.values())
    commit()
    session = persistence.load_match(session.match_id)
    assert not any('alchemy_court_spent' in c.condition_id for c in session.engine.state.actors[H.FOE].conditions.values())


def test_alchemy_choking_smoke_denies_voiced_abilities_until_the_casters_next_start():
    engine = _alchemy_arena(['TAL_ALCHEMY_CHOKING_SMOKE_PELLET'], foe_talents=[
        'tianxia.path.body_refining.feature.iron_voice'])
    engine.state.current_actor_id = H.FOE
    assert 'Iron Voice' in H._legal(engine)
    _act(engine, ME, 'Choking Smoke Pellet', destination=engine.state.actors[H.FOE].position)
    engine.state.current_actor_id = H.FOE
    assert 'typed.silenced' in _conds(engine.state.actors[H.FOE])
    assert 'Iron Voice' not in H._legal(engine)
    assert 'Fu (Short Axe) attack' in H._legal(engine)
    _begin_turn(engine, ME)
    engine.state.current_actor_id = H.FOE
    assert 'Iron Voice' in H._legal(engine)


@pytest.mark.parametrize('dc,saved', [(FAIL,False),(PASS,True)])
def test_alchemy_meridian_sealing_blocks_a_real_typed_cp_recovery_until_the_printed_turn(dc, saved):
    engine = _alchemy_arena(['TAL_ALCHEMY_MERIDIAN_SEALING_PILL'], dc=dc,
                           foe_talents=['TAL_ALCHEMY_QI_INFUSION_PILL'])
    foe = engine.state.actors[H.FOE]
    _act(engine, ME, 'Meridian-Sealing Pill', H.FOE)
    resource = 'resource:core.stamina'
    foe.resources[resource] = 10
    _act(engine, H.FOE, 'Qi Infusion Pill')
    assert foe.resources[resource] == 10
    assert 'typed.no_cp_regain' in _conds(foe)
    _begin_turn(engine, H.FOE)
    assert ('typed.no_cp_regain' not in _conds(foe)) == saved
    if not saved:
        candidate = next(c for c in engine.legal_candidates() if str(getattr(c.kind,'value',c.kind)) == 'END_TURN')
        engine.execute_intent(H.ActionIntent(intent_id='end-sealed-turn', actor_id=H.FOE,
            decision_id=candidate.decision_id,candidate_id=candidate.candidate_id,state_version=candidate.state_version))
        assert 'typed.no_cp_regain' not in _conds(foe)


def test_alchemy_nerve_pill_denies_bonus_actions_without_denying_normal_actions():
    engine = _alchemy_arena(['TAL_ALCHEMY_POISON_PILL'],foe_talents=[
        'tianxia.path.body_refining.feature.iron_voice'])
    _act(engine, ME, 'Poison Pill: Nerve Pill', H.FOE)
    engine.state.current_actor_id = H.FOE
    assert 'Iron Voice' not in H._legal(engine)
    assert 'Fu (Short Axe) attack' in H._legal(engine)
    assert not engine.state.actors[H.FOE].reaction_available
    _begin_turn(engine, ME)
    engine.state.current_actor_id = H.FOE
    assert 'Iron Voice' in H._legal(engine)


def test_alchemy_rotting_pill_blocks_a_real_healing_pill():
    engine = _alchemy_arena(['TAL_ALCHEMY_POISON_PILL'],foe_talents=['TAL_ALCHEMY_HEALING_PILL'])
    _act(engine, ME, 'Poison Pill: Rotting Pill', H.FOE)
    foe = engine.state.actors[H.FOE]
    hp = foe.current_hp
    assert hp < foe.maximum_hp
    _act(engine, H.FOE, 'Healing Pill')
    assert foe.current_hp == hp
    assert any(m.target_field == 'healing_reduction' and m.value == 'none' for m in foe.modifiers.values())


def test_alchemy_pill_devouring_increases_only_field_formula_save_dcs_and_expires():
    engine = _alchemy_arena(['tianxia.talent.alchemy.pill_devouring','TAL_ALCHEMY_BACKDRAFT_FUMES'],dc=50,cl=15)
    _act(engine, ME, 'Pill Devouring')
    def formula_dc():
        events = _act(engine, ME, 'Field Formula: Numbing Smoke',destination=engine.state.actors[H.FOE].position)
        return H._payloads(events,'SAVE_ROLLED')[0]['dc']
    assert formula_dc() == 52
    # Only the formula's DC changes, not the character's compiled save-DC number.
    assert all((a.parameters.get('typed') or {}).get('numbers',{}).get('save_dc') == 50 for a in
               engine.action_catalog.values() if a.owner_id == ME and a.display_name.startswith('Field Formula:'))
    H._me(engine).armor_class = -50
    events = _strike(engine, H.FOE, ME)
    assert [e.payload['dc'] for e in events if e.event_type == 'SAVE_ROLLED'
            and e.source_definition_id == 'TAL_ALCHEMY_BACKDRAFT_FUMES'] == [50]
    engine.state.round_number += 10
    _begin_turn(engine, ME)
    assert formula_dc() == 50

F1, F2, F3 = "actor:factory.foe1", "actor:factory.foe2", "actor:factory.foe3"


def _returning_smoke(option, *, decline=False):
    from combat.gate2_runtime_models import ReactionDecision

    bundles = [compile_character(H._sheet('tianxia.sphere.alchemy',
        ['TAL_ALCHEMY_SMOKE_OF_RETURNING_BREATH'] if actor_id == ME else [], H.AXE_KIT, cl=10, dc=50),
        actor_id=actor_id) for actor_id in (ME, ALLY, H.FOE)]
    engine = Gate4ControllerEngine(H.ROOT, match_seed='a', typed_bundles=tuple(bundles), roster_setup={
        'primary_actor_ids':[ME,ALLY,H.FOE], 'team_by_actor':{ME:'team:a',ALLY:'team:a',H.FOE:'team:b'},
        'starting_positions':{ME:{'x':3,'y':6},ALLY:{'x':3,'y':7},H.FOE:{'x':4,'y':6}}})
    _begin_turn(engine, ME)
    engine._gain_resource(H._me(engine), 'resource:named.reagent_stock', 4, 'test:prepared_reagents')
    engine._gain_resource(engine.state.actors[H.FOE], 'resource:named.reagent_stock', 4, 'test:prepared_reagents')
    seen = []

    def answer(request):
        if request['reaction_source_id'] != 'choice:needle.returning_breath':
            return None, None
        seen.append(request)
        return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=request['reactor_id'],
            reaction_source_id=request['reaction_source_id'], selection='DECLINE' if decline else 'USE',
            option_ids=() if decline else (option,)), None

    engine.set_reaction_provider(answer)
    return engine, seen


@pytest.mark.parametrize('option,condition', [('end_deafened','deafened'),('stand','prone')])
def test_returning_breath_beneficiary_chooses_one_condition_end_without_movement_cost(option, condition):
    engine, seen = _returning_smoke(option)
    ally = engine.state.actors[ALLY]
    for name in ('deafened','prone'):
        engine._apply_condition(ally, 'condition:typed.' + name, 'test:ailment', H.FOE,
                                expires_on='UNTIL_REMOVED', data={})
    movement = ally.movement_remaining_ft
    _act(engine, ME, 'Field Formula: Medicinal Smoke', ALLY)
    assert seen and seen[0]['reactor_id'] == ALLY
    assert seen[0]['extension_choice']['maximum_selections'] == 1
    assert 'typed.' + condition not in _conds(ally)
    assert 'typed.' + ('prone' if condition == 'deafened' else 'deafened') in _conds(ally)
    assert 'typed.save_against' not in _conds(ally)
    assert ally.movement_remaining_ft == movement
    assert ally.temporary_hp > 0


def test_returning_breath_chosen_con_advantage_is_consumed_by_the_next_actual_con_save():
    engine, seen = _returning_smoke('next_con_save')
    ally = engine.state.actors[ALLY]
    _act(engine, ME, 'Field Formula: Medicinal Smoke', ALLY)
    assert seen and seen[0]['reactor_id'] == ALLY
    assert 'typed.save_against' in _conds(ally)
    _act(engine, H.FOE, 'Field Formula: Numbing Smoke', destination=ally.position)
    rolls = [e.payload for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == ALLY]
    assert rolls[-1]['mode'] == 'ADVANTAGE'
    assert 'typed.save_against' not in _conds(ally)
    _act(engine, H.FOE, 'Field Formula: Numbing Smoke', destination=ally.position)
    rolls = [e.payload for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == ALLY]
    assert rolls[-1]['mode'] == 'NORMAL'


def test_returning_breath_con_advantage_expires_at_the_casters_start_not_the_beneficiarys():
    engine, seen = _returning_smoke('next_con_save')
    _act(engine, ME, 'Field Formula: Medicinal Smoke', ALLY)
    assert seen
    _begin_turn(engine, ALLY)
    assert 'typed.save_against' in _conds(engine.state.actors[ALLY])
    _begin_turn(engine, ME)
    assert 'typed.save_against' not in _conds(engine.state.actors[ALLY])


def test_returning_breath_can_be_declined_without_losing_medicinal_smokes_core():
    engine, seen = _returning_smoke('next_con_save', decline=True)
    _act(engine, ME, 'Field Formula: Medicinal Smoke', ALLY)
    assert seen
    ally = engine.state.actors[ALLY]
    assert 'typed.save_against' not in _conds(ally)
    assert ally.temporary_hp > 0


def test_returning_breath_does_not_end_blindness_without_its_printed_causal_qualification():
    engine, seen = _returning_smoke('end_blinded')
    ally = engine.state.actors[ALLY]
    engine._apply_condition(ally, 'condition:typed.blinded', 'test:unknown_cause', H.FOE,
                            expires_on='UNTIL_REMOVED', data={})
    events = _act(engine, ME, 'Field Formula: Medicinal Smoke', ALLY)
    assert seen
    assert 'typed.blinded' in _conds(ally)
    assert 'typed.save_against' not in _conds(ally)
    assert any(e.event_type == 'GM_RIDER' and 'alchemical irritation' in str(e.payload) for e in events)

MANDATE = "Fu (Short Axe) attack: Headsman's Mandate"


def _three_foes(talents, positions, *, dc=16):
    me = _axes(talents, dc=dc)
    foes = [compile_character(H._sheet(None, [], H.AXE_KIT), actor_id=a) for a in (F1, F2, F3)]
    engine = Gate4ControllerEngine(H.ROOT, match_seed="R3", typed_bundles=(me, *foes), roster_setup={
        "primary_actor_ids": [ME, F1, F2, F3], "team_by_actor": {ME: "team:a", F1: "team:b", F2: "team:b", F3: "team:b"},
        "starting_positions": {a: {"x": x, "y": y} for a, (x, y) in zip((ME, F1, F2, F3), positions)}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    for actor_id in (F1, F2, F3):
        engine.state.actors[actor_id].armor_class = -50
    H._ready(engine)
    return engine


def test_headsmans_mandate_frightens_the_hostiles_that_saw_the_target_fall():
    """"If this attack reduces the target to 0 HP, hostile creatures of your choice within 30 feet that saw the blow must
    succeed on a Wisdom saving throw or be Frightened of you until the end of your next turn": a GM line.  The near foe rolls
    and is Frightened; the one 80 feet away is not asked; nothing is asked when the target survives."""
    talents = ["TAL_AXES_HEADSMAN_S_MANDATE"]
    engine = _three_foes(talents, [(3, 6), (4, 6), (4, 9), (19, 6)], dc=FAIL)
    engine.state.actors[F1].current_hp = 5
    events = H._use(engine, MANDATE, F1)
    assert not engine.state.actors[F1].active
    assert [p["actor_id"] for p in H._payloads(events, "SAVE_ROLLED")] == [F2]
    assert "typed.frightened" in _conds(engine.state.actors[F2]) and "typed.frightened" not in _conds(engine.state.actors[F3])

    survivor = _three_foes(talents, [(3, 6), (4, 6), (4, 9), (19, 6)], dc=FAIL)
    events = H._use(survivor, MANDATE, F1)
    assert survivor.state.actors[F1].active
    assert F2 not in [p["actor_id"] for p in H._payloads(events, "SAVE_ROLLED")]
    assert "typed.frightened" not in _conds(survivor.state.actors[F2])


def test_headsmans_mandate_stops_the_target_teleporting_until_its_next_turn_ends():
    """"Failed Save: ... cannot teleport": a GM line.  The target holds ``deny_teleport`` and its own teleport does nothing."""
    engine, _ = H._axes_cast(["TAL_AXES_HEADSMAN_S_MANDATE"], MANDATE, dc=FAIL)
    foe = H._foe(engine)
    assert "typed.deny_teleport" in _conds(foe)
    action = engine.action_catalog[next(a for a in H._me(engine).action_ids if "HEWING" in a.upper() or "Hewing" in a)]
    ctx = typed_executor.Context(engine, foe, action, None, action.parameters["typed"], [foe], foe, {})
    start = foe.position
    typed_executor._teleport(ctx, Position(x=start.x + 3, y=start.y))
    assert foe.position == start

    saved, _ = H._axes_cast(["TAL_AXES_HEADSMAN_S_MANDATE"], MANDATE, dc=PASS)
    free = H._foe(saved)
    assert "typed.deny_teleport" not in _conds(free)
    ctx = typed_executor.Context(saved, free, action, None, action.parameters["typed"], [free], free, {})
    start = free.position
    typed_executor._teleport(ctx, Position(x=start.x + 3, y=start.y))
    assert free.position == Position(x=start.x + 3, y=start.y)  # a foe that saved teleports as it likes


# ------------------------------------------------------------------------------------------------ Axes, second half


def _grow(engine, actor_id=AN, cells=2):
    """Make a creature ``cells`` cells wide (Large = 2, Huge = 3)."""
    engine.actor_footprints[actor_id] = engine._footprint(actor_id).model_copy(update={
        "width_cells": cells, "height_cells": cells,
        "occupied_relative_cells": tuple(Position(x=x, y=y) for x in range(cells) for y in range(cells))})


def test_falling_mountain_judgment_is_a_30_foot_cone_or_a_60_foot_line():
    """"Area: 30-foot cone or 60-foot line from you": the cone was the only shape; the line reaches a foe 50 feet away that the
    cone cannot."""
    talents = ["TAL_AXES_FALLING_MOUNTAIN_JUDGMENT"]
    names = set(H._rows(H._bundle(H.AXES, [H.HEWING, *talents], H.AXE_KIT, cl=15)))
    assert {"Falling Mountain Judgment: 30-foot cone", "Falling Mountain Judgment: 60-foot line"} <= names
    line = H._engine(H._bundle(H.AXES, [H.HEWING, *talents], H.AXE_KIT, cl=15, dc=FAIL), foe_at=(13, 6))
    H._use(line, "Falling Mountain Judgment: 60-foot line at 13,6", target=None)
    assert H._foe(line).current_hp < H._foe(line).maximum_hp and "typed.prone" in H._conditions(H._foe(line))
    cone = H._engine(H._bundle(H.AXES, [H.HEWING, *talents], H.AXE_KIT, cl=15, dc=FAIL), foe_at=(13, 6))
    assert not [n for n in H._legal(cone) if n.startswith("Falling Mountain Judgment: 30-foot cone at 13,6")]  # 50 feet: out of the cone
    near = H._engine(H._bundle(H.AXES, [H.HEWING, *talents], H.AXE_KIT, cl=15, dc=FAIL), foe_at=(6, 6))
    H._use(near, "Falling Mountain Judgment: 30-foot cone at 6,6", target=None)
    assert H._foe(near).current_hp < H._foe(near).maximum_hp


def test_lodged_axe_pull_pulls_you_to_a_larger_target():
    """"If the target is larger or fixed in place, you may pull yourself 10 feet toward it instead": a larger target was skipped
    (no save, no movement at all)."""
    name, talents = "Lodged Axe Pull", ["TAL_AXES_LODGED_AXE_PULL"]
    engine = H._engine(_axes(talents, dc=FAIL), foe_at=(8, 6))
    _grow(engine, cells=3)  # Huge: two sizes larger than a Medium creature
    H._bite(engine)
    start = H._me(engine).position
    H._use(engine, name)
    assert H._foe(engine).position == Position(x=8, y=6)  # the Huge creature stays
    assert H._me(engine).position == Position(x=start.x + 2, y=start.y)  # you are pulled 10 feet (2 cells) toward it
    large = H._engine(_axes(talents, dc=FAIL), foe_at=(8, 6))
    _grow(large, cells=2)  # Large: no more than one size larger, so it is the one pulled
    H._bite(large)
    H._use(large, name)
    assert H._foe(large).position == Position(x=6, y=6) and H._me(large).position == start


def test_poleaxe_gate_is_only_a_hook_and_the_size_clause_is_the_saves_own():
    """"When you choose Hook on Hewing Strike ... you may either pull the target 10 feet, knock it Prone on a failed Strength
    saving throw, or prevent it from moving closer to you ... A creature more than one size larger than you has Advantage on the
    saving throw": the modifier was offered on every Hewing Strike option, ran the pull AND the save at once, had no third
    choice, and the size clause was an Advantage row that gave the TARGET Advantage on its next saving throw whatever its size."""
    talents = ["TAL_AXES_POLEAXE_GATE"]
    names = sorted(n for n in H._rows(_axes(talents)) if "Poleaxe Gate" in n)
    assert names == [STRIKE + "Hook + Poleaxe Gate: " + option for option in ("Hold Off", "Knock Prone", "Pull 10 Feet")]
    prone = STRIKE + "Hook + Poleaxe Gate: Knock Prone"
    engine, _ = H._axes_cast(talents, prone, dc=FAIL)
    assert "typed.save_against" not in _conds(H._foe(engine)) and "typed.prone" in _conds(H._foe(engine))
    assert H._foe(engine).position == Position(x=4, y=6)  # the Knock Prone choice does not also pull
    total = _save_total(talents, prone)
    # a creature two sizes larger has Advantage: the same seed rolls a different total or two d20s
    huge = H._engine(_axes(talents, dc=total))
    _grow(huge, cells=3)
    events = H._use(huge, prone)
    save = H._payloads(events, "SAVE_ROLLED")[0]
    assert save.get("mode") == "ADVANTAGE" or len(save.get("rolls") or ()) == 2, save
    pulled, _ = H._axes_cast(talents, STRIKE + "Hook + Poleaxe Gate: Pull 10 Feet")
    assert H._foe(pulled).position == Position(x=4, y=6)  # already in reach: nowhere nearer to be pulled to


def _move_squares(engine, actor_id):
    """The squares the creature is offered to walk to on its own turn."""
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    engine.state.current_actor_id = actor_id
    engine._system_start_turn()
    return {(c.destination.x, c.destination.y) for c in engine.legal_candidates()
            if c.actor_id == actor_id and getattr(c.kind, "value", c.kind) == "MOVE" and c.destination is not None}


def test_hold_off_stops_the_target_walking_closer_to_you_until_your_next_turn():
    """"prevent it from moving closer to you until the start of your next turn" (Poleaxe Gate): the option existed only as words."""
    talents, name = ["TAL_AXES_POLEAXE_GATE"], STRIKE + "Hook + Poleaxe Gate: Hold Off"
    engine, _ = H._axes_cast(talents, name)
    me = H._me(engine).position
    H._foe(engine).position = Position(x=6, y=6)  # it has since been driven back: the bar is on where it may walk from here
    squares = _move_squares(engine, H.AN)
    assert squares and all(engine.grid.distance_ft(Position(x=x, y=y), me) >= engine.grid.distance_ft(H._foe(engine).position, me)
                           for x, y in squares)
    assert "typed.no_approach" in _conds(H._foe(engine))
    control = H._engine(_axes(talents), foe_at=(6, 6))
    assert any(engine.grid.distance_ft(Position(x=x, y=y), me) < engine.grid.distance_ft(Position(x=6, y=6), me)
               for x, y in _move_squares(control, H.AN))  # without the bar it may walk in


def _with_ally(talents, *, dc, foe_at=(4, 6), ally_at=(9, 9)):
    """The axe fighter (3,6), an ally of its own and a Bloodied foe, all Factory fighters."""
    ally_id = "actor:factory.ally"
    bundles = (compile_character(H._sheet(H.AXES, [H.HEWING, *talents], H.AXE_KIT, cl=10, dc=dc), actor_id=ME),
               compile_character(H._sheet(None, [], H.AXE_KIT), actor_id=ally_id),
               compile_character(H._sheet(None, [], H.AXE_KIT), actor_id=H.FOE))
    engine = Gate4ControllerEngine(H.ROOT, match_seed="a", typed_bundles=bundles, roster_setup={
        "primary_actor_ids": [ME, ally_id, H.FOE], "team_by_actor": {ME: "team:a", ally_id: "team:a", H.FOE: "team:b"},
        "starting_positions": {ME: {"x": 3, "y": 6}, ally_id: {"x": ally_at[0], "y": ally_at[1]}, H.FOE: {"x": foe_at[0], "y": foe_at[1]}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    engine.state.actors[H.FOE].armor_class = -50
    engine.state.actors[H.FOE].current_hp = engine.state.actors[H.FOE].maximum_hp // 4
    H._ready(engine)
    return engine, ally_id


def test_red_line_keeps_a_frightened_target_from_closing_on_your_ally_or_gives_it_disadvantage_against_that_ally():
    """"Failed Save: ... the target cannot willingly move closer to one ally of your choice ... Successful Save: ... it has
    Disadvantage on the next attack roll it makes against that ally": both halves were a GM line (the success half was a
    Disadvantage on its next attack against anybody)."""
    talents, name = ["TAL_AXES_HEADSMAN_S_RED_LINE"], STRIKE + "Bite + Headsman's Red Line"
    failed, ally_id = _with_ally(talents, dc=FAIL)
    H._use(failed, name, target=H.FOE)
    held = _conds(failed.state.actors[H.FOE])["typed.no_approach"]
    assert held.data["avoid"] == ally_id  # the caster's ally nearest the target, not the caster
    failed.state.actors[H.FOE].position = Position(x=6, y=9)  # it has since been driven off, so there is room to walk either way
    ally, start = failed.state.actors[ally_id].position, failed.state.actors[H.FOE].position
    squares = _move_squares(failed, H.FOE)
    assert squares and all(failed.grid.distance_ft(Position(x=x, y=y), ally) >= failed.grid.distance_ft(start, ally) for x, y in squares)
    assert any(failed.grid.distance_ft(Position(x=x, y=y), failed.state.actors[ME].position)
               < failed.grid.distance_ft(start, failed.state.actors[ME].position) for x, y in squares)  # it may still close on the caster

    saved, ally_id = _with_ally(talents, dc=PASS)
    H._use(saved, name, target=H.FOE)
    foe = saved.state.actors[H.FOE]
    assert "typed.no_approach" not in _conds(foe)
    assert ("attack_mode_vs", f"DISADVANTAGE:{ally_id}") in H._modifiers(foe)


def test_headsmans_red_line_gives_a_creature_immune_to_frightened_advantage_on_the_save(monkeypatch):
    """"Creatures immune to Frightened have Advantage on the saving throw": a GM line."""
    talents, name = ["TAL_AXES_HEADSMAN_S_RED_LINE"], STRIKE + "Bite + Headsman's Red Line"
    engine = H._engine(_axes(talents, dc=16, cl=10))
    H._foe(engine).current_hp = H._foe(engine).maximum_hp // 4  # Bloodied
    monkeypatch.setattr(typed_executor, "condition_immune", lambda eng, actor, condition: condition == "frightened")
    save = H._payloads(H._use(engine, name), "SAVE_ROLLED")
    assert save and (save[0].get("mode") == "ADVANTAGE" or len(save[0].get("rolls") or ()) == 2), save


def _foe_strikes_me(talent, *, my_ac, option=None, cl=10, dc=16, foe_conditions=()):
    """The foe makes a weapon attack on the axe fighter (AC ``my_ac``) who holds ``talent`` as a reaction; ``option`` picks a
    menu entry of that reaction ahead of the fight (the reaction plan)."""
    plan = {"options": {talent: option}} if option is not None else None
    me_bundle = compile_character(H._sheet(H.AXES, [H.HEWING, talent], H.AXE_KIT, cl=cl, dc=dc), actor_id=ME, reaction_plan=plan)
    foe_bundle = compile_character(H._sheet(None, [], H.AXE_KIT), actor_id=H.FOE)
    # seed "a": the first foe roll is not a natural 1
    engine = Gate4ControllerEngine(H.ROOT, match_seed="a", typed_bundles=(me_bundle, foe_bundle), roster_setup={
        "primary_actor_ids": [ME, H.FOE], "team_by_actor": {ME: "team:a", H.FOE: "team:b"},
        "starting_positions": {ME: {"x": 3, "y": 6}, H.FOE: {"x": 4, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(H.FOE)
    engine.state.current_actor_id = H.FOE
    engine._system_start_turn()
    me = engine.state.actors[ME]
    me.armor_class = my_ac
    for condition in foe_conditions:  # e.g. "condition:typed.mounted"
        engine._apply_condition(engine.state.actors[H.FOE], condition, "test:setup", ME, expires_on="UNTIL_REMOVED")
    attack = next(c for c in engine.legal_candidates() if c.actor_id == H.FOE and ME in (c.target_ids or ())
                  and ".weapon." in c.source_definition_id and (engine.action_catalog[c.source_definition_id].range_ft or 5) <= 5)
    before = len(engine.events)
    engine.execute_intent(H.ActionIntent(intent_id="foe-attack", decision_id=attack.decision_id, candidate_id=attack.candidate_id,
                                         state_version=attack.state_version, actor_id=H.FOE, target_ids=attack.target_ids))
    return engine, engine.events[before:]


def test_haft_guard_steps_or_bites_only_when_it_reduces_the_damage_to_nothing():
    """"If this reduces the damage to 0, you may move 5 feet without provoking Opportunity Attacks from the attacker, or you may
    place Bite on the attacker's weapon": the 5-foot step ran however much damage got through and Bite was never placed.  The
    reaction is now a two-option menu (the reaction plan picks one), each option with the reduction and its own zero-damage rider."""
    talent = "TAL_AXES_HAFT_GUARD"
    bundle = compile_character(H._sheet(H.AXES, [H.HEWING, talent], H.AXE_KIT), actor_id=ME)
    reaction = next(r for r in bundle["typed_reactions"] if r.get("name") == "Haft Guard")
    assert reaction["option_labels"] == ["Step away", "Bite the weapon"]
    stepped, events = _foe_strikes_me(talent, my_ac=-50, option=0)
    assert [e for e in events if e.event_type == "REACTION_RESOLVED"]
    bitten, _ = _foe_strikes_me(talent, my_ac=-50, option=1)
    foe_after = bitten.state.actors[H.FOE]
    from combat.typed_executor import bears_mark
    assert bears_mark(foe_after, ME, "Bite") and not bears_mark(stepped.state.actors[H.FOE], ME, "Bite")
    assert stepped.state.actors[ME].position != Position(x=3, y=6) and bitten.state.actors[ME].position == Position(x=3, y=6)


def test_poleaxe_armor_court_puts_bite_on_a_creature_that_missed_you():
    """"When a creature inside your reach misses you with a melee attack, you may use your Reaction to place Bite on that
    creature": the reaction only made the target roll a Strength save that did nothing."""
    from combat.typed_executor import bears_mark

    engine, events = _foe_strikes_me("TAL_AXES_POLEAXE_ARMOR_COURT", my_ac=60)
    assert [e for e in events if e.event_type == "ATTACK_ROLLED"]
    if not [e for e in events if e.event_type == "REACTION_RESOLVED"]:
        raise AssertionError("no reaction: " + str([e.event_type for e in events]))
    assert bears_mark(engine.state.actors[H.FOE], ME, "Bite") and not engine.state.actors[ME].reaction_available


def test_a_mounted_target_of_dragon_felling_chop_saves_with_disadvantage():
    """"If the target is mounted, climbing, or flying by wings rather than hovering, it has Disadvantage on the save": a GM line.
    Mounted is a state the table keeps (combat/ext/mounts.py); climbing and flying are not, and stay the GM's."""
    talents, name = ["TAL_AXES_DRAGON_FELLING_CHOP"], STRIKE + "Drive + Dragon-Felling Chop"
    plain = H._payloads(H._axes_cast(talents, name, dc=16)[1], "SAVE_ROLLED")[0]
    assert plain.get("mode") in (None, "NORMAL") and len(plain.get("dice") or ()) == 1
    engine = H._engine(_axes(talents, dc=16))
    engine._apply_condition(H._foe(engine), "condition:typed.mounted", "test:setup", ME, expires_on="UNTIL_REMOVED")
    saved = H._payloads(H._use(engine, name), "SAVE_ROLLED")[0]
    assert saved.get("mode") == "DISADVANTAGE" or len(saved.get("dice") or ()) == 2, saved


def test_poleaxe_armor_court_stops_a_mounted_creatures_movement_when_it_fails_the_save():
    """"If the creature was mounted ... it must also succeed on a Strength saving throw or its remaining movement this turn
    becomes 0": a GM line.  A foot soldier is not affected."""
    mounted, _ = _foe_strikes_me("TAL_AXES_POLEAXE_ARMOR_COURT", my_ac=60, dc=50, foe_conditions=("condition:typed.mounted",))
    assert mounted.state.actors[H.FOE].movement_remaining_ft == 0
    on_foot, _ = _foe_strikes_me("TAL_AXES_POLEAXE_ARMOR_COURT", my_ac=60, dc=50)
    assert on_foot.state.actors[H.FOE].movement_remaining_ft > 0
    saved, _ = _foe_strikes_me("TAL_AXES_POLEAXE_ARMOR_COURT", my_ac=60, dc=-40, foe_conditions=("condition:typed.mounted",))
    assert saved.state.actors[H.FOE].movement_remaining_ft > 0


def test_hewing_intent_axe_attacks_overcome_resistance_to_nonmagical_weapons():
    """"Your axe attacks count as magical for overcoming ordinary Resistance to nonmagical bludgeoning, piercing, and slashing
    damage": a GM line, so a Body-Tempered target halved every axe blow."""
    def damage(talents):
        me = compile_character(H._sheet(H.AXES, [H.HEWING, *talents], H.AXE_KIT, cl=10), actor_id=ME)
        sheet = H._sheet(None, [], H.AXE_KIT)
        sheet["spheres_and_talents"]["learned_talent_record_ids"] = ["tianxia.path.body_refining.feature.body_tempering"]
        engine = Gate4ControllerEngine(H.ROOT, match_seed="a", typed_bundles=(me, compile_character(sheet, actor_id=H.FOE)), roster_setup={
            "primary_actor_ids": [ME, H.FOE], "team_by_actor": {ME: "team:a", H.FOE: "team:b"},
            "starting_positions": {ME: {"x": 3, "y": 6}, H.FOE: {"x": 4, "y": 6}}})
        engine.state.current_slot_index = engine.state.initiative_order.index(ME)
        engine.state.current_actor_id = ME
        engine._system_start_turn()
        engine.state.actors[H.FOE].armor_class = -50
        H._ready(engine)
        events = H._use(engine, "Fu (Short Axe) attack", target=H.FOE)
        committed = H._payloads(events, "DAMAGE_COMMITTED")[0]
        return committed["rolled_or_pending_damage"], committed["hp_damage"]

    rolled, taken = damage([])
    assert taken < rolled  # resisted
    rolled, taken = damage(["TAL_AXES_HEWING_INTENT"])
    assert taken == rolled  # a magical blow


def _two_foes(talents, *, second_at=(4, 7), dc=16):
    """The axe fighter (3,6) and two Factory foes side by side: one at (4,6), one at ``second_at``."""
    other = "actor:factory.second"
    bundles = (compile_character(H._sheet(H.AXES, [H.HEWING, *talents], H.AXE_KIT, cl=10, dc=dc), actor_id=ME),
               compile_character(H._sheet(None, [], H.AXE_KIT), actor_id=H.FOE),
               compile_character(H._sheet(None, [], H.AXE_KIT), actor_id=other))
    engine = Gate4ControllerEngine(H.ROOT, match_seed="a", typed_bundles=bundles, roster_setup={
        "primary_actor_ids": [ME, H.FOE, other], "team_by_actor": {ME: "team:a", H.FOE: "team:b", other: "team:b"},
        "starting_positions": {ME: {"x": 3, "y": 6}, H.FOE: {"x": 4, "y": 6}, other: {"x": second_at[0], "y": second_at[1]}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    for actor_id in (H.FOE, other):
        engine.state.actors[actor_id].armor_class = -50
    H._ready(engine)
    return engine, other


def _use_on(engine, name, target):
    """``H._use`` takes the first legal candidate of that name; with two foes standing there is one per target."""
    candidate = next(c for c in engine.legal_candidates() if c.display_name == name and target in (c.target_ids or ()))
    before = len(engine.events)
    engine.execute_intent(H.ActionIntent(intent_id=f"i-{name}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                         state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids,
                                         destination=candidate.destination))
    return engine.events[before:]


def test_cleaving_arc_swings_at_a_second_creature_beside_the_first():
    """"threaten a second creature within your reach and within 5 feet of the original target. Make a second melee weapon attack
    against that creature": it was ``extra_attacks``, a second swing at the SAME creature."""
    name = STRIKE + "Bite + Cleaving Arc"
    engine, other = _two_foes(["TAL_AXES_CLEAVING_ARC"])
    events = _use_on(engine, name, H.FOE)
    rolls = H._payloads(events, "ATTACK_ROLLED")
    assert len(rolls) == 2 and [e.target_ids for e in events if e.event_type == "ATTACK_ROLLED"] == [(H.FOE,), (other,)]
    assert engine.state.actors[other].current_hp < engine.state.actors[other].maximum_hp  # normal weapon damage
    assert "typed.mark.bite.actor:factory.sweep" not in _conds(engine.state.actors[other])  # no Hewing rider on it
    alone, _ = _two_foes(["TAL_AXES_CLEAVING_ARC"], second_at=(4, 9))  # nobody else within 5 feet of the first: one attack
    assert len(H._payloads(_use_on(alone, name, H.FOE), "ATTACK_ROLLED")) == 1


def test_cleaving_arc_second_attack_has_advantage_after_bite_was_consumed_this_turn():
    """"If the first target had Bite from you and you consumed it with another Axes talent this turn, the second attack has
    Advantage": a GM line."""
    talents = ["TAL_AXES_CLEAVING_ARC", "TAL_AXES_RENDING_HEW"]
    engine, other = _two_foes(talents)
    engine._apply_condition(engine.state.actors[H.FOE], typed_executor.mark_condition_id("Bite", ME), "test:bite", ME, expires_on="UNTIL_REMOVED")
    _use_on(engine, STRIKE + "Bite + Rending Hew", H.FOE)  # consumes the Bite
    assert not typed_executor.bears_mark(engine.state.actors[H.FOE], ME, "Bite")
    H._ready(engine)
    second = [e for e in _use_on(engine, STRIKE + "Bite + Cleaving Arc", H.FOE) if e.event_type == "ATTACK_ROLLED"][1]
    assert second.target_ids == (other,) and second.payload.get("mode") == "ADVANTAGE"
    fresh, _ = _two_foes(talents)
    plain = [e for e in _use_on(fresh, STRIKE + "Bite + Cleaving Arc", H.FOE) if e.event_type == "ATTACK_ROLLED"][1]
    assert plain.payload.get("mode") == "NORMAL"


def _paint_difficult(engine, cell):
    """Difficult ground painted on the map at one square (a zone of the map's own, like the map editor's terrain)."""
    from combat import zones
    from combat.gate2_runtime_models import ZoneState

    where = Position(x=cell[0], y=cell[1])
    engine.state.zones["zone:map:test"] = ZoneState(
        zone_id="zone:map:test", source_definition_id="map:terrain", owner_id=zones.MAP_OWNER, center=where, radius_cells=0,
        affected_cells=(where,), concentration_link=False, created_round=1,
        trigger_profile={"kind": zones.KIND, "name": "Mud", "difficult": "all", "triggers": [], "inside": []})


def test_low_chop_drops_a_target_standing_on_difficult_ground_when_it_fails_the_dexterity_save():
    """"If the target is standing on difficult terrain, mud, snow, roots, rubble ... it must also succeed on a Dexterity saving
    throw or fall Prone": a GM line."""
    name = STRIKE + "Hamper"  # Low Chop is not optional: it is part of the Hamper option

    def chop(dc, *, muddy):
        engine = H._engine(_axes(["TAL_AXES_LOW_CHOP"], dc=dc))
        if muddy:
            _paint_difficult(engine, (4, 6))
        H._use(engine, name)
        return engine

    assert "typed.prone" in _conds(H._foe(chop(FAIL, muddy=True)))
    assert "typed.prone" not in _conds(H._foe(chop(PASS, muddy=True)))  # the save held
    assert "typed.prone" not in _conds(H._foe(chop(FAIL, muddy=False)))  # firm ground


SHIELD_KIT = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.fu", "name": "Fu (Short Axe)", "quantity": 1},
                                        {"item_id": "tianxia.mortal.armor.shield", "name": "Shield", "quantity": 1}]}}


def _shielded_sheet():
    """The Factory fighter who carries the Shield, with the printed Shield proficiency that earns its +2.

    The +2 is a training grant (combat/ext/shield_training.py; ``test_mgr_t14_shield_training_base``): a carrier
    with no proficiency compiles a 0 ``shield_ac`` row. This fighter is proficient, so the shield rider tests
    below measure what the riders take off, not whether the carrier may use a shield."""
    return {**H._sheet(None, [], SHIELD_KIT), "proficiencies": {"armor": ["Shield"]}}


def _shield_duel(talents, *, dc=16, ally=False):
    """The axe fighter (3,6) against a Factory fighter with a shield (4,6); AC -50 so every attack is rolled to hit and the
    ``target_ac`` of each ATTACK_ROLLED shows what the shield still lends (-50 with it, -52 with it broken)."""
    ids = [ME, H.FOE] + (["actor:factory.ally"] if ally else [])
    bundles = [compile_character(H._sheet(H.AXES, [H.HEWING, *talents], H.AXE_KIT, cl=10, dc=dc), actor_id=ME),
               compile_character(_shielded_sheet(), actor_id=H.FOE)]
    starts = {ME: {"x": 3, "y": 6}, H.FOE: {"x": 4, "y": 6}}
    teams = {ME: "team:a", H.FOE: "team:b"}
    if ally:
        bundles.append(compile_character(H._sheet(None, [], H.AXE_KIT), actor_id="actor:factory.ally"))
        starts["actor:factory.ally"], teams["actor:factory.ally"] = {"x": 4, "y": 7}, "team:a"
    engine = Gate4ControllerEngine(H.ROOT, match_seed="a", typed_bundles=tuple(bundles), roster_setup={
        "primary_actor_ids": ids, "team_by_actor": teams, "starting_positions": starts})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    engine.state.actors[H.FOE].armor_class = -50
    H._ready(engine)
    return engine


def _ac_seen(events):
    return [p["target_ac"] for p in H._payloads(events, "ATTACK_ROLLED")]


def _plain_attack(engine, actor_id=ME, name="Fu (Short Axe) attack"):
    candidate = next(c for c in engine.legal_candidates() if c.actor_id == actor_id and c.display_name == name and H.FOE in (c.target_ids or ()))
    before = len(engine.events)
    engine.execute_intent(H.ActionIntent(intent_id=f"i-{actor_id}-{len(engine.events)}", decision_id=candidate.decision_id,
                                         candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=actor_id,
                                         target_ids=candidate.target_ids))
    return engine.events[before:]


def test_the_fighter_carrying_a_shield_is_known_to_the_table():
    """A shield is a fact about its proficient fighter (its +2 is inside the AC number): the compiler records it."""
    with_shield = compile_character(_shielded_sheet(), actor_id=H.FOE)
    assert [r for r in with_shield["typed_passives"] if r.get("block") == "shield_ac"] == [{"feature_id": "shield_ac", "block": "shield_ac", "amount": 2}]
    assert not [r for r in compile_character(H._sheet(None, [], H.AXE_KIT), actor_id=H.FOE)["typed_passives"] if r.get("block") == "shield_ac"]


def test_split_guard_takes_the_shield_off_the_next_axe_attack_only():
    """"Split Guard. Until the end of your current turn, the target cannot benefit from Shield AC against the next axe attack you
    make against it": a GM line ("the table tracks AC as a single number")."""
    engine = _shield_duel([])
    first = H._use(engine, STRIKE + "Split Guard", target=H.FOE)
    assert _ac_seen(first) == [-50]  # the Split Guard blow itself still meets the shield
    assert "typed.guard_broken" in _conds(engine.state.actors[H.FOE])
    H._ready(engine)
    second = _plain_attack(engine)
    assert _ac_seen(second) == [-52]  # the next axe attack: no shield
    H._ready(engine)
    assert _ac_seen(_plain_attack(engine)) == [-50]  # spent by that one


def test_shield_catching_beard_strips_the_shield_from_every_attack_on_a_failure_and_the_next_axe_attack_on_a_success():
    """"Failed Save: Until the start of your next turn, the target cannot benefit from Shield AC against your attacks.
    Successful Save: Until the end of your current turn, ... against your next axe attack": two GM lines."""
    name = STRIKE + "Bite + Shield-Catching Beard"
    failed = _shield_duel(["TAL_AXES_SHIELD_CATCHING_BEARD"], dc=FAIL)
    H._use(failed, name, target=H.FOE)
    seen = []
    for _ in range(2):
        H._ready(failed)
        seen += _ac_seen(_plain_attack(failed))
    assert seen == [-52, -52]  # every attack of yours until the start of your next turn
    saved = _shield_duel(["TAL_AXES_SHIELD_CATCHING_BEARD"], dc=PASS)
    H._use(saved, name, target=H.FOE)
    seen = []
    for _ in range(2):
        H._ready(saved)
        seen += _ac_seen(_plain_attack(saved))
    assert seen == [-52, -50]  # the next one only


def test_split_the_shield_wall_opens_the_target_to_the_next_attack_by_anyone():
    """"loses the benefit of Shield AC, Half Cover, or Three-Quarters Cover against the next attack made against it before the
    start of your next turn": the attack that follows may be an ally's."""
    engine = _shield_duel(["TAL_AXES_SPLIT_THE_SHIELD_WALL"], ally=True)
    H._use(engine, "Split the Shield Wall", target=H.FOE)
    ally = "actor:factory.ally"
    engine.state.current_actor_id = ally
    engine.state.actors[ally].action_available = True
    assert _ac_seen(_plain_attack(engine, actor_id=ally, name="Fu (Short Axe) attack")) == [-52]
    engine.state.actors[ally].action_available = True
    assert _ac_seen(_plain_attack(engine, actor_id=ally, name="Fu (Short Axe) attack")) == [-50]


def test_split_the_shield_wall_also_strips_half_cover_from_a_ranged_attack():
    """"... loses the benefit of Shield AC, Half Cover, or Three-Quarters Cover against the next attack": cover is the engine's own
    figure for a ranged attack, cancelled for that one attack."""
    def thrown(broken):
        engine = _shield_duel(["TAL_AXES_SPLIT_THE_SHIELD_WALL"])
        engine.grid.cover = {(5, 6)}  # a low wall between the axe fighter (3,6) and the shielded foe (7,6)
        engine.__dict__.pop("_wall_base", None)
        if broken:
            H._use(engine, "Split the Shield Wall", target=H.FOE)
            H._ready(engine)
        engine.state.actors[H.FOE].position = Position(x=7, y=6)
        return H._payloads(_plain_attack(engine, name="Fu (Short Axe) thrown"), "ATTACK_ROLLED")[0]

    assert thrown(False)["target_ac"] == -48  # -50 and the cover's +2
    assert thrown(True)["target_ac"] == -52  # neither the cover nor the shield


# ----------------------------------------------------------------------------------------------------------------- Beauty

BEAUTY = "tianxia.sphere.beauty"
ALLY = "actor:factory.ally"


def test_axes_body_reach_applies_only_while_the_form_is_active():
    from combat.ext.axes_body_reach import STATE

    engine = _beauty_arena([H.HEWING, "TAL_AXES_MOUNTAIN_FELLING_AXE_BODY"], cl=15,
                           extra_spheres=(H.AXES,), foe_at=(5, 6))
    extended = "Fu (Short Axe) attack (Mountain-Felling reach)"
    assert extended not in H._legal(engine)
    _act(engine, ME, "Mountain-Felling Axe Body")
    assert extended in H._legal(engine)
    events = _act(engine, ME, extended, H.FOE)
    assert H._payloads(events, "ATTACK_ROLLED")
    engine.state.round_number += 10
    _begin_turn(engine, ME)
    assert STATE not in {c.condition_id for c in H._me(engine).conditions.values()}
    assert extended not in H._legal(engine)


def test_axes_body_reach_extends_the_opportunity_attack_and_its_eligibility():
    from combat import typed_reactions
    from combat.gate2_runtime_models import ActionIntent

    engine = _beauty_arena([H.HEWING, "TAL_AXES_MOUNTAIN_FELLING_AXE_BODY"], cl=15,
                           extra_spheres=(H.AXES,), foe_at=(5, 6))
    me, foe = H._me(engine), engine.state.actors[H.FOE]
    assert typed_reactions.opportunity_reach(engine, me) == 5
    _act(engine, ME, "Mountain-Felling Axe Body")
    assert typed_reactions.opportunity_reach(engine, me) == 10
    _begin_turn(engine, H.FOE)
    candidate = next(c for c in engine.legal_candidates() if c.destination == Position(x=6, y=6)
                     and str(getattr(c.kind, "value", c.kind)) == "MOVE")
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id="test-form-oa", actor_id=H.FOE,
        decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
        state_version=candidate.state_version, destination=candidate.destination))
    assert H._payloads(engine.events[before:], "ATTACK_ROLLED")


def test_axes_body_reach_leaves_thrown_axe_range_unchanged():
    from combat.ext.axes_body_reach import SUFFIX

    bundle = _axes(["TAL_AXES_CAST_AXE", "TAL_AXES_MOUNTAIN_FELLING_AXE_BODY"], cl=15)
    extended = [a for a in bundle["action_catalog"] if a["source_definition_id"].endswith(SUFFIX)]
    assert extended
    assert all(" thrown" not in a["display_name"] and "Cast Axe" not in a["display_name"] for a in extended)


def _beauty_arena(talents, *, dc=16, ally=False, foe_at=(4, 6), cl=10, foe_talents=(), ally_beauty=False, extra_spheres=()):
    """A Beauty fighter (3,6) [Wisdom save DC ``dc``], a plain Factory foe, and optionally an ally of the Beauty fighter."""
    sheet = H._sheet(BEAUTY, list(talents), H.AXE_KIT, cl=cl, dc=dc)
    sheet["spheres_and_talents"]["sphere_record_ids"].extend(extra_spheres)
    sheet["spheres_and_talents"]["automatic_sphere_component_record_ids"].extend(
        key for key, row in H._mechanics().items() if row.get("kind") == "base_ability" and row.get("sphere_id") in extra_spheres)
    bundles = [compile_character(sheet, actor_id=ME),
               compile_character(H._sheet(BEAUTY if foe_talents else None, list(foe_talents), H.AXE_KIT, dc=50), actor_id=H.FOE)]
    starts, teams = {ME: {"x": 3, "y": 6}, H.FOE: {"x": foe_at[0], "y": foe_at[1]}}, {ME: "team:a", H.FOE: "team:b"}
    if ally:
        bundles.append(compile_character(H._sheet(BEAUTY if ally_beauty else None, [], H.AXE_KIT, dc=dc), actor_id=ALLY))
        starts[ALLY], teams[ALLY] = {"x": 3, "y": 7}, "team:a"
    engine = Gate4ControllerEngine(H.ROOT, match_seed="a", typed_bundles=tuple(bundles), roster_setup={
        "primary_actor_ids": list(starts), "team_by_actor": teams, "starting_positions": starts})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    H._ready(engine)
    return engine


def _act(engine, actor_id, name, target=None, *, destination=None):
    """``actor_id`` takes the legal action of that name (aimed at ``target`` when given), on its own turn."""
    engine.state.current_actor_id = actor_id
    actor = engine.state.actors[actor_id]
    actor.action_available, actor.bonus_action_available, actor.reaction_available = True, True, True
    candidate = next(c for c in engine.legal_candidates() if c.actor_id == actor_id and (c.display_name == name or c.display_name.startswith(name + " at ")) and (target is None or target in (c.target_ids or ()))
                     and (destination is None or c.destination == destination))
    before = len(engine.events)
    engine.execute_intent(H.ActionIntent(intent_id=f"i-{actor_id}-{name}-{len(engine.events)}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                         state_version=candidate.state_version, actor_id=actor_id, target_ids=candidate.target_ids, destination=candidate.destination))
    return engine.events[before:]


def _begin_turn(engine, actor_id):
    """Start ``actor_id``'s turn the way the engine does (its turn flags reset, turn-start hooks run)."""
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    engine.state.current_actor_id = actor_id
    engine._system_start_turn()


def _strike(engine, attacker, target):
    """A plain weapon attack: the events it made."""
    return _act(engine, attacker, "Fu (Short Axe) attack", target)


def _move_actor(engine, actor_id, destination):
    engine.state.current_actor_id = actor_id
    candidate = next(c for c in engine.legal_candidates() if c.destination == destination
                     and str(getattr(c.kind, "value", c.kind)) == "MOVE")
    before = len(engine.events)
    engine.execute_intent(H.ActionIntent(intent_id=f"move-{len(engine.events)}", actor_id=actor_id,
        decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
        state_version=candidate.state_version, destination=candidate.destination))
    return engine.events[before:]


@pytest.mark.parametrize("dc,saved", [(FAIL, False), (PASS, True)])
def test_beauty_motion_shapes_only_the_first_accepted_opportunity_attack(dc, saved):
    from combat import typed_reactions
    from combat.ext.beauty_motion import TRAIL

    engine = _beauty_arena(["tianxia.talent.beauty.beauty_in_motion"], dc=dc, foe_at=(4, 4))
    me, foe = H._me(engine), engine.state.actors[H.FOE]
    assert "Beauty in Motion" not in H._legal(engine)
    _move_actor(engine, ME, Position(x=3, y=4))
    resource = "resource:core.stamina"
    before = me.resources[resource]
    _act(engine, ME, "Beauty in Motion")
    assert me.resources[resource] == before - 1
    assert TRAIL in {c.condition_id for c in me.conditions.values()}
    # Eligibility queries are pure and do not spend the first-OA allowance.
    for _ in range(2):
        assert typed_reactions.wants_opportunity_attack(engine, foe, me)
    assert TRAIL in {c.condition_id for c in me.conditions.values()}
    events = _move_actor(engine, ME, Position(x=2, y=4))
    assert TRAIL not in {c.condition_id for c in me.conditions.values()}
    triggered = H._payloads(events, "PASSIVE_TRIGGERED")
    assert any(p.get("beauty_motion") and p["automatic_miss"] == (not saved) for p in triggered)
    rolls = [e.payload for e in events if e.event_type == "ATTACK_ROLLED" and e.actor_id == H.FOE]
    if saved:
        assert len(rolls) == 1 and rolls[0]["mode"] == "DISADVANTAGE"
    else:
        assert not rolls
    assert not foe.reaction_available


def test_beauty_motion_expires_at_the_users_next_start_without_an_attack():
    from combat.ext.beauty_motion import TRAIL

    engine = _beauty_arena(["tianxia.talent.beauty.beauty_in_motion"], foe_at=(4, 4))
    _move_actor(engine, ME, Position(x=3, y=4))
    _act(engine, ME, "Beauty in Motion")
    _begin_turn(engine, ME)
    assert TRAIL not in {c.condition_id for c in H._me(engine).conditions.values()}
    assert "Beauty in Motion" not in H._legal(engine)


@pytest.mark.parametrize("cl,destination", [(4, Position(x=3, y=4)), (5, Position(x=3, y=3))])
def test_unapproachable_poise_moves_immediately_at_the_printed_realm_distance(cl, destination):
    from combat.gate2_runtime_models import ReactionDecision

    engine = _beauty_arena(["tianxia.talent.beauty.unapproachable_poise"], dc=FAIL, cl=cl)
    _act(engine, ME, "Catch the Eye", H.FOE)
    offered = []

    def answer(request):
        if request['reaction_source_id'] == 'choice:needle.rider_step':
            offered.extend(request['extension_choice']['option_ids'])
            return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=request['reactor_id'],
                reaction_source_id=request['reaction_source_id'], selection='USE',
                option_ids=(f'cell:{destination.x},{destination.y}',)), None
        return None, None

    engine.set_reaction_provider(answer)
    _begin_turn(engine, H.FOE)
    me, foe = H._me(engine), engine.state.actors[H.FOE]
    old_budget = me.movement_remaining_ft
    events = _strike(engine, H.FOE, ME)
    assert me.position == destination
    assert me.movement_remaining_ft == old_budget
    assert 'spark_step_ignore_oa_from' not in me.turn_flags
    assert f'cell:{destination.x},{destination.y}' in offered
    assert not [e for e in events if e.event_type == 'ATTACK_ROLLED']
    assert not [e for e in events if e.event_type == 'REACTION_RESOLVED'
                and e.actor_id == H.FOE and e.source_definition_id == 'system:combat.opportunity_attack']


def test_unapproachable_poise_exempts_only_the_creature_that_failed_the_save():
    from combat.gate2_runtime_models import ReactionDecision

    engine = _beauty_arena(["tianxia.talent.beauty.unapproachable_poise"], dc=FAIL, ally=True)
    outsider = engine.state.actors[ALLY]
    outsider.team_id = engine.state.actors[H.FOE].team_id
    _act(engine, ME, 'Catch the Eye', H.FOE)

    def answer(request):
        if request['reaction_source_id'] == 'choice:needle.rider_step':
            return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=request['reactor_id'],
                reaction_source_id=request['reaction_source_id'], selection='USE', option_ids=('cell:3,4',)), None
        return None, None

    engine.set_reaction_provider(answer)
    _begin_turn(engine, H.FOE)
    events = _strike(engine, H.FOE, ME)
    assert H._me(engine).position == Position(x=3, y=4)
    assert not outsider.reaction_available
    assert any(e.event_type == 'ATTACK_ROLLED' and e.actor_id == ALLY for e in events)


def test_catch_the_eye_captivates_by_the_owners_rules_and_a_saver_resists_it_for_ten_minutes():
    """"A Captivated creature ... has Disadvantage on Wisdom (Perception) checks to notice creatures other than you; it cannot make Opportunity
    Attacks against creatures other than you; the first time on each of its turns that it targets a creature other than you ... it must make a Wisdom
    saving throw" and "A creature that succeeds on this saving throw has Advantage on saving throws against your Catch the Eye for 10 minutes": the
    table had no rule for Captivated ("a tracked status the GM enforces") and put a GM line on the resisted save."""
    engine = _beauty_arena([], dc=50, ally=True, extra_spheres=("tianxia.sphere.fire",))
    events = _act(engine, ME, "Catch the Eye", H.FOE)
    foe = engine.state.actors[H.FOE]
    held = _conds(foe)["typed.captivated"]
    assert held.data["bar"] == {"captivated": True, "fragile": "source_side",
                                "declare_save": {"remedy": "choose", "ability": "wis", "vs": "others", "dc": 50,
                                                 "resists": "BEAUTY_BASE_CATCH_THE_EYE"}}
    from combat.ext import charm_rules
    assert charm_rules.notice(engine, foe, engine.state.actors[ALLY]) == "DISADVANTAGE"
    assert charm_rules.notice(engine, foe, engine.state.actors[ME]) is None
    # AUTO52 2026-10-05: the printed declaration save now runs, so the GM line it replaced is gone.
    assert not [e for e in events if e.event_type == "GM_RIDER" and "hostile action" in str(e.payload)]
    # Captivated's printed ending requires damage; forcing a damaging save alone does not end it.
    engine._add_modifier(foe, "test:fire_immunity", "damage_immunity", "ADD", "FIRE", "ALWAYS", expires_on="UNTIL_REMOVED")
    harm = _act(engine, ME, "Conflagration", destination=foe.position)
    assert any(e.actor_id == H.FOE for e in harm if e.event_type == "SAVE_ROLLED")
    assert not any(e.payload.get("hp_damage") or e.payload.get("temporary_hp_absorbed")
                   for e in harm if e.event_type == "DAMAGE_COMMITTED" and H.FOE in e.target_ids)
    assert "typed.captivated" in _conds(foe)

    # a save made: it resists Catch the Eye from this caster for ten minutes (Advantage on the save, no GM line)
    saved = _beauty_arena([], dc=-40)
    events = _act(saved, ME, "Catch the Eye", H.FOE)
    assert "typed.captivated" not in _conds(saved.state.actors[H.FOE]) and "typed.resist_ability" in _conds(saved.state.actors[H.FOE])
    assert not [e for e in events if e.event_type == "GM_RIDER" and "Advantage on saving throws" in str(e.payload)]
    saved.state.actors[H.FOE].active and H._ready(saved)
    again = H._payloads(_act(saved, ME, "Catch the Eye", H.FOE), "SAVE_ROLLED")[0]
    assert again.get("mode") == "ADVANTAGE" or len(again.get("dice") or ()) == 2, again


def test_a_captivated_creature_cannot_make_opportunity_attacks_against_others_and_is_freed_by_damage():
    """"it cannot make Opportunity Attacks against creatures other than you" and "Captivated ends early if ... you or your allies damage it"."""
    from combat.ext import charm_rules

    engine = _beauty_arena([], dc=50, ally=True)
    _act(engine, ME, "Catch the Eye", H.FOE)
    foe, ally = engine.state.actors[H.FOE], engine.state.actors[ALLY]
    assert charm_rules.opportunity(engine, foe, ally) is False and charm_rules.opportunity(engine, foe, engine.state.actors[ME]) is None
    # damage from the caster's side ends it
    engine.state.actors[H.FOE].armor_class = -50
    _act(engine, ALLY, "Fu (Short Axe) attack", H.FOE)
    assert "typed.captivated" not in _conds(engine.state.actors[H.FOE])


def _beauty_cast(suffix, name, *, dc=50, ally=True):
    engine = _beauty_arena(["tianxia.talent.beauty." + suffix], dc=dc, ally=ally)
    _act(engine, ME, "Catch the Eye", H.FOE)
    engine._remove_condition(engine.state.actors[H.FOE], "condition:typed.captivated", "test:preparation")
    return engine, _act(engine, ME, name, H.FOE)


def _attack_choices(engine, actor_id, target_id):
    engine.state.current_actor_id = actor_id
    actor = engine.state.actors[actor_id]
    actor.action_available = True
    return [c for c in engine.legal_candidates() if c.actor_id == actor_id and c.display_name == "Fu (Short Axe) attack"
            and target_id in c.target_ids]


def _picks(engine, ids):
    from combat.gate2_runtime_models import ReactionDecision
    seen = []

    def answer(request):
        if request["reaction_source_id"] == "choice:needle.beauty_targets":
            seen.append(request)
            return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                    reaction_source_id=request["reaction_source_id"], selection="USE", option_ids=tuple(ids)), None
        return None, None

    engine.set_reaction_provider(answer)
    return seen


def test_beauty_beyond_form_uses_the_players_bounded_targets_and_initial_save_immunity():
    engine = _beauty_arena(["tianxia.talent.beauty.beauty_beyond_form"], ally=True, dc=50)
    seen = _picks(engine, [H.FOE, ALLY])
    _act(engine, ME, "Beauty Beyond Form")
    assert seen and seen[0]["extension_choice"]["maximum_selections"] == min(2 * engine.state.actors[ME].proficiency_bonus, len(seen[0]["extension_choice"]["option_ids"]))
    assert "typed.charmed" in _conds(engine.state.actors[H.FOE])
    assert "typed.charmed" in _conds(engine.state.actors[ALLY])  # the printed targets are not restricted to enemies
    assert not _attack_choices(engine, H.FOE, ME)
    saved = _beauty_arena(["tianxia.talent.beauty.beauty_beyond_form"], dc=-40)
    _picks(saved, [H.FOE])  # The new compiled action asks for its creatures; choose the intended saver.
    _act(saved, ME, "Beauty Beyond Form")
    assert "typed.resist_ability" in _conds(saved.state.actors[H.FOE])
    saved.set_reaction_provider(None)
    H._ready(saved)
    events = _act(saved, ME, "Beauty Beyond Form")
    assert not [event for event in events if event.event_type == "SAVE_ROLLED" and event.actor_id == H.FOE]


def test_face_that_halts_the_army_captivates_all_chosen_targets_and_denies_reactions():
    engine = _beauty_arena(["tianxia.talent.beauty.face_that_halts_the_army"], ally=True, dc=50)
    seen = _picks(engine, [H.FOE, ALLY])
    _act(engine, ME, "Face That Halts the Army")
    assert seen[0]["extension_choice"]["maximum_selections"] == min(engine.state.actors[ME].proficiency_bonus, len(seen[0]["extension_choice"]["option_ids"]))
    for target in (H.FOE, ALLY):
        assert "typed.captivated" in _conds(engine.state.actors[target])
        assert not engine.state.actors[target].reaction_available
    saved = _beauty_arena(["tianxia.talent.beauty.face_that_halts_the_army"], dc=-40)
    _picks(saved, [H.FOE])
    _act(saved, ME, "Face That Halts the Army")
    assert "typed.captivated" in _conds(saved.state.actors[H.FOE])
    assert saved.state.actors[H.FOE].reaction_available
    _begin_turn(saved, ME)
    assert "typed.captivated" not in _conds(saved.state.actors[H.FOE])


def test_captive_audience_keeps_the_cone_and_separate_failure_success_mark_durations():
    engine = _beauty_arena(["tianxia.talent.beauty.captive_audience"], ally=True, dc=50)
    _picks(engine, [H.FOE])
    candidate = next(c for c in engine.legal_candidates() if c.display_name.startswith("Captive Audience at ") and c.destination is not None
                     and c.destination.x > 3 and c.destination.y == 6)
    engine.execute_intent(H.ActionIntent(intent_id="beauty-cone", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                         state_version=candidate.state_version, actor_id=ME, destination=candidate.destination))
    foe = engine.state.actors[H.FOE]
    assert "typed.captivated" in _conds(foe)
    held = next(c for c in foe.conditions.values() if c.condition_id.startswith("condition:typed.mark.beauty_mark"))
    assert held.expires_on.startswith("START_OF_SLOT_AT:")
    assert "typed.captivated" not in _conds(engine.state.actors[ALLY])


@pytest.mark.parametrize("suffix,name", [("court_of_one", "Court of One"), ("lotus_gaze_pacification", "Lotus Gaze Pacification"),
                                         ("beauty_that_ends_war", "Beauty That Ends War"), ("unbearable_splendor", "Unbearable Splendor")])
def test_beauty_charm_attack_bans_and_source_side_damage_endings(suffix, name):
    engine, _ = _beauty_cast(suffix, name)
    assert not _attack_choices(engine, H.FOE, ME)
    foe = engine.state.actors[H.FOE]
    foe.temporary_hp = 100
    engine._commit_damage(foe, 1, "PSYCHIC", "test:ally", ALLY, None, reaction_depth=2)
    assert "typed.charmed" not in _conds(foe)  # damage wholly absorbed by Temporary HP still breaks a fragile charm


def test_beauty_that_ends_war_successful_repeated_save_grants_immunity():
    engine, _ = _beauty_cast("beauty_that_ends_war", "Beauty That Ends War")
    foe = engine.state.actors[H.FOE]
    foe.saving_throws["WIS"] = 100
    engine._expire_typed_for_checkpoint("END_OF_TURN", H.FOE)
    assert "typed.charmed" not in _conds(foe)
    assert "typed.resist_ability" in _conds(foe)


def test_envious_glance_captivates_and_penalizes_only_first_other_target_attack_each_turn():
    engine, _ = _beauty_cast("envious_glance", "Envious Glance")
    assert "typed.captivated" in _conds(engine.state.actors[H.FOE])
    # AUTO52 2026-10-05: the Captivated declaration save now runs, so the creature has to make it before its first
    # hostile action of the turn. It saves here (the printed penalty clock is what this case is about).
    engine.state.actors[H.FOE].saving_throws["WIS"] = 100
    _begin_turn(engine, H.FOE)
    engine.state.actors[ALLY].armor_class = -50
    assert H._payloads(_strike(engine, H.FOE, ALLY), "ATTACK_ROLLED")[0]["mode"] == "DISADVANTAGE"
    engine.state.actors[H.FOE].action_available = True
    assert H._payloads(_strike(engine, H.FOE, ALLY), "ATTACK_ROLLED")[0]["mode"] == "NORMAL"


def test_envious_glance_re_aims_the_first_other_target_attack_at_the_charmer_when_the_declaration_save_fails():
    """"the first time on each of its turns that it targets a creature other than you with an attack ... it must make a
    Wisdom saving throw": AUTO52, the same Captivated bar Envious Glance imposes.
    AUTO52f1: the printed failure is the creature's own choice, and "choose you if legal" is now a real outcome --
    that attack is re-aimed at the charmer, not merely logged as such. It is asked at the attack's declaration, so
    only that one attack is affected, and the save is "the first time on each of its turns" and already spent."""
    engine, _ = _beauty_cast("envious_glance", "Envious Glance")
    _begin_turn(engine, H.FOE)
    engine.state.actors[ALLY].armor_class = -50
    events = _strike(engine, H.FOE, ALLY)
    reaimed = [e for e in events if e.event_type == "ATTACK_RETARGETED" and e.target_ids == (ME,)]
    assert reaimed, events
    assert reaimed[0].payload["original_target_id"] == ALLY
    assert [e for e in events if e.event_type == "PASSIVE_TRIGGERED"
            and (e.payload or {}).get("declaration_save")][0].payload["remedy"] == "redirect"
    assert not [e for e in events if e.event_type == "ATTACK_FORCED_MISS"], "the attack was re-aimed, not lost"
    assert _attack_choices(engine, H.FOE, ME)         # the charmer stays a legal target
    assert _attack_choices(engine, H.FOE, ALLY)       # a later attack is not withdrawn by the printed rule


def test_tears_like_pearls_repeats_on_ally_harm_not_at_turn_end():
    engine, _ = _beauty_cast("tears_like_pearls", "Tears Like Pearls")
    foe = engine.state.actors[H.FOE]
    held = _conds(foe)["typed.charmed"]
    assert "repeat_save" not in held.data
    assert not _attack_choices(engine, H.FOE, ME)
    engine.state.actors[ALLY].team_id = foe.team_id
    foe.saving_throws["WIS"] = 100
    engine._commit_damage(engine.state.actors[ALLY], 1, "PSYCHIC", "test:harm", ME, None, reaction_depth=2)
    assert "typed.charmed" not in _conds(foe)


def test_beauty_that_judges_wounds_the_judged_creature_for_the_harm_it_deals():
    # AUTO52 2026-10-05: the printed wound is answered from damage_dealt (the typed damage pipeline, after
    # defences), not from an event hook, so it is ordinary damage with its own riders -- which is what the owner
    # integration instruction that kept this line as GM work was waiting for.
    engine, _ = _beauty_cast("beauty_that_judges", "Beauty That Judges")
    foe = engine.state.actors[H.FOE]
    _begin_turn(engine, H.FOE)
    engine.state.actors[ALLY].armor_class = -50
    before = foe.current_hp
    events = _strike(engine, H.FOE, ALLY)
    # "your Proficiency Bonus + your key ability modifier", the caster's own compiled numbers
    numbers = next(a for a in engine.action_catalog.values() if a.display_name == "Beauty That Judges").parameters["typed"]["numbers"]
    assert foe.current_hp == before - (numbers["pb"] + numbers["key_mod"]), foe.current_hp
    # "This effect ends early if you damage the target": the caster's own wound ends the judgment.
    assert "typed.charmed" not in _conds(foe)
    action = next(a for a in engine.action_catalog.values() if a.display_name == 'Beauty That Judges')
    assert not [line for line in action.parameters['typed']['riders'] if 'by hand' in line]
    # the printed clock is the first time on each of its turns, and the charm is gone either way
    foe.action_available = True
    _strike(engine, H.FOE, ALLY)
    assert foe.current_hp == before - (numbers["pb"] + numbers["key_mod"])


def test_aura_of_unapproachable_elegance_affects_only_the_owners_marked_creatures():
    from combat import zones
    engine = _beauty_arena(["tianxia.talent.beauty.aura_of_unapproachable_elegance"], dc=50, ally=True)
    _act(engine, ME, "Catch the Eye", H.FOE)
    _act(engine, ME, "Aura of Unapproachable Elegance")
    assert (3, 6) in zones.difficult_cells(engine, engine.state.actors[H.FOE])
    assert not zones.difficult_cells(engine, engine.state.actors[ALLY])
    _begin_turn(engine, H.FOE)
    assert "typed.bar" in _conds(engine.state.actors[H.FOE])
    assert not _attack_choices(engine, H.FOE, ME)
    _begin_turn(engine, ME)
    assert "typed.bar" in _conds(engine.state.actors[H.FOE])  # expires on target's next start, not the owner's
    _begin_turn(engine, H.FOE)
    # It saves again in the aura; succeeding ends the prior bar without imposing another.
    engine.state.actors[H.FOE].saving_throws["WIS"] = 100
    _begin_turn(engine, H.FOE)
    assert "typed.bar" not in _conds(engine.state.actors[H.FOE])


def test_lotus_court_aura_rolls_at_turn_start_and_spends_first_roll_even_against_owner():
    engine = _beauty_arena(["tianxia.talent.beauty.lotus_court_aura"], dc=50, ally=True)
    events = _act(engine, ME, "Lotus Court Aura")
    assert not H._payloads(events, "SAVE_ROLLED")  # no save at casting
    _begin_turn(engine, H.FOE)
    assert "typed.bar" in _conds(engine.state.actors[H.FOE])
    engine.state.actors[ME].reaction_available = False
    first = _strike(engine, H.FOE, ME)
    assert H._payloads(first, "ATTACK_ROLLED")[0]["mode"] == "NORMAL"
    engine.state.actors[H.FOE].action_available = True
    assert H._payloads(_strike(engine, H.FOE, ALLY), "ATTACK_ROLLED")[0]["mode"] == "NORMAL"


def test_domain_of_perfect_moment_initial_mark_then_marked_turn_start_bar():
    from combat import zones

    engine = _beauty_arena(["tianxia.talent.beauty.domain_of_the_perfect_moment"], dc=50, ally=True)
    _picks(engine, [H.FOE])
    _act(engine, ME, "Domain of the Perfect Moment")
    assert typed_executor.bears_mark(engine.state.actors[H.FOE], ME, "Beauty Mark")
    assert "typed.charmed" in _conds(engine.state.actors[H.FOE])
    _begin_turn(engine, H.FOE)
    assert "typed.bar" in _conds(engine.state.actors[H.FOE])
    assert "typed.bar" not in _conds(engine.state.actors[ALLY])
    engine.state.round_number += 1
    before = len(engine.events)
    _begin_turn(engine, H.FOE)
    assert not H._payloads(engine.events[before:], "SAVE_ROLLED")
    assert "typed.bar" not in _conds(engine.state.actors[H.FOE])
    # A fresh activation has a fresh first-start allowance.
    for zone in zones.typed_zones(engine):
        zones.remove(engine, zone, "test:recast")
    _act(engine, ME, "Domain of the Perfect Moment")
    engine.state.round_number += 1
    before = len(engine.events)
    _begin_turn(engine, H.FOE)
    assert H._payloads(engine.events[before:], "SAVE_ROLLED")
    assert "typed.bar" in _conds(engine.state.actors[H.FOE])
    # An unmarked hostile start does not consume a later marked first start.
    engine.state.actors[ALLY].team_id = engine.state.actors[H.FOE].team_id
    before = len(engine.events)
    _begin_turn(engine, ALLY)
    assert not H._payloads(engine.events[before:], "SAVE_ROLLED")
    _act(engine, ME, "Catch the Eye", ALLY)
    engine.state.round_number += 1
    before = len(engine.events)
    _begin_turn(engine, ALLY)
    assert H._payloads(engine.events[before:], "SAVE_ROLLED")
    assert "typed.bar" in _conds(engine.state.actors[ALLY])


def test_face_that_halts_the_army_allows_the_caster_among_chosen_creatures():
    engine = _beauty_arena(["tianxia.talent.beauty.face_that_halts_the_army"], dc=50)
    _picks(engine, [ME])
    _act(engine, ME, "Face That Halts the Army")
    assert "typed.captivated" in _conds(engine.state.actors[ME])
    assert "typed.reaction_denied" in _conds(engine.state.actors[ME])


def test_unbearable_splendor_allows_only_one_activity_on_its_turn():
    from combat import typed_reactions
    engine, _ = _beauty_cast("unbearable_splendor", "Unbearable Splendor")
    _begin_turn(engine, H.FOE)
    assert not typed_reactions._can_react(engine, engine.state.actors[H.FOE])
    engine.state.actors[ALLY].armor_class = -50
    _strike(engine, H.FOE, ALLY)
    assert not [c for c in engine.legal_candidates() if c.actor_id == H.FOE and str(c.kind).endswith("MOVE")]


def test_red_lip_command_success_ends_its_mark():
    engine, _ = _beauty_cast("red_lip_command", "Red Lip Command", dc=-40)
    assert not typed_executor.bears_mark(engine.state.actors[H.FOE], ME, "Beauty Mark")


def test_world_adorning_gesture_does_not_create_difficult_terrain_from_the_negative_sentence():
    from combat import zones
    engine = _beauty_arena(["tianxia.talent.beauty.world_adorning_gesture"], dc=50)
    _act(engine, ME, "World-Adorning Gesture")
    assert zones.typed_zones(engine)
    assert not zones.difficult_cells(engine, engine.state.actors[H.FOE])


@pytest.mark.parametrize("cl,count", [(11, 2), (17, 3)])
def test_grace_that_shames_the_cruel_uses_printed_level_scaled_dice(cl, count):
    engine = _beauty_arena(["tianxia.talent.beauty.grace_that_shames_the_cruel"], dc=50, ally=True, cl=cl)
    # AUTO52 2026-10-05: Catch the Eye is saved here, so the creature bears the Beauty Mark this talent needs
    # without being Captivated (the Captivated declaration save is exercised by its own tests) and its own Wisdom
    # save below still fails, so the printed damage rolls.
    engine.state.actors[H.FOE].saving_throws["WIS"] = 100
    _act(engine, ME, "Catch the Eye", H.FOE)
    assert "typed.captivated" not in _conds(engine.state.actors[H.FOE])
    engine.state.actors[H.FOE].saving_throws["WIS"] = 0
    _begin_turn(engine, H.FOE)
    engine.state.actors[ALLY].armor_class = -50
    events = _strike(engine, H.FOE, ALLY)
    rolls = [event.payload for event in events if event.event_type == "DAMAGE_ROLLED"
             and event.source_definition_id == "tianxia.talent.beauty.grace_that_shames_the_cruel"]
    assert rolls and rolls[0]["expression"].startswith(f"{count}d8"), rolls


def test_jewel_mind_reflection_spends_two_cp_marks_and_captivates_the_saving_throw_source():
    engine = _beauty_arena(["tianxia.talent.beauty.jewel_mind_reflection"], dc=50,
                           foe_talents=["tianxia.talent.beauty.tears_like_pearls"])
    owner = engine.state.actors[ME]
    owner.saving_throws["WIS"] = 100
    resource = "resource:core.stamina"
    before = owner.resources[resource]
    _act(engine, H.FOE, "Tears Like Pearls", ME)
    foe = engine.state.actors[H.FOE]
    assert typed_executor.bears_mark(foe, ME, "Beauty Mark")
    assert "typed.captivated" in _conds(foe)
    assert owner.resources[resource] == before - 2


def test_turn_the_blade_aside_does_not_affect_a_charm_immune_attacker():
    engine = _beauty_arena([], dc=50)
    _act(engine, ME, "Catch the Eye", H.FOE)
    foe = engine.state.actors[H.FOE]
    engine.typed_passive_rows[H.FOE].append({"block":"condition_immunity", "conditions":["charmed"]})
    _begin_turn(engine, H.FOE)
    # All the rows are compiled on the real character; the reaction must be left out of the attack checkpoint.
    events = _strike(engine, H.FOE, ME)
    assert not [event for event in events if event.event_type == "REACTION_RESOLVED"
                and event.source_definition_id == "BEAUTY_BASE_TURN_THE_BLADE_ASIDE"]


def test_radiant_rivalry_watches_a_chosen_marked_creature_holds_one_mark_and_spends_for_plus_two_dc():
    from combat.ext import beauty_rivalry
    engine = _beauty_arena(["tianxia.talent.beauty.radiant_rivalry"], dc=-40)
    _act(engine, ME, "Catch the Eye", H.FOE)
    _act(engine, ME, "Radiant Rivalry")
    watch = _conds(engine.state.actors[ME])["typed.rivalry_watch"]
    assert watch.data["target_id"] == H.FOE
    _act(engine, ME, "Catch the Eye", H.FOE)
    assert "typed.rivalry_mark" in _conds(engine.state.actors[ME])
    events = _act(engine, ME, "Catch the Eye", H.FOE)
    assert H._payloads(events, "SAVE_ROLLED")[0]["dc"] == -38
    assert any(event.event_type == "CONDITION_REMOVED" and event.payload.get("condition_id") == beauty_rivalry.MARK for event in events)
    assert len([c for c in engine.state.actors[ME].conditions.values() if c.condition_id == beauty_rivalry.MARK]) == 1


def test_captivated_ends_as_soon_as_its_source_becomes_hidden():
    from combat import stealth
    engine = _beauty_arena([], dc=50)
    _act(engine, ME, "Catch the Eye", H.FOE)
    engine._apply_condition(engine.state.actors[ME], stealth.HIDDEN, "test:hidden", ME, expires_on="UNTIL_REMOVED", data={"stealth_total":30})
    assert "typed.captivated" not in _conds(engine.state.actors[H.FOE])
    assert typed_executor.bears_mark(engine.state.actors[H.FOE], ME, "Beauty Mark")


def test_catch_the_eye_resistance_belongs_to_one_caster_not_every_beauty_user():
    engine = _beauty_arena([], dc=-40, ally=True, ally_beauty=True)
    _act(engine, ME, "Catch the Eye", H.FOE)
    assert "typed.resist_ability" in _conds(engine.state.actors[H.FOE])
    other = _act(engine, ALLY, "Catch the Eye", H.FOE)
    assert H._payloads(other, "SAVE_ROLLED")[0]["mode"] == "NORMAL"
    own = _act(engine, ME, "Catch the Eye", H.FOE)
    assert H._payloads(own, "SAVE_ROLLED")[0]["mode"] == "ADVANTAGE"


def test_catch_the_eye_resistance_covers_variants_of_the_same_printed_ability():
    engine = _beauty_arena([], dc=-40)
    _act(engine, ME, "Catch the Eye", H.FOE)
    assert "typed.resist_ability" in _conds(engine.state.actors[H.FOE])
    original = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.display_name == "Catch the Eye")
    # A compiled augmentation changes the runtime action ID, retaining the printed mechanic in typed.source.
    variant = original.model_copy(deep=True, update={"source_definition_id": original.source_definition_id + ":variant_fixture",
                                                  "display_name":"Catch the Eye (variant fixture)"})
    engine.action_catalog[variant.source_definition_id] = variant
    actor = engine.state.actors[ME]
    actor.action_ids = (*actor.action_ids, variant.source_definition_id)
    events = _act(engine, ME, variant.display_name, H.FOE)
    assert H._payloads(events, "SAVE_ROLLED")[0]["mode"] == "ADVANTAGE"
