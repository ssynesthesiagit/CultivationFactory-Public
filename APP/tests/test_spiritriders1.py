"""Spirit diagnosis facts at the persisted table boundary."""
from tests.hunt15_support import LEFT, RIGHT, act, action_sender, fight, turn
from tests.hunt23_support import fight as prepared_fight
from tests.h1_support import ROOT
from combat.gate5_service import CombatService
from tests.test_lock_choices import install

SOUL_GAZE = "tianxia.path.spirit_awakening.feature.soul_gaze"
PAPER_DRAGON = "tianxia.subpath.qi.paper_cultivator.feature.paper_dragon"


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
    assert action_sender(combat, table, mid, SOUL_GAZE, target_id=RIGHT)([])["status"] == "COMMITTED"
    summary = next(r["summary"] for r in table.events(mid, 0)["events"] if "Soul Gaze on" in r["summary"])
    assert "Vulnerabilities: FIRE" in summary
    assert "Cultivation Level: lower than yours" in summary
    assert "A spiritual barrier is present." in summary
    assert "FORBIDDEN SECRET" not in summary
    assert "Soul Anchor" not in summary and "Bond" not in summary
    # The entire disclosure is the listed facts plus exactly the provider sentence.
    import re
    assert re.fullmatch(
        r"Soul Gaze on Visiting Fighter: Hit Points \d+/\d+; "
        r"Resistances: [^;]+; Immunities: [^;]+; Vulnerabilities: FIRE; "
        r"Cultivation Level: lower than yours; No Resonance Mark from you\. "
        r"A spiritual barrier is present\.", summary)
    assert CombatService(ROOT, tmp_path)._load_session(mid).mechanical.replay()["status"] == "PASS"


def test_soul_gaze_reveals_paper_dragon_passive_vulnerability_after_reload(tmp_path):
    def resources(bundle):
        if bundle["actor_id"] == RIGHT:
            bundle["actor_template"]["resources"].append(
                {"resource_id": "resource:core.qi", "initial": 30, "maximum": 30})

    combat, table, mid = prepared_fight(tmp_path, [SOUL_GAZE], [PAPER_DRAGON],
                                        primary="Resonance", prepare_bundle=resources)
    turn(table, mid, RIGHT)
    assert act(table, mid, PAPER_DRAGON)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    dragon = next(a for a in loaded.engine.state.actors.values()
                  if (a.summon or {}).get("group") == "paper_dragon")
    for _ in range(6):
        if table.state(mid)["menu"].get("actor_id") == LEFT:
            break
        assert act(table, mid, "end")["status"] == "COMMITTED"
    assert action_sender(combat, table, mid, SOUL_GAZE, target_id=dragon.entity_id)([])["status"] == "COMMITTED"
    summary = next(r["summary"] for r in table.events(mid, 0)["events"] if "Soul Gaze on Paper Dragon" in r["summary"])
    assert "Vulnerabilities: FIRE" in summary
    assert CombatService(ROOT, tmp_path)._load_session(mid).mechanical.replay()["status"] == "PASS"
