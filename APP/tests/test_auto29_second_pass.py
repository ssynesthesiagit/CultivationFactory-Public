"""Second-pass Beastmastery durations and actual typed saving throws."""
import pytest

from tests.cw2_service_support import seal
from tests.worker2_support import OWNER, FOE, fixture, candidate
from tests.worker2_support import settle, settle_turn as turn, reload
from combat.factory_compiler import compile_character
from tests.h1_support import sheet

TAMER = 'TAL_BEASTMASTERY_BEAST_TAMER'
ENDURING = 'TAL_BEASTMASTERY_ENDURING_CONTROL'


def setup(kind):
    def prepare(bundles):
        for b, bonus in zip(bundles, [100, -100, 0]):
            b['actor_template']['initiative_bonus'] = bonus
            b['actor_template']['maximum_hp'] = 300
            seal(b)
        bundles[2]['actor_template']['creature_types'] = [kind]
        bundles[2]['actor_template']['saving_throws']['CHA'] = -100
        seal(bundles[2])
    return prepare


@pytest.mark.parametrize('owns', [True, False])
def test_enduring_control_uses_eight_hour_native_clock_after_table_reload(tmp_path, owns):
    combat, table, mid = fixture(tmp_path, [TAMER, *([ENDURING] if owns else [])],
        bundle_transform=setup('Beast'))
    initial = combat._load_session(mid).engine.state
    deadline = f'START_OF_SLOT_AT:{initial.round_number + (4800 if owns else 100)}:{initial.current_slot_index}'
    settle(table, mid, candidate(combat, mid, 'Beast Tamer', target=FOE).candidate_id)
    e = reload(tmp_path, mid)
    conditions = [c for c in e.state.actors[FOE].conditions.values() if c.source_actor_id == OWNER]
    assert any(c.condition_id == 'condition:typed.charmed' for c in conditions)
    assert conditions and all(c.expires_on == deadline for c in conditions)
    assert e.state.actors[OWNER].resources['resource:core.martial_focus'] == 0


@pytest.mark.parametrize('kind,bonus', [('Beast', 0), ('Monstrosity', 2)])
def test_beast_tamer_nonbeast_save_bonus_is_in_committed_save(tmp_path, kind, bonus):
    combat, table, mid = fixture(tmp_path, [TAMER, 'TAL_BEASTMASTERY_BROAD_SKILLS'],
        bundle_transform=setup(kind))
    settle(table, mid, candidate(combat, mid, 'Beast Tamer', target=FOE).candidate_id)
    e = reload(tmp_path, mid)
    saved = next(ev for ev in reversed(e.events) if ev.event_type == 'SAVE_ROLLED' and ev.actor_id == FOE)
    # The existing typed-save path applies a positive target bonus by lowering DC.
    assert saved.payload['dc'] == 16 - bonus
    assert saved.payload['modifier'] == -100


def test_shared_saddle_rhythm_is_once_each_round_not_once_each_fight(tmp_path):
    talent = 'TAL_BEASTMASTERY_SHARED_SADDLE_RHYTHM'
    def mounted(bundles):
        bundles[0] = compile_character(sheet([talent], cl=15), actor_id=OWNER,
            summon_plan={'mount': 'warhorse', 'beasts': []})
        setup('Beast')(bundles)
    combat, table, mid = fixture(tmp_path, [talent], foe_position={'x': 12, 'y': 6}, bundle_transform=mounted)
    for _ in range(2):
        settle(table, mid, candidate(combat, mid, "Mount: Dash").candidate_id)
        settle(table, mid, candidate(combat, mid, 'Shared Saddle Rhythm: mount gains Temporary HP').candidate_id)
        e = reload(tmp_path, mid)
        mount = next(a for a in e.state.actors.values() if (a.summon or {}).get('source') == 'rider')
        assert mount.temporary_hp == 4
        offered = {c.source_definition_id for c in e.legal_candidates()}
        assert not any(a.display_name.startswith('Shared Saddle Rhythm') for a in e.action_catalog.values()
            if a.source_definition_id in offered)
        settle(table, mid, table.state(mid)['menu']['end_turn'])
        turn(table, mid, OWNER)
