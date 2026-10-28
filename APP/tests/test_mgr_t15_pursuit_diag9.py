"""TEMPORARY diagnostics #9: Blink Guard receipt provenance (not for commit)."""
import json

from combat import ext
from combat.ext.ability_source import mechanic_of, compiled_feature_rows
from tests.cw2_service_support import add_action
from tests.worker2_support import turn, OWNER, ALLY, FOE
from tests.test_mgr_t15_pursuit_horizon import fight, action, chase_events


def test_diag_blink_guard_receipt(tmp_path):
    trace = []
    hooks = ext._HOOKS['committed_teleport_receipt']
    for index, fn in enumerate(list(hooks)):
        if getattr(fn, '__name__', '') == 'pursuit_teleport':
            def wrapper(engine, receipt, fn=fn):
                actor = engine.state.actors[receipt['actor_id']]
                source = receipt['source_definition_id']
                feature = receipt['source_feature_id']
                action = engine.action_catalog.get(source)
                trace.append(('receipt', dict(receipt),
                              {'catalog': action is not None,
                               'owner': getattr(action, 'owner_id', None),
                               'owner_is_actor': getattr(action, 'owner_id', None) == actor.entity_id,
                               'in_action_ids': source in (actor.action_ids or ()),
                               'mechanic': mechanic_of(action) if action is not None else None,
                               'mechanic_is_feature': (mechanic_of(action) if action is not None else None) == feature,
                               'source_is_feature': source == feature,
                               'feature_rows': len(compiled_feature_rows(engine, actor.entity_id, feature)),
                               'actor_action_ids': list(actor.action_ids or ())[:8],
                               'catalog_has_feature': any(
                                   mechanic_of(a) == feature for a in engine.action_catalog.values()
                                   if getattr(a, 'owner_id', None) == actor.entity_id)}))
                return fn(engine, receipt)
            hooks[index] = wrapper

    def prepare(bundles):
        add_action(bundles[0], 'Trigger attack', [{'type': 'attack', 'attack_kind': 'ranged_cultivation',
                   'count': 1, 'on_hit': []}], typed={'numbers': {'cl': 14, 'pb': 5, 'attack_bonus': 100, 'save_dc': 16}})
    combat, table, mid = fight(tmp_path, prepare=prepare,
                               foe_talents=['tianxia.talent.space.blink_guard'])
    engine, prompts = action(tmp_path, mid, 'Trigger attack', target=FOE)
    report = {'trace': [str(row) for row in trace],
              'chase': len(chase_events(engine)),
              'prompts': [p['context'].get('reaction_source_id') for p in prompts],
              'foe': engine.state.actors[FOE].position.model_dump()}
    assert False, 'DIAG ' + json.dumps(report, default=str)
