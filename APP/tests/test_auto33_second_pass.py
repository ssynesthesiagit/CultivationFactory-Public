"""Yin's reduction follow-ups consume committed amounts and native timed ownership."""
import pytest

from combat.typed_executor import bears_mark
from tests.cw2_service_support import add_action, seal
from tests.worker2_support import OWNER, FOE, fixture, candidate, act, settle, reload, turn

BORROWED = 'TAL_YIN_BORROWED_CONSEQUENCE'
RETURN = 'TAL_YIN_RETURN_THE_OVEREXTENSION'
BRIGHT = 'TAL_YIN_STILL_THE_BRIGHT_STRIKE'
FORCE = 'TAL_YIN_SPENDING_A_WANING_MARK#diminish_force'


def fight(tmp_path, talents, *, amount=5, kind='cold', yang=False, cl=15, qi=100, ask=True):
    def prepare(bundles):
        for bundle, initiative in zip(bundles, [100, -100, 0]):
            bundle['actor_template']['initiative_bonus'] = initiative
            bundle['actor_template']['maximum_hp'] = 300
            seal(bundle)
        next(r for r in bundles[0]['actor_template']['resources'] if r['resource_id'] == 'resource:core.qi')['initial'] = qi
        seal(bundles[0])
        add_action(bundles[2], 'Deal packet', [{'type': 'damage', 'flat': amount,
            'damage_types': [kind], 'applies_to': 'target'}], typed={'yang_aspected': yang})
        add_action(bundles[2], 'Replace temporary HP', [{'type': 'temp_hp', 'flat': 20, 'applies_to': 'target'}])
    combat, table, mid = fixture(tmp_path, talents or ['TAL_YIN_WOUND_THAT_REFUSES_DAWN'], cl=cl,
                                seed='YIN-SECOND-PASS', bundle_transform=prepare, ask=ask)
    settle(table, mid, candidate(combat, mid, 'Mark the Waning', target=FOE).candidate_id)
    reload(tmp_path, mid)
    turn(table, mid, FOE)
    return combat, table, mid


def reduction(engine):
    receipt = next(e for e in engine.events if e.event_type == 'REACTION_RESOLVED'
                   and e.source_definition_id == FORCE and e.payload.get('checkpoint') == 'DAMAGE_APPLICATION')
    return receipt.payload['pending_before'] - receipt.payload['pending_after']


@pytest.mark.parametrize('kind,yang,owned,replace', [
    ('cold', False, True, False), ('fire', False, True, False),
    ('radiant', False, True, False), ('thunder', False, True, False),
    ('cold', True, True, False), ('cold', False, False, False),
    ('cold', False, True, True)])
def test_borrowed_actual_reduction_type_bonus_and_owned_expiry(tmp_path, kind, yang, owned, replace):
    combat, table, mid = fight(tmp_path, [BORROWED] if owned else [], kind=kind, yang=yang)
    settle(table, mid, candidate(combat, mid, 'Deal packet', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    cut = reduction(engine)
    assert cut == 5  # The three-die quote is larger, but only five damage existed.
    gains = [e for e in engine.events if e.event_type == 'TEMP_HP_GRANTED' and e.source_definition_id == BORROWED]
    expected = cut // 2 + (4 if kind in {'fire', 'radiant', 'thunder'} or yang else 0)
    assert bool(gains) == owned
    if owned:
        assert gains[-1].payload['offered'] == expected
        assert engine.state.actors[OWNER].temporary_hp == expected
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == 100
    assert not bears_mark(engine.state.actors[FOE], OWNER, 'Waning Mark')
    if replace:
        settle(table, mid, candidate(combat, mid, 'Replace temporary HP', target=OWNER).candidate_id)
        reload(tmp_path, mid)
        turn(table, mid, OWNER)
        assert reload(tmp_path, mid).state.actors[OWNER].temporary_hp == 20
    else:
        turn(table, mid, OWNER)
        assert reload(tmp_path, mid).state.actors[OWNER].temporary_hp == 0


@pytest.mark.parametrize('choice,owned,qi,cl,amount', [
    ('cold', True, 100, 15, 5), ('necrotic', True, 100, 15, 5),
    ('psychic', True, 100, 15, 5), (None, True, 100, 15, 5),
    (None, False, 100, 15, 5), (None, True, 1, 15, 5),
    ('cold', True, 100, 1, 100)])
def test_return_actual_cut_choice_cap_cost_and_decline(tmp_path, choice, owned, qi, cl, amount):
    combat, table, mid = fight(tmp_path, [RETURN] if owned else [], qi=qi, cl=cl, amount=amount)
    prompts = settle(table, mid, candidate(combat, mid, 'Deal packet', target=OWNER).candidate_id,
                     {'choice:needle.yin_return_overextension': choice})
    engine = reload(tmp_path, mid)
    asked = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.yin_return_overextension']
    assert bool(asked) == (owned and qi >= 2)
    damage = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
              and e.source_definition_id == RETURN]
    assert bool(damage) == bool(choice)
    if choice:
        assert damage[0].target_ids == (FOE,)
        assert damage[0].payload['hp_damage'] == min(reduction(engine), 3 * cl)
        assert damage[0].payload['damage_type'].lower() == choice
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == qi - (2 if choice else 0)
    assert engine.state.actors[OWNER].reaction_available
    assert not bears_mark(engine.state.actors[FOE], OWNER, 'Waning Mark')


@pytest.mark.parametrize('owned', [True, False])
def test_still_bright_spent_force_slows_until_subject_start(tmp_path, owned):
    combat, table, mid = fight(tmp_path, [BRIGHT] if owned else [])
    settle(table, mid, candidate(combat, mid, 'Deal packet', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    slowed = [m for m in engine.state.actors[FOE].modifiers.values() if m.source_definition_id == BRIGHT]
    assert bool(slowed) == owned
    if owned:
        assert slowed[0].value == -10
        assert slowed[0].expires_on == 'START_OF_SOURCE_NEXT_TURN'
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, FOE)
    assert not any(m.source_definition_id == BRIGHT for m in reload(tmp_path, mid).state.actors[FOE].modifiers.values())


def test_return_preview_repeats_without_cost_and_automatic_route(tmp_path):
    for ask in (True, False):
        path = tmp_path / str(ask)
        combat, table, mid = fight(path, [RETURN, BORROWED], ask=ask)
        if not ask:
            combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
        attack = candidate(combat, mid, 'Deal packet', target=OWNER)
        before = combat._load_session(mid).engine.state.model_dump(mode='json')
        preview = act(table, mid, attack.candidate_id)
        if ask:
            assert preview['status'] == 'REACTION_REQUIRED', preview
            assert preview['reaction']['context']['reaction_source_id'] == 'choice:needle.yin_return_overextension'
            assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
            assert act(table, mid, attack.candidate_id)['reaction'] == preview['reaction']
            settle(table, mid, attack.candidate_id, {'choice:needle.yin_return_overextension': 'cold'})
        else:
            assert preview['status'] == 'COMMITTED', preview
        engine = reload(path, mid)
        assert engine.state.actors[OWNER].resources['resource:core.qi'] == 98
        assert engine.state.actors[OWNER].temporary_hp == 2
        assert engine.state.actors[FOE].current_hp == 295
        assert len([e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
                    and e.source_definition_id == RETURN]) == 1
