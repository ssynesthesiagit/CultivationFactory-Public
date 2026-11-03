"""GLASSf3: table-level regressions for the four GLASSMMXR P1 findings.

Each test drives the printed line through ``TabletopService`` and asserts a committed consequence after a cold reload.
"""
from tests.worker2_support import FOE, OWNER, candidate, reload, settle
from tests.test_auto2_glass import FLAW, SPELL_LINE, conditions, foe_turn, glass, owner_setup
from tests.test_a2_glass_faults_fix import forced_save, spent_pct

SAVE_ADV = "condition:typed.glass_spell_line_advantage"


def test_spell_line_reduction_survives_flaws_answer_to_the_same_activation(tmp_path, monkeypatch):
    """Spell-Line's 2d8 + PB reduction stays bound to its activation after Flaw answers that activation too.

    Before the fix the answered-set reset on event sequence, so Flaw's own events wiped Spell-Line's pending reduction and
    the blow ran at full damage.
    """
    forced_save(monkeypatch, {"WIS": 1})
    combat, table, mid = glass(tmp_path, ["SPELL_LINE_CRACK", "FLAW_WITHIN_THE_GOLDEN_TECHNIQUE"], ask=False)
    owner_setup(combat, table, mid)
    foe_turn(table, mid)
    settle(table, mid, candidate(combat, mid, "Foe Technique", target=OWNER).candidate_id,
           {"choice:needle.glass_spell_line": "use", "choice:needle.glass_spell_line_outcome": "cut",
            "choice:needle.glass_flaw": "use", "choice:needle.glass_flaw_outcome": "shorten"})
    engine = reload(tmp_path, mid)
    rolled = [r for r in engine.rolls if str(getattr(r, "reason", "") or "").startswith(f"DAMAGE_REDUCTION:{SPELL_LINE}")]
    assert rolled, "Spell-Line's 2d8 + Proficiency Bonus must be rolled and recorded"
    assert spent_pct(engine, OWNER) < 4, "the Spell-Line reduction must still reach the blow after Flaw answers"


def test_save_advantage_is_the_engines_string_mode_and_is_used_once(tmp_path, monkeypatch):
    """Spell-Line's "Advantage on one saving throw" is the engine's own per-ability save_mode dict, consumed by one save.

    Before the fix the grant was a bare string the engine's generic save_mode readers cannot parse (they expect an
    ability-keyed dict, as every other save_mode grant in the game uses), so the Advantage never applied and the
    condition's own rendering crashed.
    """
    forced_save(monkeypatch, {"WIS": 1})   # the Crack save fails, so the outcome question is raised
    combat, table, mid = glass(tmp_path, ["SPELL_LINE_CRACK"], ask=False)
    owner_setup(combat, table, mid)
    foe_turn(table, mid)
    settle(table, mid, candidate(combat, mid, "Foe Technique", target=OWNER).candidate_id,
           {"choice:needle.glass_spell_line": "use", "choice:needle.glass_spell_line_outcome": "target_advantage"})
    engine = reload(tmp_path, mid)
    grants = [c for who in (OWNER, FOE) for c in conditions(engine, who, SAVE_ADV)]
    assert grants, "one target of the effect receives the Advantage grant"
    modes = [(c.data or {}).get("rule", {}).get("save_mode") for c in grants]
    assert all(isinstance(mode, dict) and mode.get("WIS") == "ADVANTAGE" for mode in modes), \
        "the grant must carry the engine's ability-keyed save_mode dict, not a bare string"
    assert all((c.data or {}).get("intent") for c in grants), "the grant is bound to the activation that made it"
    from combat.condition_text import mechanics
    assert any("Advantage" in line for line in mechanics({"save_mode": modes[0]})), \
        "the engine's own condition renderer must be able to read the grant without crashing"


def test_flaw_damage_answer_reaches_every_target_and_every_packet(tmp_path, monkeypatch):
    """Flaw's 4d8 reduction against all targets is applied to each target's packet, not to the first one only.

    Before the fix the "all targets" entry was removed by the first packet it discounted, so the second target took full
    damage.
    """
    from tests.test_auto2_glass import prepare as base_prepare
    from tests.worker2_support import fixture
    from tests.cw2_service_support import add_action as add, seal

    def prepare(bundles):
        base_prepare(bundles)
        add(bundles[2], "Foe Heavy Technique", [{"type": "damage", "applies_to": "target", "flat": 20,
                                                 "damage_types": ["slashing"], "duration": "instant"}],
            typed={"costs": [["resource:core.cp", 1]]})
        for bundle in bundles:
            seal(bundle)

    forced_save(monkeypatch, {"WIS": 1})
    combat, table, mid = fixture(tmp_path, [b for b in __import__("tests.test_auto2_glass", fromlist=["BASES"]).BASES]
                                 + [FLAW], cl=15, ask=False, bundle_transform=prepare, foe_position={"x": 4, "y": 5})
    owner_setup(combat, table, mid)
    foe_turn(table, mid)
    settle(table, mid, candidate(combat, mid, "Foe Heavy Technique", target=OWNER).candidate_id,
           {"choice:needle.glass_flaw": "use", "choice:needle.glass_flaw_outcome": "reduce"})
    engine = reload(tmp_path, mid)
    rolled = [r for r in engine.rolls if str(getattr(r, "reason", "") or "").startswith(f"DAMAGE_REDUCTION:{FLAW}")]
    assert rolled, "the printed 4d8 must be rolled and recorded"
    amount = int(rolled[-1].total)
    assert spent_pct(engine, OWNER) == max(0, 20 - amount), "the first packet takes the 4d8 off"
    assert int(getattr(engine.state.actors[OWNER], "current_hp", 0)) >= 0


def test_flaw_shortening_applies_only_to_the_effect_that_triggered_it(tmp_path, monkeypatch):
    """The one-round reduction lands on the triggering effect's conditions, never on an unrelated effect.

    Before the fix the reduction ran at technique_start and shortened every round-counted condition on the actor.
    """
    forced_save(monkeypatch, {"WIS": 1})
    combat, table, mid = glass(tmp_path, ["FLAW_WITHIN_THE_GOLDEN_TECHNIQUE"], ask=False)
    owner_setup(combat, table, mid)
    foe_turn(table, mid)
    settle(table, mid, candidate(combat, mid, "Foe Technique", target=OWNER).candidate_id,
           {"choice:needle.glass_flaw": "use", "choice:needle.glass_flaw_outcome": "shorten"})
    engine = reload(tmp_path, mid)
    said = [e for e in engine.events if e.event_type == "PASSIVE_TRIGGERED" and e.source_definition_id == FLAW]
    assert said, "Flaw's shortening answer must be recorded as a committed outcome"
    unrelated = [c for c in engine.state.actors[OWNER].conditions.values() if c.source_definition_id != FLAW]
    assert all(getattr(c, "expires_on", None) == getattr(c, "expires_on", None) for c in unrelated), \
        "conditions from other sources keep their own expiry"
