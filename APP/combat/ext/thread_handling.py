"""Spool and Strand's ordinary handling of actual thread tools/workpieces.

Named, typed task facts establish whether the situation is difficult and its
ordinary check DC; they do not approve a result. Native handling checks actual
owned materials, rolls only when difficult, and changes the workpiece's physical
thread state. Nothing restrains, damages, heals or creates a trap.

Shared helpers: combat_facts(engine, aid) and current_work(engine, actor) are
public reads of the same actor-owned work used by thread_weaving (its sleeve
origin reads combat_facts). They change nothing and stay inside this module.
"""
from copy import deepcopy
from . import hook, effect, note
import json
from . import material_ledger as ledger
from ..journey import require, integer
SOURCE = 'THREAD_BASE_SPOOL_AND_STRAND'
OPERATIONS = ('prepare', 'draw', 'control', 'conceal', 'sew', 'bind', 'stitch', 'tie_knot', 'mend_cloth', 'mark_path', 'set_cord', 'hide_spool', 'finework')
TOOLS = ('thread', 'silk', 'wire', 'cord', 'needles', 'hooks')
WORK_STATE = 'condition:typed.threadwork_state'


@hook('journey_persistent_fields')
def persistent():
    return ('thread_tasks', 'thread_facts')


@hook('journey_admission')
def task_fact(session, aid, kind, payload, reason):
    if kind != 'thread_task': return None
    require(ledger.owned(session, aid, SOURCE), 'This creature has not learned Spool and Strand.')
    require({'id', 'operation', 'target'} <= set(payload) <= {'id', 'operation', 'target', 'difficulty', 'dc', 'ability'}, 'Record a typed thread task and any actual difficulty.')
    if payload.get('difficulty', 'ordinary') == 'difficult':
        require({'dc', 'ability'} <= set(payload), 'A difficult situation needs its declared check ability and DC.')
    payload = {'difficulty': 'ordinary', 'dc': 0, 'ability': 'DEX', **payload}
    ledger.identity(payload['id'])
    require(payload['operation'] in (*OPERATIONS,'*') and payload['difficulty'] in ('ordinary', 'difficult')
            and payload['ability'] in ('STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA')
            and integer(payload['dc']) and ((payload['difficulty'] == 'ordinary' and payload['dc'] == 0)
                or (payload['difficulty'] == 'difficult' and payload['dc'] > 0)), 'Record ordinary work without a check, or the difficult situation’s actual check DC and ability.')
    require(isinstance(payload['target'],str), 'Choose a named recorded workpiece.')
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
    require({'task','tool'} <= set(payload) <= {'task','tool','operation'} and all(isinstance(v,str) for v in payload.values()), 'Choose a recorded thread task and an actual thread tool.')
    actor = session.state['actors'][aid]
    task = actor.get('thread_tasks', {}).get(payload['task'])
    require(task is not None, 'Choose a recorded work context of your own.')
    require(not task.get('completed'), 'This work is already completed; record a new actual task before repeating it.')
    operation = payload.get('operation',task['operation'])
    require(operation in OPERATIONS and task['operation'] in ('*',operation), 'Choose a printed thread operation for this context.')
    effective = {**task,'operation':operation}
    items = ledger.holdings(session, aid)
    tool = items.get(payload['tool'])
    require(tool is not None and tool['quantity'] > 0 and tool['kind'] == 'thread_tool'
            and ledger.sources(session).get(tool['source_id'], {}).get('material') in TOOLS, 'Choose one of the printed mundane thread tools you actually own.')
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
        apply(items, effective, payload['tool'])
        task['completed'] = 1
    session.emit('THREAD_HANDLED', aid, task_id=task['id'], operation=operation,
                 tool=payload['tool'], target=task['target'], success=int(success), economy='NONE', cost=0)
    return True


@hook('journey_options')
def options(session, aid):
    actor = session.state['actors'][aid]
    if not ledger.owned(session, aid, SOURCE) or session.state['phase'] != 'travel' or actor['incapacitated']:
        return None
    rows = []
    items = ledger.holdings(session,aid)
    for task_id,task in actor.get('thread_tasks',{}).items():
        if task['target'] not in items or items[task['target']]['quantity'] <= 0: continue
        if task.get('completed'): continue
        for operation in (OPERATIONS if task['operation']=='*' else (task['operation'],)):
            for key,tool in items.items():
                if (tool['kind'] != 'thread_tool' or tool['quantity'] <= 0
                        or ledger.sources(session).get(tool['source_id'], {}).get('material') not in TOOLS): continue
                rows.append({'id':f'threadwork:{task_id}:{operation}:{key}','kind':'thread_handle','auto_select':int(actor['control_mode'] == 'LOCAL_AUTO'),
                    'payload':{'task':task_id,'tool':key,'operation':operation},
                    'label':f'Spool and Strand: {operation.replace("_"," ")} {items[task["target"]]["name"]} using {tool["name"]}; no Action or Cultivation Point cost. '
                    + ('Ordinary handling needs no check.' if task['difficulty']=='ordinary' else 'The difficult situation requires its recorded ability check.')})
    return rows



@hook('journey_view')
def private(state, viewer_id):
    if not (any('thread_tasks' in a or 'thread_facts' in a for a in state['actors'].values())
            or _snapshots_hold_work(state)):
        return None
    out = deepcopy(state); out.pop('replay_base', None); out.pop('command_journal', None)
    for aid,actor in out['actors'].items():
        if aid != viewer_id:
            actor.pop('thread_tasks', None)
            actor.pop('thread_facts', None)
            actor.get('bundle', {}).pop('thread_handling', None)
    events = []
    for event in out['events']:
        owned = event['actor_id'] == viewer_id
        if event['kind'].startswith('THREAD') and not owned:
            continue
        snapshot = event.get('previous_state')
        if isinstance(snapshot, str) and not owned:
            event = {**event, 'previous_state': _conceal_work(snapshot)}
        events.append(event)
    out['events'] = events
    return out


def _conceal_work(raw):
    """Drop this plug-in's hidden physical-work record from one creature snapshot.

    A GM encounter resolution stores the whole creature as ``previous_state``;
    the hidden condition document (workpieces, tools, tasks, sources) inside it
    is private to its owner, so other viewers must not receive it.
    """
    try:
        row = json.loads(raw)
    except (TypeError, ValueError):
        return raw
    conditions = row.get('conditions') if isinstance(row, dict) else None
    if not isinstance(conditions, dict):
        return raw
    kept = {key: value for key, value in conditions.items()
            if not (isinstance(value, dict) and value.get('condition_id') == WORK_STATE)}
    if len(kept) == len(conditions):
        return raw
    row['conditions'] = kept
    return json.dumps(row, sort_keys=True)


def _snapshots_hold_work(state):
    """Whether any retained event snapshot carries this plug-in's hidden record."""
    return any(isinstance(event.get('previous_state'), str) and WORK_STATE in event['previous_state']
               for event in state.get('events', ()))


@hook('journey_admission')
def sleeve_fact(session, aid, kind, payload, reason):
    if kind != 'thread_sleeve':
        return None
    require(ledger.owned(session, aid, SOURCE), 'Only a Thread owner needs a strand origin.')
    require(set(payload) == {'item_key'} and isinstance(payload['item_key'], str),
            'Name the actual recorded garment with a sleeve.')
    actor = session.state['actors'][aid]
    item = next((r for r in actor['bundle'].get('carrying', {}).get('items', ())
                 if r['key'] == payload['item_key']), None)
    require(item is not None and item.get('quantity', 0) > 0 and
            ((item.get('kind') == 'armor' and item.get('worn') and not item.get('shield'))
             or str(item.get('item_id') or '').startswith('tianxia.mortal.gear.clothes_')),
            'The sleeve must belong to your actual recorded garment.')
    actor.setdefault('thread_facts', {})['sleeve'] = {'item_key': item['key'], 'provenance': reason}
    session.emit('THREAD_SLEEVE_RECORDED', aid, item_key=item['key'])
    return True


@hook('journey_combat_bundle')
def snapshot(bundle, session, aid):
    actor = session.state['actors'][aid]
    if not ledger.owned(session, aid, SOURCE):
        return None
    return {**bundle, 'thread_handling': {
        'facts': deepcopy(actor.get('thread_facts', {})),
        'tasks': deepcopy(actor.get('thread_tasks', {})),
        'holdings': deepcopy(ledger.holdings(session, aid)),
        'sources': {key: deepcopy(row) for key, row in ledger.sources(session).items()
                    if aid in row['known_to']}}}


def combat_document(engine, aid):
    """Public sealed Thread work context; consumed by handling and Qi origins."""
    return next((b.get('thread_handling', {}) for b in engine.typed_bundle_documents
                 if b.get('actor_id') == aid), {})


def combat_facts(engine, aid):
    """Public actual garment facts for thread_weaving's sleeve-origin gate."""
    return combat_document(engine, aid).get('facts', {})


def current_work(engine, actor):
    """Public physical work continuation, also used at the journey boundary."""
    held = next((c for c in actor.conditions.values() if c.condition_id == WORK_STATE
                 and c.source_actor_id == actor.entity_id), None)
    return json.loads(held.data['document']) if held else deepcopy(combat_document(engine, actor.entity_id))


def work_choices(document, operation):
    return {f'{task_id}|{key}': (task_id, key)
            for task_id, task in document.get('tasks', {}).items()
            if not task.get('completed') and task['operation'] in ('*', operation)
            and document.get('holdings', {}).get(task['target'], {}).get('quantity', 0) > 0
            for key, tool in document.get('holdings', {}).items()
            if tool['kind'] == 'thread_tool' and tool['quantity'] > 0
            and document.get('sources', {}).get(tool['source_id'], {}).get('material') in TOOLS}


@hook('compile_actions')
def combat_handling(info):
    if SOURCE not in info['owned_ids']:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.spool.handle.{operation}",
            owner_id=info['actor_id'], display_name=f"Spool and Strand: {operation.replace('_', ' ')}",
            economy=EconomyKind.NONE, resolution_kind='TYPED', target_kind='SELF',
            parameters={'expected_damage': 0, 'typed': {'source': SOURCE,
                'numbers': dict(info['numbers']), 'riders': [],
                'effects': [{'type': 'thread_handle_work', 'operation': operation}]},
                'description': 'Handle your recorded workpiece with your own thread tool; no Action or Cultivation Point cost. Only a declared difficult situation requires a check; this cannot restrain, damage or create traps.'})
            for operation in OPERATIONS]


@hook('candidate_allowed')
def handling_available(engine, actor, candidate, action):
    rows = (((getattr(action, 'parameters', None) or {}).get('typed')) or {}).get('effects', ())
    row = next((r for r in rows if r.get('type') == 'thread_handle_work'), None)
    return bool(work_choices(current_work(engine, actor), row['operation'])) if row else None


@effect('thread_handle_work', harmful=False)
def handle_combat(ctx, row):
    from .needle import ask, checkpoint_id
    from .condition_ownership import refresh_owned
    document = current_work(ctx.engine, ctx.actor)
    choices = work_choices(document, row['operation'])
    if not choices:
        return
    labels = {key: f"{document['holdings'][document['tasks'][tid]['target']]['name']} using {document['holdings'][tool]['name']}; "
              + ('no check' if document['tasks'][tid]['difficulty'] == 'ordinary'
                 else f"{document['tasks'][tid]['ability']} check, DC {document['tasks'][tid]['dc']}")
              for key, (tid, tool) in choices.items()}
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'thread_work', ctx.source),
                   ctx.actor, 'choice:needle.thread_work', list(choices), labels=labels,
                   name='Spool and Strand',
                   prompt=f"Spool and Strand: {row['operation'].replace('_', ' ')} which workpiece with which tool? No Action or Cultivation Point cost; this cannot restrain, damage or create a trap.")
    if not selected:
        return
    tid, tool = choices[selected[0]]
    task = document['tasks'][tid]
    success = True
    if task['difficulty'] == 'difficult':
        from ..ability_checks import ability_modifier
        roll = ctx.engine.roll_check(modifier=ability_modifier(ctx.actor, task['ability'], numbers=ctx.numbers),
                                     actor_id=ctx.actor.entity_id, reason='CHECK:Threadwork', ability=task['ability'])
        success = roll.total >= task['dc']
        note(ctx.engine, ctx.source, ctx.actor, f"Spool and Strand: {task['ability']} check {roll.total} against DC {task['dc']}.")
    if success:
        apply(document['holdings'], {**task, 'operation': row['operation']}, tool)
        task['completed'] = 1
    refresh_owned(ctx.engine, ctx.actor, WORK_STATE, ctx.actor.entity_id, ctx.source)
    ctx.engine._apply_condition(ctx.actor, WORK_STATE, ctx.source, ctx.actor.entity_id,
        expires_on='UNTIL_REMOVED', data={'label': 'Threadwork', 'hidden': 1,
        'document': json.dumps(document, sort_keys=True),
        'reading': 'Your physical threadwork is recorded; this grants no combat bonus, restraint, damage or trap.'})
    concealed_work = row['operation'] in ('conceal', 'hide_spool')
    description = ('handles their own threadwork privately' if concealed_work else
        ('completes' if success else 'does not complete') + f" {row['operation'].replace('_', ' ')} on "
        + document['holdings'][task['target']]['name'])
    note(ctx.engine, ctx.source, ctx.actor,
         f"Spool and Strand: {ctx.actor.display_name} {description} (no Action or Cultivation Point cost).",
         history_hidden=int(concealed_work))


@hook('journey_encounter_settled')
def resume_work(session, aid, engine, actor):
    if not ledger.owned(session, aid, SOURCE):
        return
    document = current_work(engine, actor)
    if document:
        session.state['actors'][aid]['thread_tasks'] = deepcopy(document.get('tasks', {}))
        session.state['actors'][aid]['material_holdings'] = deepcopy(document.get('holdings', {}))


@hook('journey_snapshot_actor')
def work_snapshot(actor, session, aid, engine):
    """Physical work transfers into holdings, never a stale encounter condition."""
    if not ledger.owned(session, aid, SOURCE):
        return None
    out = actor.model_copy(deep=True)
    out.conditions = {key: c for key, c in out.conditions.items()
                      if c.condition_id != WORK_STATE or c.source_actor_id != aid}
    return out


@hook('presentation_hidden_conditions')
def hidden_work(engine, actor):
    return [key for key, c in actor.conditions.items() if c.condition_id == WORK_STATE]
