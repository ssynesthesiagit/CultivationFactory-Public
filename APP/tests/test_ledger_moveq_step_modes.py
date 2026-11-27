"""A material route may not use its Swim allowance to step onto dry ground."""
import pytest

from combat.diagnostics import CombatGate1Error
from combat.ext.athletics_momentum import routes
from combat.gate2_runtime_models import ActionIntent, Position
from combat.movement_speeds import speed
from combat.tabletop_service import TabletopError
from tests.test_a2_axes import (
    BOOST, FOE, HEW, KNEE, STRIKE, assert_grant_choice, assert_grant_move,
    earn_momentum, setup, use,
)
from tests.test_lock_choices import install
from tests.worker2_support import reload, turn


@pytest.mark.parametrize('stopped_walk', (False, True), ids=('both-modes', 'zero-walk'))
@pytest.mark.parametrize('separate_grant', (False, True), ids=('ordinary', 'momentum'))
def test_swim_route_cannot_pay_for_dry_step(tmp_path, monkeypatch, stopped_walk, separate_grant):
    monkeypatch.setenv('CF_EMBED_MENU', '0')
    install(monkeypatch, 'd20_result', lambda *args: {
        'source_id': 'test:knee-hit', 'operation': 'replace', 'natural_result': 20})
    water = {'region_id': 'water', 'terrain_type': 'OPEN', 'material': 'water',
             'material_only': True, 'movement_cost': 0,
             'cells': [{'x': x, 'y': y} for x in (4, 5) for y in (7, 8, 9)]}
    combat, table, mid = setup(tmp_path, [HEW, KNEE], dc=-100, foe_walk=10, foe_swim=30,
        foe_talents=(BOOST, 'TAL_ATHLETICS_TERRAIN_GLIDE'), terrain_regions=[water])
    if stopped_walk:
        use(combat, table, mid, STRIKE + " + Hook the Giant's Knee",
            choices={'choice:needle.movement_mode': 'walk'})
    turn(table, mid, FOE)

    engine = combat._load_session(mid).engine
    target = engine.state.actors[FOE]
    assert speed(engine, target, 'walk') == (0 if stopped_walk else 10)
    assert speed(engine, target, 'swim') == 30
    dry = Position(x=4, y=5)
    wet = Position(x=4, y=7)
    offered = (routes(engine, target, 'horizontal', 20) if separate_grant else engine.legal_candidates())
    swimming = {c.destination: c for c in offered if c.kind == 'MOVE' and c.metadata.get('movement_mode') == 'swim'}
    assert wet in swimming
    assert (dry in swimming) is not stopped_walk

    if separate_grant:
        earn_momentum(combat, table, mid)
        if stopped_walk:
            # Exercise settlement even when a previously issued route is
            # supplied directly, bypassing the now-correct grant menu.
            stale = swimming[wet].model_copy(update={
                'destination': dry, 'canonical_path': (target.position, dry)})
            intent = ActionIntent(intent_id='test:momentum', decision_id=stale.decision_id,
                candidate_id=stale.candidate_id, state_version=stale.state_version, actor_id=FOE,
                destination=stale.destination)
            with pytest.raises(CombatGate1Error) as exc:
                engine._resolve_movement(target, stale, intent, granted_ft=20, grant_source=BOOST)
            assert exc.value.diagnostic.code == 'GATE2_MOVEMENT_BUDGET_EXCEEDED'
            assert target.position == Position(x=4, y=6)
        destination = wet if stopped_walk else dry
        choice = 'choice:needle.athletics.momentum_destination'
        option = f'cell:{destination.x},{destination.y}'
        prompts = use(combat, table, mid, 'Unwilling Boost: use horizontal momentum', choices={choice: option})
        assert_grant_choice(prompts, choice, option)
        assert_grant_move(reload(tmp_path, mid), BOOST, 'swim', destination.model_dump(mode='json'))
        return

    state = table.state(mid)
    menu = state['menu']
    decision, version = menu['decision_id'], menu['state_version']
    origin = target.position.model_dump(mode='json')
    dry_path = [origin, dry.model_dump(mode='json')]
    if stopped_walk:
        with pytest.raises(TabletopError, match='more movement than remains'):
            table.preview_move_path(mid, decision, version, FOE, dry_path, 'swim')
        with pytest.raises(TabletopError):
            table.commit_move_path(mid, swimming[wet].candidate_id, decision, version, FOE, dry_path,
                                   state['last_sequence'], movement_mode='swim')
        assert reload(tmp_path, mid).state.actors[FOE].position == target.position

    destination = wet if stopped_walk else dry
    path = [origin, destination.model_dump(mode='json')]
    quote = table.preview_move_path(mid, decision, version, FOE, path, 'swim')['candidate']
    assert quote['movement_cost_ft'] == 5
    answers = []
    for _ in range(8):
        result = table.commit_move_path(mid, quote['candidate_id'], decision, version, FOE, path,
            state['last_sequence'], movement_mode='swim', reactions=answers)
        if result['status'] != 'REACTION_REQUIRED':
            break
        answers.append({**result['reaction']['context'], 'selection': 'DECLINE', 'option_ids': []})
    assert result['status'] == 'COMMITTED', result
    assert reload(tmp_path, mid).state.actors[FOE].position == destination
