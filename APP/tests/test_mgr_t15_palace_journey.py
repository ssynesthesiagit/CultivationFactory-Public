"""Palace Long Rest recharge through public journey/combat transactions."""
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.retired_arena_support import HistoricalArenaWriter
from tests.worker2_support import candidate, settle, turn, reload
from combat.ext.taiyin_palace import SOURCE, FOUNDATION, PICK

A = 'actor:factory.palace_owner'
B = 'actor:factory.palace_foe'
NAME = 'Perfected — True Moon Yin Palace'


def test_real_long_rest_recovers_exact_palace_use_across_fights(tmp_path, monkeypatch):
    def document(self, pid):
        doc = sheet([], cl=15, name=pid)
        if pid == 'palace_owner':
            doc['foundation'] = {'foundation_id': FOUNDATION, 'stage': 'Perfected'}
        return doc

    monkeypatch.setattr(CombatService, '_factory_owner_sheet', document)
    fresh = lambda: CombatService(ROOT, tmp_path)
    # Pillar Arena is retired, so only the sealed-fixture writer may name it; play itself uses the sealed journey.
    service = HistoricalArenaWriter(ROOT, tmp_path)
    arena_id = 'battlefield:factory_pillar_arena'
    spots = {A: {'x': 3, 'y': 6}, B: {'x': 6, 'y': 6}}
    journey = service.create_journey(project_ids=['palace_owner', 'palace_foe'], arena_id=arena_id,
        positions=spots, base_paces={A: 5, B: 5}, control_modes={A: 'MANUAL', B: 'MANUAL'})
    jid = journey['journey_id']
    mid = fresh().journey_start_combat(jid, 0, {A: 'team:a', B: 'team:b'}, maximum_rounds=11)['match_id']
    combat = fresh()
    table = TabletopService(combat, tmp_path)
    turn(table, mid, A)
    settle(table, mid, candidate(combat, mid, NAME, target=A).candidate_id, choices={PICK: [A]})
    engine = reload(tmp_path, mid)
    used = next(e.payload['resource_id'] for e in engine.events
                if e.event_type == 'RESOURCE_SPENT' and SOURCE in e.source_definition_id)
    assert engine.state.actors[A].resources[used] == 0
    # Wait out the actual minute and end the encounter, with no GM effect-clear flag.
    for _ in range(30):
        if combat._load_session(mid).engine.state.terminal_result is not None:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    assert reload(tmp_path, mid).state.terminal_result is not None
    state = fresh().journey_state(jid)
    state = fresh().journey_resume(jid, state['revision'])
    assert state['actors'][A]['resources'][used] == 0
    # Starting the next fight does not refill a use paid before this Long Rest.
    second = fresh().journey_start_combat(jid, state['revision'], {A: 'team:a', B: 'team:b'}, maximum_rounds=1)['match_id']
    combat = fresh()
    table = TabletopService(combat, tmp_path)
    engine = reload(tmp_path, second)
    assert engine.state.actors[A].resources[used] == 0
    for _ in range(5):
        if combat._load_session(second).engine.state.terminal_result is not None:
            break
        settle(table, second, table.state(second)['menu']['end_turn'])
    state = fresh().journey_state(jid)
    state = fresh().journey_resume(jid, state['revision'])
    rested = fresh().journey_act(jid, state['revision'], A, 'long_rest', {})
    assert rested['actors'][A]['resources'][used] == 1
    assert rested['seconds'] >= 28800
    assert fresh().journey_state(jid) == rested
    third = fresh().journey_start_combat(jid, rested['revision'], {A: 'team:a', B: 'team:b'}, maximum_rounds=1)['match_id']
    assert reload(tmp_path, third).state.actors[A].resources[used] == 1
