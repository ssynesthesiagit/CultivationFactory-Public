"""Native reaction receipts use the same attack budget, without lock-file edits."""
from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.hunt24_support import A
from tests.hunt23_support import action_sender, turn
from tests.test_hunt24_reduction import attack_bundle, SOURCE


def test_native_stamina_guard_covers_mixed_hit_and_reloads(tmp_path):
    bundle = compile_character(sheet([]), actor_id=A)
    attack_bundle(bundle)
    bundle.pop('bundle_sha256', None)
    bundle['bundle_sha256'] = canonical_sha256(bundle)
    svc = CombatService(ROOT, tmp_path)
    mid = svc._finish_factory_match([bundle], [A, AN], {A:'a',AN:'b'},
        {A:{'x':3,'y':6}, AN:{'x':4,'y':6}}, svc.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],
        [A], [AN], control_modes={A:'MANUAL', AN:'MANUAL'}, match_seed='HUNT24',
        display_name='Native reduction regression', maximum_rounds=4)['match_id']
    table = TabletopService(svc, tmp_path); turn(table, mid, A)
    send = action_sender(svc, table, mid, SOURCE, target_id=AN)
    answers = []
    for _ in range(12):
        result = send(answers)
        if result['status'] != 'REACTION_REQUIRED':
            break
        prompt = result['reaction']
        guard = prompt['context']['reaction_source_id'] == 'reaction:core.stamina_guard'
        answers.append({**prompt['context'], 'selection':'USE' if guard else 'DECLINE', 'spend':2 if guard else 0})
    assert result['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    resolution = next(e for e in loaded.engine.events if e.event_type == 'REACTION_RESOLVED'
                      and e.source_definition_id == 'reaction:core.stamina_guard')
    packets = [e.payload for e in loaded.engine.events if e.event_type == 'DAMAGE_COMMITTED' and AN in e.target_ids]
    assert len(packets) == 2
    assert sum(p['hp_damage'] for p in packets) == max(0, sum(p['rolled_or_pending_damage'] for p in packets) - resolution.payload['reduction'])
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
