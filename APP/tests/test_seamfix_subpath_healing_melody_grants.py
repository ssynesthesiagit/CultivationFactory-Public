"""Subpath grant regressions for the Healing Melody seam (round F2).

Compile-level checks on the sheet the connected character exports. An exported Subpath
feature id is a record of an earlier grant, so only the native selection check may keep it;
a Subpath feature compiles at its own effective source CL, not the whole character's CL.
"""
from types import SimpleNamespace

from combat.ext.qi_subpaths_five import feather_fall, FEATHER
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.worker2_support import OWNER

QI = 'tianxia.path.qi_cultivation'
MELODY = 'tianxia.subpath.qi.sound_cultivator.feature.healing_melody'
CLOUD_SUBPATH = 'tianxia.subpath.qi.cloud_walker'


def document(cl, *, subpaths=(), effective_cl=None, exported=()):
    doc = sheet([], cl=cl, name='Grant check')
    row = {'path_id': QI, 'attainment': cl, 'effective_cl': cl if effective_cl is None else effective_cl}
    doc['path_and_subpath'] = {'paths': [row], 'subpaths': [{'subpath_id': sid, 'owning_path_id': QI} for sid in subpaths],
                               'source_granted_subpath_feature_record_ids': list(exported)}
    return doc


def melody_actions(bundle):
    return [a for a in bundle['action_catalog'] if (a.get('parameters') or {}).get('typed', {}).get('source') == MELODY]


def test_stale_export_is_withheld_when_no_subpath_is_selected():
    # The character respecs out of Sound Cultivator, but the old export still names Healing Melody.
    bundle = compile_character(document(18, exported=[MELODY]), actor_id=OWNER)
    assert not melody_actions(bundle)


def test_stale_export_is_withheld_when_only_another_subpath_is_selected():
    # A valid Cloud Walker grant keeps working; the stale Sound Cultivator export does not reopen Melody.
    bundle = compile_character(document(18, subpaths=[CLOUD_SUBPATH], exported=[MELODY]), actor_id=OWNER)
    assert not melody_actions(bundle)
    assert any(row['feature_id'] == FEATHER for row in bundle['typed_passives'])


def test_export_still_grants_a_validly_selected_subpath_feature():
    # Control: the same export at CL6 with the native selection grants Healing Melody exactly once.
    bundle = compile_character(document(6, subpaths=['tianxia.subpath.qi.sound_cultivator'], exported=[MELODY]), actor_id=OWNER)
    assert len(melody_actions(bundle)) >= 1


def test_lower_effective_cl_seals_cloud_walker_passive_at_its_own_source_cl():
    # Cloud Walker acquired at effective CL6 on a CL18 character: printed fall reduction is 5 x 6 = 30, not 5 x 18.
    bundle = compile_character(document(18, subpaths=[CLOUD_SUBPATH], effective_cl=6), actor_id=OWNER)
    row = next(row for row in bundle['typed_passives'] if row['feature_id'] == FEATHER)
    assert row['cl'] == 6
    engine = SimpleNamespace(typed_passive_rows={OWNER: bundle['typed_passives']})
    actor = SimpleNamespace(entity_id=OWNER)
    assert feather_fall(engine, actor, 90, None, None) == {'amount': 60}


def test_full_cl_cloud_walker_passive_still_uses_the_character_cl():
    bundle = compile_character(document(18, subpaths=[CLOUD_SUBPATH]), actor_id=OWNER)
    row = next(row for row in bundle['typed_passives'] if row['feature_id'] == FEATHER)
    assert row['cl'] == 18
