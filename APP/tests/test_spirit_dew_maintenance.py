"""Compiled outward Concentration support through paid native table actions."""
import pytest

from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.test_a2_foundations3 import add_action, pool
from tests.test_spirit_dew_reduction import OWNER_ROW
from tests.worker2_support import OWNER, ALLY, FOE, candidate, fixture, reload, settle, turn

REFRAIN = 'tianxia.talent.music.soul_stirring_refrain'
WAR = 'tianxia.talent.music.war_song'


@pytest.mark.parametrize('owns', [True, False])
def test_compiled_calm_helps_ally_maintain_then_generates_after_settlement(tmp_path, owns):
    doc = sheet([REFRAIN] + ([OWNER_ROW] if owns else []), foundation={
        'foundation_id': 'origin_spirit_body_v0_2B', 'stage': 'Awakened',
        'resource': {'name': 'Spirit-Source Dew', 'resource_id': 'tianxia.resource.test',
                     'maximum': 1, 'current': 0}})
    bundle = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})

    def delivery(bundles):
        add_action(bundles[2], 'Concentration pressure', [
            {'type': 'damage', 'flat': 1, 'damage_types': ['force'], 'applies_to': 'target'}])

    combat, table, mid = fixture(tmp_path, [], owner_bundle=bundle, ally_talents=[WAR],
                                bundle_transform=delivery, seed='DEW-CALM-MAINTENANCE', named=True)
    before = reload(tmp_path, mid)
    qi = before.state.actors[OWNER].resources['resource:core.qi']
    cid = candidate(combat, mid, 'Soul-Stirring Refrain: Calm', target=ALLY).candidate_id
    for _ in range(2):
        table.state(mid)
        # Repeated legal menu previews cannot spend Qi or give the provider Dew.
        assert candidate(combat, mid, 'Soul-Stirring Refrain: Calm', target=ALLY).candidate_id == cid
        preview = reload(tmp_path, mid)
        assert preview.state.actors[OWNER].resources['resource:core.qi'] == qi
        assert preview.state.actors[OWNER].resources.get(pool('spirit'), 0) == 0
    settle(table, mid, cid, choices={})
    supported = reload(tmp_path, mid)
    assert supported.state.actors[OWNER].resources['resource:core.qi'] == qi - 6
    assert supported.state.actors[OWNER].resources.get(pool('spirit'), 0) == 0
    support = next(c for c in supported.state.actors[ALLY].conditions.values()
                   if c.condition_id == 'condition:typed.music_calm')
    assert support.source_actor_id == OWNER
    assert REFRAIN in support.source_definition_id
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'War Song').candidate_id)
    assert reload(tmp_path, mid).state.actors[ALLY].concentration is not None
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Concentration pressure', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    saved = next(e for e in reversed(engine.events) if e.event_type == 'SAVE_ROLLED'
                 and e.source_definition_id == 'system:combat.concentration')
    assert saved.actor_id == ALLY
    assert saved.payload['success'] is True
    assert engine.state.actors[ALLY].concentration is not None
    assert engine.state.actors[OWNER].resources.get(pool('spirit'), 0) == int(owns)
