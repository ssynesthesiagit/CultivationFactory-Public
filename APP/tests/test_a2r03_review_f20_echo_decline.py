"""Standalone Generate Pack Echo works through declined table reactions."""
import pytest

from combat import pressure
from combat.gate2_rolls import DeterministicRollAuthority
from tests import auto8f1_table_support as t
from tests import test_a2r11_foundations as f

GENERATE = 'foundation.beast_echo_marrow_v0_2A.generate_pack_echo'


@pytest.mark.parametrize('talents', [
    [GENERATE, 'TAL_ATHLETICS_SURE_GRIP'],
    [GENERATE, 'TAL_BRUTE_MOUNTAIN_MOVING_PALM',
     'TAL_SPIRIT_COMPANIONS_BINDING_SEAL'],
], ids=['script-1', 'script-2'])
def test_standalone_scope_hit_generates_after_declining_reactions(tmp_path, monkeypatch, talents):
    monkeypatch.setattr(DeterministicRollAuthority, '_die', f._scripted_die)

    def prepare(bundles):
        for bundle in bundles:
            bundle['actor_template']['armor_class'] = 10
        foe = next(b for b in bundles if b['actor_id'] == t.FOE)
        # A real damage reaction window, explicitly declined through the table.
        foe['typed_reactions'].append({
            'feature_id': 'test:declinable_guard', 'name': 'Test Guard',
            'block': 'damage_reduction', 'resource_id': 'resource:core.stamina',
            'cost': 1, 'bonus': 1, 'dice': '', 'trigger': 'any_damage',
            'minimum_damage': 1,
            'requires_reaction': True, 'ask': True,
        })

    ctx = t.fixture(tmp_path, talents, seed='A2R03F20', allies=(t.SECOND,),
                    ask_actors=(t.FOE,), bundle_transform=prepare)
    before = ctx['stored_engine']()
    actor = before.state.actors[t.OWNER]
    pool = 'resource:named.pack_echo'
    assert actor.resources[pool] == 0
    _, prompts = f._play(
        ctx['table'], ctx['match_id'],
        f._candidate(ctx['table'], ctx['match_id'], 'Unarmed Strike', t.FOE),
        answer='DECLINE')
    assert any(p['reaction'] == 'Test Guard' for p in prompts)
    cold = ctx['stored_engine']()
    # Generate Pack Echo is a "No Action / Triggered" ability (printed text),
    # so the only reaction window is the declinable damage guard. The old
    # generic reaction row for the Echo is not offered as a second window.
    windows = [e for e in cold.events if e.event_type == 'REACTION_WINDOW_OPENED']
    assert len(windows) == 1, [e.event_type for e in cold.events]
    declined = [i for i, e in enumerate(cold.events) if e.event_type == 'REACTION_DECLINED']
    assert declined, [e.event_type for e in cold.events]
    # A declined reaction settles as a decline, never as a paid resolution.
    assert not any(e.event_type == 'REACTION_RESOLVED' for e in cold.events)
    assert any(e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == t.OWNER
               for e in cold.events)
    assert cold.state.actors[t.OWNER].resources[pool] == 1
    assert cold.state.actors[t.OWNER].turn_flags[pressure.CLOCK][pool]['count'] == 1
    gains = [i for i, e in enumerate(cold.events) if e.event_type == 'RESOURCE_GAINED'
             and e.actor_id == t.OWNER and e.source_definition_id == 'passive:' + GENERATE]
    assert len(gains) == 1
    # The Echo becomes available after the hit resolves (the printed
    # "available after the hit resolves" clause), not during the window.
    assert gains[0] > declined[-1]
    assert not any(e.event_type == 'RESOURCE_SPENT' and e.actor_id == t.FOE
                   for e in cold.events)
    t.reload_identical(ctx['combat'], ctx['match_id'], tmp_path)
