"""Yellow-Spring's triggered soul must be serializable in a saved table fight."""
from combat.ext import life_state
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import ALLY, LEFT, RIGHT, HOLD, table_fight, on_hold


def test_yellow_spring_soul_commits_and_reloads_through_table(monkeypatch, tmp_path):
    seal_source = "tianxia.talent.life.yellow_spring_refusal_seal"
    combat, table, mid = table_fight(tmp_path, ["tianxia.talent.life.one_breath_resuscitation"],
                                    ally_talents=["TAL_BERSERKER_DEATHLESS"])
    def sealed_death(engine):
        target = engine.state.actors[ALLY]
        # Set up the printed pre-existing seal; exercise its death trigger in
        # the accepted action, including condition removal and table storage.
        engine._apply_condition(target, life_state.SEAL, seal_source, LEFT, expires_on="UNTIL_REMOVED",
                                data={"label": "Yellow-Spring Refusal Seal", "caster": LEFT})
        engine._commit_damage(target, target.current_hp, "FORCE", "test:blow", RIGHT, None, reaction_depth=0)
        for _ in range(3):
            engine._commit_damage(target, 1, "FORCE", "test:blow", RIGHT, None, reaction_depth=0)
    on_hold(monkeypatch, sealed_death)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    target = loaded.engine.state.actors[ALLY]
    soul = life_state.soul_of(target)
    assert soul is not None and soul.data["seal"] is True
    assert type(soul.data["window"]) is int and soul.data["window"] == 10
    assert not any(c.condition_id == life_state.SEAL for c in target.conditions.values())
    assert loaded.mechanical.replay()["status"] == "PASS"
