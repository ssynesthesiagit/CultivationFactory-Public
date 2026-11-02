"""Native checks of existing Refraction delivery, not whole-row completion.

The sheet stage is supplied by the table fixture; these checks do not prove
stage advancement, scene importance, intent, or GM acceptance of limitations.
"""
import hashlib
import json
from pathlib import Path

import pytest

from combat.ext import foundation_combat as foundation
from tests.test_a2_foundations_two import table_fixture, use
from tests.worker2_support import ALLY, FOE, OWNER, reload, turn


PREFIX = 'foundation.glass_heart_meridian_v0_2A.'
REFRACTION = PREFIX + 'perfected_glass_heart_refraction'


@pytest.mark.parametrize('leaf,digest', [
    ('refined_beauty_without_lie', 'fc62d5f086e0b1035d44478cdc15a5781221e291dee43e562ac460414e21e8c9'),
    ('refined_refracted_technique', '497fddc8c1710610c066c7b5b64f29c21b4486a17645ebcb2baa1e47d53a90b4'),
    ('perfected_glass_heart_refraction', '61816edc9a444066bdb28e17dbde5d325392650930e0ceaa01f899faca3fcced'),
])
def test_full_decoded_source_pin(leaf, digest):
    rules = json.loads((Path(__file__).resolve().parents[1] /
                        'authority/typed_mechanics/rules_text.json').read_text())
    assert hashlib.sha256(rules[PREFIX + leaf].encode()).hexdigest() == digest


@pytest.mark.parametrize('stage,available', [
    ('Awakened', False), ('Refined', False), ('Perfected', True),
])
def test_native_refraction_stage_and_wrong_owner_boundary(tmp_path, stage, available):
    _, table, mid = table_fixture(tmp_path, 'glass', current=0, stage=stage)
    engine = reload(tmp_path, mid)
    assert any(REFRACTION in c.source_definition_id for c in engine.legal_candidates()) == available
    assert foundation.held(engine.state.actors[OWNER], 'glass_refraction') is None
    turn(table, mid, ALLY)
    engine = reload(tmp_path, mid)
    assert not any(REFRACTION in c.source_definition_id for c in engine.legal_candidates())


def test_native_refraction_self_state_expires_after_ten_rounds(tmp_path):
    combat, table, mid = table_fixture(tmp_path, 'glass', current=0)
    before = reload(tmp_path, mid).state.actors[OWNER].resources['resource:core.qi']
    use(combat, table, mid, 'Perfected — Glass Heart Refraction')
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.resources['resource:core.qi'] == before - 2
    assert owner.resource_maximums[foundation.pool('glass')] == 1
    assert owner.resources[foundation.pool('glass')] == 0
    assert foundation.held(owner, 'glass_refraction')
    assert all(foundation.held(actor, 'glass_refraction') is None
               for identity, actor in engine.state.actors.items() if identity != OWNER)
    for _ in range(9):
        turn(table, mid, FOE)
        turn(table, mid, OWNER)
    assert foundation.held(reload(tmp_path, mid).state.actors[OWNER], 'glass_refraction')
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert foundation.held(engine.state.actors[OWNER], 'glass_refraction') is None
    assert not any(REFRACTION in c.source_definition_id for c in engine.legal_candidates())
