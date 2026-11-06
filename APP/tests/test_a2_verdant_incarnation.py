"""The incarnation's printed Fire interruption survives a saved table turn."""
import pytest
from combat.canonical import canonical_sha256
from combat.ext import verdant_chassis as verdant
from tests.worker2_support import OWNER, FOE, fixture, candidate, settle, reload, prompt_turn, sealed_native_attack

SOW = 'TAL_VERDANT_GROWTH_SOW_LIVING_CLAIM'
INC = 'tianxia.talent.verdant_growth.verdant_incarnation_body_becomes_the_ancient_tree'


@pytest.mark.parametrize('damage,legacy,expected', [('FIRE',False,0),('COLD',False,1),('FIRE',True,1)])
def test_incarnation_next_claim_interruption(tmp_path,damage,legacy,expected):
    def attacks(bundles):
        for b in bundles:
            if b['actor_id'] == FOE:
                sealed_native_attack(b,'Scorch',damage_type=damage,modifier=1,attack_bonus=100)
            if legacy:
                for row in b['typed_passives']:
                    row.pop('fire_stunts_claim',None)
                b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    combat,table,mid=fixture(tmp_path,[SOW,INC],bundle_transform=attacks)
    settle(table,mid,candidate(combat,mid,'Verdant Incarnation: Body Becomes the Ancient Tree').candidate_id)
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    prompt_turn(table,mid,FOE)
    settle(table,mid,candidate(combat,mid,'Scorch',target=OWNER).candidate_id)
    engine=reload(tmp_path,mid)
    assert any(e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids and e.payload['reduced_to'] > 0
               for e in engine.events)
    assert bool([c for c in engine.state.actors[OWNER].conditions.values()
                 if c.condition_id == 'condition:typed.verdant_scorched']) == (damage=='FIRE' and not legacy)
    # This marker is consumed by the next owner-start hook, after it suppresses the claim.
    markers = [c for c in engine.state.actors[OWNER].conditions.values()
               if c.condition_id == 'condition:typed.verdant_scorched']
    assert all(c.expires_on == 'CONSUMED' for c in markers)
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    prompt_turn(table,mid,OWNER)
    engine=reload(tmp_path,mid)
    assert len(verdant.claims(engine,engine.state.actors[OWNER])) == expected
    assert not any(c.condition_id == 'condition:typed.verdant_scorched' for c in engine.state.actors[OWNER].conditions.values())
    # Only that next start is blocked; the following start creates its normal claim.
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    prompt_turn(table,mid,OWNER)
    engine=reload(tmp_path,mid)
    assert len(verdant.claims(engine,engine.state.actors[OWNER])) == expected+1
