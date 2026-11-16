"""Spirit diagnosis facts at the persisted table boundary."""
from tests.hunt15_support import LEFT, RIGHT, act, action_sender, fight, turn
from tests.test_lock_choices import install

SOUL_GAZE = "tianxia.path.spirit_awakening.feature.soul_gaze"


def test_soul_gaze_reports_selected_facts_and_provider_only(monkeypatch, tmp_path):
    def setup(engine, kind, kwargs):
        if kind != "HOLD_POSITION_COMMITTED" or kwargs["actor_id"] != LEFT:
            return
        target = engine.state.actors[RIGHT]
        engine._add_modifier(target, "test:vulnerability", "damage_vulnerability", "ADD",
                             "FIRE", "ALL", expires_on="UNTIL_REMOVED", source_actor_id=RIGHT)
        engine._apply_condition(target, "condition:test.hidden", "test:hidden", RIGHT,
                                expires_on="UNTIL_REMOVED",
                                data={"rule": {"effective_cultivation_level": 5},
                                      "secret": "FORBIDDEN SECRET"})

    def provider(ctx, subject):
        if any(c.condition_id == "condition:test.hidden" for c in subject.conditions.values()):
            return "A spiritual barrier is present."

    install(monkeypatch, "event", setup)
    install(monkeypatch, "diagnosis_reveal", provider)
    combat, table, mid = fight(tmp_path, [SOUL_GAZE], primary="Resonance")
    turn(table, mid, LEFT)
    assert act(table, mid, "system:combat.hold_position")["status"] == "COMMITTED"
    assert action_sender(combat, table, mid, "Soul Gaze", target_id=RIGHT)([])["status"] == "COMMITTED"
    summary = next(r["summary"] for r in table.events(mid, 0)["events"] if "Soul Gaze on" in r["summary"])
    assert "Vulnerabilities: FIRE" in summary
    assert "Cultivation Level: lower than yours" in summary
    assert "A spiritual barrier is present." in summary
    assert "FORBIDDEN SECRET" not in summary
    assert "Soul Anchor" not in summary and "Bond" not in summary
