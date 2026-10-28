"""Place Mandate acquisition and existing delivery through native table commits.

Only real portable-sheet ownership is varied; no injected effects or fact receipts.
The whole base row remains open for the Vessel/consent boundaries in the report.
"""
import pytest

from tests import r1i_service_support as S
from tests.test_a2_imbuement import cold, turn, QI
from combat.ext import persist_augment as P

BASE = "IMBUEMENT_BASE_PLACE_MANDATE"
IMB = "tianxia.talent.imbuement."


def place_rows(engine, target):
    actor = engine.state.actors[target]
    return [row for row in (*actor.conditions.values(), *actor.modifiers.values())
            if ".mandate.imbue." in row.source_definition_id
            and getattr(row, "condition_id", "") != "condition:typed.concentration_deadline"]


@pytest.mark.parametrize("owns", [False, True])
def test_place_requires_own_base_record_not_fray_marker(monkeypatch, tmp_path, owns):
    real = S.sheet
    def sheet(*args, **kwargs):
        doc = real(*args, **kwargs)
        components = doc.get("spheres_and_talents", {}).get("automatic_sphere_component_record_ids", [])
        if not owns and BASE in components:
            components.remove(BASE)
        return doc
    monkeypatch.setattr(S, "sheet", sheet)
    combat, table, mid, send, commit = S.fixture(tmp_path, [IMB + "quicken_and_slow"], allies=[S.SECOND])
    engine = cold(tmp_path, mid)
    ids = engine.state.actors[S.OWNER].action_ids
    assert any(".mandate.imbue." in aid for aid in ids) == owns
    assert any(".mandate.fray." in aid for aid in ids), "the separate Fray provider must remain available"
    labels = [g["label"] for g in table.state(mid)["menu"]["actions"]]
    assert any("Place Mandate: Quicken" in label for label in labels) == owns
    assert not any("Place Mandate: Physique" in label for label in labels), "unknown options are not acquired"
    assert not any(".mandate.imbue." in aid for aid in engine.state.actors[S.FOE].action_ids)


@pytest.mark.parametrize("target", [S.OWNER, S.SECOND])
def test_known_option_base_action_range_cost_and_cold_reload(tmp_path, target):
    combat, table, mid, send, commit = S.fixture(tmp_path, [IMB + "quicken_and_slow"], allies=[S.SECOND], wide=True,
        positions={S.OWNER: {"x": 3, "y": 6}, S.SECOND: {"x": 9, "y": 6}, S.FOE: {"x": 10, "y": 6}})
    before = cold(tmp_path, mid).state.actors[S.OWNER].resources[QI]
    commit(S.candidate(table, mid, "Place Mandate: Quicken", target))
    engine = cold(tmp_path, mid)
    actor = engine.state.actors[S.OWNER]
    assert actor.resources[QI] == before
    assert not actor.action_available
    assert actor.concentration
    action = engine.action_catalog[actor.concentration.source_definition_id]
    assert action.range_ft == 30
    assert action.parameters["typed"]["duration"] == {"kind": "minutes", "amount": 10, "concentration": True}
    assert place_rows(engine, target)
    assert not place_rows(engine, S.FOE)
    assert not place_rows(engine, S.SECOND if target == S.OWNER else S.OWNER)
    assert not any(e.event_type == "SAVE_ROLLED" and e.actor_id == target for e in engine.events)


def test_base_setting_is_free_action_costs_two_and_keeps_remaining_duration(tmp_path):
    combat, table, mid, send, commit = S.fixture(tmp_path, [IMB + "quicken_and_slow"], allies=[S.SECOND])
    commit(S.candidate(table, mid, "Place Mandate: Quicken", S.SECOND))
    original = cold(tmp_path, mid).state.actors[S.OWNER]
    deadline = next(row.expires_on for row in original.conditions.values()
                    if row.condition_id == "condition:typed.concentration_deadline")
    turn(table, mid, commit)
    engine = cold(tmp_path, mid)
    actor = engine.state.actors[S.OWNER]
    before, available = actor.resources[QI], actor.action_available
    # Delay setting until a later turn: its deadline must still be the original one.
    commit(S.candidate(table, mid, "Set Mandate:"))
    engine = cold(tmp_path, mid)
    actor = engine.state.actors[S.OWNER]
    assert actor.resources[QI] == before - 2
    assert actor.action_available == available
    assert actor.concentration is None
    record = P.persisted(engine, actor, BASE)
    assert len(record) == 1 and record[0][1].expires_on == deadline
    assert place_rows(engine, S.SECOND)
    assert all(row.expires_on == deadline for row in place_rows(engine, S.SECOND))
    # A set Mandate still fills the default one-Mandate load.
    commit(S.candidate(table, mid, "Place Mandate: Quicken", S.OWNER))
    engine = cold(tmp_path, mid)
    assert not P.persisted(engine, engine.state.actors[S.OWNER], BASE)
    assert not place_rows(engine, S.SECOND)
    assert place_rows(engine, S.OWNER)


def test_place_out_of_range_candidate_is_absent(tmp_path):
    combat, table, mid, send, commit = S.fixture(tmp_path, [IMB + "quicken_and_slow"], allies=[S.SECOND], wide=True,
        positions={S.OWNER: {"x": 3, "y": 6}, S.SECOND: {"x": 10, "y": 6}, S.FOE: {"x": 4, "y": 6}})
    choices = [o for g in table.state(mid)["menu"]["actions"] if g["label"] == "Place Mandate: Quicken"
               for o in g["options"]]
    assert any(S.OWNER in o.get("target_ids", []) for o in choices)
    assert not any(S.SECOND in o.get("target_ids", []) for o in choices)
