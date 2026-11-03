"""Empty Palm compares and records owning-Path authority through table commits and reloads."""
from types import SimpleNamespace

import pytest

from combat.canonical import canonical_sha256
from combat.ext import end_effect
from combat.gate2_rolls import DeterministicRollAuthority
from tests import test_mgr_empty_palm as P
from tests import worker2_support as W

WARD = "action:test.split_level_ward"


@pytest.fixture(scope="module")
def split_acquired(tmp_path_factory):
    service, project = P._build_acquisition(tmp_path_factory.mktemp("split-palm"), cl=10)
    # Character CL remains 10 while the owning Qi Path has attainment 6.
    service.set_path_attainment(project, P.QI, 6)
    return service, project


def split_bundle(service, project):
    """Retain real Qi6 ownership with independently recorded CL10 technique scaling.

    Normal Subpath compilation scales CL tiers at Path attainment. Explicitly
    seal the higher scaling number here to exercise the separate Source CL
    contract (including legacy action documents), not to change acquisition.
    """
    owner = P.bundle(service, project, cl=10)
    assert owner["cl"] == 10
    for action in owner["action_catalog"]:
        typed = action.get("parameters", {}).get("typed", {})
        if typed.get("source") == P.EMPTY_PALM:
            assert typed["numbers"]["source_cl"] == 6
            typed["numbers"]["cl"] = 10
    owner.pop("bundle_sha256", None)
    owner["bundle_sha256"] = canonical_sha256(owner)
    return owner


@pytest.mark.parametrize(
    "legacy_user,effect_cl,effect_source_cl,resists,boundary",
    [
        (False, 8, None, False, "end"),   # Qi6 cannot automatically suppress CL8.
        (False, 8, None, True, None),     # The stronger effect can resist.
        (False, 10, 4, True, "start"),    # Opposing character CL10, Source CL4.
        (False, 10, 6, True, "start"),    # Equal Source CL needs only the check.
        (True, 8, None, True, "start"),   # A legacy user falls back to character CL10.
    ],
)
def test_unravel_uses_both_recorded_source_levels_through_commit_and_reload(
    split_acquired, tmp_path, monkeypatch, legacy_user, effect_cl, effect_source_cl, resists, boundary
):
    original = DeterministicRollAuthority._die

    def ordinary_d20(roller, sides):
        # Keep real attack/save/check resolution, and reproduce every die on replay.
        if sides == 20:
            counter = roller.counter
            roller.counter += 1
            return 15, counter
        return original(roller, sides)

    monkeypatch.setattr(DeterministicRollAuthority, "_die", ordinary_d20)
    service, project = split_acquired
    owner = split_bundle(service, project)

    def setup(bundles):
        for row in bundles:
            if row["actor_id"] == W.OWNER and legacy_user:
                for action in row["action_catalog"]:
                    typed = action.get("parameters", {}).get("typed", {})
                    if typed.get("source") == P.EMPTY_PALM:
                        typed["numbers"].pop("source_cl", None)
            if row["actor_id"] == W.FOE:
                numbers = {"cl": effect_cl, "save_dc": 14}
                if effect_source_cl is not None:
                    numbers["source_cl"] = effect_source_cl
                row["actor_template"].update(
                    armor_class=1, maximum_hp=400, saving_throws={"CON": 50 if resists else -50}
                )
                row["actor_template"]["action_ids"].append(WARD)
                row["action_catalog"].append({
                    "source_definition_id": WARD, "display_name": "Raise test ward",
                    "owner_id": W.FOE, "economy": "ACTION", "resolution_kind": "TYPED",
                    "target_kind": "SELF",
                    "parameters": {"typed": {
                        "source": "TAL_VOID_VOID_MERIDIAN_SEAL", "numbers": numbers,
                        "effects": [{
                            "type": "condition", "condition": "poisoned", "applies_to": "self",
                            "duration": {"kind": "minutes", "amount": 1},
                            "condition_data": {"origin_save": {"ability": "CON", "dc": 14}},
                        }],
                    }},
                })
            row.pop("bundle_sha256", None)
            row["bundle_sha256"] = canonical_sha256(row)

    combat, table, mid = W.fixture(
        tmp_path, [], cl=10, owner_bundle=owner, bundle_transform=setup,
        positions={W.OWNER: {"x": 3, "y": 6}, W.FOE: {"x": 4, "y": 6},
                   W.ALLY: {"x": 12, "y": 12}},
        seed="UNRAVEL-SPLIT-LEVEL",
    )
    before = W.reload(tmp_path, mid)
    numbers = P.palm_action(before, "Unravel Manifestation").parameters["typed"]["numbers"]
    assert numbers["cl"] == 10
    assert numbers.get("source_cl") == (None if legacy_user else 6)
    W.turn(table, mid, W.FOE)
    W.settle(table, mid, W.candidate(combat, mid, "Raise test ward").candidate_id)
    W.turn(table, mid, W.OWNER)
    before = W.reload(tmp_path, mid)
    held = P._affected(before).model_dump(mode="json")
    event_count = len(before.events)
    qi = before.state.actors[W.OWNER].resources["resource:core.qi"]
    prompts = W.settle(
        table, mid, W.candidate(combat, mid, "Empty Palm: Unravel Manifestation", target=W.FOE).candidate_id,
        picks={P.DAMAGE_TYPE_PROMPT: ["FORCE"]},
    )
    source_level = effect_source_cl if effect_source_cl is not None else effect_cl
    prompt = next(p for p in prompts
                  if p["context"]["reaction_source_id"] == "choice:needle.empty_palm_unravel")
    assert f"Source CL {source_level}" in prompt["choice"]["options"][0]["label"]
    engine = W.reload(tmp_path, mid)
    events = engine.events[event_count:]
    saves = [e for e in events if e.event_type == "SAVE_ROLLED"]
    checks = [e for e in events if e.event_type == "CHECK_ROLLED"
              and e.payload.get("skill") == "Cultivation Check"]
    mine = 10 if legacy_user else 6
    assert len(saves) == int(source_level > mine)
    if saves:
        assert saves[0].payload["dice"] == [15]
        assert saves[0].payload["success"] is resists
    assert len(checks) == int(source_level >= mine and not (source_level > mine and resists))
    if checks:
        assert checks[0].payload["actor"]["dice"] == [15]
        assert checks[0].payload["dc"] == 14 and checks[0].payload["success"] is True
    affected = P._affected(engine)
    assert affected.expires_on == held["expires_on"]  # Duration and costs are retained.
    assert engine.state.actors[W.OWNER].resources["resource:core.qi"] == qi - 3
    assert P.mark_count(engine.state.actors[W.FOE], W.OWNER) == 1
    if boundary is None:
        assert affected.condition_id == "condition:typed.poisoned"
        assert not engine.state.actors[W.FOE].turn_flags.get("typed_round_suppressed")
        return
    assert affected.condition_id == "condition:typed.suppressed.poisoned"
    receipt = engine.state.actors[W.FOE].turn_flags["typed_round_suppressed"][-1]
    # The shared receipt omits the legacy default end boundary.
    assert receipt.get("boundary", "end") == boundary
    W.settle(table, mid, table.state(mid)["menu"]["end_turn"])
    engine = W.reload(tmp_path, mid)
    if boundary == "start":
        assert P._affected(engine).condition_id == "condition:typed.suppressed.poisoned"
        W.turn(table, mid, W.OWNER)
        engine = W.reload(tmp_path, mid)
    assert P._affected(engine).condition_id == "condition:typed.poisoned"


@pytest.mark.parametrize("operation,condition_id", [
    ("Empty the Meridian", P.palm.NO_REGAIN),
    ("Hollow the Weapon", P.palm.HOLLOWED_ITEM),
])
def test_conditions_record_owning_path_source_cl_through_commit_and_reload(
    split_acquired, tmp_path, monkeypatch, operation, condition_id
):
    from combat.ext import condition_authority

    original = DeterministicRollAuthority._die

    def ordinary_d20(roller, sides):
        if sides == 20:
            counter = roller.counter
            roller.counter += 1
            return 15, counter
        return original(roller, sides)

    monkeypatch.setattr(DeterministicRollAuthority, "_die", ordinary_d20)
    service, project = split_acquired

    def setup(bundles):
        for row in bundles:
            if row["actor_id"] != W.FOE:
                continue
            row["actor_template"].update(
                armor_class=1, maximum_hp=400, saving_throws={"CON": -50, "CHA": -50}
            )
            row.pop("bundle_sha256", None)
            row["bundle_sha256"] = canonical_sha256(row)

    combat, table, mid = W.fixture(
        tmp_path, [], cl=10, owner_bundle=split_bundle(service, project),
        foe_kit={"starting_kit": P._cultivated_kit()}, bundle_transform=setup,
        positions={W.OWNER: {"x": 3, "y": 6}, W.FOE: {"x": 4, "y": 6},
                   W.ALLY: {"x": 12, "y": 12}},
        seed="PALM-CONDITION-SPLIT-LEVEL",
    )
    before = W.reload(tmp_path, mid)
    numbers = P.palm_action(before, operation).parameters["typed"]["numbers"]
    assert numbers["cl"] == 10 and numbers["source_cl"] == 6
    W.settle(
        table, mid, W.candidate(combat, mid, "Empty Palm: " + operation, target=W.FOE).candidate_id,
        picks={P.DAMAGE_TYPE_PROMPT: ["FORCE"], P.POOL_PROMPT: ["resource:core.qi"],
               P.ITEM_PROMPT: [P._item_key("treasure_weapon")]},
    )
    engine = W.reload(tmp_path, mid)
    conditions = [condition for condition in engine.state.actors[W.FOE].conditions.values()
                  if condition.condition_id == condition_id]
    assert conditions
    assert all(condition.data["source_cl"] == 6 for condition in conditions)
    assert all(condition_authority.source_cl(engine, condition) == 6 for condition in conditions)


@pytest.mark.parametrize("numbers,bundles,expected", [
    ({"cl": 10, "source_cl": 6}, [], 6),
    ({"cl": 8}, [], 8),
    ({}, [{"actor_id": W.FOE, "cl": 9}], 9),
    ({}, [], 1),
])
def test_shared_effect_authority_keeps_legacy_fallbacks(numbers, bundles, expected):
    action = SimpleNamespace(parameters={"typed": {"numbers": numbers}})
    engine = SimpleNamespace(action_catalog={WARD: action}, typed_bundle_documents=bundles)
    item = SimpleNamespace(source_definition_id=WARD, source_actor_id=W.FOE)
    assert end_effect.source_cl(SimpleNamespace(engine=engine), item) == expected
