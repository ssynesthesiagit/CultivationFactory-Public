"""Scoped canonical Alchemy regressions ported from f9bb6793.

Most cases exercise the deterministic engine directly; the explicitly named
persistence cases submit real saved intents and reload their tables.
"""
import importlib.util
from pathlib import Path
import pytest
from combat import typed_executor
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import Position
from combat.gate4_engine import Gate4ControllerEngine
_spec = importlib.util.spec_from_file_location('_alchemy_harness', Path(__file__).with_name('test_review_sw-athletics.py'))
H = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(H)
ME, FAIL, PASS = H.ME, H.FAIL, H.PASS
BITTER = 'TAL_ALCHEMY_BITTER_DREGS'
DREG = 'resource:named.bitter_dreg'
STOCK = 'resource:named.reagent_stock'
INTENSIFY = 'tianxia.talent.alchemy.formula_intensification'
CAULDRON = 'tianxia.talent.alchemy.court_of_the_three_legged_cauldron'
F2 = 'actor:factory.second_foe'


def _conds(actor):
    return {c.condition_id.removeprefix("condition:"): c for c in actor.conditions.values()}


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
    # This substitution fixture has spent its ordinary Long Rest stock already.
    actor = engine.state.actors[ME]
    engine._spend_resource(actor, STOCK, actor.resources.get(STOCK, 0), 'test:empty_reagents')
    engine._gain_resource(engine.state.actors[ME], DREG, 2, 'test:prepared_dregs')
    # Alchemy's Reagent Stock pool is sized full at compile time (PB + key modifier,
    # see combat/ext/alchemy_stock.py), so this arena spends the prepared uses to
    # reach the state these cases are about: no Reagent Stock in hand, which is
    # what makes the plain recipe's "one Reagent Stock" cost unaffordable and the
    # Bitter Dregs variant a real substitution.
    # test_bitter_dregs_prepared_stock_and_resolved_backlash_survive_table_commit_reload
    # below builds the same 0-stock arena through a real match's genesis setup.
    engine._spend_resource(engine.state.actors[ME], STOCK, engine.state.actors[ME].resources[STOCK], 'test:prepared_stock_spent')
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


def test_bitter_dregs_empty_area_and_medicine_do_not_trigger_all_success_backlash():
    from combat import ext

    engine = _bitter_arena()
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and
        a.display_name == 'Field Formula: Numbing Smoke + Bitter Dregs')
    # The candidate menu omits empty areas. Qualify the interpreter boundary
    # directly for a target list that became empty before effects resolve.
    ctx = typed_executor.Context(engine, engine.state.actors[ME], action, None, action.parameters['typed'], [], None)
    typed_executor.run_effects(ctx, action.parameters['typed']['effects'])
    ext.run('technique_final', ctx)
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


def _move_actor(engine, actor_id, destination):
    engine.state.current_actor_id = actor_id
    candidate = next(c for c in engine.legal_candidates() if c.destination == destination
                     and str(getattr(c.kind, "value", c.kind)) == "MOVE")
    before = len(engine.events)
    engine.execute_intent(H.ActionIntent(intent_id=f"move-{len(engine.events)}", actor_id=actor_id,
        decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
        state_version=candidate.state_version, destination=candidate.destination))
    return engine.events[before:]
