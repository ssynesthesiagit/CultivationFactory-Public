"""Spirit-Calling Tune's next attack survives the singer's next turn and reload."""
import pytest

from tests.test_a2_music_second_pass import setup, engine, _act_when, table_next, ME, FOE, M
from tests.test_auto72_music import _add_test_action


@pytest.mark.parametrize("automatic", [False, True])
def test_spirit_next_attack_is_not_lost_at_singers_next_turn(tmp_path, automatic):
    def transform(bundles):
        foe = bundles[2]
        foe["actor_template"]["creature_types"] = ["Spirit"]
        foe["actor_template"]["saving_throws"]["WIS"] = -100
        _add_test_action(foe, name="Test Spirit Attack", source_id="action:test.mgr_spirit_attack",
                         target_kind="HOSTILE_ENTITY", range_ft=30,
                         effects=[{"type": "attack", "attack_kind": "ranged", "attack_bonus": 100,
                                   "dice": {"count": 1, "sides": 4}, "damage_types": ["piercing"],
                                   "applies_to": "target"}])

    root = tmp_path / "spirit"
    combat, table, mid = setup(root, [M + "spirit_calling_tune"], "mgr-t15-spirit",
                              automatic=automatic, ask_actors=(FOE,) if automatic else (ME, FOE),
                              bundle_transform=transform)
    _act_when(combat, table, mid, root, lambda e, c: c.actor_id == ME and FOE in c.target_ids
              and "Spirit-Calling Tune" in c.display_name and "Disadvantage on Next Attack" in c.display_name)
    e = engine(combat, mid)
    started = e.state.actors[ME].turns_started
    timers = [c for c in e.state.actors[ME].conditions.values()
              if c.condition_id == "condition:typed.concentration_deadline"]
    assert len(timers) == 1, "the printed one-minute concentration maximum is enforced"
    for _ in range(8):
        table_next(combat, table, mid, root)
        e = engine(combat, mid)
        if e.state.current_actor_id == ME and e.state.actors[ME].turns_started > started:
            break
    else:
        raise AssertionError("the singer's next turn never arrived")
    assert any(m.target_field == "attack_mode" and m.value == "DISADVANTAGE"
               and M + "spirit_calling_tune" in m.source_definition_id
               for m in e.state.actors[FOE].modifiers.values())
    _act_when(combat, table, mid, root, lambda e, c: c.actor_id == FOE and c.display_name == "Test Spirit Attack"
              and ME in c.target_ids)
    e = engine(combat, mid)
    attacks = [ev for ev in e.events if ev.event_type == "ATTACK_ROLLED"
               and ev.source_definition_id == "action:test.mgr_spirit_attack"]
    assert len(attacks) == 1 and attacks[0].payload["mode"] == "DISADVANTAGE"
    assert not any(m.target_field == "attack_mode" and M + "spirit_calling_tune" in m.source_definition_id
                   for m in e.state.actors[FOE].modifiers.values()), "only the next attack spends the benefit"
