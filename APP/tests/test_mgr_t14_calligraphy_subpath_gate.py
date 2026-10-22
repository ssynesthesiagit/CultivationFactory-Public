"""The compiler's Subpath gate is source-level and general, not Calligraphy-only.

Regression for the cross-Subpath review: a feature of a Subpath the character
actually selected is admitted only at or above its printed level, whatever other
id source named it. Features of other Subpaths keep their existing route
(feature-list ownership) and are compiled exactly as before, so the change does
not reach unrelated families. Every feature of the selected Subpath keeps its
printed options; only this lane's Calligraphy records seal the owning Path's CL
into their numbers, while a non-Calligraphy Subpath keeps the character CL (Dust
Cultivator's Choking Dust is the control).
"""
from pathlib import Path

from combat.factory_compiler import compile_character
from combat.subpath_acquisition import admit_subpath_features
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


def test_selected_subpath_below_printed_level_drops_every_route_to_its_features():
    bundle = character(path_cl=9, subpaths=[CALLIGRAPHY], extra={
        'earned_feature_occurrences': [{'feature_id': GREAT, 'occurrence_id': 'occ-great'}],
        'path_feature_record_ids': [GREAT, HEAVEN, BINDING, LIVING],
    })
    assert rows(bundle, GREAT) == [], 'Great Character needs Subpath CL 10'
    assert rows(bundle, HEAVEN) == [], "Heaven's Script needs Subpath CL 18"
    assert rows(bundle, BINDING) == [], 'Character of Binding needs Subpath CL 14'
    assert rows(bundle, LIVING), 'Living Character is printed at Subpath CL 3'


def test_other_subpaths_keep_their_feature_list_route_and_are_not_gated():
    """A Calligraphy id named by a Dust character's own sheet is not a Dust
    progression feature, so the Calligraphy gate (a selected-Subpath rule) leaves
    Dust's features and the historical feature-list route alone. This is the
    cross-Subpath control the review asked for: Dust's numbers keep the character
    CL (18), never the Qi Path CL (16), because its printed text measures CL as the
    character's."""
    bundle = character(path_cl=16, subpaths=[DUST], extra={
        'earned_feature_occurrences': [{'feature_id': GREAT, 'occurrence_id': 'occ-great'}],
        'path_feature_record_ids': [GREAT],
    })
    assert rows(bundle, CHOKING) and all(cl == 18 for _, _, cl in rows(bundle, CHOKING))
    assert len(rows(bundle, DUST_TO_DUST)) == 3
    assert len(rows(bundle, SANDSTORM)) == 1
    assert rows(bundle, PRIMORDIAL) == [], 'Primordial Dust needs Subpath CL 18'
    assert rows(bundle, GREAT), 'a feature-list id keeps its existing ownership contract'


def test_other_subpath_keeps_the_character_cl_and_every_printed_option():
    """Only this lane's Calligraphy records seal the owning Path CL. Choking Dust prints
    "3d6 at CL6, 4d6 at CL11, 5d6 at CL17" -- the character's CL -- so a Dust character
    at character CL 18 with Qi Path CL 16 keeps 18 on every printed option. A broad,
    all-Subpath scaling changed that (lead F10 addendum, 2026-10-22); this pins it back."""
    bundle = character(path_cl=16, subpaths=[DUST], character_cl=18)
    chokes = rows(bundle, CHOKING)
    assert {name for name, _, _ in chokes} == {'Choking Dust: Choking Mode', 'Choking Dust: Eroding Mode'}
    assert all(cl == 18 for _, _, cl in chokes), 'Dust numbers keep character CL 18, not the Qi Path CL 16'
    assert len(rows(bundle, DUST_TO_DUST)) == 3
    assert rows(bundle, LIVING) == [], 'Calligraphy features are inert for a Dust character'


def test_gate_filters_only_selected_subpath_features():
    levels = {CHOKING: {'cl': 4, 'min_cl': 6}, GREAT: {'cl': 9, 'min_cl': 10}}
    grants = {}
    ids = ['tianxia.sphere.fire.base_projection', 'tianxia.path.qi_cultivation.feature.qi_core', GREAT, CHOKING]
    assert admit_subpath_features(ids, levels, grants) == [
        'tianxia.sphere.fire.base_projection', 'tianxia.path.qi_cultivation.feature.qi_core']
    # At or above the printed level the feature is admitted, and an explicit
    # owner-recorded native admission keeps its own route.
    assert admit_subpath_features([CHOKING], levels, {CHOKING: 16}) == [CHOKING]
    assert admit_subpath_features([GREAT], levels, {}, explicit_admissions=[GREAT]) == [GREAT]
