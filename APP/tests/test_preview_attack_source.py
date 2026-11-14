from combat import attack_modes
from combat.ext.sniper_precision import FAR
from combat.roll_reasons import attack_preview
from tests.auto_worker1_support import LEFT, RIGHT, fight, reload, resolve


def thrown_fight(tmp_path):
    dagger = {'items': [{'item_id': 'tianxia.mortal.weapon.bi_shou',
                         'name': 'Bi Shou (Dagger)', 'quantity': 1}]}

    def prepare(bundle):
        if bundle['actor_id'] != LEFT:
            return
        for action in bundle['action_catalog']:
            if action['display_name'] == 'Bi Shou (Dagger) thrown':
                typed = action['parameters'].get('typed') or {}
                typed.update(range_ft=20, long_range_ft=60, strike_penalty_provenance=1)
                action['range_ft'] = 60

    combat, table, mid = fight(tmp_path, [FAR], left_kit=dagger,
        positions={LEFT: {'x': 3, 'y': 5}, RIGHT: {'x': 10, 'y': 5}},
        bundle_edit=prepare)
    engine = combat._load_session(mid).engine
    action = next(a for a in engine.action_catalog.values()
                  if a.owner_id == LEFT and a.display_name == 'Bi Shou (Dagger) thrown')
    return combat, table, mid, engine, action


def table_roll(combat, table, mid, action):
    def send(answers):
        state = table.state(mid)
        menu = state['menu']
        candidates = combat._load_session(mid).engine.legal_candidates()
        matches = [c for c in candidates if c.source_definition_id == action.source_definition_id
                   and RIGHT in c.target_ids]
        assert matches, {'labels': [group['label'] for group in menu['actions']],
                         'candidates': [c.model_dump(mode='json') for c in candidates]}
        return table.act(mid, matches[0].candidate_id, menu['decision_id'], menu['state_version'],
                         state['last_sequence'], answers)

    resolve(send)
    return next(e.payload for e in reversed(reload(combat, mid).events)
                if e.event_type == 'ATTACK_ROLLED' and e.actor_id == LEFT)


def test_far_shot_preview_matches_table_roll(tmp_path):
    combat, table, mid, engine, action = thrown_fight(tmp_path)
    preview = attack_preview(engine, engine.state.actors[LEFT], engine.state.actors[RIGHT], action)
    assert not [row for row in preview['mode_sources'] if row['effect'] == 'Long range']
    assert preview['mode'] == table_roll(combat, table, mid, action)['mode'] == 'NORMAL'


def test_explicit_attack_removals_match_roll(tmp_path):
    combat, table, mid, engine, action = thrown_fight(tmp_path)
    effect = next(e for e in action.parameters['typed']['effects'] if e.get('type') == 'attack')
    tokens = attack_modes.removed(engine, engine.state.actors[LEFT], engine.state.actors[RIGHT],
                                  ranged=True, attack=(action.source_definition_id, effect))
    assert tokens == frozenset(table_roll(combat, table, mid, action)['attack_mode_removed'])
    assert 'DISADVANTAGE:long_range' in tokens
