"""The compiler's Subpath gate is source-level for every Subpath, not one family.

Regression for the cross-Subpath review: a printed Subpath feature is admitted
only by a real selection of its own Subpath at or above that feature's printed
level. A feature named by another id source (earned occurrence, path feature
record, automatic component) never opens a Subpath the character did not select.
Every feature of the selected Subpath keeps its printed options and scales its
numbers by the owning Path's effective CL (the Subpath index's Source CL basis),
so a non-Calligraphy Subpath (Dust Cultivator's Choking Dust) is unaffected by
the Calligraphy work and the Calligraphy work is inert for it.
"""
from pathlib import Path

from combat.factory_compiler import compile_character
from combat.subpath_acquisition import admit_subpath_features, subpath_feature_index
from tests.h1_support import sheet

ROOT = Path(__file__).resolve().parents[1]
QI = 'tianxia.path.qi_cultivation'
CALLIGRAPHY = 'tianxia.subpath.qi.calligraphy_cultivator'
DUST = 'tianxia.subpath.qi.dust_cultivator'
LIVING = CALLIGRAPHY + '.feature.living_character'
GREAT = CALLIGRAPHY + '.feature.great_character'
HEAVEN = CALLIGRAPHY + '.feature.heaven_s_script'
BINDING = CALLIGRAPHY + '.feature.character_of_binding'
CHOKING = DUST + '.feature.choking_dust'
DUST_TO_DUST = DUST + '.feature.dust_to_dust'
SANDSTORM = DUST + '.feature.sandstorm_field'
PRIMORDIAL = DUST + '.feature.primordial_dust'


def character(*, path_cl, subpaths, character_cl=18, extra=None):
    doc = sheet([], cl=character_cl, primary='Qi')
    doc['path_and_subpath'] = {
        'paths': [{'path_id': QI, 'attainment': path_cl, 'effective_cl': path_cl}],
        'subpaths': [{'subpath_id': subpath, 'owning_path_id': QI} for subpath in subpaths],
    }
    doc['path_and_subpath'].update(extra or {})
    return compile_character(doc, actor_id='actor:gate')


def rows(bundle, source=None):
    out = []
    for action in bundle['action_catalog']:
        params = action['parameters'] if isinstance(action, dict) else action.parameters
        typed = (params.get('typed') or {}) if isinstance(params, dict) else (params.typed or {})
        if source is None or typed.get('source') == source:
            name = action['display_name'] if isinstance(action, dict) else action.display_name
            out.append((name, typed.get('source'), (typed.get('numbers') or {}).get('cl')))
    return out


def test_unselected_subpath_feature_is_never_admitted_by_another_id_source():
    bundle = character(path_cl=16, subpaths=[DUST], extra={
        'earned_feature_occurrences': [{'feature_id': GREAT, 'occurrence_id': 'occ-great'}],
        'path_feature_record_ids': [HEAVEN, BINDING],
    })
    assert rows(bundle, GREAT) == []
    assert rows(bundle, HEAVEN) == []
    assert rows(bundle, BINDING) == []
    # The selected Subpath is untouched by the other family's ids.
    assert {name.split(':')[0] for name, _, cl in rows(bundle, CHOKING)} == {'Choking Dust'}
    assert all(cl == 16 for _, _, cl in rows(bundle, CHOKING))


def test_selected_subpath_features_above_and_below_their_printed_level():
    low = character(path_cl=9, subpaths=[CALLIGRAPHY])
    assert rows(low, LIVING), 'Living Character at CL 3 is printed for a CL 9 Subpath'
    assert rows(low, GREAT) == [], 'Great Character needs Subpath CL 10'
    assert rows(low, BINDING) == [], 'Character of Binding needs Subpath CL 14'

    high = character(path_cl=18, subpaths=[CALLIGRAPHY])
    assert len(rows(high, GREAT)) == 5
    assert {name.split(': ')[1] for name, _, _ in rows(high, GREAT)} == {
        'Great Character of Mountain', 'Great Character of River', 'Great Character of Storm',
        'Great Character of Gate', 'Great Character of Silence'}
    assert rows(high, HEAVEN), "Heaven's Script at CL 18 is printed for a CL 18 Subpath"


def test_other_subpath_scales_by_owning_path_cl_and_keeps_every_printed_option():
    bundle = character(path_cl=16, subpaths=[DUST], character_cl=18)
    chokes = rows(bundle, CHOKING)
    assert {name for name, _, _ in chokes} == {'Choking Dust: Choking Mode', 'Choking Dust: Eroding Mode'}
    assert all(cl == 16 for _, _, cl in chokes), 'Dust numbers use the Qi Path CL, not character CL 18'
    assert len(rows(bundle, DUST_TO_DUST)) == 3
    assert len(rows(bundle, SANDSTORM)) == 1
    assert rows(bundle, PRIMORDIAL) == [], 'Primordial Dust needs Subpath CL 18'
    assert rows(bundle, LIVING) == [], 'Calligraphy features are inert for a Dust character'


def test_gate_passes_non_subpath_records_and_drops_only_printed_features():
    index = subpath_feature_index(ROOT)
    assert index[CHOKING] == DUST
    assert index[GREAT] == CALLIGRAPHY
    ids = ['tianxia.sphere.fire.base_projection', 'tianxia.path.qi_cultivation.feature.qi_core', GREAT, CHOKING]
    kept = admit_subpath_features(ids, ROOT, {CHOKING: 16})
    assert kept == ['tianxia.sphere.fire.base_projection', 'tianxia.path.qi_cultivation.feature.qi_core', CHOKING]
    # An explicit owner-recorded native admission keeps its own route.
    assert set(admit_subpath_features([GREAT], ROOT, {}, explicit_admissions=[GREAT])) == {GREAT}
