"""Qi Storage Talisman records survive real table commits and restore their recorded CP."""
import json
import os
from pathlib import Path

import pytest

from combat.canonical import canonical_sha256
from combat.ext.talismans import PREPARED, QI_ACTIVATION
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService, CombatServiceError
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_lock2_persistence import act
from tests.hunt12_support import candidate, reload, send

ME, FOE = "actor:factory.h48-talisman", "actor:factory.h48-talisman-foe"
QI = "resource:core.qi"
TALISMAN = "tianxia.talent.talismans.qi_storage_talisman"


def _fight(tmp_path, charges=None, qi_initial=10, legacy=False):
    bundle = compile_character(sheet([TALISMAN], cl=10), actor_id=ME, reaction_plan={"ask": True})
    # Set the test's initial pool in the sealed genesis bundle, as a synthetic fight setup.
    for resource in bundle["actor_template"]["resources"]:
        if resource["resource_id"] == QI:
            resource["initial"] = qi_initial
    unsigned = {key: value for key, value in bundle.items() if key != "bundle_sha256"}
    bundle["bundle_sha256"] = canonical_sha256(unsigned)
    foe = compile_character(sheet([], cl=10), actor_id=FOE)
    for resource in foe["actor_template"]["resources"]:
        if resource["resource_id"] == QI:
            resource["initial"] = 10
    unsigned = {key: value for key, value in foe.items() if key != "bundle_sha256"}
    foe["bundle_sha256"] = canonical_sha256(unsigned)
    combat = CombatService(ROOT, tmp_path)
    if not legacy:
        requested = None if charges is None else {ME: ["setup-choice:qi_storage_charges:" + ",".join(map(str, charges))]}
        bundle = combat._with_prefight(bundle, requested)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        [bundle, foe], [ME, FOE], {ME: "team:factory", FOE: "team:opponents"},
        {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [ME], [FOE],
        control_modes={ME: "MANUAL", FOE: "MANUAL"}, match_seed="H48-TALISMAN",
        display_name="Qi Storage Talisman regression", maximum_rounds=20)["match_id"]
    while table.state(mid)["menu"]["actor_id"] != ME:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    return combat, table, mid


def _take(combat, table, mid, name):
    chosen = candidate(combat, mid, lambda row: row.display_name == name)
    return send(combat, table, mid, chosen)


def _stored_rows(state):
    return [row for row in state.state.actors[ME].conditions.values()
            if row.condition_id.startswith("condition:typed.qi_storage_talisman")]


def _prepared_count():
    bundle = compile_character(sheet([TALISMAN], cl=10), actor_id=ME)
    return next(row["maximum"] for row in bundle["actor_template"]["resources"]
                if row["resource_id"] == "resource:named.prepared_talismans")


def test_default_stores_proficiency_bonus_and_restores_after_commit_reload(tmp_path):
    combat, table, mid = _fight(tmp_path, qi_initial=0)
    stored = reload(tmp_path, mid)
    rows = _stored_rows(stored)
    assert rows and all(row.data["stored_cp"] == 4 for row in rows)
    sheet_state = table.state(mid)["presentation"]
    me = next(row for row in sheet_state["actors"] if row["entity_id"] == ME)
    assert any(row["display_name"] == "Qi Storage Talisman: 4 CP stored" for row in me["conditions"])
    assert _take(combat, table, mid, "Qi Storage Talisman")["status"] == "COMMITTED"
    after = reload(tmp_path, mid)
    assert after.state.actors[ME].resources[QI] == 4
    assert len(_stored_rows(after)) == len(rows) - 1


def test_lower_pre_fight_choice_restores_exact_amount_after_commit_reload(tmp_path):
    combat, table, mid = _fight(tmp_path, charges=[2, *([0] * (_prepared_count() - 1))])
    stored = reload(tmp_path, mid)
    assert [row.data["stored_cp"] for row in sorted(_stored_rows(stored), key=lambda row: row.applied_sequence)] == [2, *([0] * (_prepared_count() - 1))]
    assert _take(combat, table, mid, "Qi Storage Talisman")["status"] == "COMMITTED"
    after = reload(tmp_path, mid)
    assert after.state.actors[ME].resources[QI] == 12


def test_activation_stops_at_holder_maximum_after_commit_reload(tmp_path):
    bundle = compile_character(sheet([TALISMAN], cl=10), actor_id=ME, reaction_plan={"ask": True})
    qi = next(row for row in bundle["actor_template"]["resources"] if row["resource_id"] == QI)
    qi_initial = int(qi["maximum"]) - 1
    combat, table, mid = _fight(tmp_path, qi_initial=qi_initial)
    assert _take(combat, table, mid, "Qi Storage Talisman")["status"] == "COMMITTED"
    after = reload(tmp_path, mid)
    assert after.state.actors[ME].resources[QI] == after.state.actors[ME].resource_maximums[QI]


def test_no_in_combat_fill_action_exists():
    bundle = compile_character(sheet([TALISMAN], cl=10), actor_id=ME)
    assert not any("Fill Qi Storage Talisman" in row["display_name"] for row in bundle["action_catalog"])


def test_fights_without_a_charge_record_keep_legacy_proficiency_recovery(tmp_path):
    combat, table, mid = _fight(tmp_path, qi_initial=0, legacy=True)
    assert _take(combat, table, mid, "Qi Storage Talisman")["status"] == "COMMITTED"
    after = reload(tmp_path, mid)
    assert after.state.actors[ME].resources[QI] == 4  # legacy unrecorded talisman restores PB (4)


def _next_turn(table, mid):
    assert act(table, mid, "end")["status"] == "COMMITTED"
    while table.state(mid)["menu"]["actor_id"] != ME:
        assert act(table, mid, "end")["status"] == "COMMITTED"


@pytest.mark.parametrize("fresh_service", [False, True])
@pytest.mark.parametrize("all_zero", [False, True])
def test_individual_charges_exhaustion_and_ready_across_table_reload(tmp_path, fresh_service, all_zero):
    count = _prepared_count()
    charges = [0] * count if all_zero else [index % 3 for index in range(count)]
    combat, table, mid = _fight(tmp_path, charges=charges, qi_initial=0)
    restored = 0
    for index, charge in enumerate(charges):
        assert _take(combat, table, mid, "Qi Storage Talisman")["status"] == "COMMITTED"
        restored += charge
        assert combat.verify(mid)["status"] == "PASS"
        after = reload(tmp_path, mid)
        assert after.state.actors[ME].resources[QI] == restored
        assert after.state.actors[ME].resources[PREPARED] == count - index - 1
        assert len(_stored_rows(after)) == count - index - 1
        for engine in (after, combat._load_session(mid).engine):
            assert QI_ACTIVATION not in engine.__dict__
            assert all("qi_storage_cp" not in action.parameters for action in engine.action_catalog.values())
        if fresh_service:
            combat = CombatService(ROOT, tmp_path)
            table = TabletopService(combat, tmp_path)
        _next_turn(table, mid)
    # Exhausted inventory never offers an executable activation.
    assert not any(row.display_name == "Qi Storage Talisman" and row.legal
                   for row in combat._load_session(mid).engine.legal_candidates())
    assert _take(combat, table, mid, "Ready a talisman")["status"] == "COMMITTED"
    ready = reload(tmp_path, mid)
    assert ready.state.actors[ME].resources[PREPARED] == 1
    assert not _stored_rows(ready)
    if fresh_service:
        combat = CombatService(ROOT, tmp_path)
        table = TabletopService(combat, tmp_path)
    assert _take(combat, table, mid, "Qi Storage Talisman")["status"] == "COMMITTED"
    after = reload(tmp_path, mid)
    assert after.state.actors[ME].resources[QI] == restored + 4
    assert after.state.actors[ME].resources[PREPARED] == 0
    assert combat.verify(mid)["status"] == "PASS"


@pytest.mark.parametrize("answer", [
    "setup-choice:qi_storage_charges:-1,{rest}",
    "setup-choice:qi_storage_charges:5,{rest}",
    "setup-choice:qi_storage_charges:1.5,{rest}",
    "setup-choice:qi_storage_charges:bad,{rest}",
    "setup-choice:qi_storage_charges:1",
    "setup-choice:qi_storage_charges:",
    "setup-choice:qi_storage_charges",
    "setup-choice:unknown:1",
])
def test_setup_validation_rejects_invalid_answers(tmp_path, answer):
    bundle = compile_character(sheet([TALISMAN], cl=10), actor_id=ME)
    rest = ",".join(["0"] * (_prepared_count() - 1))
    with pytest.raises(CombatServiceError) as error:
        CombatService(ROOT, tmp_path)._with_prefight(bundle, {ME: [answer.format(rest=rest)]})
    assert error.value.diagnostic.code == "COMBAT_UI_DATA_INVALID"


def test_setup_validation_rejects_repeated_answers(tmp_path):
    bundle = compile_character(sheet([TALISMAN], cl=10), actor_id=ME)
    answer = "setup-choice:qi_storage_charges:" + ",".join(["0"] * _prepared_count())
    with pytest.raises(CombatServiceError):
        CombatService(ROOT, tmp_path)._with_prefight(bundle, {ME: [answer, answer]})


@pytest.mark.skipif(not os.environ.get("SOL33_PRECHANGE_SAVES"), reason="opt-in synthetic captures made at predecessor commit")
def test_prechange_saved_fights_load_verify_and_replay():
    """Run against captures generated before editing this lane; never live owner data."""
    root = Path(os.environ["SOL33_PRECHANGE_SAVES"])
    for name, expected in json.loads((root / "before.json").read_text()).items():
        combat = CombatService(ROOT, root / name)
        mid = expected["match_id"]
        session = combat._load_session(mid)
        assert combat.verify(mid)["status"] == "PASS"
        assert combat.replay(mid)["status"] == "PASS"
        assert canonical_sha256(session.engine.state.model_dump(mode="json")) == expected["state"]
        assert canonical_sha256([row.model_dump(mode="json") for row in session.engine.events]) == expected["events"]
        if "rolls" in expected:
            assert canonical_sha256([row.model_dump(mode="json") for row in session.engine.rolls]) == expected["rolls"]
