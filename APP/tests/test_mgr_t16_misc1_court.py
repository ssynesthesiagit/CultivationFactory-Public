"""Grave Court location information is a live, caster-owned domain grant."""
import pytest

from combat import senses
from combat.canonical import canonical_sha256
from combat.ext.death_riders import COURT_ID, court_locations
from tests.worker2_support import OWNER, ALLY, FOE, candidate, fixture, reload, settle, turn

DARK = ['DARK_BASE_DARKNESS', 'TAL_DARK_PURE_DARKNESS']


@pytest.mark.parametrize('owns', [True, False])
def test_grave_court_knows_creature_location_without_granting_sight(tmp_path, owns):
    combat, table, mid = fixture(tmp_path, [COURT_ID] if owns else [],
        ally_talents=DARK, seed='T16-GRAVE-LOCATION'+str(owns),
        battlefield_transform=lambda arena: arena.update(terrain_regions=[]))
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Shape Darkness: Pure Darkness').candidate_id)
    settle(table, mid, candidate(combat, mid, 'Darkness', at=(6, 6)).candidate_id)
    turn(table, mid, OWNER)
    if owns:
        row = next(c for c in combat._load_session(mid).engine.legal_candidates()
                   if 'Court of the Ninth Grave' in c.display_name)
        settle(table, mid, row.candidate_id)
    engine = reload(tmp_path, mid)
    viewer, target = engine.state.actors[OWNER], engine.state.actors[FOE]
    assert not senses.perceives(engine, viewer, target, sight_only=True)
    assert (court_locations(engine, viewer, target) is True) is owns
    assert court_locations(engine, engine.state.actors[ALLY], target) is None
    if owns:
        assert senses.pinpoints(engine, viewer, target)
        turn(table, mid, FOE)
        engine = combat._load_session(mid).engine
        move = next(c for c in engine.legal_candidates() if c.kind == 'MOVE'
                    and c.destination and (c.destination.x,c.destination.y,c.destination.z)==(10,6,0))
        settle(table, mid, move.candidate_id)
        engine = reload(tmp_path,mid)
        assert court_locations(engine,engine.state.actors[OWNER],engine.state.actors[FOE]) is None


@pytest.mark.parametrize('stronger,source,located', [
    (1, COURT_ID, False), (0, COURT_ID, True), (1, 'another_domain', True),
])
def test_declared_stronger_concealment_veto_survives_a_table_commit_and_reload(tmp_path,stronger,source,located):
    def seal(bundles):
        b=bundles[2];sid='action:test.location_concealment'
        b['action_catalog'].append({'source_definition_id':sid,'display_name':'Location concealment',
            'owner_id':FOE,'economy':'ACTION','resolution_kind':'TYPED','target_kind':'SELF','costs':[],
            'parameters':{'typed':{'source':sid,'effects':[{'type':'condition','condition':'invisible',
                'applies_to':'self','duration':'until_removed','condition_data':{'rule':{
                    'domain_location_blocked':{'source_ids':[source],'stronger':stronger}}}}]}}})
        b['actor_template']['action_ids'].append(sid)
        b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    combat,table,mid=fixture(tmp_path,[COURT_ID],bundle_transform=seal,
        seed='T16-GRAVE-STRONGER'+str(stronger)+source)
    row=next(c for c in combat._load_session(mid).engine.legal_candidates()
             if 'Court of the Ninth Grave' in c.display_name)
    settle(table,mid,row.candidate_id)
    turn(table,mid,FOE)
    settle(table,mid,candidate(combat,mid,'Location concealment').candidate_id)
    engine=reload(tmp_path,mid)
    assert (court_locations(engine,engine.state.actors[OWNER],engine.state.actors[FOE]) is True) is located
