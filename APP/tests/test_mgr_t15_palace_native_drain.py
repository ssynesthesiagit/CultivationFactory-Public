"""Palace consumes native pressure provenance, through committed table actions."""
import pytest

from combat.factory_compiler import compile_character
from combat.ext.soul_warden import DRAIN
from combat.ext.taiyin_palace import FOUNDATION, PICK, STATE, protects
from tests.h1_support import sheet
from tests.cw2_service_support import seal
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload


def game(tmp_path):
    owner = sheet([], foundation=None)
    owner['foundation'] = {'foundation_id': FOUNDATION, 'stage': 'Perfected'}
    foe = sheet([DRAIN], cl=18, primary='Resonance', key='WIS', dc=40)
    foe['identity']['path'] = 'Spirit Awakening'
    # Keep the real drain's failure consequences from defeating the recipient.
    def durable(bundles):
        bundles[1]['actor_template']['maximum_hp'] = 500
        seal(bundles[1])
    return fixture(tmp_path, [], owner_bundle=compile_character(owner, actor_id=OWNER),
                   foe_sheet=foe, bundle_transform=durable, seed='PALACE-NATIVE-DRAIN')


def activate(combat, table, mid):
    settle(table, mid, candidate(combat, mid, 'Perfected — True Moon Yin Palace',
                                target=OWNER).candidate_id, choices={PICK: [ALLY]})


@pytest.mark.parametrize('active', [True, False])
def test_native_necrotic_soul_drain_save_after_table_reload(tmp_path, active):
    combat, table, mid = game(tmp_path)
    if active:
        activate(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == STATE for c in engine.state.actors[OWNER].conditions.values()) is active
    turn(table, mid, FOE)
    before = len(combat._load_session(mid).engine.events)
    settle(table, mid, candidate(combat, mid, 'Soul Drain and Death Custody: Necrotic',
                                target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    saves = [e for e in engine.events[before:] if e.event_type == 'SAVE_ROLLED' and e.actor_id == ALLY]
    assert len(saves) == 1
    assert saves[0].payload['mode'] == ('ADVANTAGE' if active else 'NORMAL')


@pytest.mark.parametrize('named, expected', [
    ({'damage:necrotic', 'pressure:drain'}, True),
    ({'damage:necrotic'}, False),
    ({'pressure:drain'}, False),
    ({'damage:psychic', 'pressure:drain'}, False),
])
def test_necrotic_drain_requires_both_native_provenance_facts(tmp_path, named, expected):
    combat, table, mid = game(tmp_path)
    activate(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert protects(engine, engine.state.actors[ALLY], engine.state.actors[FOE], named) is expected
