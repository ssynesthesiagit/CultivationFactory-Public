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
LEGENDARY = 'tianxia.talent.talismans.legendary_talisman_crafting'
QI = 'tianxia.path.qi_cultivation'
SPIRIT = 'tianxia.path.spirit_awakening'


def check_choices(sheet, have, state):
    """Talismans Path Synergies: Living Ink and Spirit-Written Seal.

    Use native owned Path IDs and the shipped Sphere/Path authority, never a
    character name, key ability, or a caller-supplied claim of Path ownership.
    """
    from factory_authoring.path_access import access
    paths = set(have['paths']) | {have['path_id']}
    if paths & {QI, SPIRIT}:
        admitted = access().get(SPHERE) or {}
        paths &= set(admitted.get('primary', [])) | set(admitted.get('open', []))
    else:
        paths.clear()  # unrelated/no Path needs no synergy authority lookup
    abilities = (sheet.get('ability_scores_and_statistics') or {}).get('abilities') or []
    if isinstance(abilities, str):
        abilities = json.loads(abilities)
    scores = {row.get('ability'): row.get('score') for row in abilities}
    choices = [{'value': ability, 'label': name, 'modifier': (scores[ability] - 10) // 2}
               for ability, name in [('INT', 'Intelligence'), ('WIS', 'Wisdom (Spirit-Written Seal)')]
               if (ability == 'INT' or SPIRIT in paths) and type(scores.get(ability)) is int]
    return choices, QI in paths and not state.get('qi_reroll_used', 0)


def outcome(project):
    total = project['check']['total']
    return ('learned' if total >= project['check_dc'] else
            'destroyed' if total <= project['check_dc'] - 5 else 'failed')


def procedure_forms(menu):
    """Complete source-owned forms for the sheet and out-of-combat seat caller."""
    def field(name, label, kind='text', **extra):
        return {'name': name, 'label': label, 'type': kind, **extra}
    def form(key, action, label, fields, defaults=None, gm=True):
        return {'id': key, 'action': action, 'label': label, 'fields': fields,
                'defaults': defaults or {}, 'gm': gm}
    formula_options = lambda rows: [{'value': r['id'], 'label': r['name']} for r in rows]
    forms = [form('grant-' + grant['rank'], 'choose', grant['label'],
                  [field('formula_id', 'Formula', 'select', options=formula_options(grant['options']), seat_choice=True)], gm=False)
             for grant in menu['grants'] if grant['options']]
    if menu['discoverable']:
        forms.append(form('discover', 'discover', 'Record a talisman discovered in play', [
            field('formula_id', 'Discovered formula', 'select', options=formula_options(menu['discoverable'])),
            field('discovery_id', 'Name this physical talisman (unique)'), field('provenance', 'Where it was found; GM confirmation'),
            field('crafting_dc', 'Crafting DC (leave empty for the printed rank default)', 'integer', optional=True)]))
    for index, project in enumerate(menu['projects']):
        key = 'project-' + str(index)
        defaults = {'discovery_id': project['discovery_id']}
        name = formula_catalog()[project['formula_id']]['name'] + ' — ' + project['discovery_id']
        if project['status'] == 'studying':
            forms.append(form(key, 'study', name + ': record actual study', [
                field('minutes', 'Elapsed study minutes', 'integer', minimum=1,
                      maximum=project['required_minutes'] - project['studied_minutes'])], defaults))
        elif project['status'] == 'awaiting_crafting_check':
            forms.append(form(key, 'check', name + ': report the crafting check', [
                field('ability', 'Check ability', 'select', options=menu['check_abilities'], seat_choice=True),
                field('d20', 'Physical d20 result', 'integer', minimum=1, maximum=20),
                field('roll_provenance', 'GM confirmation of this roll'),
                field('tool_name', 'Proficient tool approved by the GM', optional=True),
                field('tool_provenance', 'GM confirmation of tool proficiency and medium', optional=True),
                field('paid_cp', 'CP paid before rolling (adds +1 per point)', 'integer', minimum=0, maximum=menu['pb'], optional=True),
                field('payment_provenance', 'GM confirmation of the CP payment', optional=True)], defaults))
        elif project['status'] == 'awaiting_reroll':
            decisions = [{'value': 'decline', 'label': 'Keep the failed result'}]
            if menu['qi_reroll_available']:
                decisions.insert(0, {'value': 'reroll', 'label': 'Living Ink: reroll once per long rest; use the new result'})
            if menu['paid_reroll_available']:
                decisions.insert(-1, {'value': 'paid_reroll', 'label':
                    'Legendary Talisman Crafting: spend 5 CP to reroll; use the new result'})
            forms.append(form(key, 'resolve_failure', name + ': decide before failure or destruction', [
                field('decision', 'Failed Talisman Crafting Check: choose a reroll or keep the result',
                      'select', options=decisions, seat_choice=True),
                field('d20', 'New physical d20 (reroll only)', 'integer', minimum=1, maximum=20, optional=True),
                field('roll_provenance', 'GM confirmation of the new roll (reroll only)', optional=True),
                *([field('paid_cp', 'CP already paid for Legendary reroll (exactly 5; adds no bonus)',
                         'integer', minimum=5, maximum=5, optional=True),
                   field('payment_provenance', 'GM confirmation of the separate 5 CP reroll payment', optional=True)]
                  if menu['paid_reroll_available'] else [])], defaults))
        elif project['status'] == 'failed':
            forms.append(form(key, 'retry', name + ': start fresh study of the intact talisman', [], defaults))
    if menu['qi_reroll_used']:
        forms.append(form('long-rest', 'long_rest', 'Record a completed long rest to restore Living Ink', [
            field('rest_id', 'Unique completed long rest'), field('provenance', 'GM confirmation of the completed rest')]))
    return forms


def require(ok, message):
    if not ok:
        raise TabletopError('TABLE_FORMULA_INVALID', message, 409)


def external_text(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 500


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
    abilities, reroll = check_choices(sheet, have, state)
    menu = {'id': NAMESPACE, 'name': 'Talisman formula knowledge', 'revision': state.get('revision', 0),
             'grants': grants, 'discoverable': formulas if ADVANCED in have['talents'] else [],
             'projects': deepcopy(state.get('projects') or []),
             'study_minutes': 240 if archivist else 480,
             'check_requirement': 'After study, make a Talisman Crafting Check against the formula crafting DC + 2. '
                                  'Roll a d20 and add your Proficiency Bonus and the chosen ability modifier. '
                                  'Spirit Awakening may use Wisdom instead of Intelligence. '
                                  'Living Ink may reroll a failed check once per long rest before finalizing failure or destruction. '
                                  'Legendary Talisman Crafting may instead reroll a failed check for 5 Cultivation Points (CP). '
                                  'Either reroll must use the new result with the original modifiers. '
                                  'Report the physical d20 and any GM-confirmed tool proficiency or already-paid CP. '
                                  'Failure by 5 or more destroys the studied talisman.',
             'check_inputs': ['d20', 'roll_provenance', 'tool_name', 'tool_provenance', 'paid_cp', 'payment_provenance'],
             'payment_help': 'Before rolling, you may spend Cultivation Points (CP), up to your Proficiency Bonus, '
                             'for +1 to the check per point. Record that payment at the physical table; '
                             'this procedure does not deduct points from an active digital fight.',
            'pb': have['pb'], 'check_abilities': abilities, 'qi_reroll_available': reroll,
            'paid_reroll_available': LEGENDARY in have['talents'],
            'qi_reroll_used': int(bool(state.get('qi_reroll_used', 0)))}
    menu['forms'] = procedure_forms(menu)
    return [menu]


@hook('table_procedure_command')
def command(sheet, namespace, state, action, payload, gm):
    if namespace != NAMESPACE:
        return None
    have, archivist = ownership(sheet)
    require(SPHERE in have['spheres'], 'You need the Talismans sphere.')
    if action == 'choose':
        require(set(payload) == {'formula_id'}, 'Choose one printed formula.')
        require(isinstance(payload.get('formula_id'), str), 'Choose one printed formula.')
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
        require(isinstance(payload.get('formula_id'), str), 'Choose one printed formula.')
        require(ADVANCED in have['talents'], 'Advanced Talisman Crafting is required to reverse engineer a formula.')
        formula = formula_catalog().get(payload.get('formula_id'))
        require(formula and formula['rank'] in ('Common', 'Uncommon') and formula['minimum_cl'] <= have['cl'],
                'Reverse engineering permits Common or Uncommon formulae whose prerequisites you meet.')
        require(formula['id'] not in have['talents'], 'You already know that formula.')
        for key in ('discovery_id', 'provenance'):
            require(external_text(payload.get(key)),
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
                                 'paid_cp', 'payment_provenance', 'ability'}, 'Unknown crafting-check detail.')
        for key in ('roll_provenance', 'tool_name', 'tool_provenance', 'payment_provenance'):
            if key in payload:
                require(external_text(payload[key]), 'External check facts must be nonempty text of at most 500 characters.')
        require(ADVANCED in have['talents'], 'Advanced Talisman Crafting is required to reverse engineer a formula.')
        project = next((p for p in state.get('projects') or [] if p['discovery_id'] == payload.get('discovery_id')), None)
        require(project and project['status'] == 'awaiting_crafting_check', 'Finish the required study before the crafting check.')
        die, cp = payload.get('d20'), payload.get('paid_cp', 0)
        require(type(die) is int and 1 <= die <= 20, 'Report the actual physical d20 result, from 1 to 20.')
        require(type(cp) is int and 0 <= cp <= have['pb'], 'The crafting check permits paid CP up to your Proficiency Bonus.')
        for key in ('roll_provenance', *(['payment_provenance'] if cp else []),
                    *(['tool_provenance'] if payload.get('tool_name') else [])):
            require(external_text(payload.get(key)),
                    'The GM must record the actual roll, paid CP, and any proficient tool approved for this formula.')
        require(not payload.get('tool_name') or isinstance(payload['tool_name'], str) and len(payload['tool_name']) <= 120,
                'Name the proficient tool approved by the GM for this medium.')
        abilities, reroll = check_choices(sheet, have, state)
        ability = next((a for a in abilities if a['value'] == payload.get('ability', 'INT')), None)
        require(ability, 'Choose a recorded Intelligence score, or Wisdom if you own Spirit Awakening.')
        modifier = ability['modifier']
        tool_bonus = have['pb'] if payload.get('tool_name') else 0
        total = die + have['pb'] + modifier + tool_bonus + cp
        project['check'] = {**deepcopy(payload), 'pb': have['pb'], 'ability': ability['value'], 'ability_modifier': modifier,
                            'tool_bonus': tool_bonus, 'total': total}
        project['status'] = ('awaiting_reroll' if total < project['check_dc'] and
                             (reroll or LEGENDARY in have['talents']) else outcome(project))
    elif action == 'resolve_failure':
        require(gm, 'The GM must confirm the crafting-check decision and any new die.')
        require(set(payload) <= {'discovery_id', 'decision', 'd20', 'roll_provenance', 'paid_cp', 'payment_provenance'},
                'Unknown reroll detail.')
        project = next((p for p in state.get('projects') or [] if p['discovery_id'] == payload.get('discovery_id')), None)
        require(project and project['status'] == 'awaiting_reroll', 'There is no failed check awaiting a decision.')
        decision = payload.get('decision')
        require(decision in ('reroll', 'paid_reroll', 'decline'),
                'Choose an owned reroll or keep the failed result.')
        if decision in ('reroll', 'paid_reroll'):
            require(ADVANCED in have['talents'], 'Advanced Talisman Crafting is required to reverse engineer a formula.')
            if decision == 'reroll':
                require(check_choices(sheet, have, state)[1], 'Living Ink is not available until your next long rest.')
                require(not ({'paid_cp', 'payment_provenance'} & set(payload)),
                        'Living Ink is free; do not record a Legendary reroll payment.')
            else:
                require(LEGENDARY in have['talents'], 'You need Legendary Talisman Crafting for the paid reroll.')
                require(type(payload.get('paid_cp')) is int and payload['paid_cp'] == 5 and
                        external_text(payload.get('payment_provenance')),
                        'The GM must confirm exactly 5 CP already paid for this reroll; the payment adds no check bonus.')
            die = payload.get('d20')
            require(type(die) is int and 1 <= die <= 20 and external_text(payload.get('roll_provenance')),
                    'Report the new physical d20 and its GM confirmation.')
            first = deepcopy(project['check'])
            project['check'].update(d20=die, roll_provenance=payload['roll_provenance'],
                                    total=first['total'] - first['d20'] + die, rerolled=1, first_roll=first,
                                    reroll_source=QI if decision == 'reroll' else LEGENDARY)
            if decision == 'reroll':
                state['qi_reroll_used'] = 1
            else:
                project['check']['reroll_payment'] = {'paid_cp': 5, 'payment_provenance': payload['payment_provenance']}
        else:
            require(set(payload) <= {'discovery_id', 'decision'}, 'Keeping the result does not accept a new roll.')
        project['status'] = outcome(project)
    elif action == 'long_rest':
        require(gm and set(payload) == {'rest_id', 'provenance'} and
                all(external_text(payload.get(k)) for k in ('rest_id', 'provenance')),
                'The GM must confirm a uniquely identified completed long rest.')
        require(QI in (set(have['paths']) | {have['path_id']}), 'Living Ink requires Qi Cultivation.')
        require(not any(p['status'] == 'awaiting_reroll' for p in state.get('projects') or []),
                'Resolve pending crafting-check decisions before recording a later rest.')
        rests = state.setdefault('completed_rests', [])
        require(payload['rest_id'] not in rests, 'That long rest was already recorded.')
        rests.append(payload['rest_id'])
        state['qi_reroll_used'] = 0
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
