"""Failing-path regressions for the R3 pre-merge review."""
import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests import test_riders_lane3 as L


@pytest.mark.parametrize('foe_mode', ['MANUAL', 'LOCAL_AUTO'])
def test_court_zone_save_asks_owner_damage_type_at_table_turn_start(tmp_path, foe_mode):
    owner, foe = L.ME, L.H.FOE
    bundles = [compile_character(L.H._sheet('tianxia.sphere.alchemy',
        [L.CAULDRON, L.FURNACE] if a == owner else [], L.H.AXE_KIT, dc=L.FAIL, cl=15),
        actor_id=a, reaction_plan={'ask': True}) for a in (owner, foe)]
    # Prepared reagents are genesis fixture data, not a downtime crafting claim.
    for resource in bundles[0]['actor_template']['resources']:
        if resource['resource_id'] == L.STOCK:
            resource['initial'] = 4
    from combat.canonical import canonical_sha256
    bundles[0]['bundle_sha256'] = canonical_sha256({k:v for k,v in bundles[0].items() if k != 'bundle_sha256'})
    combat = CombatService(L.H.ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(bundles, [owner, foe], {owner:'team:a', foe:'team:b'},
        {owner:{'x':3,'y':6}, foe:{'x':4,'y':6}},
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'], [owner], [foe],
        control_modes={owner:'MANUAL', foe:'MANUAL'}, match_seed='R3I-ZONE',
        display_name='Court zone regression', maximum_rounds=5)['match_id']

    def act(cid, answers=()):
        menu = table.state(mid)['menu']
        return table.act(mid, cid, menu['decision_id'], menu['state_version'], 0, list(answers))

    while table.state(mid)['menu']['actor_id'] != owner:
        assert act(table.state(mid)['menu']['end_turn'])['status'] == 'COMMITTED'
    for name in ('Court of the Three-Legged Cauldron', 'World Within the Furnace: Fire'):
        engine = combat._load_session(mid).engine
        candidate = next(c for c in engine.legal_candidates()
            if c.display_name.startswith(name) and (name.startswith('Court') or c.destination == engine.state.actors[foe].position))
        answers = []
        for _ in range(8):
            result = act(candidate.candidate_id, answers)
            if result['status'] == 'COMMITTED':
                break
            assert result['status'] == 'REACTION_REQUIRED'
            prompt = result['reaction']
            answers.append({**prompt['context'], 'selection':'USE',
                'option_ids':[prompt['choice']['options'][0]['id']]})
        assert result['status'] == 'COMMITTED'
    combat.set_controller_mode(mid, actor_id=foe, controller_mode=foe_mode)
    cid = table.state(mid)['menu']['end_turn']
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    answers, court = [], None
    for _ in range(8):
        result = act(cid, answers)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED'
        prompt = result['reaction']
        context = prompt['context']
        source = context['reaction_source_id']
        if source == 'choice:needle.cauldron_damage':
            court = prompt
            assert context['reactor_id'] == owner
            assert all(s in prompt['moment'] for s in ('Court of the Three-Legged Cauldron', 'World Within the Furnace',
                combat._load_session(mid).engine.state.actors[foe].display_name))
            assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
            assert act(cid, answers)['reaction'] == prompt
            option = 'force'
        elif source == 'choice:needle.furnace_target':
            option = 'include'
        else:
            option = prompt['choice']['options'][0]['id']
        answers.append({**context, 'selection':'USE', 'option_ids':[option]})
    assert court is not None, 'Court must recognize the generated Alchemy zone trigger'
    assert result['status'] == 'COMMITTED'
    loaded = CombatService(L.H.ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.current_actor_id == foe
    amount = L._conds(loaded.engine.state.actors[owner])['typed.alchemy_court_damage'].data['amount']
    damage = [e.payload for e in loaded.engine.events if e.event_type == 'DAMAGE_COMMITTED'
              and foe in e.target_ids and e.payload['damage_type'] == 'FORCE']
    assert len(damage) == 1 and damage[0]['hp_damage'] == amount
    assert any('alchemy_court_spent' in c.condition_id for c in loaded.engine.state.actors[foe].conditions.values())
    assert loaded.mechanical.replay()['status'] == 'PASS'


def test_no_approach_filters_crossing_paths_even_with_legal_endpoints():
    from combat.gate2_runtime_models import Position
    from combat.ext.move_limits import CONDITION

    engine, _ = L.H._axes_cast(['TAL_AXES_POLEAXE_GATE'],
        L.STRIKE + 'Hook + Poleaxe Gate: Hold Off')
    actor = L.H._foe(engine)
    actor.position = Position(x=6, y=6)
    L._begin_turn(engine, actor.entity_id)
    protected = L.H._me(engine).position
    held = next(c for c in actor.conditions.values() if c.condition_id == CONDITION)
    # The unrestricted engine supplies actual paths, including crossing moves
    # whose endpoints are no closer. Restoring the real rider must remove them.
    del actor.conditions[held.instance_id]
    unrestricted = [c for c in engine.legal_candidates() if c.kind.value == 'MOVE']
    actor.conditions[held.instance_id] = held
    initial = engine.grid.distance_ft(actor.position, protected)
    crossing = [c for c in unrestricted if engine.grid.distance_ft(c.destination, protected) >= initial
        and any(engine.grid.distance_ft(p, protected) < initial for p in c.canonical_path)]
    assert crossing, 'Fixture must contain a path that defeats an endpoint-only check'
    legal = [c for c in engine.legal_candidates() if c.kind.value == 'MOVE']
    assert legal
    # Route selection may now choose a different equal-cost path for the same
    # endpoint/candidate id. Enforce the actual bound path, not the old id.
    by_id = {c.candidate_id: c for c in legal}
    for old in crossing:
        if old.candidate_id in by_id:
            assert by_id[old.candidate_id].canonical_path != old.canonical_path
    for candidate in legal:
        distances = [engine.grid.distance_ft(actor.position, protected),
                     *(engine.grid.distance_ft(p, protected) for p in candidate.canonical_path)]
        assert all(after >= before for before, after in zip(distances, distances[1:]))


def test_no_approach_rejects_an_approach_after_moving_farther_away():
    from types import SimpleNamespace
    from combat.gate2_runtime_models import Position
    from combat.ext.move_limits import gate

    engine, _ = L.H._axes_cast(['TAL_AXES_POLEAXE_GATE'],
        L.STRIKE + 'Hook + Poleaxe Gate: Hold Off')
    actor = L.H._foe(engine)
    actor.position = Position(x=6, y=6)
    # Both traversed cells are at least the starting distance away, but the
    # second step approaches after the first stepped away.
    path = [actor.position, Position(x=7,y=6), Position(x=6,y=7)]
    candidate = SimpleNamespace(kind='MOVE', destination=path[-1], canonical_path=path)
    assert gate(engine, actor, candidate, None) is False
    candidate.canonical_path = [actor.position, Position(x=7,y=6), Position(x=7,y=7)]
    candidate.destination = candidate.canonical_path[-1]
    assert gate(engine, actor, candidate, None) is None


@pytest.mark.parametrize('saved', [False, True])
def test_fragile_charm_breaks_on_multiple_type_save_without_damage(saved):
    """Select the intended creature using the reviewed Beauty choice transport
    (fix/hunt26 b4670368, FIX26r.review.md: explicit self recipients now stay
    selected; R23 21d34259 retained explicit Beauty target picks).
    """
    engine = L._beauty_arena(['tianxia.talent.beauty.beauty_beyond_form', 'ASH_TAL_ASHEN_BURIAL'],
        dc=L.FAIL, extra_spheres=('tianxia.sphere.ash',))
    L._picks(engine, [L.H.FOE])
    L._act(engine, L.ME, 'Beauty Beyond Form')
    engine.set_reaction_provider(None)
    foe = engine.state.actors[L.H.FOE]
    assert 'typed.charmed' in L._conds(foe)
    for kind in ('FIRE', 'NECROTIC', 'PSYCHIC'):
        engine._add_modifier(foe, 'test:immunity', 'damage_immunity', 'ADD', kind,
            'ALWAYS', expires_on='UNTIL_REMOVED')
    foe.saving_throws['STR'] = 100 if saved else -100
    before = foe.current_hp
    events = L._act(engine, L.ME, 'Ashen Burial', foe.entity_id)
    saves = [e for e in events if e.event_type == 'SAVE_ROLLED' and e.actor_id == foe.entity_id]
    assert saves and saves[0].payload['success'] == saved
    assert foe.current_hp == before
    assert not any(e.payload.get('hp_damage') or e.payload.get('temporary_hp_absorbed')
        for e in events if e.event_type == 'DAMAGE_COMMITTED' and foe.entity_id in e.target_ids)
    assert 'typed.charmed' not in L._conds(foe)


def test_ends_war_recast_rewrite_fate_failure_never_grants_immunity():
    from combat.gate2_runtime_models import ReactionDecision

    rewrite = 'tianxia.subpath.qi.divination_cultivator.feature.rewrite_fate'
    from combat.gate4_engine import Gate4ControllerEngine
    sheet = L.H._sheet(L.BEAUTY, ['tianxia.talent.beauty.beauty_that_ends_war', rewrite], L.H.AXE_KIT,
        dc=L.FAIL, cl=18)
    sheet['ability_scores_and_statistics']['primary_resource'] = {'name':'Qi', 'maximum':60}
    bundles = [compile_character(sheet, actor_id=L.ME, reaction_plan={'ask':True}),
        compile_character(L.H._sheet(None, [], L.H.AXE_KIT), actor_id=L.H.FOE)]
    engine = Gate4ControllerEngine(L.H.ROOT, match_seed='R3I-REWRITE', typed_bundles=bundles,
        roster_setup={'primary_actor_ids':[L.ME,L.H.FOE], 'team_by_actor':{L.ME:'team:a',L.H.FOE:'team:b'},
            'starting_positions':{L.ME:{'x':3,'y':6},L.H.FOE:{'x':4,'y':6}}})
    L._begin_turn(engine, L.ME)
    engine.typed_ask_reactors = {L.ME}
    # The first cast uses the raw failure. The recast uses the compiled reaction.
    engine.set_reaction_provider(lambda r: (ReactionDecision(checkpoint=r['checkpoint'],
        reactor_id=r['reactor_id'], reaction_source_id=r['reaction_source_id'], selection='DECLINE'), None))
    L._act(engine, L.ME, 'Beauty That Ends War', L.H.FOE)
    foe = engine.state.actors[L.H.FOE]
    assert 'typed.charmed' in L._conds(foe)
    foe.saving_throws['WIS'] = 100
    requests = []

    def answer(request):
        if request['reaction_source_id'] != 'reaction:typed.' + rewrite:
            return None, None
        requests.append(request)
        return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=L.ME,
            reaction_source_id=request['reaction_source_id'], selection='USE'), None

    engine.set_reaction_provider(answer)
    events = L._act(engine, L.ME, 'Beauty That Ends War', foe.entity_id)
    assert requests
    assert any(e.event_type == 'SAVE_ROLLED' and e.actor_id == foe.entity_id and e.payload['success'] for e in events)
    assert any(e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == rewrite for e in events)
    assert 'typed.charmed' in L._conds(foe)
    assert 'typed.resist_ability' not in L._conds(foe)
    assert not any(e.event_type == 'CONDITION_APPLIED' and e.payload['condition_id'] == 'condition:typed.resist_ability' for e in events)
    assert any(c.display_name == 'Beauty That Ends War' and foe.entity_id in c.target_ids
        for c in engine.legal_candidates()) is False  # this cast spent the Action
    engine.state.actors[L.ME].action_available = True
    assert any(c.display_name == 'Beauty That Ends War' and foe.entity_id in c.target_ids for c in engine.legal_candidates())


@pytest.mark.parametrize('initial_dc,final', [(L.PASS,'failure'), (L.FAIL,'success')])
def test_ends_war_recast_immunity_matches_final_outcome(initial_dc, final):
    engine, _ = L._beauty_cast('beauty_that_ends_war', 'Beauty That Ends War')
    foe = engine.state.actors[L.H.FOE]
    action = next(a for a in engine.action_catalog.values() if a.owner_id == L.ME and a.display_name == 'Beauty That Ends War')
    action.parameters['typed']['numbers']['save_dc'] = initial_dc
    engine._typed_roll_outcome = {foe.entity_id: final}
    events = L._act(engine, L.ME, 'Beauty That Ends War', foe.entity_id)
    immunity = [c for c in foe.conditions.values() if c.condition_id == 'condition:typed.resist_ability']
    assert len(immunity) == (1 if final == 'success' else 0)
    applied = [e for e in events if e.event_type == 'CONDITION_APPLIED' and e.payload['condition_id'] == 'condition:typed.resist_ability']
    assert len(applied) == len(immunity)
    from combat.typed_executor import active_save_pending
    assert not active_save_pending(engine, action.source_definition_id, foe.entity_id)


def test_axe_guard_break_applies_to_oa_during_defenders_reaction_step():
    from combat import typed_reactions
    from combat.gate4_engine import Gate4ControllerEngine
    from combat.gate2_runtime_models import ActionIntent, ReactionDecision, Position

    defender, third = L.H.FOE, 'actor:factory.third'
    bundles = [L._axes([], dc=L.FAIL),
        compile_character(L.H._sheet(L.BEAUTY, ['tianxia.talent.beauty.unapproachable_poise'],
            L.SHIELD_KIT, dc=L.FAIL), actor_id=defender, reaction_plan={'ask':True}),
        compile_character(L.H._sheet(None, [], L.H.AXE_KIT), actor_id=third)]
    engine = Gate4ControllerEngine(L.H.ROOT, match_seed='R3I-GUARD-OA', typed_bundles=bundles,
        roster_setup={'primary_actor_ids':[L.ME,defender,third],
            'team_by_actor':{L.ME:'team:a',third:'team:a',defender:'team:b'},
            'starting_positions':{L.ME:{'x':3,'y':6},defender:{'x':4,'y':6},third:{'x':5,'y':6}}})
    L._begin_turn(engine, defender)
    L._act(engine, defender, 'Catch the Eye', third)
    L._begin_turn(engine, L.ME)
    engine.state.actors[defender].armor_class = -50
    L._act(engine, L.ME, L.STRIKE + 'Split Guard', defender)
    assert 'typed.guard_broken' in L._conds(engine.state.actors[defender])
    engine.typed_ask_reactors = {defender}
    steps = []

    def answer(request):
        if request['reaction_source_id'] == 'choice:needle.rider_step':
            steps.append(request)
            ids = ('cell:4,8',)
        else:
            ids = ()
        return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=request['reactor_id'],
            reaction_source_id=request['reaction_source_id'], selection='USE', option_ids=ids), None

    engine.set_reaction_provider(answer)
    candidate = next(c for c in engine.legal_candidates() if c.kind.value == 'END_TURN')
    intent = ActionIntent(intent_id='third-off-turn-attack', actor_id=L.ME,
        decision_id=candidate.decision_id, candidate_id=candidate.candidate_id, state_version=candidate.state_version)
    # Another creature's off-turn attack provokes the marked defender's actual
    # Poise reaction step. The step avoids that attacker, but provokes our axe OA
    # while the axe user's current-turn Split Guard window is still active.
    before = len(engine.events)
    engine._active_intent = intent
    try:
        typed_reactions.opportunity_attack(engine, engine.state.actors[third], engine.state.actors[defender], intent)
    finally:
        engine._active_intent = None
    events = engine.events[before:]
    assert steps and engine.state.actors[defender].position == Position(x=4,y=8)
    assert engine.state.current_actor_id == L.ME
    oa = [e for e in events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == L.ME]
    assert len(oa) == 1
    assert engine.action_catalog[oa[0].source_definition_id].display_name == 'Opportunity Attack'
    assert oa[0].payload['target_ac'] == -52
    assert 'typed.guard_broken' not in L._conds(engine.state.actors[defender])
    # It was consumed by that OA, so the following axe attack faces Shield AC.
    events = L._act(engine, L.ME, 'Fu (Short Axe) thrown', defender)
    assert L._ac_seen(events) == [-50]


def test_guard_weapon_kind_is_independent_of_attack_labels():
    from combat.gate2_runtime_models import ActionDefinition

    engine = L._shield_duel([])
    L.H._use(engine, L.STRIKE + 'Split Guard', target=L.H.FOE)
    saber = compile_character(L.H._sheet(None, [], {'starting_kit':{'items':[
        {'item_id':'tianxia.mortal.weapon.dao', 'quantity':1}]} }), actor_id=L.ME)
    row = next(a for a in saber['action_catalog'] if a['parameters'].get('typed', {}).get('source') == 'tianxia.mortal.weapon.dao'
               and '#' not in a['source_definition_id'] and '.weapon.' in a['source_definition_id'] and a['economy'] == 'ACTION')
    # Labels are presentation fixtures; both attacks retain their compiled items.
    action = ActionDefinition.model_validate({**row, 'display_name':'Axe-looking saber attack'})
    engine.action_catalog[action.source_definition_id] = action
    engine.state.actors[L.ME].action_ids = (*engine.state.actors[L.ME].action_ids, action.source_definition_id)
    assert L._ac_seen(L._act(engine, L.ME, action.display_name, L.H.FOE)) == [-50]
    assert 'typed.guard_broken' in L._conds(engine.state.actors[L.H.FOE])
    axe = next(a for a in engine.action_catalog.values() if a.owner_id == L.ME and a.display_name == 'Fu (Short Axe) attack')
    axe = axe.model_copy(update={'display_name':'Plain strike'})
    engine.action_catalog[axe.source_definition_id] = axe
    assert L._ac_seen(L._act(engine, L.ME, axe.display_name, L.H.FOE)) == [-52]
    assert 'typed.guard_broken' not in L._conds(engine.state.actors[L.H.FOE])
