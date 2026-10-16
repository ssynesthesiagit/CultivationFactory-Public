"""Spool and Strand's ordinary handling of actual thread tools/workpieces.

Named, typed task facts establish whether the situation is difficult and its
ordinary check DC; they do not approve a result. Native handling checks actual
owned materials, rolls only when difficult, and changes the workpiece's physical
thread state. Nothing restrains, damages, heals or creates a trap.
"""
from copy import deepcopy
from . import hook
from . import material_ledger as ledger
from ..journey import require, integer
SOURCE = 'THREAD_BASE_SPOOL_AND_STRAND'
OPERATIONS = ('prepare', 'draw', 'control', 'conceal', 'sew', 'bind', 'stitch', 'tie_knot', 'mend_cloth', 'mark_path', 'set_cord', 'hide_spool', 'finework')
TOOLS = ('thread', 'silk', 'wire', 'cord', 'needles', 'hooks')


@hook('journey_persistent_fields')
def persistent():
    return ('thread_tasks',)


@hook('journey_admission')
def task_fact(session, aid, kind, payload, reason):
    if kind != 'thread_task': return None
    require(ledger.owned(session, aid, SOURCE), 'This creature has not learned Spool and Strand.')
    require(set(payload) == {'id', 'operation', 'target', 'difficulty', 'dc', 'ability'}, 'Record a typed thread task and its actual difficulty.')
    ledger.identity(payload['id'])
    require(payload['operation'] in OPERATIONS and payload['difficulty'] in ('ordinary', 'difficult')
            and payload['ability'] in ('DEX', 'CON', 'INT', 'WIS')
            and integer(payload['dc']) and ((payload['difficulty'] == 'ordinary' and payload['dc'] == 0)
                or (payload['difficulty'] == 'difficult' and payload['dc'] > 0)), 'Record ordinary work without a check, or the difficult situation’s actual check DC and ability.')
    target = ledger.holdings(session, aid).get(payload['target'])
    require(target is not None and target['quantity'] > 0, 'Choose an actual workpiece this creature owns.')
    tasks = session.state['actors'][aid].setdefault('thread_tasks', {})
    require(payload['id'] not in tasks, 'That thread task already exists.')
    tasks[payload['id']] = {**deepcopy(payload), 'provenance': reason, 'completed': 0}
    session.emit('THREAD_TASK_RECORDED', aid, task_id=payload['id'])
    return True


def apply(holdings, task, tool_key):
    tool, target = holdings.get(tool_key), holdings.get(task['target'])
    require(tool is not None and tool['quantity'] > 0 and tool['kind'] == 'thread_tool', 'Use your own actual thread, silk, wire, cord, needles or hooks.')
    require(target is not None and target['quantity'] > 0, 'The named workpiece is no longer available.')
    state = target.setdefault('threadwork', {})
    op = task['operation']
    if op in ('sew', 'stitch'): state['stitched'] = 1
    elif op == 'mend_cloth': state['mended'] = 1
    elif op in ('bind', 'tie_knot'): state['knotted'] = 1
    elif op == 'set_cord': state['cord_set'] = 1
    elif op in ('hide_spool', 'conceal'): state['concealed'] = 1
    elif op == 'mark_path': state['path_marked'] = 1
    elif op in ('prepare', 'draw', 'control'): state['handling'] = op
    else: state['fine_threadwork'] = 1
    state['tool_id'] = tool_key
    return state


@hook('journey_command')
def handle(session, aid, kind, payload):
    if kind != 'thread_handle': return None
    require(ledger.owned(session, aid, SOURCE) and not session.state['actors'][aid]['incapacitated'], 'An active Spool and Strand owner must perform this handling.')
    require(set(payload) == {'task', 'tool'}, 'Choose a recorded thread task and an actual thread tool.')
    actor = session.state['actors'][aid]
    task = actor.get('thread_tasks', {}).get(payload['task'])
    require(task is not None and not task['completed'], 'Choose an unfinished task of your own.')
    items = ledger.holdings(session, aid)
    tool = items.get(payload['tool'])
    require(tool is not None and tool['quantity'] > 0 and tool['kind'] == 'thread_tool'
            and ledger.sources(session)[tool['source_id']]['material'] in TOOLS, 'Choose one of the printed mundane thread tools you actually own.')
    success = True
    if task['difficulty'] == 'difficult':
        from ..gate2_rolls import DeterministicRollAuthority
        roller = DeterministicRollAuthority(session.state['journey_id'] + ':threadwork')
        roller.counter = actor.get('material_preparation', {}).get('thread_roll_counter', 0)
        roll = roller.d20(modifier=ledger.numbers(session, aid)['ability_mods'][task['ability']], actor_id=aid, reason='CHECK:Threadwork')
        actor.setdefault('material_preparation', {})['thread_roll_counter'] = roller.counter
        success = roll.total >= task['dc']
        session.emit('THREADWORK_CHECK', aid, task_id=task['id'], roll=roll.model_dump(mode='json'), dc=task['dc'])
    if success:
        apply(items, task, payload['tool'])
        task['completed'] = 1
    session.emit('THREAD_HANDLED', aid, task_id=task['id'], operation=task['operation'],
                 tool=payload['tool'], target=task['target'], success=int(success), economy='NONE', cost=0)
    return True


@hook('journey_options')
def options(session, aid):
    actor = session.state['actors'][aid]
    if not ledger.owned(session, aid, SOURCE) or session.state['phase'] != 'travel' or actor['incapacitated']:
        return None
    return [{'id': f'threadwork:{task_id}:{key}', 'kind': 'thread_handle', 'payload': {'task': task_id, 'tool': key},
             'label': f'Spool and Strand: {task["operation"].replace("_", " ")} {items[task["target"]]["name"]} using {tool["name"]}; no Action or Cultivation Point cost. ' + ('Ordinary handling needs no check.' if task['difficulty'] == 'ordinary' else 'The difficult situation requires its recorded ability check.')}
            for task_id, task in actor.get('thread_tasks', {}).items() if not task['completed']
            for items in [ledger.holdings(session, aid)] if task['target'] in items and items[task['target']]['quantity'] > 0
            for key,tool in items.items() if tool['kind'] == 'thread_tool' and tool['quantity'] > 0]


@hook('journey_view')
def private(state, viewer_id):
    if not any('thread_tasks' in a for a in state['actors'].values()): return None
    out = deepcopy(state); out.pop('replay_base', None); out.pop('command_journal', None)
    for aid,actor in out['actors'].items():
        if aid != viewer_id: actor.pop('thread_tasks', None)
    out['events'] = [e for e in out['events'] if not e['kind'].startswith('THREAD') or e['actor_id'] == viewer_id]
    return out
