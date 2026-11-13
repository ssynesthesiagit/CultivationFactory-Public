"""Fixed Unarmed Strike damage is journalled without inventing a die."""
from combat.history_feed import format_history_feed
from combat.tabletop import dice_rows
from tests.test_unarmed_strike_options import fight
from tests.hunt12_support import ME, FOE, candidate, hit_dice, send


def test_unarmed_fixed_damage_is_not_sent_to_dice_tray(tmp_path, monkeypatch):
    combat, table, mid = fight(tmp_path)
    strike = candidate(combat, mid, lambda c: c.display_name == "Unarmed Strike" and c.target_ids == (FOE,))
    hit_dice(monkeypatch)
    assert send(combat, table, mid, strike)["status"] == "COMMITTED"
    engine = combat._load_session(mid).engine
    event = next(e for e in engine.events if e.event_type == "DAMAGE_ROLLED"
                 and e.source_definition_id == strike.source_definition_id)
    roll = event.payload
    assert roll["total"] == 5
    assert roll["dice"] == []
    assert roll["expression"] == "5+0"
    rows = format_history_feed([event.model_dump(mode="json")], [roll], pre_state=None,
                               post_state={"actors": {}}, actor_names={ME: "Fighter", FOE: "Foe"},
                               definition_names={strike.source_definition_id: "Unarmed Strike"})
    assert "Unarmed Strike damage" in rows[0]["summary"]
    assert "5+0" in rows[0]["summary"] and "1d2" not in rows[0]["summary"]
    assert dice_rows([roll], {}, {}) == []

    attack = next(e.payload for e in engine.events if e.event_type == "ATTACK_ROLLED"
                  and e.source_definition_id == strike.source_definition_id)
    (row,) = dice_rows([attack], {}, {})
    assert row["groups"] and row["groups"][0]["sides"] == 20
