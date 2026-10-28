"""Close Quarters uses one post-correction cover rule for attached creatures."""
import pytest

from combat import ext
from combat.gate2_rolls import DeterministicRollAuthority
from combat.tabletop import normalize_map, to_battlefield
from tests.athletics_table_support import add_action
from tests.test_mgr_t16_athletics2_scale import SCALE, QUARTERS, climb
from tests.worker2_support import (
    OWNER, ALLY, FOE, fixture, settle, turn, reload, candidate, sealed_native_attack,
)

STATE = 'condition:test.athletics2.sf3'


@ext.effect('athletics2_sf3_setup')
def setup(ctx, eff):
    for who in (OWNER, ALLY):
        ctx.engine._apply_condition(ctx.engine.state.actors[who], STATE, ctx.source,
            ctx.actor.entity_id, expires_on='UNTIL_REMOVED',
            data={'independent_cover': eff['cover'] if who == OWNER else 0,
                  'correction': eff['correction'] if who == ALLY else 0})


@ext.hook('directional_cover')
def independent_cover(engine, attacker, target, context):
    return next((c.data['independent_cover'] for c in target.conditions.values()
                 if c.condition_id == STATE and c.data['independent_cover']), None)


@ext.hook('attack_miss_correction')
def correction(engine, actor, target, spec, roll, intent, total, armor_class):
    bonus = next((c.data['correction'] for c in actor.conditions.values()
                  if c.condition_id == STATE), 0)
    if bonus:
        return {'source_id': 'test:athletics2.sf3.correction',
                'label': 'Test attack correction', 'bonus': bonus}


def game(tmp_path, *, typed, cover, bonus):
    def prepare(bundles):
        for b in bundles:
            who = b['actor_id']
            b['skills'] = {'Athletics': 100, 'Acrobatics': 100} if who == OWNER else {
                'Athletics': -100, 'Acrobatics': -100}
            if who == OWNER:
                b['actor_template']['armor_class'] = 20
                add_action(b, 'Prepare cover regression', [{'type': 'athletics2_sf3_setup',
                                                           'cover': cover, 'correction': bonus}])
            elif who == FOE:
                b['actor_template'].update(size_category='Large', armor_class=1)
            elif typed:
                add_action(b, 'Outside regression attack', [{'type': 'attack', 'attack_kind': 'spell',
                    'attack_bonus': 10, 'range_ft': 60,
                    'on_hit': [{'type': 'damage', 'flat': 3, 'damage_types': ['force']},
                               {'type': 'condition', 'condition': 'restrained'}]}])
                b['action_catalog'][-1].update(target_kind='HOSTILE_ENTITY', range_ft=60)
            else:
                sealed_native_attack(b, 'Outside regression attack', attack_bonus=10)
    arena = to_battlefield(normalize_map({'display_name': 'Cover regression',
        'width_squares': 12, 'height_squares': 10, 'roofs': {'enabled': False}}))
    combat, table, mid = fixture(tmp_path, [SCALE, QUARTERS], bundle_transform=prepare,
        positions={OWNER: {'x': 3, 'y': 6}, FOE: {'x': 4, 'y': 6}, ALLY: {'x': 8, 'y': 6}},
        battlefield=arena, team_overrides={ALLY: 'team:opponents'}, named=True,
        seed='MGR-T16-SF3-' + tmp_path.name)
    from tests.auto8f1_table_support import candidate_id
    settle(table, mid, candidate_id(table.state(mid)['menu'], 'Prepare cover regression'))
    climb(table, mid)
    turn(table, mid, ALLY)
    return combat, table, mid


@pytest.mark.parametrize('typed', [False, True], ids=['native', 'typed'])
@pytest.mark.parametrize('cover,bonus,recipient', [
    (5, 0, None),       # Equal independent cover still defeats the original roll.
    (0, 3, OWNER),     # Correct against AC 25 before considering the carrier.
    (0, 0, FOE),       # Cover-only miss still transfers, including typed riders.
    (0, 1, FOE),       # A failed correction transfers its corrected total once.
], ids=['independent-cover', 'corrected-hit', 'transfer', 'corrected-transfer'])
def test_attached_close_quarters_cover_at_table(tmp_path, monkeypatch, typed, cover, bonus, recipient):
    combat, table, mid = game(tmp_path, typed=typed, cover=cover, bonus=bonus)
    raw = DeterministicRollAuthority.raw_d20
    def roll(self, **kwargs):
        result = raw(self, **kwargs)
        if kwargs['actor_id'] == ALLY and kwargs['reason'].startswith('ATTACK:'):
            return result.model_copy(update={'natural_result': 12, 'dice': (12,), 'total': 22})
        return result
    monkeypatch.setattr(DeterministicRollAuthority, 'raw_d20', roll)
    settle(table, mid, candidate(combat, mid, 'Outside regression attack', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    rolls = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == ALLY]
    assert len(rolls) == 1 and rolls[0].payload['target_ac'] == 25
    assert rolls[0].target_ids == (OWNER,)
    transfers = [e for e in engine.events if e.payload.get('attack_redirected')]
    assert len(transfers) == int(recipient == FOE)
    if transfers:
        assert transfers[0].target_ids == (FOE,)
        assert transfers[0].payload['roll_id'] == rolls[0].payload['roll_id']
        assert transfers[0].payload['total'] == 22 + bonus
    corrections = [e for e in engine.events if e.payload.get('attack_correction')]
    assert len(corrections) == int(bool(bonus))
    assert all(e.target_ids == (OWNER,) for e in corrections)
    for who in (OWNER, FOE):
        actor = engine.state.actors[who]
        assert (actor.current_hp < actor.maximum_hp) is (who == recipient)
        if typed:
            assert any(c.condition_id == 'condition:typed.restrained' for c in actor.conditions.values()) is (who == recipient)
    damage = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == ALLY]
    if recipient:
        assert damage and all(e.target_ids == (recipient,) for e in damage)
    else:
        assert not damage
