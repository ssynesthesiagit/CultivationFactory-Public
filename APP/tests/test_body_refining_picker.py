"""S1 acceptance 3, 4, 8: real Grow and creation payloads, no GM override."""
import pytest

from character_creation.creative_controller.linear_menus import _Candidate, _path_legal
from factory_authoring.path_access import blocked
from tests.body_refining_support import BODY, QI, DARK, PID, UPGRADE, install, service, sheet


@pytest.mark.parametrize("cl", [1, 4])
def test_owner_dark_default_is_legal_in_real_payload(tmp_path, cl):
    install(tmp_path, sheet(cl=cl))
    payload = service(tmp_path).advancement(PID)
    row = next(r for r in payload["spheres"] if r["id"] == DARK)
    assert row["legal"] and not row["gm"] and not row["reasons"]
    assert row["body_refining_variant"]["label"] == "Dark — Body Refining: Night-Bound Body"
    assert "no Insight or level requirement" in row["body_refining_variant"]["gate_note"]
    assert all("not open" not in reason for reason in row["reasons"])


def test_qi_boundary_and_projection_refusal_unchanged(tmp_path):
    install(tmp_path, sheet(paths=[QI]))
    row = next(r for r in service(tmp_path).advancement(PID)["spheres"] if r["id"] == DARK)
    # Compendium L17872 prints Qi Cultivation as Dark's PRIMARY Path.
    # S1 acceptance 4 says "illegal", contradicting both print and the owner
    # instruction to preserve primary/open entries. Preserve the printed access.
    assert row["legal"] and row["body_refining_variant"] is None
    from factory_authoring.path_access import _mechanics, TYPED
    lava = next(k for k, r in _mechanics(TYPED.stat().st_mtime).items() if r["name"] == "Lava Spit")
    assert "projects Qi" in blocked(lava, [BODY])
    assert blocked(lava, [BODY, QI]) is None


def test_creation_keeps_default_label_without_a_new_choice():
    state = {"by_slot": {"path_choice": [BODY]}}
    candidate = _Candidate((DARK,), "Dark")
    result = _path_legal({}, {}, state, "sphere_route", [candidate], 1)
    assert result[0].cue == "Dark — Body Refining: Night-Bound Body"
    assert result[0].choice_ids == (DARK,)
    # No label or new decision after the upgrade or for an unrelated Path.
    state["by_slot"]["insight_occurrence"] = [UPGRADE]
    assert _path_legal({}, {}, state, "sphere_route", [candidate], 1) == [candidate]
    assert _path_legal({}, {}, {"by_slot": {"path_choice": [QI]}}, "sphere_route", [candidate], 1) == [candidate]


def test_learning_and_upgrade_round_trip_through_cold_service(tmp_path):
    install(tmp_path, sheet())
    first = service(tmp_path)
    first.add_advancement(PID, "sphere", DARK)
    cold = service(tmp_path)
    document = cold.combat._factory_owner_sheet(PID)
    from factory_authoring.body_refining_variants import selected
    assert selected(DARK, document, require_owned=True)
    option = next(r for r in cold.advancement(PID)["insights"] if r["id"] == UPGRADE)
    assert option["legal"]
    cold.add_insight(PID, UPGRADE, note="Completed body training")
    after = service(tmp_path).combat._factory_owner_sheet(PID)
    assert UPGRADE in after["spheres_and_talents"]["cultivation_insight_record_ids"]
    assert selected(DARK, after) is None
    service(tmp_path).remove_advancement(PID, "insight", "0")
    assert selected(DARK, service(tmp_path).combat._factory_owner_sheet(PID))


def test_path_filter_survives_a_stale_body_refining_authority(monkeypatch):
    """BRS1F22R finding 1: a stale authority pin (ValueError) must skip only the Body Refining labels.
    The Path filter still drops the Sphere a Body Refiner cannot learn; before the fix the fallback
    returned every candidate and re-admitted it."""
    from factory_authoring import body_refining_variants
    from factory_authoring.path_access import access, can_learn

    blocked_sphere = next(s for s in access() if not can_learn(s, {BODY}))
    assert can_learn(DARK, {BODY})

    def stale(*args, **kwargs):
        raise ValueError("stale authority pin")

    monkeypatch.setattr(body_refining_variants, "access", stale)
    candidates = [_Candidate((blocked_sphere,), "Blocked"), _Candidate((DARK,), "Dark")]
    state = {"by_slot": {"path_choice": [BODY]}}
    result = _path_legal({}, {}, state, "sphere_route", candidates, 1)
    assert [c.choice_ids for c in result] == [(DARK,)]
