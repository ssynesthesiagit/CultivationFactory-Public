"""TEMPORARY diagnostics #4 for the Pursuit teleport trigger (not for commit)."""
import json

from combat import ext
from tests.worker2_support import turn, OWNER, ALLY, FOE
from tests.test_mgr_t15_pursuit_horizon import fight, action, chase_events


def test_diag_flash_step_gates(tmp_path):
    combat, table, mid = fight(tmp_path, foe_talents=['TAL_ATHLETICS_FLASH_STEP'])
    turn(table, mid, FOE)
    engine, prompts = action(tmp_path, mid, 'Flash Step', pending=True)
    report = {}
    receipt = {'actor_id': FOE, 'source_definition_id': 'action:typed.bab13d9948.flash_step',
               'source_feature_id': 'TAL_ATHLETICS_FLASH_STEP', 'willing': 1, 'self_teleport': 1}
    actor = engine.state.actors[FOE]
    watcher = engine.state.actors[OWNER]
    from combat.ext.ability_source import mechanic_of, compiled_feature_rows
    from combat.typed_reactions import (_ordered_generic_rows, _can_trigger, _generic_affordable,
                                        _generic_in_range, _subject_ok)
    act = engine.action_catalog.get(receipt['source_definition_id'])
    report['catalog_owner'] = act.owner_id if act is not None else None
    report['in_action_ids'] = receipt['source_definition_id'] in actor.action_ids
    report['mechanic'] = mechanic_of(act) if act is not None else None
    report['compiled'] = len(compiled_feature_rows(engine, actor.entity_id, receipt['source_feature_id']))
    rows = _ordered_generic_rows(engine, OWNER, 'sky_pursuit_teleport')
    report['rows'] = [(r.get('kind'), r.get('feature_id')) for r in rows]
    if rows:
        row = rows[0]
        report['can_trigger'] = _can_trigger(engine, watcher, row)
        report['affordable'] = _generic_affordable(engine, watcher, row)
        report['in_range'] = _generic_in_range(engine, watcher, actor, row)
        report['subject_ok'] = _subject_ok(engine, watcher, actor, row)
        report['reaction_available'] = watcher.reaction_available
        report['stamina'] = watcher.resources.get('resource:core.stamina')
        report['once_used'] = watcher.turn_flags.get('once_per_round:typed.tianxia.subpath.body.sky_treading_tendon_school.feature.pursuit_without_horizon')
        from combat.target_knowledge import can_see
        report['can_see'] = can_see(engine, watcher, actor)
    try:
        ext.run_strict('committed_teleport_receipt', engine, receipt)
        report['manual_dispatch'] = 'returned'
    except BaseException as exc:  # noqa: BLE001 - diagnostics
        report['manual_dispatch'] = f'{type(exc).__name__}: {exc}'
    report['chase_after'] = len(chase_events(engine))
    report['provider'] = repr(getattr(engine, '_gate4_reaction_provider', None))
    assert False, 'DIAG ' + json.dumps(report, default=str)


def test_diag_blink_guard_visible_landing(tmp_path):
    from tests.cw2_service_support import add_action

    def prepare(bundles):
        add_action(bundles[0], 'Trigger attack', [{'type': 'attack', 'attack_kind': 'ranged_cultivation',
                   'count': 1, 'on_hit': []}], typed={'numbers': {'cl': 14, 'pb': 5, 'attack_bonus': 100, 'save_dc': 16}})
    combat, table, mid = fight(tmp_path, prepare=prepare,
                               foe_talents=['tianxia.talent.space.blink_guard'])
    seen = []

    def pick(prompt, options):
        seen.append(prompt['context']['reaction_source_id'])
        if prompt['context']['reaction_source_id'] == 'choice:needle.reaction_teleport':
            for option in options:
                if option.get('cell') == {'x': 8, 'y': 6}:
                    return option['id']
        return ((prompt.get('choice') or {}).get('preferred') or [options[0]['id']])[0]

    engine, prompts = action(tmp_path, mid, 'Trigger attack', target=FOE, pick=pick)
    report = {'seen': seen, 'chase': len(chase_events(engine)),
              'foe_pos': (engine.state.actors[FOE].position.x, engine.state.actors[FOE].position.y),
              'owner_pos': (engine.state.actors[OWNER].position.x, engine.state.actors[OWNER].position.y),
              'prompts': [p['context']['reaction_source_id'] for p in prompts]}
    assert False, 'DIAG ' + json.dumps(report, default=str)
