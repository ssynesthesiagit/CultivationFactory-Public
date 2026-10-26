"""Native source access, movement, senses and automatic-seat boundaries."""
import json
from pathlib import Path

import pytest

from app.core import FoundryError
from combat.gate4_adapters import ManualControllerAdapter
from tests.test_ns1r_non_sphere_authority import authority, insert_project, QI, BODY
from tests.ns1r_evidence_helpers import ap_award, commit_authority_event
from tests.h1_support import sheet
from tests.test_mgr_t15_vanishing_native import setup, activate, held, VANISH, TRUE_SIGHT_FEATURES
from tests.worker2_support import OWNER, FOE, settle, reload
from tests.test_r9i_karma_persistence import act
from tests.hunt12_support import hit_dice

PARENT = "tianxia.subpath.qi.ninpo_adept"
# The native NS1R producer authenticates these dynamic identity-map inputs.
# Literal real paths let the safe exporter retain the actual source closure.
NS1R_INPUTS = (
    "non_sphere_authority/authority/Background_Core_Authority_v1.json",
    "non_sphere_authority/authority/Exact_Named_Method_Foundation_Overrides_v0_6.json",
    "non_sphere_authority/authority/Foundation_Runtime_Authority_v0_4C.json",
    "non_sphere_authority/authority/Foundation_Trait_Reference_v0_6.json",
    "non_sphere_authority/authority/Method_Compatibility_Trait_Taxonomy_v0_6.json",
    "non_sphere_authority/authority/Tianxia_Compatibility_Result_v0_6.schema.json",
    "non_sphere_authority/authority/Tianxia_Exact_Named_Overrides_v0_6.schema.json",
    "non_sphere_authority/authority/Tianxia_Foundation_Traits_v0_6.schema.json",
    "non_sphere_authority/authority/Tianxia_Foundations_Unified_Transparent_GM_Screen_Catalog_v0_4C.md",
    "non_sphere_authority/authority/Tianxia_Method_Compatibility_Traits_v0_6.schema.json",
    "non_sphere_authority/authority/Tianxia_Method_Registry_v0_6.schema.json",
    "non_sphere_authority/authority/Tianxia_Methods_Typed_Registry_v0_6.json",
    "non_sphere_authority/authority/Tianxia_PHB_Backgrounds_v2_BOOK_CLEAN_ORIGIN_RECONCILED_v0_6.md",
    "non_sphere_authority/authority/Tianxia_Path_Index_Master_P2A.json",
    "non_sphere_authority/authority/Tianxia_Subpath_Tradition_Index_Master_P2B.json",
    "non_sphere_authority/authority/Tianxia_Trait_Provenance_v0_6.schema.json",
    "non_sphere_authority/authority/body_refining.path_index.p2a.json",
    "non_sphere_authority/authority/open_ended_compatibility_resolver.py",
    "non_sphere_authority/authority/qi_cultivation.path_index.p2a.json",
    "non_sphere_authority/authority/spirit_awakening.path_index.p2a.json",
)


def test_native_scripture_access_and_cl14_record(authority):
    root = Path(__file__).resolve().parents[1]
    identities = json.loads((root / "non_sphere_authority/authority/NS1R_AUTHORITY_IDENTITIES.json").read_text())
    assert {Path(path).name for path in NS1R_INPUTS} == set(identities["files"])
    service, db = authority
    project = "vanishing-source-access"
    insert_project(db, project, target_cl=14)
    service.initialize_for_project(project, target_cl=14, path_ids=[QI], method_id="METHOD-001")
    with pytest.raises(FoundryError) as wrong_path:
        service.select_subpath(project, BODY, PARENT)
    assert wrong_path.value.code == "NS1R_PATH_SUBPATH_MISMATCH"
    with pytest.raises(FoundryError) as low:
        service.select_subpath(project, QI, PARENT)
    assert low.value.code == "NS1R_SUBPATH_CL3_REQUIRED"
    service.allocate_advancement(project, {QI: 13},
        evidence_id=ap_award(db, service, project, "METHOD-001", 14, 13), idempotency_key="vanishing-cl14")
    with pytest.raises(FoundryError) as no_scripture:
        service.select_subpath(project, QI, PARENT)
    assert no_scripture.value.code == "NS1R_RESTRICTED_TRADITION_ACCESS_REQUIRED"
    # A validated durable native authority event; never a GM-done flag.
    access = commit_authority_event(db, service, project, "subpath_access", {"selection_id": PARENT})
    state = service.select_subpath(project, QI, PARENT, access_source_records=[access])
    assert next(p for p in state["paths"] if p["path_id"] == QI)["subpath_or_tradition_id"] == PARENT
    record = service.project_locked_subpath_catalog_record(PARENT)
    assert VANISH in str(record)
    assert service.get_state(project)["access_source_records"]


@pytest.mark.parametrize("true_sight", [False, True])
def test_native_movement_through_reach_preserves_owned_invisibility(tmp_path, true_sight):
    foe = sheet(TRUE_SIGHT_FEATURES if true_sight else [], cl=14)
    combat, table, mid = setup(tmp_path, foe_sheet=foe)
    activate(combat, table, mid)
    before = reload(tmp_path, mid)
    mark = len(before.events)
    move = next(c for c in before.legal_candidates() if str(c.kind) == "MOVE"
                and c.destination.x == 2 and c.destination.y == 6)
    settle(table, mid, move.candidate_id, choices={})
    after = reload(tmp_path, mid)
    assert held(after.state.actors[OWNER], "invisible")
    assert held(after.state.actors[OWNER], "vanishing_state")
    # A tracking/perceiving capability doesn't remove the target's condition.
    if true_sight:
        from combat.target_knowledge import can_see
        assert can_see(after, after.state.actors[FOE], after.state.actors[OWNER])
    else:
        assert not any(e.event_type == "ATTACK_ROLLED" and e.actor_id == FOE for e in after.events[mark:])


def test_automatic_seat_can_choose_vanishing_without_a_model(tmp_path):
    combat, table, mid = setup(tmp_path, ask=False)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    engine = combat._load_session(mid).engine
    chosen = next(c for c in engine.legal_candidates()
                  if c.source_definition_id in engine.action_catalog
                  and engine.action_catalog[c.source_definition_id].display_name == "Vanishing Technique")
    real = combat.controller

    class SelectedController:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _: (chosen.candidate_id, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(real, name)

    combat.controller = SelectedController()
    try:
        settle(table, mid, chosen.candidate_id, auto=True)
    finally:
        combat.controller = real
    assert held(reload(tmp_path, mid).state.actors[OWNER], "invisible")


@pytest.mark.parametrize("true_sight", [False, True])
def test_oa_exception_while_harmful_action_has_revealed_owner(tmp_path, monkeypatch, true_sight):
    from tests.test_mgr_t15_vanishing_damage import attack

    hit_dice(monkeypatch, save_roll=20)
    foe = sheet(TRUE_SIGHT_FEATURES if true_sight else [], cl=14)
    combat, table, mid = setup(tmp_path, foe_sheet=foe)
    activate(combat, table, mid)
    settle(table, mid, attack(reload(tmp_path, mid), OWNER, FOE).candidate_id, choices={})
    visible = reload(tmp_path, mid)
    assert not held(visible.state.actors[OWNER], "invisible")
    mark = len(visible.events)
    move = next(c for c in visible.legal_candidates() if str(c.kind) == "MOVE"
                and c.destination.x == 2 and c.destination.y == 6)
    preview = act(table, mid, move.candidate_id)
    assert preview["status"] == "REACTION_REQUIRED"
    rid = preview["reaction"]["context"]["reaction_source_id"]
    settle(table, mid, move.candidate_id, {rid: "first"})
    after = reload(tmp_path, mid)
    rolls = [e for e in after.events[mark:] if e.event_type == "ATTACK_ROLLED" and e.actor_id == FOE]
    assert rolls and all(e.payload["mode"] == ("NORMAL" if true_sight else "DISADVANTAGE") for e in rolls)
    assert held(after.state.actors[OWNER], "vanishing_state")
    assert not held(after.state.actors[OWNER], "invisible")
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    assert held(reload(tmp_path, mid).state.actors[OWNER], "invisible")
