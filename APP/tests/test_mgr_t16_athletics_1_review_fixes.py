"""Cover-transfer aftermath and truces through recorded table commits/reloads."""
import pytest

from combat.typed_executor import bears_mark
from combat.ext.athletics import close_cover, close_attack_penalty, close_contact
from tests.test_mgr_t16_athletics_1_close import game, enter
from tests.auto8f1_table_support import OWNER, FOE, SECOND, candidate_id, reload_identical
from tests.test_a2_athletics_second_pass import add_action


def original_roll(monkeypatch):
    from combat.gate2_rolls import DeterministicRollAuthority as Roller
    raw = Roller.raw_d20
    def roll(self, **kwargs):
        result = raw(self, **kwargs)
        if kwargs['actor_id'] == SECOND and kwargs['reason'].startswith('ATTACK:'):
            return result.model_copy(update={'natural_result': 10, 'dice': (10,), 'total': 20})
        return result
    monkeypatch.setattr(Roller, 'raw_d20', roll)


def test_transferred_hit_conductive_rider_uses_recipient_and_retains_sequence_aim(tmp_path, monkeypatch):
    def prepare(bs):
        owner = next(b for b in bs if b['actor_id'] == OWNER)
        add_action(owner, 'Outside two attacks', [{'type': 'test_t16_outside_attack', 'count': 2}])
    g = game(tmp_path, transfer=True,
             talents_by_actor={SECOND: ['TAL_LIGHTNING_CONDUCTIVE_STRIKE']}, bundle_transform=prepare)
    enter(g)
    original_roll(monkeypatch)
    g['commit'](candidate_id(g['menu'](), 'Outside two attacks'))
    engine = g['stored_engine']()
    assert bears_mark(engine.state.actors[FOE], SECOND, 'Conductive')
    assert not bears_mark(engine.state.actors[OWNER], SECOND, 'Conductive')
    rolls = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == SECOND]
    assert len(rolls) == 2 and all(e.target_ids == (OWNER,) for e in rolls)
    assert len([e for e in engine.events if e.payload.get('attack_redirected')]) == 2
    assert engine.state.actors[OWNER].current_hp == engine.state.actors[OWNER].maximum_hp
    reload_identical(g['combat'], g['match_id'], g['userdata'])


def test_transferred_recipient_miss_applies_miss_effect_only_to_recipient(tmp_path, monkeypatch):
    def prepare(bs):
        next(b for b in bs if b['actor_id'] == FOE)['actor_template']['armor_class'] = 30
        owner = next(b for b in bs if b['actor_id'] == OWNER)
        add_action(owner, 'Outside miss rider', [{'type': 'test_t16_outside_attack',
            'on_miss': [{'type': 'mark', 'mark': 'Conductive', 'applies_to': 'target',
                         'duration': {'kind': 'until_start_of_your_next_turn'}}]}])
    g = game(tmp_path, transfer=True, bundle_transform=prepare)
    enter(g)
    original_roll(monkeypatch)
    g['commit'](candidate_id(g['menu'](), 'Outside miss rider'))
    engine = g['stored_engine']()
    assert any(e.payload.get('attack_redirected') for e in engine.events)
    assert bears_mark(engine.state.actors[FOE], SECOND, 'Conductive')
    assert not bears_mark(engine.state.actors[OWNER], SECOND, 'Conductive')
    assert all(a.current_hp == a.maximum_hp for a in engine.state.actors.values())
    reload_identical(g['combat'], g['match_id'], g['userdata'])


@pytest.mark.parametrize('relation', ['ALLY', 'NEUTRAL'])
def test_relation_change_stops_combat_effects_preserves_occupancy(tmp_path, monkeypatch, relation):
    g = game(tmp_path, transfer=True)
    enter(g)
    combat, mid = g['combat'], g['match_id']
    combat.change_relations(mid, change={'kind': 'ACTOR_RELATION', 'subject': OWNER,
        'other': FOE, 'relation': relation}, expected_state_version=g['stored_engine']().state.state_version)
    reload_identical(combat, mid, g['userdata'])
    engine = g['stored_engine']()
    owner, foe, outside = (engine.state.actors[who] for who in (OWNER, FOE, SECOND))
    assert close_contact(engine, owner, foe)
    assert engine._shared_occupancy_pair(OWNER, FOE)
    assert close_attack_penalty(engine, owner, outside) is None
    assert close_cover(engine, outside, owner, {}) is None
    assert close_cover(engine, outside, foe, {}) is None
    original_roll(monkeypatch)
    g['commit'](candidate_id(g['menu'](), 'Outside attack'))
    engine = g['stored_engine']()
    assert not any(e.payload.get('attack_redirected') for e in engine.events)
    roll = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == SECOND][-1]
    assert roll.payload['cover_bonus'] == 0
    assert engine.state.actors[FOE].current_hp == engine.state.actors[FOE].maximum_hp
    reload_identical(combat, mid, g['userdata'])
