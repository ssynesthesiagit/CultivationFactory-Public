"""Preserved predecessor diagnostic with its capacity gap now repaired.

The combat fixture compiles printed source records on a supplied sheet. It does
not exercise character creation/CL14 acquisition. No Harmony, field, ownership
condition, or spend receipt is injected into the engine. Native acquisition and
the consumer chain are tested separately in test_mgr_t14_yin_yang_native.py.
"""
import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from tests.worker2_support import ALLY, OWNER, candidate, fixture, reload, settle

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'tianxia.subpath.qi.yin_yang_cultivator.feature.'
ESSENCE = PREFIX + 'essence_circulation'
FLOW = PREFIX + 'balanced_flow'
HARMONY = 'resource:named.harmony'
QI = 'resource:core.qi'


def test_controlling_record_and_shared_source_identity():
    text = json.loads((ROOT / 'authority/typed_mechanics/rules_text.json').read_text())[ESSENCE]
    assert hashlib.sha256(text.encode()).hexdigest() == (
        '5dd8dd8671952cfe3fcdb3b48840bce3c96416b6f53364b0a8231da8bb55f806')
    with zipfile.ZipFile(ROOT / 'BundledContent/Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip') as archive:
        for suffix, expected in (
            ('Tianxia_Qi_Cultivation_Shared_Subpath_Rules_R4.md',
             'b0853fd30b2fb92571ce25a0b24ac5cd5c8962603c4ae33fc2b8f90ed4d48ab2'),
            ('Tianxia_Qi_Cultivation_Subpath_Compendium_R19.md',
             'ca25b88915a2d83324a23feed94a54409d359369dbd0452fb29d28b938262584'),
        ):
            member, = [name for name in archive.namelist() if name.endswith(suffix)]
            assert hashlib.sha256(archive.read(member)).hexdigest() == expected


@pytest.mark.parametrize('owns', [False, True])
def test_compiled_source_table_commit_and_cold_replay_audit(tmp_path, owns):
    records = [FLOW, PREFIX + 'reversal', PREFIX + 'taiji_field']
    combat, table, mid = fixture(tmp_path, [*records, *([ESSENCE] if owns else [])],
                                 cl=14, seed='MGR-T14-ESSENCE-AUDIT')
    before = reload(tmp_path, mid)
    actor = before.state.actors[OWNER]
    qi = actor.resources[QI]
    harmony = actor.resources.get(HARMONY)
    prompts = settle(table, mid, candidate(combat, mid, 'Restorative Palm', target=ALLY).candidate_id)
    after = reload(tmp_path, mid)
    actor = after.state.actors[OWNER]
    assert actor.resources[QI] == qi - 2
    assert harmony == actor.resources.get(HARMONY) == 0
    assert not [p for p in prompts if 'essence_circulation' in p['context']['reaction_source_id']]
    print(json.dumps({'audit_only': True, 'owns_essence': owns,
        'cl': 14, 'pb': actor.proficiency_bonus,
        'harmony_current': actor.resources.get(HARMONY),
        'harmony_maximum': actor.resource_maximums.get(HARMONY),
        'palm_qi_spent': qi - actor.resources[QI],
        'mechanical_replay': 'PASS',
        'essence_action_names': [a.display_name for a in after.action_catalog.values()
            if (a.parameters.get('typed') or {}).get('source') == ESSENCE]}, sort_keys=True))


def test_open_capacity_clause_after_real_table_commit_and_cold_reload(tmp_path):
    combat, table, mid = fixture(tmp_path, [FLOW, ESSENCE], cl=14,
                                 seed='MGR-T14-ESSENCE-CAPACITY')
    settle(table, mid, candidate(combat, mid, 'Restorative Palm', target=ALLY).candidate_id)
    actor = reload(tmp_path, mid).state.actors[OWNER]
    assert actor.resource_maximums.get(HARMONY) == actor.proficiency_bonus + 2
