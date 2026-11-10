"""Owned follow-ups keep one payment and offer only usable weapons at the table."""
import json
from pathlib import Path
import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests import test_riders_c7 as c7
from tests.r10_fixup_support import cast_sender, commit, fixed_dice


def table_fight(tmp_path, features, *, items=(), legacy_king=False):
    combat = CombatService(c7.ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    owner = c7.sheet(features, items=items)
    owner['path_and_subpath']['path_record_ids'] = ['tianxia.path.body_refining']
    bundles = [c7.compile_character(owner, actor_id=c7.ME), c7.bundle([], actor_id=c7.FOE, spheres={}, name='Target')]
    if legacy_king:
        # Exact generic row compiled at 0d6ea59, retained as compact evidence.
        row = json.loads((Path(__file__).parent / 'fixtures/r24_beast_king_legacy.json').read_text())
        bundles[0]['typed_reactions'].append(row)
    mid = combat._finish_factory_match(bundles, [c7.ME, c7.FOE],
        {c7.ME: 'team:factory', c7.FOE: 'team:opponents'},
        {c7.ME: {'x': 3, 'y': 6}, c7.FOE: {'x': 4, 'y': 6}},
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'], [c7.ME], [c7.FOE],
        control_modes={c7.ME: 'MANUAL', c7.FOE: 'MANUAL'}, match_seed='R24-PLUGIN-ACTIVATION',
        display_name='Owned activation regression', maximum_rounds=20)['match_id']
    while table.state(mid)['menu']['actor_id'] != c7.ME:
        commit(cast_sender(combat, table, mid, 'End turn'),
               lambda prompt: (prompt['choice']['options'][0]['id'], not prompt['choice'].get('allow_decline')))
    return combat, table, mid


@pytest.mark.parametrize('legacy_king', [False, True])
def test_beast_king_has_one_paid_prompt_and_one_spend_after_commit_reload(tmp_path, monkeypatch, legacy_king):
    combat, table, mid = table_fight(tmp_path, [c7.BEAST + 'beast_scripture_initiate',
                                               c7.BEAST + 'beast_king_s_technique'], legacy_king=legacy_king)
    before = combat._load_session(mid).engine.state.actors[c7.ME].resources[c7.STAMINA]
    fixed_dice(monkeypatch, [19] * 80)
    strike = c7.unarmed(combat._load_session(mid).engine)
    def select(prompt):
        choice = prompt['context']['reaction_source_id']
        if choice == 'choice:needle.beast_king':
            assert '1 Stamina' in prompt['moment'] and 'Target' in prompt['moment']
            return prompt['choice']['options'][0]['id'], True
        if not prompt['choice'].get('allow_decline'):
            return prompt['choice']['options'][0]['id'], True
        return None, False
    prompts = commit(cast_sender(combat, table, mid, strike, target=c7.FOE), select)
    assert sum(p['context']['reaction_source_id'] == 'choice:needle.beast_king' for p in prompts) == 1
    loaded = CombatService(c7.ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[c7.ME].resources[c7.STAMINA] == before - 1
    spends = [event for event in loaded.engine.events if event.event_type == 'RESOURCE_SPENT'
              and event.source_definition_id == c7.BEAST + 'beast_king_s_technique']
    assert len(spends) == 1 and spends[0].payload['amount'] == 1
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('ready_staff', [False, True])
def test_eight_limb_offers_readied_form_then_commits_reloads_replays(tmp_path, monkeypatch, ready_staff):
    combat, table, mid = table_fight(tmp_path, [c7.MANDALA + 'eight_limb_battle_pattern'], items=(c7.JIAN, c7.GUN))
    fixed_dice(monkeypatch, [19] * 80)
    if ready_staff:
        commit(cast_sender(combat, table, mid, 'Stow Jian'))
    else:
        commit(cast_sender(combat, table, mid, 'Stow Gun'))
    before = combat._load_session(mid).engine.state.actors[c7.ME].resources[c7.HANDS]
    offered = []
    def select(prompt):
        if prompt['context']['reaction_source_id'].endswith('eight_limb_attack'):
            offered.extend(option['id'] for option in prompt['choice']['options'])
            wanted = '.weapon.gun' if ready_staff else '.weapon.jian'
            assert any(wanted in option for option in offered)
            assert all(('.weapon.jian' if ready_staff else '.weapon.gun') not in option for option in offered)
            return next(option for option in offered if wanted in option), True
        if not prompt['choice'].get('allow_decline'):
            return prompt['choice']['options'][0]['id'], True
        return None, False
    strike = c7.unarmed(combat._load_session(mid).engine)
    commit(cast_sender(combat, table, mid, strike, target=c7.FOE), select)
    assert offered
    loaded = CombatService(c7.ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[c7.ME].resources[c7.HANDS] == before - 2
    assert len([event for event in loaded.engine.events if event.event_type == 'ATTACK_ROLLED']) == 2
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
