"""Inventory runtime compiled NONE actions without a fight or owner data."""
import argparse
from collections import Counter, defaultdict
from functools import lru_cache
import json
from pathlib import Path
import sys

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
IMMEDIATE = {'damage', 'healing', 'gain_resource', 'spend_resource', 'temp_hp',
             'hold_at_1hp', 'forced_movement', 'drop_item', 'pickup_item',
             'attack', 'movement', 'zone', 'move_zone', 'veil_escape_move',
             'remove_condition', 'equipment_grip'}
ACTOR = 'actor:factory.inventory'


def kits():
    from tests.test_auto_tabik import SHEET, KIT, NINPO, QI_FEATURES
    from tests.test_auto_shi import PRESSURE_POINTS_TALENTS, FOUNDATION, DAO
    from tests.test_setting_choices import _sheet, HIDDEN
    from tests.hunt36_support import HIDDEN as HUNT_HIDDEN, VEIL
    from tests.h1_support import sheet, mechanics
    from combat.ext.flowing_river import TALENTS, RESPONSE, TWO_CURRENTS_MEET

    # Reproduce the named fixture builders' input kits, without their fights.
    yield 'test_auto_tabik:ninpo', {**SHEET, 'equipment': [{'starting_kit': KIT}],
        'path_and_subpath': {'path_feature_record_ids': NINPO},
        'spheres_and_talents': {'sphere_record_ids': [], 'learned_talent_record_ids': []}}
    yield 'test_auto_tabik:qi', {**SHEET, 'equipment': [{'starting_kit': KIT}],
        'path_and_subpath': {'path_feature_record_ids': QI_FEATURES},
        'spheres_and_talents': {'sphere_record_ids': [], 'learned_talent_record_ids': []}}
    yield 'test_auto_shi:points', {**SHEET, 'equipment': [DAO], 'foundation': FOUNDATION,
        'spheres_and_talents': {'sphere_record_ids': ['tianxia.sphere.pressure_points'],
                              'learned_talent_record_ids': PRESSURE_POINTS_TALENTS}}
    settings = _sheet()
    settings['spheres_and_talents']['learned_talent_record_ids'] += [HIDDEN, RESPONSE, *TALENTS, TWO_CURRENTS_MEET]
    settings['spheres_and_talents']['sphere_record_ids'].append('tianxia.sphere.flowing_river')
    yield 'test_setting_choices:dark-flowing', settings
    yield 'hunt36_support:hidden-veil', sheet([HUNT_HIDDEN, VEIL], cl=15, kit={'starting_kit': KIT})

    # There is no global ActionDefinition catalogue: compilation needs a sheet.
    # Sweep all ownership records, not just no_action authority records, since
    # ordinary actions and passives can synthesize NONE selectors/activations.
    families = defaultdict(list)
    for mid, row in sorted(mechanics().items()):
        family = (row.get('sphere_id') or row.get('foundation_id') or row.get('subpath_id')
                  or row.get('path_id') or row.get('kind'))
        families[family].append(mid)
    for family, mids in sorted(families.items()):
        document = sheet(mids, cl=20, kit={'starting_kit': KIT})
        block = document.setdefault('spheres_and_talents', {})
        # h1.sheet handles the usual sphere/path/foundation namespaces. Include
        # all remaining records explicitly so its fixture convenience filtering
        # does not silently omit Insights or other source-owning definitions.
        block['learned_talent_record_ids'] = sorted(set(block.get('learned_talent_record_ids', []))
            | {mid for mid in mids if mechanics()[mid].get('kind') != 'cultivation_insight'})
        block['cultivation_insight_record_ids'] = [mid for mid in mids
            if mechanics()[mid].get('kind') == 'cultivation_insight']
        yield f'compiler-family:{family}', document


def classify(action, composition):
    p = action.parameters or {}
    effects = (p.get('typed') or {}).get('effects') or []
    types = {e.get('type') for e in effects}
    if types and types <= {'flowing_choice', 'flowing_step'}:
        return 'b', 'typed standing reaction configuration', ''
    if composition:
        return 'a', 'approved runtime option_composition', ''
    if p.get('setting_only') is True and action.target_kind == 'SELF' and not action.costs:
        return 'a', 'setting_only=true; SELF; no immediate cost', 'STOPPED: no option_composition approval; requires a core/plugin contract change'
    if types & IMMEDIATE:
        return 'c', 'typed immediate mutation: ' + ', '.join(sorted(types)), ''
    return 'unclassified', ('missing typed.effects' if not effects else
                            'missing explicit effect timing/scope; types=' + ', '.join(sorted(str(t) for t in types))), ''


@lru_cache(maxsize=1)
def actions():
    """Every compiled NONE action the synthetic actor owns, with the kit that compiled it."""
    from combat.factory_compiler import compile_character
    from combat.gate2_runtime_models import ActionDefinition
    out = []
    for kit, document in kits():
        try:
            bundle = compile_character(document, actor_id=ACTOR)
        except ValueError as error:
            raise ValueError(f'{kit}: {error}') from error
        owned = set(bundle['actor_template']['action_ids'])
        out += [(kit, ActionDefinition.model_validate(raw)) for raw in bundle['action_catalog']
                if raw['economy'] == 'NONE' and raw['source_definition_id'] in owned]
    return out


def rows():
    from combat.ext.setting_choices import composition_spec
    found = {}
    for kit, action in actions():
        spec = composition_spec(action)
        kind, reason, stopped = classify(action, spec)
        # Retain distinct contracts for the same source across kits.
        key = (action.source_definition_id, kind, reason, json.dumps(spec, sort_keys=True), stopped)
        found.setdefault(key, set()).add(kit)
    return [(source, kind, reason, spec, stopped, ', '.join(sorted(owners)))
            for (source, kind, reason, spec, stopped), owners in sorted(found.items())]


def table():
    found = rows()
    counts = Counter(row[1] for row in found)
    lines = ['Source: runtime `compile_character` ActionDefinitions owned by the synthetic actor, filtered to economy NONE '
        '(five named fixture kits plus every typed ownership family, no fight).', '',
        'Classes: (a) later-use preference; (b) standing configuration; (c) immediate activation; '
        'unclassified rows name the missing typed contract.', '',
        ', '.join(f'{kind}: {counts[kind]}' for kind in ('a', 'b', 'c', 'unclassified')), '',
        '| Source definition id | Class | In option_composition | Typed evidence / missing field / STOPPED reason | Synthetic kits |',
        '| --- | --- | --- | --- | --- |']
    for source, kind, reason, spec, stopped, owners in found:
        approval = 'yes' if spec != 'null' else 'no'
        lines.append(f'| `{source}` | {kind} | {approval} | {reason}{"; " + stopped if stopped else ""} | {owners} |')
    return '\n'.join(lines)


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    print(table())


if __name__ == '__main__':
    main()
