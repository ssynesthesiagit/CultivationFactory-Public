"""Listening Sutra's post-check choices through table preview and saved state."""
import pytest

from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.test_r4_integration import P, F, fixture, reach, send, candidate, auto_candidate

SUTRA = "tianxia.talent.metal.bell_monastery_listening_sutra"
NAME = "Bell-Monastery Listening Sutra"


@pytest.mark.parametrize("ai_owner", [False, True])
@pytest.mark.parametrize("ac,count", [(1, 2), (20, 1)])
def test_sutra_check_choices_rollback_reload_and_source_expiry(tmp_path, ai_owner, ac, count):
    combat, table, mid = fixture(tmp_path, [SUTRA], foe_ac=ac, seed="R4-SUTRA")
    reach(table, mid, P)
    cid = candidate(table, mid, NAME, F)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    if ai_owner:
        auto_candidate(combat, mid, P, cid)
        assert table.auto_step(mid, 0)["status"] == "COMMITTED"
        combat.set_controller_mode(mid, actor_id=P, controller_mode="MANUAL")
    else:
        result = send(table, mid, cid)
        assert result["status"] == "REACTION_REQUIRED"
        prompt = result["reaction"]
        for text in (NAME, "Rider Foe"):
            assert text in prompt["moment"]
        assert prompt["choice"]["minimum"] == count
        assert prompt["choice"]["maximum"] == count
        assert not prompt["choice"]["allow_decline"]
        assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
        picks = ["Reduce AC by 2", "Advantage on next attack (GM)"][:count]
        answer = {**prompt["context"], "selection": "USE", "option_ids": picks}
        assert send(table, mid, cid, [answer])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    mods = [m for m in loaded.engine.state.actors[F].modifiers.values() if m.target_field == "armor_class"]
    assert len(mods) == 1 and mods[0].value == -2
    assert mods[0].expires_on == "START_OF_SOURCE_NEXT_TURN"
    checks = [e for e in loaded.engine.events if e.event_type == "CHECK_ROLLED" and e.payload.get("skill") == "Metal Check"]
    assert len(checks) == 1 and checks[0].payload["success"]
    margin = checks[0].payload["actor"]["total"] - checks[0].payload["dc"]
    assert (2 if margin >= 5 else 1) == count
    assert not any(e.event_type == "ATTACK_ROLLED" for e in loaded.engine.events)
    assert loaded.engine.state.actors[P].resources["resource:core.qi"] == before["actors"][P]["resources"]["resource:core.qi"] - 2
    assert not any(m.target_field == "incoming_attack_mode" for m in loaded.engine.state.actors[F].modifiers.values())
    assert loaded.mechanical.replay()["status"] == "PASS"
    reach(table, mid, F)
    assert any(m.target_field == "armor_class" for m in CombatService(ROOT, tmp_path)._load_session(mid).engine.state.actors[F].modifiers.values())
    reach(table, mid, P)
    assert not any(m.target_field == "armor_class" for m in CombatService(ROOT, tmp_path)._load_session(mid).engine.state.actors[F].modifiers.values())
    assert not any(NAME in o.get("label", g["label"])
                   for g in table.state(mid)["menu"]["actions"] for o in g["options"])
    assert CombatService(ROOT, tmp_path)._load_session(mid).mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("ai_owner", [False, True])
def test_failed_sutra_check_spends_once_without_attack_or_choice(tmp_path, ai_owner):
    combat, table, mid = fixture(tmp_path, [SUTRA], foe_ac=1000, seed="R4-SUTRA-FAIL")
    reach(table, mid, P)
    cid = candidate(table, mid, NAME, F)
    before = combat._load_session(mid).engine.state.actors[P].resources["resource:core.qi"]
    if ai_owner:
        auto_candidate(combat, mid, P, cid)
        result = table.auto_step(mid, 0)
    else:
        result = send(table, mid, cid)
    assert result["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    check = next(e for e in loaded.engine.events if e.event_type == "CHECK_ROLLED" and e.payload.get("skill") == "Metal Check")
    assert not check.payload["success"]
    assert loaded.engine.state.actors[P].resources["resource:core.qi"] == before - 2
    assert not loaded.engine.state.actors[F].modifiers
    assert not any(e.event_type == "ATTACK_ROLLED" for e in loaded.engine.events)
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("ac,picks", [
    (20, ["Suppress one eligible benefit (GM)"]),
    (1, ["Suppress one eligible benefit (GM)", "Flaw-sign ignores half cover (GM)"]),
])
def test_gm_choices_do_not_automatically_apply_unselected_ac_or_suppression(tmp_path, ac, picks):
    combat, table, mid = fixture(tmp_path, [SUTRA], foe_ac=ac, seed="R4-SUTRA")
    reach(table, mid, P)
    cid = candidate(table, mid, NAME, F)
    prompt = send(table, mid, cid)["reaction"]
    answer = {**prompt["context"], "selection": "USE", "option_ids": picks}
    assert send(table, mid, cid, [answer])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    target = loaded.engine.state.actors[F]
    assert not target.modifiers and not target.conditions
    lines = [e.payload.get("rider", "") for e in loaded.engine.events if e.event_type == "GM_RIDER"]
    for text in ("suppress one non-Secret", "allows allies to ignore half cover")[:len(picks)]:
        assert any(text in line for line in lines)
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_sphere_check_uses_current_general_ac_modifiers():
    from types import SimpleNamespace
    from combat.ext.riders_shared import sphere_check
    from tests.test_riders_lane4 import _metal

    engine, actor, target = _metal(SUTRA)
    engine._add_modifier(target, "test:armor", "armor_class", "ADD", 3, "ALWAYS", expires_on="UNTIL_REMOVED")
    action = next(a for a in engine.action_catalog.values() if a.display_name == NAME)
    ctx = SimpleNamespace(engine=engine, actor=actor, target=target, source=action.source_definition_id,
                          numbers={"pb": 6, "key_mod": 2})
    sphere_check(ctx, {"type": "sphere_check", "dc_of": "ac", "name": "Metal Check"})
    check = next(e for e in engine.events if e.event_type == "CHECK_ROLLED")
    assert check.payload["dc"] == target.armor_class + 3
