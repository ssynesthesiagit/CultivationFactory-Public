"""Cleave's internal attack index is never presented as an attack entitlement."""
from combat.factory_compiler import compile_character
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet, script
from tests.test_factory_combat_compiler import _weapons_of, ACTOR
from tests.test_lock2_persistence import act


def test_cleave_follow_up_name_survives_table_reload(tmp_path, monkeypatch):
    original = Gate4ControllerEngine._resolve_attack_spec
    def hit(engine, *args, **kwargs):
        script(engine, [19, *([1] * 40)])
        return original(engine, *args, **kwargs)
    monkeypatch.setattr(Gate4ControllerEngine, "_resolve_attack_spec", hit)
    bundle, rows = _weapons_of(["tianxia.mortal.weapon.ji"],
        paths=("tianxia.path.body_refining",), spheres=["tianxia.sphere.weapons"])
    foes = ["actor:factory.cleave-first", "actor:factory.cleave-second"]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    ids = [ACTOR, *foes]
    mid = combat._finish_factory_match([bundle, *[compile_character(sheet([]), actor_id=a) for a in foes]],
        ids, {ACTOR: "team:a", **{a: "team:b" for a in foes}},
        dict(zip(ids, [{"x": 3, "y": 6}, {"x": 5, "y": 6}, {"x": 5, "y": 7}])),
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [ACTOR], foes,
        control_modes={a: "MANUAL" for a in ids}, match_seed="LOG1-CLEAVE",
        display_name="Cleave history", maximum_rounds=5)["match_id"]
    while table.state(mid)["menu"]["actor_id"] != ACTOR:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    state = table.state(mid)
    candidate = next(c for c in combat._load_session(mid).engine.legal_candidates()
        if c.source_definition_id == rows["ji"]["source_definition_id"] and c.target_ids == (foes[0],))
    asked = table.act(mid, candidate.candidate_id, state["menu"]["decision_id"],
        state["menu"]["state_version"], state["last_sequence"], [])
    # Cleave is optional ("you can make"): the manual owner is asked and picks the second creature (L47).
    assert asked["status"] == "REACTION_REQUIRED" and asked["reaction"]["reaction"] == "Cleave"
    answer = {**asked["reaction"]["context"], "selection": "USE", "option_ids": [foes[1]]}
    assert table.act(mid, candidate.candidate_id, state["menu"]["decision_id"],
        state["menu"]["state_version"], state["last_sequence"], [answer])["status"] == "COMMITTED"
    fresh = CombatService(ROOT, tmp_path)
    boundary = fresh.history(mid)["boundaries"][-1]
    attacks = [e for e in boundary["events"] if e["event_type"] == "ATTACK_ROLLED"]
    assert len(attacks) == 2
    assert attacks[1]["payload"]["attack_label"] == "Cleave follow-up"
    summaries = [r["summary"] for r in boundary["feed"] if r["event_type"] == "ATTACK_ROLLED"]
    assert "Cleave follow-up" in summaries[1]
    assert not any("additional attack 99" in s for s in summaries)
    assert fresh._load_session(mid).mechanical.replay()["status"] == "PASS"
