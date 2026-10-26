"""Review counterexamples at the table transaction and cold replay boundary."""
import pytest

from combat.gate4_adapters import ManualControllerAdapter
from tests import worker2_support as W
from tests.cw2_service_support import add_action, seal
from tests.test_auto2_sand import STORM, prepare
from tests.test_auto2_sand_palm import EDGE, PALM, bonus


def automatic(combat, table, mid, actor, candidate_id):
    """Select a legal AI action; keep the production reaction controller."""
    real = combat.controller

    class SelectedController:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _: (candidate_id, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(real, name)

    combat.set_controller_mode(mid, actor_id=actor, controller_mode='LOCAL_AUTO')
    combat.controller = SelectedController()
    try:
        result = table.auto_step(mid, table.state(mid)['last_sequence'])
        assert result['status'] == 'COMMITTED', result
    finally:
        combat.controller = real
    return result


@pytest.mark.parametrize('allies', [True, False])
@pytest.mark.parametrize('native', [False, True])
def test_local_auto_storm_exempts_only_current_perceived_allies(tmp_path, allies, native):
    c, t, m = W.fixture(tmp_path, [STORM], owner_dc=-100, ask=False, bundle_transform=prepare)
    if not allies:
        state = c._load_session(m).engine.state
        c.change_relations(m, change={'kind':'ACTOR_RELATION', 'subject':W.OWNER,
            'other':W.ALLY, 'relation':'ENEMY'}, expected_state_version=state.state_version)
    automatic(c, t, m, W.OWNER, W.candidate(c, m, 'Thousand-Mile Sandstorm Body').candidate_id)
    e = W.reload(tmp_path, m)
    zone = next(z for z in e.state.zones.values() if z.active and 'THOUSAND_MILE' in z.source_definition_id)
    assert zone.trigger_profile['profile']['ranged_exempt'] == ([W.ALLY] if allies else [])
    c.set_controller_mode(m, actor_id=W.OWNER, controller_mode='MANUAL')
    for actor, expected in [(W.ALLY, 'NORMAL' if allies else 'DISADVANTAGE'), (W.FOE, 'DISADVANTAGE')]:
        W.turn(t, m, actor)
        target = W.FOE if actor == W.ALLY else W.ALLY
        W.settle(t, m, W.candidate(c, m, 'Native Sand Bow' if native else 'Sand Test Bow', target=target).candidate_id)
        roll = next(x for x in reversed(W.reload(tmp_path, m).events)
                    if x.event_type == 'ATTACK_ROLLED' and x.actor_id == actor)
        assert roll.payload['mode'] == expected


def palm_fight(tmp_path, monkeypatch, native, *, retaliation=False, buried=False):
    original = W.sheet

    def sheet(mids, **kwargs):
        doc = original(mids, **kwargs)
        if EDGE in mids:
            doc.setdefault('spheres_and_talents', {})['cultivation_insight_record_ids'] = [PALM]
        return doc

    monkeypatch.setattr(W, 'sheet', sheet)

    def setup(bundles):
        prepare(bundles)
        bundles[0]['actor_template']['saving_throws']['CON'] = -100
        # Deterministic confirmed off-turn hit, rather than a random OA miss.
        for action in bundles[0]['action_catalog']:
            if action['source_definition_id'].endswith('.opportunity_attack'):
                action['parameters']['typed']['numbers']['attack_bonus'] = 100
        if native:
            source = W.sealed_native_attack(bundles[0], 'Palm Review Strike', range_ft=None,
                attack_bonus=100, count=1, sides=2, modifier=0)
            action = next(a for a in bundles[0]['action_catalog'] if a['source_definition_id'] == source)
            action['parameters']['attack_kind'] = 'weapon'
            action['economy'] = 'NONE'
        else:
            add_action(bundles[0], 'Palm Review Strike', [{'type':'attack', 'attack_kind':'weapon',
                'on_hit':[{'type':'damage', 'flat':1, 'damage_types':['bludgeoning']}]}],
                typed={'weapon':{'ability_modifier':2}, 'range_ft':None,
                       'numbers':{'pb':4, 'key_mod':2, 'cl':15, 'attack_bonus':100}})
        seal(bundles[0])

    c, t, m = W.fixture(tmp_path, [EDGE, STORM], bundle_transform=setup, owner_dc=-100,
        foe_sheet=original(['TAL_SAND_SAND_SHELL'] if retaliation else []),
        positions={W.OWNER:{'x':3,'y':6}, W.ALLY:{'x':3,'y':7}, W.FOE:{'x':4,'y':6}})
    if retaliation:
        W.turn(t, m, W.FOE)
        W.settle(t, m, W.candidate(c, m, 'Sand Shell').candidate_id)
        W.turn(t, m, W.OWNER)
    W.settle(t, m, W.candidate(c, m, 'Thousand-Mile Sandstorm Body').candidate_id,
             {'choice:needle.sandstorm_designated':None})
    if buried:
        W.settle(t, m, W.candidate(c, m, 'Prepare Burial', target=W.FOE).candidate_id)
    return c, t, m


@pytest.mark.parametrize('native', [False, True])
@pytest.mark.parametrize('buried,amount', [(False,4), (True,6)])
def test_palm_hit_receipt_survives_shell_retaliation_and_concentration_loss(tmp_path, monkeypatch, native, buried, amount):
    from combat.ext.sand_terrain import standing_in
    c, t, m = palm_fight(tmp_path, monkeypatch, native, retaliation=True, buried=buried)
    e = W.reload(tmp_path, m)
    assert e.state.actors[W.OWNER].concentration is not None
    assert all(standing_in(e, W.OWNER, e.state.actors[key]) for key in (W.OWNER, W.FOE))
    sequence = e.state.event_sequence
    prompts = W.settle(t, m, W.candidate(c, m, 'Palm Review Strike', target=W.FOE).candidate_id,
                       {'choice:needle.sand_glass_palm':'use'})
    e = W.reload(tmp_path, m)
    assert e.state.actors[W.OWNER].concentration is None
    assert not standing_in(e, W.OWNER, e.state.actors[W.OWNER])
    recent = [x for x in e.events if x.sequence > sequence]
    retaliation = next(x for x in recent if x.event_type == 'DAMAGE_COMMITTED' and x.actor_id == W.FOE)
    ended = next(x for x in recent if x.event_type == 'CONCENTRATION_ENDED' and x.actor_id == W.OWNER)
    hits = bonus(e)
    assert len(hits) == 1 and hits[0].payload['reduced_to'] == amount
    assert retaliation.sequence < ended.sequence < hits[0].sequence
    assert any(p['context']['reaction_source_id'] == 'choice:needle.sand_glass_palm' for p in prompts)


def test_palm_gets_another_use_on_a_real_intervening_creature_turn(tmp_path, monkeypatch):
    c, t, m = palm_fight(tmp_path, monkeypatch, False)
    W.settle(t, m, W.candidate(c, m, 'Palm Review Strike', target=W.FOE).candidate_id,
             {'choice:needle.sand_glass_palm':'use'})
    assert len(bonus(W.reload(tmp_path, m))) == 1
    W.turn(t, m, W.FOE)
    e = W.reload(tmp_path, m)
    assert e.state.current_actor_id == W.FOE
    assert not e.state.actors[W.OWNER].turn_flags.get('typed_once_turn:sand_glass_palm')
    move = next(x for x in c._load_session(m).engine.legal_candidates()
                if x.kind == 'MOVE' and x.destination and (x.destination.x, x.destination.y) == (5,6))
    prompts = W.settle(t, m, move.candidate_id, {'reaction:typed.opportunity_attack':'first',
                                               'choice:needle.sand_glass_palm':'use'})
    e = W.reload(tmp_path, m)
    assert e.state.current_actor_id == W.FOE
    assert len(bonus(e)) == 2
    assert any(p['context']['reaction_source_id'] == 'choice:needle.sand_glass_palm'
               and p['context']['reactor_id'] == W.OWNER for p in prompts)
    assert any(x.event_type == 'ATTACK_ROLLED' and x.actor_id == W.OWNER
               and 'opportunity' in x.source_definition_id for x in e.events)


@pytest.mark.parametrize('native', [False, True])
def test_palm_receipt_keeps_hit_time_buried_upgrade(tmp_path, monkeypatch, native):
    from combat import ext
    c, t, m = palm_fight(tmp_path, monkeypatch, native, buried=True)

    # A test-only damage-trigger producer ends burial between the hit and its
    # final rider. It uses the ordinary condition-removal event, not a state edit.
    def end_burial(engine, event_type, kwargs):
        if (event_type == 'DAMAGE_COMMITTED' and kwargs.get('actor_id') == W.OWNER
                and kwargs.get('target_ids') == (W.FOE,)
                and 'palm_review_strike' in kwargs.get('source_definition_id', '')
                and not (kwargs.get('payload') or {}).get('display_source_id')):
            engine._remove_condition(engine.state.actors[W.FOE], 'condition:typed.buried', 'test:burial-ended-on-damage')

    monkeypatch.setitem(ext._HOOKS, 'event', [*ext._HOOKS.get('event', []), end_burial])
    W.settle(t, m, W.candidate(c, m, 'Palm Review Strike', target=W.FOE).candidate_id,
             {'choice:needle.sand_glass_palm':'use'})
    e = W.reload(tmp_path, m)
    assert not any(x.condition_id == 'condition:typed.buried' for x in e.state.actors[W.FOE].conditions.values())
    assert len(bonus(e)) == 1 and bonus(e)[0].payload['reduced_to'] == 6


def test_manual_storm_keeps_enemy_choices_with_automatic_reaction_plan(tmp_path):
    c, t, m = W.fixture(tmp_path, [STORM], owner_dc=-100, ask=False, bundle_transform=prepare)
    prompts = W.settle(t, m, W.candidate(c, m, 'Thousand-Mile Sandstorm Body').candidate_id,
                       {'choice:needle.sandstorm_designated':[W.FOE]})
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.sandstorm_designated')
    assert {x['id'] for x in prompt['choice']['options']} == {W.ALLY, W.FOE}
    e = W.reload(tmp_path, m)
    zone = next(z for z in e.state.zones.values() if z.active and 'THOUSAND_MILE' in z.source_definition_id)
    assert zone.trigger_profile['profile']['ranged_exempt'] == [W.FOE]
