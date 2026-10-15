"""Source-backed formula knowledge and discovered-formula study at the table.

Producers/consumers: TabletopService.procedure records choices and GM-confirmed
discoveries/work/check dice; table_advance overlays earned knowledge into the
ordinary compiler. Learning never manufactures a crafted talisman. Study uses
Advanced Talisman Crafting's eight hours, halved only for an admitted Archivist.
The table may report physical check dice and GM-confirmed external payments/tool
facts. The consumer derives totals/outcomes; it never invents a die or debits a
combat pool for an out-of-combat payment. External receipts stay in the project.
"""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
import re

from . import hook
from ..tabletop import TabletopError

APP = Path(__file__).resolve().parents[2]
NAMESPACE = 'talisman_formulae'
ARCHIVIST = 'insight.formula-archivist'
SPHERE = 'tianxia.sphere.talismans'
ADVANCED = 'tianxia.talent.talismans.advanced_talisman_crafting'


def require(ok, message):
    if not ok:
        raise TabletopError('TABLE_FORMULA_INVALID', message, 409)


@lru_cache(maxsize=1)
def formula_catalog():
    """Only actual printed, ranked formulae; no guessed or Secret records."""
    texts = json.loads((APP / 'authority/typed_mechanics/rules_text.json').read_text())
    result = {}
    for key, text in texts.items():
        rank = re.search(r'^Rank: (Common|Uncommon|Rare|Very Rare|Legendary)\s*$', text, re.M)
        if not key.startswith('tianxia.talent.talismans.') or not rank:
            continue
        name = text.splitlines()[0].removeprefix('#### ').split(' - ')[0]
        minimum = re.search(r'Prerequisite: CL (\d+)\+', text)
        result[key] = {'id': key, 'name': name, 'rank': rank[1],
                       'minimum_cl': int(minimum[1]) if minimum else 1,
                       'rules': text}
    return result


def ownership(sheet):
    """Use native source/hash admission rather than treating an ID as authority."""
    from ..factory_compiler import compile_character
    from ..table_advance import known
    have = known(sheet)
    block = sheet.get('spheres_and_talents') or {}
    selected = set(block.get('cultivation_insight_record_ids') or [])
    selected.update(row.get('insight_id') for row in block.get('cultivation_insight_occurrences') or [])
    archivist = False
    if ARCHIVIST in selected and SPHERE in have['spheres'] and have['cl'] >= 6:
        bundle = compile_character(sheet, actor_id='actor:table.formula-reader')
        archivist = any(row.get('id') == ARCHIVIST and row.get('status') != 'manual'
                        for row in bundle.get('diagnostics', {}).get('insights', []))
    return have, archivist


@hook('table_procedure_options')
def options(sheet, states):
    have, archivist = ownership(sheet)
    if SPHERE not in have['spheres'] or not (archivist or ADVANCED in have['talents']):
        return None
    state = states.get(NAMESPACE) or {}
    choices = state.get('choices') or []
    formulas = [deepcopy(row) for row in formula_catalog().values()
                if row['minimum_cl'] <= have['cl'] and row['id'] not in have['talents']
                and row['rank'] in ('Common', 'Uncommon')]
    grants = []
    if archivist:
        for rank in ('Common', 'Uncommon'):
            if not any(row.get('rank') == rank for row in choices):
                grants.append({'rank': rank, 'options': [row for row in formulas if row['rank'] == rank],
                               'label': f'Formula Archivist: learn one additional {rank} formula. No crafting cost; knowledge only.'})
    return [{'id': NAMESPACE, 'name': 'Talisman formula knowledge', 'revision': state.get('revision', 0),
             'grants': grants, 'discoverable': formulas if ADVANCED in have['talents'] else [],
             'projects': deepcopy(state.get('projects') or []),
             'study_minutes': 240 if archivist else 480,
             'check_requirement': 'After study, make a Talisman Crafting Check against the formula crafting DC + 2. '
                                  'Report the physical d20 and any GM-confirmed tool proficiency or already-paid CP. '
                                  'Failure by 5 or more destroys the studied talisman.',
             'check_inputs': ['d20', 'roll_provenance', 'tool_name', 'tool_provenance', 'paid_cp', 'payment_provenance']}]


@hook('table_procedure_command')
def command(sheet, namespace, state, action, payload, gm):
    if namespace != NAMESPACE:
        return None
    have, archivist = ownership(sheet)
    require(SPHERE in have['spheres'], 'You need the Talismans sphere.')
    if action == 'choose':
        require(set(payload) == {'formula_id'}, 'Choose one printed formula.')
        formula = formula_catalog().get(payload.get('formula_id'))
        require(archivist, 'You need Formula Archivist at CL 6 or higher.')
        require(formula and formula['rank'] in ('Common', 'Uncommon') and formula['minimum_cl'] <= have['cl'],
                'Choose a Common or Uncommon formula whose prerequisites you meet.')
        require(formula['id'] not in have['talents'], 'You already know that formula. Choose another.')
        choices = state.setdefault('choices', [])
        require(not any(row['rank'] == formula['rank'] for row in choices),
                'Formula Archivist grants one additional formula of each rank, once.')
        choices.append({'formula_id': formula['id'], 'rank': formula['rank'], 'source': ARCHIVIST})
    elif action == 'discover':
        require(gm, 'The GM must confirm a formula actually discovered in play.')
        require(set(payload) <= {'formula_id', 'discovery_id', 'provenance', 'crafting_dc'}, 'Unknown discovery detail.')
        require(ADVANCED in have['talents'], 'Advanced Talisman Crafting is required to reverse engineer a formula.')
        formula = formula_catalog().get(payload.get('formula_id'))
        require(formula and formula['rank'] in ('Common', 'Uncommon') and formula['minimum_cl'] <= have['cl'],
                'Reverse engineering permits Common or Uncommon formulae whose prerequisites you meet.')
        require(formula['id'] not in have['talents'], 'You already know that formula.')
        for key in ('discovery_id', 'provenance'):
            require(isinstance(payload.get(key), str) and 1 <= len(payload[key].strip()) <= 500,
                    'Record the discovered talisman and where it was found in play.')
        dc = payload.get('crafting_dc', 12 if formula['rank'] == 'Common' else 15)
        require(type(dc) is int and 1 <= dc <= 100, 'The GM must confirm a whole-number formula crafting DC.')
        projects = state.setdefault('projects', [])
        require(not any(p['discovery_id'] == payload['discovery_id'] for p in projects),
                'This discovered talisman already has a study project.')
        projects.append({'discovery_id': payload['discovery_id'], 'provenance': payload['provenance'],
                         'formula_id': formula['id'], 'crafting_dc': dc, 'check_dc': dc + 2,
                         'base_minutes': 480, 'required_minutes': 240 if archivist else 480,
                         'time_source': ARCHIVIST if archivist else ADVANCED,
                         'studied_minutes': 0, 'status': 'studying'})
    elif action == 'study':
        require(set(payload) == {'discovery_id', 'minutes'}, 'Record the studied talisman and elapsed study minutes.')
        require(gm, 'The GM must confirm actual study time, including interruptions.')
        require(ADVANCED in have['talents'], 'Advanced Talisman Crafting is required to study a formula.')
        project = next((p for p in state.get('projects') or [] if p['discovery_id'] == payload['discovery_id']), None)
        require(project and project['status'] == 'studying', 'Choose an unfinished study project.')
        minutes = payload['minutes']
        require(type(minutes) is int and 0 < minutes <= project['required_minutes'] - project['studied_minutes'],
                'Record positive whole minutes, up to the remaining study time.')
        project['studied_minutes'] += minutes
        if project['studied_minutes'] == project['required_minutes']:
            project['status'] = 'awaiting_crafting_check'
    elif action == 'check':
        require(gm, 'The GM must confirm the physical crafting-check die and external facts.')
        require(set(payload) <= {'discovery_id', 'd20', 'roll_provenance', 'tool_name', 'tool_provenance',
                                 'paid_cp', 'payment_provenance'}, 'Unknown crafting-check detail.')
        require(ADVANCED in have['talents'], 'Advanced Talisman Crafting is required to reverse engineer a formula.')
        project = next((p for p in state.get('projects') or [] if p['discovery_id'] == payload.get('discovery_id')), None)
        require(project and project['status'] == 'awaiting_crafting_check', 'Finish the required study before the crafting check.')
        die, cp = payload.get('d20'), payload.get('paid_cp', 0)
        require(type(die) is int and 1 <= die <= 20, 'Report the actual physical d20 result, from 1 to 20.')
        require(type(cp) is int and 0 <= cp <= have['pb'], 'The crafting check permits paid CP up to your Proficiency Bonus.')
        for key in ('roll_provenance', *(['payment_provenance'] if cp else []),
                    *(['tool_provenance'] if payload.get('tool_name') else [])):
            require(isinstance(payload.get(key), str) and 1 <= len(payload[key].strip()) <= 500,
                    'The GM must record the actual roll, paid CP, and any proficient tool approved for this formula.')
        require(not payload.get('tool_name') or isinstance(payload['tool_name'], str) and len(payload['tool_name']) <= 120,
                'Name the proficient tool approved by the GM for this medium.')
        abilities = (sheet.get('ability_scores_and_statistics') or {}).get('abilities') or []
        if isinstance(abilities, str):
            abilities = json.loads(abilities)
        intelligence = next((a for a in abilities if a.get('ability') == 'INT'), None)
        require(intelligence and type(intelligence.get('score')) is int, 'The character needs a recorded Intelligence score.')
        modifier = (intelligence['score'] - 10) // 2
        tool_bonus = have['pb'] if payload.get('tool_name') else 0
        total = die + have['pb'] + modifier + tool_bonus + cp
        project['check'] = {**deepcopy(payload), 'pb': have['pb'], 'intelligence_modifier': modifier,
                            'tool_bonus': tool_bonus, 'total': total}
        project['status'] = ('learned' if total >= project['check_dc'] else
                             'destroyed' if total <= project['check_dc'] - 5 else 'failed')
        # Failed intact talismans may be studied again, but never recycle the
        # previous eight/four hours or allow rerolling the same completed check.
    elif action == 'retry':
        require(set(payload) == {'discovery_id'}, 'Choose the discovered talisman to study again.')
        project = next((p for p in state.get('projects') or [] if p['discovery_id'] == payload['discovery_id']), None)
        require(gm and project and project['status'] == 'failed', 'Only an intact failed study may be tried again, with GM confirmation.')
        project.setdefault('previous_checks', []).append(project.pop('check'))
        project['studied_minutes'] = 0
        project['status'] = 'studying'
    else:
        require(False, 'Choose a formula, record a discovery or study, report its crafting check, or retry an intact failed study.')
    return state


@hook('table_procedure_sheet')
def overlay(sheet, states):
    state = states.get(NAMESPACE) or {}
    if not state.get('choices') and not any(p.get('status') == 'learned' for p in state.get('projects') or []):
        return None
    have, archivist = ownership(sheet)
    if SPHERE not in have['spheres']:
        return None
    out = deepcopy(sheet)
    learned = out.setdefault('spheres_and_talents', {}).setdefault('learned_talent_record_ids', [])
    seen = set()
    for choice in state.get('choices') or []:
        formula = formula_catalog().get(choice.get('formula_id'))
        if (archivist and formula and choice.get('source') == ARCHIVIST and formula['rank'] in ('Common', 'Uncommon')
                and choice.get('rank') == formula['rank'] and formula['rank'] not in seen):
            seen.add(formula['rank'])
            if formula['id'] not in learned:
                learned.append(formula['id'])
    for project in state.get('projects') or []:
        if project.get('status') == 'learned' and project.get('formula_id') in formula_catalog():
            if project['formula_id'] not in learned:
                learned.append(project['formula_id'])
    return out
