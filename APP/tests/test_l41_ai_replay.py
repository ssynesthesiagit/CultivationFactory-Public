"""Seeded AI fight fingerprints, including the approved movement cycle control.

This deliberately covers unaffected fights (no Blood Pump or Golden Bell).
Each fingerprint includes every field of events, rolls and persisted state;
timestamps from the nonmechanical controller journal are not combat bytes.
Lock round 24 intentionally changes these seeds: at event 16 the owner Dodges
instead of moving to a repeated endpoint. The old complete fingerprints and
every changed field are retained in astra/lock24-run/l41-comparison.json.
Exact complete and projected fingerprints retain the prior checks for integer
Strength and the natural Unarmed Strike action from the admitted lock lanes.

The printed unseen-origin permission map is bound from the shipped rules prose
at match creation (combat.area_knowledge.bind_origin_permissions); the public
test snapshot scrambles that prose as test compatibility data. The complete
fingerprint protects that saved map separately against this tree's own printed
rules instead of pinning environment-dependent prose bytes.
"""
import pytest
from tests.legacy_fight_support import legacy_zero_hp
from tests.replay_assertions import remove_checked_receipt_additions, remove_redundant_observation_refreshes

from combat.area_knowledge import bind_origin_permissions
from combat.canonical import canonical_sha256
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.r1i_service_support import ROOT, fixture

WITHOUT_STRENGTH_FINGERPRINTS = {
    'SOL41-REPLAY-0': '60796756940450531de7f2d4538940055a6f237768f8f1f4b2413ffcb914f159',
    'SOL41-REPLAY-1': '473bcaf850f7d0886936e51252e851afaf85ba7e61ef1c95e268d8cc713366ba',
    'SOL41-REPLAY-2': 'b9b6597d431f4615512321d4a2a27ab9aafc11b1d9d56411606a58b5425f69eb',
}

WITHOUT_STRENGTH_OR_UNARMED_FINGERPRINTS = {
    'SOL41-REPLAY-0': '6abfad99e492bd78645ac2942c8375645ecdd69de46da374aaf7ba58893892a0',
    'SOL41-REPLAY-1': 'ae806a79fb0d676eb01e6f606bfc386afdb45e49d44831b1a2fb8a1a86317601',
    'SOL41-REPLAY-2': 'a2fc7488efc188a3f75db3c5882ef95d524ae15fe00631e9710fac2c280ced7d',
}

# Scoundrel's generic Utilize ending (42940b22, merged by df88ad00) is
# available to adjacent helpers, including characters without that talent.
# The owner-selected zero concealment policy (d63fac7d, merged by c21b1892)
# is recorded in genesis. Check both additions before the original fingerprints.
# Re-pinned for the reviewed Tricky-tier press policy (6d6d1235).
CURRENT_FINGERPRINTS = {
    'SOL41-REPLAY-0': '691b4e2af5a01fbc7fc6fe64bc2bfb9d8d642ea12af180cf4626ff5346b9af21',
    'SOL41-REPLAY-1': 'e6ed943defcba97d737496b9b388ee0d2b430abc58c3618bac6a2e08c9d18791',
    'SOL41-REPLAY-2': 'df363f0badd5c28fbf40de6bce0fb27ee6c0443d5183e96098bc2bd345e3470c',
}


@pytest.mark.parametrize("seed,expected", [
    ("SOL41-REPLAY-0", "f685a6001771e909563e736113207350124801a365a082c67ae760400770329c"),
    ("SOL41-REPLAY-1", "9bb2f901e03b4462f8cc89e30017ad18c953fc8189b471aca2dc08f90329d084"),
    ("SOL41-REPLAY-2", "e0ec14ee311b0948fa37416fe392af92d0b98c682335a216aedcf8ccd9ba6573"),
])
def test_ai_fight_matches_cycle_control_bytes(tmp_path, seed, expected, legacy_zero_hp):
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
    assert canonical_sha256(payload) == CURRENT_FINGERPRINTS[seed]
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
    remove_checked_receipt_additions(payload['events'])
    remove_redundant_observation_refreshes(payload['events'])
    assert canonical_sha256(payload) == expected
    for actor in payload['state']['actors'].values():
        assert actor.pop('strength_score') == 14
    assert canonical_sha256(payload) == WITHOUT_STRENGTH_FINGERPRINTS[seed]
    for actor in payload['state']['actors'].values():
        added = [source for source in actor['action_ids'] if source.endswith('.natural.unarmed_strike')]
        assert len(added) == 1
        actor['action_ids'] = [source for source in actor['action_ids'] if source not in added]
    assert canonical_sha256(payload) == WITHOUT_STRENGTH_OR_UNARMED_FINGERPRINTS[seed]
