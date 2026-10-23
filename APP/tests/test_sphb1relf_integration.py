"""Release integration: native reaction eligibility survives service commits.

Table actions call CombatService.submit_intent, which persists the accepted
intent through session.submit_intent -> mechanical.execute_intent. Cold loads
below also verify the resulting journal and mechanical replay.
"""
import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests.test_auto128_sand import GRIP, bury_out_of_reach, escape_checks, grip_damage, grip_prompts
from tests.worker2_support import OWNER, FOE, fixture, candidate, settle, turn


@pytest.mark.parametrize('accept', [True, False])
def test_escape_offer_remains_eligible_through_open_and_cold_reload(tmp_path, accept):
    combat, table, mid = fixture(tmp_path, [GRIP], cl=5, bundle_transform=bury_out_of_reach)
    settle(table, mid, candidate(combat, mid, 'Prepare Burial', target=FOE).candidate_id)
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Dig free of the sand').candidate_id,
                     {'reaction:typed.' + GRIP: 'USE' if accept else None})
    assert len(grip_prompts(prompts)) == 1
    saved = combat._load_session(mid)
    cold = CombatService(ROOT, tmp_path)._load_session(mid)
    assert cold.engine.state.model_dump(mode='json') == saved.engine.state.model_dump(mode='json')
    assert cold.verify()['status'] == 'PASS'
    assert cold.mechanical.replay()['status'] == 'PASS'
    assert (escape_checks(cold.engine)[-1]['actor']['mode'] == 'DISADVANTAGE') is accept
    assert bool(grip_damage(cold.engine)) is accept
    assert cold.engine.state.actors[OWNER].reaction_available is (not accept)
    assert not getattr(cold.engine, '_sand_grip_offer', False)


def test_severing_arm_keeps_its_printed_rules_after_commit_and_reload(tmp_path):
    from combat.condition_text import all_conditions
    from tests.cw2_service_support import add_action, seal

    source = 'tianxia.subpath.body.kensei.feature.severing_palm'

    def prepare(bundles):
        # Seal a producer for the exact existing Arm effect/source used by
        # Severing Palm. This checks presentation, not its attack/save eligibility.
        bundle = bundles[0]
        add_action(bundle, 'Prepare severed arm', [{'type': 'severing_arm',
                   'expires_on': 'END_OF_SOURCE_NEXT_TURN'}])
        action = bundle['action_catalog'][-1]
        old = action['source_definition_id']
        action['source_definition_id'] = source + '#arm'
        action['parameters']['typed']['source'] = source + '#arm'
        bundle['actor_template']['action_ids'] = [source + '#arm' if a == old else a
                                                  for a in bundle['actor_template']['action_ids']]
        seal(bundle)

    combat, table, mid = fixture(tmp_path, [source], primary='Stamina', bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Prepare severed arm', target=FOE).candidate_id)
    saved = combat._load_session(mid).engine.state.model_dump(mode='json')
    resumed = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    for current in (table, resumed):
        foe = next(a for a in current.state(mid)['presentation']['actors'] if a['entity_id'] == FOE)
        row = next(c for c in foe['conditions'] if c['condition_id'] == 'condition:typed.severing_arm')
        assert row['rule_text']
        assert 'Disadvantage on' in row['rule_text'] and 'weapon attacks' in row['rule_text']
        assert 'does not sever anatomy' in row['rule_text']
        assert current.combat._load_session(mid).engine.state.model_dump(mode='json') == saved
    assert 'does not sever anatomy' in all_conditions()['severing_arm']['reading']
    cold = resumed.combat._load_session(mid)
    assert cold.verify()['status'] == cold.mechanical.replay()['status'] == 'PASS'
