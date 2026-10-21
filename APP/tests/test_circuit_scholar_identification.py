"""Circuit Scholar: the printed Intelligence check bonus reaches the table's real identification checks.

Finding 1 of the F10R review: combat/ext/qiweaving_insights.py only answered true when a producer
marked the check, and no producer did, so a Circuit Scholar owner received no printed bonus in play.
Finding 2: the earlier regressions called the hook directly with a fabricated context, which proved
the arithmetic but never the wiring. These tests drive the real table action (Talismans "Read the
Script": "Make an Intelligence check using Arcana, Investigation, Calligrapher's Supplies ... On a
success, learn one: formula family; approximate rank; ...") through CombatService, commit it and
cold-reload the saved fight, then read the recorded check.

Each test runs the same action twice -- once with the insight and once without it -- and compares
the two committed rolls. The control run uses the same sheet, the same choices and the same die, so
its modifier is exactly the base the printed bonus is measured against.
"""
from copy import deepcopy

from combat.canonical import canonical_sha256
from tests.worker2_support import OWNER, candidate, fixture, reload

SCRIPT = "TALISMANS_BASE_READ_THE_SCRIPT"
QIWEAVING = "TAL_QIWEAVING_MINOR_QI_ARTS"  # Circuit Scholar's printed "Prerequisite: Qiweaving sphere"
CIRCUIT_SCHOLAR = "insight.circuit-scholar"
SKILL_CHOICE = "choice:needle.read_script_skill"
DC_CHOICE = "choice:needle.read_script_dc"


def _arcana_proficiency(bundles):
    """Seal explicit Arcana proficiency (rank 1) on the owner, exactly as a sheet would.

    Only the authoritative rank is added, so the sheet's Arcana total is untouched: the base check
    modifier stays comparable with the control run and only the printed proficiency rule moves.
    """
    bundle = bundles[0]
    bundle["skill_proficiency"] = {**(bundle.get("skill_proficiency") or {}), "Arcana": 1}
    bundle["bundle_sha256"] = canonical_sha256({k: v for k, v in bundle.items() if k != "bundle_sha256"})


def _read_the_script(tmp_path, root, *, insights=(), bundle_transform=None):
    """Take Read the Script on the table; return (engine, that check's committed RollRecord)."""
    from tests.test_auto2_talismans import take

    combat, table, mid = fixture(tmp_path / root, [SCRIPT, QIWEAVING], owner_insights=tuple(insights),
                                 bundle_transform=bundle_transform)
    take(combat, table, mid, "Read the Script", choices={SKILL_CHOICE: "Arcana",
                                                         DC_CHOICE: "clear and deliberate"})
    engine = reload(tmp_path / root, mid)
    roll = next(r for r in engine.rolls
                if r.reason.startswith("CHECK:") and r.reason.endswith(":Arcana"))
    return engine, roll


def _bundle(engine):
    return next(row for row in engine.typed_bundle_documents if row["actor_id"] == OWNER)


def test_read_the_script_pays_the_circuit_scholar_bonus(tmp_path):
    """The printed bonus must reach the real check the fighter rolls (finding 1)."""
    _, plain = _read_the_script(tmp_path, "control")
    engine, owner = _read_the_script(tmp_path, "insight", insights=(CIRCUIT_SCHOLAR,))
    pb = engine.state.actors[OWNER].proficiency_bonus
    assert pb > 0
    assert [row for row in engine.typed_passive_rows.get(OWNER, [])
            if row.get("feature_id") == CIRCUIT_SCHOLAR], "the fixture did not grant the insight"
    assert owner.modifier == plain.modifier + pb, (
        f"A Circuit Scholar rolled {owner.modifier}, but the same fighter without the insight rolled "
        f"{plain.modifier} and the Proficiency Bonus is {pb}: the printed bonus never reached the check.")


def test_read_the_script_doubles_the_bonus_when_proficient(tmp_path):
    """"If you are proficient, add double your Proficiency Bonus." """
    engine, owner = _read_the_script(tmp_path, "proficient", insights=(CIRCUIT_SCHOLAR,),
                                     bundle_transform=_arcana_proficiency)
    _, plain = _read_the_script(tmp_path, "control")
    pb = engine.state.actors[OWNER].proficiency_bonus
    assert _bundle(engine).get("skill_proficiency", {}).get("Arcana") == 1
    assert owner.modifier == plain.modifier + 2 * pb, (
        f"A fighter proficient in Arcana rolled {owner.modifier}, expected the control {plain.modifier} "
        f"plus double the Proficiency Bonus ({2 * pb}).")


def test_circuit_scholar_is_inert_without_the_insight(tmp_path):
    """A fighter who does not own the insight rolls the ordinary check (no global change)."""
    engine, roll = _read_the_script(tmp_path, "control")
    assert not [row for row in engine.typed_passive_rows.get(OWNER, [])
                if row.get("feature_id") == CIRCUIT_SCHOLAR]
    assert not (_bundle(engine).get("skill_proficiency") or {}).get("Arcana")


def test_read_the_script_still_rolls_and_records_exactly_one_check(tmp_path):
    """The seam adds a modifier only: one die, one recorded check, unchanged event shape."""
    engine, roll = _read_the_script(tmp_path, "insight", insights=(CIRCUIT_SCHOLAR,))
    checks = [r for r in engine.rolls if r.reason.startswith("CHECK:")]
    assert checks == [roll]
    events = [e for e in engine.events if e.event_type == "CHECK_ROLLED"]
    assert len(events) == 1
    assert events[0].payload.get("skill") == "Arcana"


def _seal_exhaustion(bundles):
    """A free pre-fight Action that gives its owner one level of Exhaustion.

    Exhaustion prints a penalty to every d20 Test (attacks, ability checks and saves), so it is a
    real ``check_bonus`` subscriber that does not belong to Circuit Scholar.
    """
    from copy import deepcopy

    bundle = bundles[0]
    base = deepcopy(next(row for row in bundle["action_catalog"] if row.get("resolution_kind") == "TYPED"))
    action = deepcopy(base)
    action.update(source_definition_id="test:circuit-scholar.exhaustion",
                  display_name="Test gain exhaustion", economy="NONE", target_kind="SELF",
                  range_ft=5, costs=[])
    typed = action["parameters"]["typed"]
    typed.update(source="test:circuit-scholar.exhaustion",
                 effects=[{"type": "exhaustion", "amount": 1, "applies_to": "self"}],
                 riders=[], duration={"kind": "instant"})
    action["parameters"]["free_primary"] = True
    action["parameters"].pop("remote_activation", None)
    action["parameters"].pop("remote_perception_required", None)
    bundle["action_catalog"].append(action)
    bundle["actor_template"]["action_ids"].append(action["source_definition_id"])
    bundle["bundle_sha256"] = canonical_sha256({k: v for k, v in bundle.items() if k != "bundle_sha256"})


def test_read_the_script_keeps_every_generic_check_effect(tmp_path):
    """Read the Script is a real Intelligence check, so every check_bonus subscriber still applies.

    The printed clause is "Make an Intelligence check using Arcana, Investigation, Calligrapher's
    Supplies, or another relevant proficiency." An owner with Exhaustion -- who need not own Circuit
    Scholar -- must still take the printed penalty (2024: -2 per level to every d20 Test). Scoping
    identification_bonus to Circuit Scholar alone would hide that effect.
    """
    from tests.test_auto2_talismans import execute, take

    def read(root, exhausted):
        combat, table, mid = fixture(tmp_path / root, [SCRIPT, QIWEAVING],
                                     bundle_transform=_seal_exhaustion if exhausted else None)
        if exhausted:
            execute(combat, mid, candidate(combat, mid, "Test gain exhaustion"))
        take(combat, table, mid, "Read the Script", choices={SKILL_CHOICE: "Arcana",
                                                             DC_CHOICE: "clear and deliberate"})
        engine = reload(tmp_path / root, mid)
        from combat.ext import forged_exhaustion

        assert forged_exhaustion.level(engine.state.actors[OWNER]) == (1 if exhausted else 0)
        assert not [row for row in engine.typed_passive_rows.get(OWNER, [])
                    if row.get("feature_id") == CIRCUIT_SCHOLAR]
        return next(r for r in engine.rolls
                    if r.reason.startswith("CHECK:") and r.reason.endswith(":Arcana"))

    plain = read("control", False)
    tired = read("exhausted", True)
    assert tired.modifier == plain.modifier - 2, (
        f"an exhausted reader rolled {tired.modifier} against {plain.modifier} without Exhaustion: "
        "the printed -2 per Exhaustion level never reached the Read the Script check")


def test_identification_marker_is_inert_for_unmarked_checks():
    """A skill name alone is not an identification, and a different ability is never one."""
    from combat.ext.identification_checks import identifying, is_identification

    class MockContext:
        def __init__(self):
            self.engine = None
            self.typed = {"ability": "INT", "skill": "Arcana"}

    assert not is_identification(MockContext())
    # The generic purpose marker records producer intent regardless of ability; the
    # Circuit Scholar provider itself must reject a marked non-Intelligence check.
    marked_wisdom = identifying(MockContext(), ability="WIS", skill="Insight")
    assert is_identification(marked_wisdom)
    from combat.ext.qiweaving_insights import circuit_scholar_check_bonus

    class Actor:
        entity_id = OWNER

    class Engine:
        typed_passive_rows = {OWNER: [{"feature_id": CIRCUIT_SCHOLAR, "pb": 3}]}

    marked_wisdom.engine = Engine()
    assert circuit_scholar_check_bonus(marked_wisdom, Actor()) is None


def test_identifying_does_not_modify_the_producer_context():
    """The marker is an ephemeral copy; nothing the producer keeps changes (no saved-fight state)."""
    from combat.ext.identification_checks import identifying

    class MockContext:
        def __init__(self):
            self.engine = None
            self.typed = {"ability": "INT", "skill": "Arcana"}

    original = MockContext()
    before = deepcopy(original.typed)
    marked = identifying(original, ability="INT", skill="Arcana", kind="talisman_effect")
    assert original.typed == before
    assert marked.typed["check_purpose"] == "identification"
    assert marked.typed["identification_kind"] == "talisman_effect"