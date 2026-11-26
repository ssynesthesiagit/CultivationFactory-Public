"""Created Radiant Aegis facing an actual compiled hostile Fear action."""
import pytest

from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.test_a2_foundations3 import pool
from tests.test_spirit_dew_maintenance import REFRAIN
from tests.test_spirit_dew_reduction import OWNER_ROW
from tests.worker2_support import OWNER, ALLY, FOE, candidate, fixture, reload, settle, turn

AEGIS = 'tianxia.talent.radiance.radiant_aegis_of_the_heart'


def test_protection_hook_documents_success_with_matching_provider():
    from pathlib import Path
    from combat import ext

    contract = Path(ext.__file__).read_text().split('# Typed save support attribution', 1)[1]
    contract = contract.split('# Final Concentration support attribution', 1)[0]
    assert 'final successful save resists a hostile' in contract
    assert 'actual matching protection provider' in contract
    assert 'Success without that provider is inert' in contract
    assert 'final failed hostile' not in contract


@pytest.mark.parametrize('target,owns', [(ALLY, True), (OWNER, True), (ALLY, False)])
def test_created_protection_credits_final_successful_save_against_hostile_fear(tmp_path, target, owns):
    doc = sheet([AEGIS] + ([OWNER_ROW] if owns else []), foundation={
        'foundation_id': 'origin_spirit_body_v0_2B', 'stage': 'Awakened',
        'resource': {'name': 'Spirit-Source Dew', 'resource_id': 'tianxia.resource.test',
                     'maximum': 1, 'current': 0}})
    bundle = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    def delivery(bundles):
        bundles[2] = compile_character(sheet([REFRAIN]), actor_id=FOE, reaction_plan={'ask': True})
    combat, table, mid = fixture(tmp_path, [], owner_bundle=bundle, bundle_transform=delivery,
                                seed='DEW-FEAR-PROTECTION-1', named=True)
    qi = reload(tmp_path, mid).state.actors[OWNER].resources['resource:core.qi']
    cid = candidate(combat, mid, 'Radiant Aegis of the Heart', target=target).candidate_id
    for _ in range(2):
        table.state(mid)
        assert candidate(combat, mid, 'Radiant Aegis of the Heart', target=target).candidate_id == cid
        assert reload(tmp_path, mid).state.actors[OWNER].resources['resource:core.qi'] == qi
    settle(table, mid, cid, choices={})
    protected = reload(tmp_path, mid)
    assert protected.state.actors[OWNER].resources['resource:core.qi'] == qi - 3
    assert protected.state.actors[OWNER].resources.get(pool('spirit'), 0) == 0
    assert any(c.source_actor_id == OWNER and AEGIS in c.source_definition_id
               for c in protected.state.actors[target].conditions.values())
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Soul-Stirring Refrain: Fear (any creature)',
                                target=target).candidate_id,
           picks={'choice:willing.consent': ['refuse']})
    engine = reload(tmp_path, mid)
    saved = next(e for e in reversed(engine.events) if e.event_type == 'SAVE_ROLLED'
                 and REFRAIN in e.source_definition_id and e.actor_id == target)
    assert saved.payload['mode'] == 'ADVANTAGE'
    assert saved.payload['success'] is True, saved.payload
    assert not any(c.condition_id == 'condition:typed.frightened'
                   for c in engine.state.actors[target].conditions.values())
    assert engine.state.actors[OWNER].resources.get(pool('spirit'), 0) == int(owns)
