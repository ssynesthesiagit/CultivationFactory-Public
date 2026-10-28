"""An actual acquired Aura retains recipients temporarily absent from the party."""
import json
import zipfile
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_mgr_t14_goruden_build import acquire
from tests.worker2_support import reload, settle, turn, candidate
from tests.test_mgr_t14_goruden import ready


def test_aura_does_not_refresh_recipient_when_party_changes(catalog_environment, monkeypatch, tmp_path):
    acquired = acquire(catalog_environment, monkeypatch)
    owner, friend, foe = 'actor:factory.gold', 'actor:factory.friend', 'actor:factory.foe'
    for pid, doc in [('gold', acquired), ('friend', sheet([], cl=18)), ('foe', sheet([], cl=18))]:
        folder = tmp_path / 'portable_characters' / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    def cold(): return CombatService(ROOT, tmp_path)
    cold().tabletop_maps.save({'display_name': 'Changing party', 'width_squares': 20,
                              'height_squares': 20, 'terrain': []})
    arena = next(k for k, v in cold().factory_arenas().items() if v['display_name'] == 'Changing party')
    positions = {owner: {'x': 3, 'y': 6}, friend: {'x': 4, 'y': 6}, foe: {'x': 15, 'y': 15}}
    def create(ids):
        return cold().create_journey(project_ids=ids, arena_id=arena,
            positions={a: p for a, p in positions.items() if a.removeprefix('actor:factory.') in ids},
            base_paces={a: 30 for a in positions if a.removeprefix('actor:factory.') in ids})
    state = create(['gold', 'friend', 'foe'])
    zone_id = None
    for stage, ids in enumerate((['gold', 'friend', 'foe'], ['gold', 'foe'], ['gold', 'friend', 'foe'])):
        if stage:
            old_id = state['journey_id']
            state = cold().journey_act(old_id, state['revision'], owner, 'finish', {})
            assert cold().journey_verify(old_id)['status'] == 'PASS'
            state = create(ids)
        jid = state['journey_id']
        teams = {a: ('team:foe' if a == foe else 'team:gold') for a in state['actors']}
        state = cold().journey_start_combat(jid, state['revision'], teams, maximum_rounds=2 if stage==0 else 1)
        mid = state['match_id']; table = TabletopService(cold(), tmp_path)
        ready(table, tmp_path, mid)
        if stage == 0:
            turn(table, mid, owner)
            settle(table, mid, candidate(cold(), mid, 'Golden Aura').candidate_id)
            zone_id = next(z.zone_id for z in reload(tmp_path, mid).state.zones.values() if z.active and z.owner_id == owner)
        assert any(z.active and z.zone_id == zone_id for z in reload(tmp_path, mid).state.zones.values())
        for _ in range(10):
            if reload(tmp_path, mid).state.terminal_result is not None: break
            settle(table, mid, table.state(mid)['menu']['end_turn'])
        e = reload(tmp_path, mid)
        assert e.state.terminal_result is not None
        benefits = [ev for ev in e.events if ev.event_type == 'TEMP_HP_GRANTED' and friend in ev.target_ids]
        assert bool(benefits) == (stage == 0)
        state = cold().journey_resume(jid, cold().journey_state(jid)['revision'])
        assert cold().journey_verify(jid)['status'] == 'PASS'
