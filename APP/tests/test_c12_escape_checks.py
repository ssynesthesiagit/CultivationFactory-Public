"""Granted escape checks use the shared resolver in real saved table actions.

No GUI or live data. Benefits are activated from owned compiled abilities;
only deterministic dice and the cancellation case's check-mode setup are fixtures.
"""
import pytest

from combat.ext import escape_options, protection, scoped_checks
from tests.r1i_service_support import fixture, candidate, force_ai_candidate, OWNER, FOE, SECOND
from tests.test_r1i_round3 import resolve, reload

PRISON = "tianxia.talent.stars.constellation_prison"
IRON = "TAL_METAL_IRON_BONE_INTERNAL_METHOD"


@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("benefit,expected_mode", [
    ("slippery", "ADVANTAGE"), ("iron", "ADVANTAGE"),
    ("unowned", "NORMAL"), ("cancel", "NORMAL"),
])
def test_owned_benefits_on_real_constellation_escape(tmp_path, monkeypatch, auto_turn, benefit, expected_mode):
    from combat.gate2_rolls import DeterministicRollAuthority
    from combat.canonical import canonical_sha256

    real = DeterministicRollAuthority.d20

    def dice(roller, **kwargs):
        # Keep saves failed and escape checks low, independent of seed/mode.
        wanted = 1 if kwargs["actor_id"] == FOE and kwargs["reason"].startswith(("SAVE:", "CHECK:")) else None
        while True:
            roll = real(roller, **kwargs)
            if wanted is None or roll.natural_result == wanted:
                return roll

    monkeypatch.setattr(DeterministicRollAuthority, "d20", dice)

    def disadvantage(bundles):
        if benefit != "cancel":
            return
        owner = bundles[0]
        action = next(a for a in owner["action_catalog"] if a["display_name"] == "Constellation Prison")
        action["parameters"]["typed"]["effects"].append(
            {"type": "ongoing", "condition": "c12_test_disadvantage", "applies_to": "target",
             "rule": {"check_mode": {"ALL": "DISADVANTAGE"}}, "expires_on": "UNTIL_REMOVED"})
        owner.pop("bundle_sha256", None)
        owner["bundle_sha256"] = canonical_sha256(owner)

    talents = [IRON] if benefit == "iron" else [protection.SLIPPERY] if benefit != "unowned" else []
    combat, table, mid, send, commit = fixture(
        tmp_path, [PRISON], foe_talents=talents, owner_dc=16, bundle_transform=disadvantage)
    # Activate the prisoner's own benefit before the caster creates a new hold.
    commit(table.state(mid)["menu"]["end_turn"])
    while table.state(mid)["menu"]["actor_id"] != FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    if benefit == "iron":
        commit(candidate(table, mid, "Iron-Bone Internal Method: Advantage on Checks"))
    elif benefit != "unowned":
        commit(candidate(table, mid, "Aegis: Slippery", FOE))
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        commit(table.state(mid)["menu"]["end_turn"])
    commit(candidate(table, mid, "Constellation Prison", FOE))
    engine = reload(tmp_path, mid)
    held = engine.state.actors[FOE]
    ((key, record),) = escape_options.options(held)
    assert all(held.conditions[g].condition_id.endswith(".constellation_prison") for g in record.data["guards"])
    if benefit == "iron":
        assert any(c.condition_id == scoped_checks.CONDITION for c in held.conditions.values())
    elif benefit != "unowned":
        assert protection.slippery_escape(engine, held, []) == "ADVANTAGE"
    if benefit == "cancel":
        assert any(c.condition_id.endswith(".c12_test_disadvantage") for c in held.conditions.values())
    while table.state(mid)["menu"]["actor_id"] != FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    cid = candidate(table, mid, "Break free")
    if auto_turn:
        force_ai_candidate(combat, mid, FOE, cid)
    before = len(reload(tmp_path, mid).events)
    resolve(combat, mid, send, cid, {"choice:needle.escape_ability": "STR"}, auto=auto_turn)
    engine = reload(tmp_path, mid)
    (check,) = [e for e in engine.events[before:] if e.event_type == "CHECK_ROLLED"]
    assert check.payload["ability"] == "STR"
    assert check.payload["actor"]["mode"] == expected_mode
    assert not check.payload["success"]
    assert key in engine.state.actors[FOE].conditions
    assert not engine.state.actors[FOE].action_available


@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("benefit", ["floor", "iron"])
def test_study_bonus_floor_scope_and_native_metadata(tmp_path, monkeypatch, auto_turn, benefit):
    from combat.gate2_rolls import DeterministicRollAuthority
    from combat.ext.illusion_riders import SUBSTANTIAL
    from tests.test_lock_choices import install
    from combat.ext import d20_floor

    # Observe native context and add a test-only flat check bonus. Actual floor
    # comes from the prisoner's real owned Complete Mandala Auspice activation.
    observed = []
    install(monkeypatch, "d20_result", lambda e, r, i: observed.append(e.d20_context(r)))
    install(monkeypatch, "check_bonus", lambda ctx, actor: 3 if actor.entity_id == FOE else None)
    real = DeterministicRollAuthority.d20

    def dice(roller, **kwargs):
        while True:
            roll = real(roller, **kwargs)
            if kwargs["actor_id"] != FOE or not kwargs["reason"].startswith(("SAVE:", "CHECK:")) or roll.natural_result == 1:
                return roll

    monkeypatch.setattr(DeterministicRollAuthority, "d20", dice)
    combat, table, mid, send, commit = fixture(
        tmp_path, [SUBSTANTIAL], foe_talents=["TAL_FATE_COMPLETE_MANDALA_AUSPICE"] if benefit == "floor" else [IRON], owner_dc=14)
    commit(table.state(mid)["menu"]["end_turn"])
    while table.state(mid)["menu"]["actor_id"] != FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    commit(candidate(table, mid, "Complete Mandala", FOE) if benefit == "floor" else
           candidate(table, mid, "Iron-Bone Internal Method: Advantage on Checks"))
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        commit(table.state(mid)["menu"]["end_turn"])
    cid = next(o["candidate_id"] for g in table.state(mid)["menu"]["actions"]
               if g["label"] == "Create Figment + Substantial Phantasm (3 CP; Grappled)"
               for o in g["options"] if o.get("destination") == {"x": 4, "y": 6})
    resolve(combat, mid, send, cid, {"choice:needle.substantial_phantasm": FOE})
    while table.state(mid)["menu"]["actor_id"] != FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    assert any(c.condition_id == (d20_floor.CONDITION if benefit == "floor" else scoped_checks.CONDITION)
               for c in reload(tmp_path, mid).state.actors[FOE].conditions.values())
    cid = candidate(table, mid, "Break free")
    if auto_turn:
        force_ai_candidate(combat, mid, FOE, cid)
    before = len(reload(tmp_path, mid).events)
    observed.clear()
    resolve(combat, mid, send, cid, {}, auto=auto_turn)
    engine = reload(tmp_path, mid)
    (check,) = [e for e in engine.events[before:] if e.event_type == "CHECK_ROLLED"]
    assert check.payload["actor"]["natural_result"] == 1
    assert check.payload["actor"]["total"] == (15 if benefit == "floor" else 6)  # INT 2 + bonus 3 + die/floor
    assert check.payload["actor"]["mode"] == "NORMAL"  # STR/CON Iron-Bone never benefits INT Study
    assert check.payload["success"] == (benefit == "floor")
    assert bool(escape_options.options(engine.state.actors[FOE])) == (benefit != "floor")
    assert any(c.source_definition_id == SUBSTANTIAL for c in engine.state.actors[FOE].conditions.values()) == (benefit != "floor")
    context = next(c for c in observed if c and c["kind"] == "check" and c["source_id"] == SUBSTANTIAL)
    assert context["actor_id"] == context["target_id"] == FOE
    assert context["source_id"] == SUBSTANTIAL and context["source_actor_id"] == OWNER
    assert context["skill"] == "Investigation" and context["dc"] == 14


@pytest.mark.parametrize("auto_turn", [False, True])
def test_owned_ink_domain_bonus_turns_granted_escape_into_success(tmp_path, monkeypatch, auto_turn):
    from combat.gate2_rolls import DeterministicRollAuthority
    real = DeterministicRollAuthority.d20

    def dice(roller, **kwargs):
        while True:
            roll = real(roller, **kwargs)
            if kwargs["actor_id"] != FOE or not kwargs["reason"].startswith(("SAVE:", "CHECK:")) or roll.natural_result == 1:
                return roll

    monkeypatch.setattr(DeterministicRollAuthority, "d20", dice)
    combat, table, mid, send, commit = fixture(
        tmp_path, [PRISON], second_talents=["tianxia.talent.ink.ink_domain"], owner_dc=5)
    while table.state(mid)["menu"]["actor_id"] != SECOND:
        commit(table.state(mid)["menu"]["end_turn"])
    commit(candidate(table, mid, "Ink Domain"))
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        commit(table.state(mid)["menu"]["end_turn"])
    commit(candidate(table, mid, "Constellation Prison", FOE))
    assert escape_options.options(reload(tmp_path, mid).state.actors[FOE])
    while table.state(mid)["menu"]["actor_id"] != FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    cid = candidate(table, mid, "Break free")
    if auto_turn:
        force_ai_candidate(combat, mid, FOE, cid)
    before = len(reload(tmp_path, mid).events)
    resolve(combat, mid, send, cid, {"choice:needle.escape_ability": "STR"}, auto=auto_turn)
    engine = reload(tmp_path, mid)
    (check,) = [e for e in engine.events[before:] if e.event_type == "CHECK_ROLLED"]
    assert check.payload["actor"]["modifier"] == 4  # STR 2 + allied Ink Domain 2
    assert check.payload["actor"]["total"] == 5 and check.payload["success"]
    assert not escape_options.options(engine.state.actors[FOE])
    assert not any(c.source_definition_id == PRISON for c in engine.state.actors[FOE].conditions.values())
