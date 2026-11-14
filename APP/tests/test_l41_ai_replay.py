"""Seeded AI fights against their own reload.

Each automatic step's live state must equal the state reloaded from its saved
session, exactly. The fight must then verify and replay. No pinned hash is
asserted here: the admitted-state checks below are value checks.
"""
import pytest
from tests.legacy_fight_support import legacy_zero_hp

from combat.area_knowledge import bind_origin_permissions
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.r1i_service_support import ROOT, fixture

@pytest.mark.parametrize("seed", ["SOL41-REPLAY-0", "SOL41-REPLAY-1", "SOL41-REPLAY-2"])
def test_ai_fight_matches_cycle_control_bytes(tmp_path, seed, legacy_zero_hp):
    combat, table, mid, _, _ = fixture(tmp_path, [], seed=seed)
    for actor_id in combat._load_session(mid).engine.state.actors:
        combat.set_controller_mode(mid, actor_id=actor_id, controller_mode="LOCAL_AUTO")
    for _ in range(24):
        result = table.auto_step(mid, 0)
        assert result["status"] == "COMMITTED", result
        current = combat._load_session(mid)
        combat = CombatService(ROOT, tmp_path)
        table = TabletopService(combat, tmp_path)
        loaded = combat._load_session(mid)
        from tests.replay_assertions import assert_replay_equal
        assert_replay_equal(loaded.engine.state.model_dump(mode="json"), current.engine.state.model_dump(mode="json"))
        if loaded.engine.state.terminal_result is not None:
            break
    assert loaded.verify()["status"] == "PASS"
    assert loaded.mechanical.replay()["status"] == "PASS"
    payload = {"state": loaded.engine.state.model_dump(mode="json"),
        "events": [e.model_dump(mode="json") for e in loaded.engine.events],
        "rolls": [r.model_dump(mode="json") for r in loaded.engine.rolls]}
    # Check every combat byte, then check each admitted state addition before
    # comparing its exact projection. No event or roll is normalized away.
    permissions = payload['events'][0]['payload'].pop('area_origin_permissions')
    assert permissions == bind_origin_permissions(ROOT)
    assert set(permissions) <= {'DARK_BASE_DARKNESS'}
    assert all(value == 0 for value in permissions.values())
    assert payload['events'][0]['payload'].pop('targeting_policy') == {
        'concealment_miss_percent': 0, 'total_concealment_miss_percent': 0}
    # Saved policy capabilities added after the round-24 control. None changes
    # this visible, adjacent, talent-free fight; check their precise bindings.
    for key, value in {
        'ai_knowledge_policy': 1,              # dac8526b
        'ai_search_policy': 1,                 # 726b97a0
        'area_knowledge_policy': 1,            # 8bc56287
        'cover_anchor_expiry_policy': 1,       # 3b597c0b
        'subject_repositioning_policy': 1,     # 3b597c0b
    }.items():
        assert payload['events'][0]['payload'].pop(key) == value
    for actor in payload['state']['actors'].values():
        added = [source for source in actor['action_ids'] if source.endswith('.utilize.scoundrel_fastening')]
        assert len(added) == 1
        action = loaded.engine.action_catalog[added[0]]
        assert action.parameters['target_requires_condition'] == 'condition:typed.impossible_fastening'
        actor['action_ids'] = [source for source in actor['action_ids'] if source not in added]
        # aa82d40a, 3a9aaa90 and 376aafc0 add ordinary creature responses to
        # Chains of Qi, Clinging Seal and figments; no talent ownership needed.
        for suffix, effect_type in (('qi5_break_chains', 'qi5_escape_chains'),
                                    ('wax_seal_attempt', 'wax_seal_attempt'),
                                    ('study_figment', 'figment_study')):
            added = [source for source in actor['action_ids'] if source.endswith('.' + suffix)]
            assert len(added) == 1
            action = loaded.engine.action_catalog[added[0]]
            assert action.economy.value == 'ACTION' and action.target_kind == 'SELF'
            assert not action.costs
            assert [row['type'] for row in action.parameters['typed']['effects']] == [effect_type]
            actor['action_ids'] = [source for source in actor['action_ids'] if source not in added]
    for actor in payload['state']['actors'].values():
        assert actor.pop('strength_score') == 14
    for actor in payload['state']['actors'].values():
        added = [source for source in actor['action_ids'] if source.endswith('.natural.unarmed_strike')]
        assert len(added) == 1
        actor['action_ids'] = [source for source in actor['action_ids'] if source not in added]
