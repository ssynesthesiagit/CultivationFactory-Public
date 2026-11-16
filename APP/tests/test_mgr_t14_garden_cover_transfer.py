"""Garden riders follow the current roll through native Close Quarters cover.

Both the absent-history crash and stale same-source lookup are exercised through
accepted table actions, persisted receipts, and a cold mechanical replay.
"""
import pytest

from combat.factory_compiler import compile_character
from combat.ext.foundation_context import CONTEXT
from combat.gate2_rolls import DeterministicRollAuthority
from tests.h1_support import sheet
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload
from tests.test_mgr_t14_garden_sum import GARDEN, GARDEN_NAME, FOUNDATION

DAMAGE = 'choice:needle.ash_garden.damage'


@pytest.mark.parametrize('earlier_same_source', [False, True])
def test_redirected_garden_hit_commits_current_roll_and_cold_reloads(tmp_path, monkeypatch, earlier_same_source):
    doc = sheet(['FIRE_TAL_FLAME_LASH'], cl=5, name='Garden owner')
    doc['foundation'] = {'foundation_id': FOUNDATION, 'stage': 'Perfected',
        'resource': {'name': 'Funeral Ash', 'resource_id': 'tianxia.resource.funeral_ash',
                     'maximum': 1, 'current': 0}}
    doc['ability_scores_and_statistics']['technique_attack_bonus'] = 10
    owner = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    foe = sheet([], cl=5, name='Cover recipient')
    foe['ability_scores_and_statistics']['hit_points']['maximum'] = 200

    def prepare(bundles):
        for bundle in bundles:
            who = bundle['actor_id']
            if who in (ALLY, FOE):
                bundle['actor_template']['armor_class'] = 20 if who == ALLY else 1
                bundle.setdefault('skills', {}).update(
                    Acrobatics=100 if who == ALLY else -100, Athletics=-100)

    # Fix only the attack die boundary; previews and replay retain their native
    # deterministic roll IDs and modifier arithmetic. The owner's +10 and die
    # 10 total 20: hit the recipient but miss AC20 +2 cover. An inconsistent
    # natural/modifier/total can be normalized by the native roll checkpoints.
    raw = DeterministicRollAuthority.raw_d20

    def roll(self, **kwargs):
        result = raw(self, **kwargs)
        if kwargs['reason'].startswith('ATTACK:'):
            return result.model_copy(update={'natural_result': 10, 'dice': (10,),
                'total': 10 + kwargs['modifier']})
        return result

    monkeypatch.setattr(DeterministicRollAuthority, 'raw_d20', roll)
    combat, table, mid = fixture(tmp_path, [], owner_bundle=owner, foe_sheet=foe, named=True,
        ally_talents=('FIRE_TAL_FLAME_LASH', 'TAL_ATHLETICS_CLOSE_QUARTERS_TRAINING'),
        team_overrides={ALLY: 'team:third'}, bundle_transform=prepare,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 5, 'y': 6}, FOE: {'x': 6, 'y': 6}},
        seed='GARDEN-COVER-' + str(earlier_same_source))

    def reach_turn(who):
        for _ in range(16):
            menu = table.state(mid)['menu']
            if menu['actor_id'] == who:
                return
            settle(table, mid, menu['end_turn'], choices={CONTEXT: 'unknown'})
        raise AssertionError('actor turn not reached')

    if earlier_same_source:
        settle(table, mid, candidate(combat, mid, 'Flame Lash', target=FOE).candidate_id)
        settle(table, mid, table.state(mid)['menu']['end_turn'], choices={CONTEXT: 'unknown'})
        reach_turn(OWNER)
    settle(table, mid, candidate(combat, mid, GARDEN_NAME, target=OWNER).candidate_id)
    settle(table, mid, table.state(mid)['menu']['end_turn'], choices={CONTEXT: 'unknown'})
    reach_turn(ALLY)
    if not earlier_same_source:
        # A different actor wounds the recipient without creating an owner roll.
        settle(table, mid, candidate(combat, mid, 'Flame Lash', target=FOE).candidate_id)
    # Flame Lash wounds AND displaces its target. Enter its committed current
    # square rather than the now-empty starting square; every step is native.
    for _ in range(6):
        current = reload(tmp_path, mid)
        provider, recipient = current.state.actors[ALLY], current.state.actors[FOE]
        if provider.position == recipient.position:
            break
        dx = (recipient.position.x > provider.position.x) - (recipient.position.x < provider.position.x)
        dy = (recipient.position.y > provider.position.y) - (recipient.position.y < provider.position.y)
        destination = {'x': provider.position.x + dx, 'y': provider.position.y + dy}
        move = next(m for m in table.state(mid)['menu']['moves'] if m['destination'] == destination)
        settle(table, mid, move['candidate_id'])
    else:
        raise AssertionError('Native movement did not reach the displaced cover recipient')
    settle(table, mid, table.state(mid)['menu']['end_turn'], choices={CONTEXT: 'unknown'})
    reach_turn(OWNER)
    before = reload(tmp_path, mid)
    first = before.state.event_sequence
    assert 0 < before.state.actors[FOE].current_hp < before.state.actors[FOE].maximum_hp
    from combat.ext.athletics import close_contact
    assert close_contact(before, before.state.actors[ALLY], before.state.actors[FOE]), 'Native shared-space entry required'
    prompts = settle(table, mid, candidate(combat, mid, 'Flame Lash', target=ALLY).candidate_id,
                     choices={CONTEXT + '.detail': 'battlefield', DAMAGE: 'poison'})
    engine = reload(tmp_path, mid)
    events = [e for e in engine.events if e.sequence > first]
    attack, = [e for e in events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER]
    assert (attack.payload['modified_total'], attack.payload['target_ac'], attack.payload['cover_bonus']) == (20, 22, 2), attack.payload
    expected = ('ash_garden_confirmed_hit', 'ash_garden_damage_choice', 'ash_garden_damage_delivered')
    counts = {'transfer': sum(bool(e.payload.get('attack_redirected')) for e in events),
        **{kind: sum(e.payload.get('fact_kind') == kind for e in events) for kind in expected}}
    assert all(count == 1 for count in counts.values()), counts
    transfer, = [e for e in events if e.payload.get('attack_redirected')]
    receipt, = [e for e in events if e.payload.get('fact_kind') == 'ash_garden_confirmed_hit']
    choice, = [e for e in events if e.payload.get('fact_kind') == 'ash_garden_damage_choice']
    delivery, = [e for e in events if e.payload.get('fact_kind') == 'ash_garden_damage_delivered']
    assert attack.target_ids == (ALLY,) and transfer.target_ids == (FOE,)
    assert all(e.payload['roll_id'] == attack.payload['roll_id'] for e in (transfer, receipt, choice, delivery))
    earlier = [e for e in before.events if e.event_type == 'ATTACK_ROLLED'
               and e.actor_id == OWNER and e.source_definition_id == attack.source_definition_id
               and e.target_ids == (FOE,)]
    assert bool(earlier) == earlier_same_source
    assert all(e.payload['roll_id'] != attack.payload['roll_id'] for e in earlier)
    packets = [e for e in events if e.event_type == 'DAMAGE_COMMITTED']
    garden, = [e for e in packets if e.payload.get('display_source_id') == GARDEN]
    assert garden.target_ids == (FOE,) and garden.payload['damage_type'].lower() == 'poison'
    assert garden.payload['rolled_or_pending_damage'] == engine.state.actors[OWNER].proficiency_bonus
    assert all(e.target_ids == (FOE,) for e in packets)
    assert before.state.actors[FOE].current_hp - engine.state.actors[FOE].current_hp == sum(
        e.payload['hp_damage'] for e in packets)
    assert engine.state.actors[ALLY].current_hp == before.state.actors[ALLY].current_hp
    question, = [p for p in prompts if p['context']['reaction_source_id'] == DAMAGE]
    assert question['affected'] == engine.state.actors[FOE].display_name
