"""Living Painting's native combat subset; not a whole-record acquisition certificate.

The acquisition test uses the real NS1R selection/AP/access producers, with the
existing sealed test authority pack. Combat fixtures compile the printed feature
into persisted tables; they do not stand in for the full Stage2 -> sheet export.
No model or browser is used. No behavior is injected into the painting itself.
"""
import pytest

from app.core import FoundryError
from combat.canonical import canonical_sha256
from combat import senses, flight, roof_movement
from tests.test_ns1r_non_sphere_authority import authority, insert_project, QI, BODY
from tests.ns1r_evidence_helpers import ap_award, commit_authority_event
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload
from tests.test_r9i_karma_persistence import act

FEATURE = "tianxia.subpath.qi.painting_cultivator.feature.living_painting"
PARENT = "tianxia.subpath.qi.painting_cultivator"
CHOICE = "choice:needle.living_painting_damage"


def test_native_acquisition_rejects_wrong_path_low_attainment_and_missing_scripture(authority):
    service, db = authority
    project = "living-painting-native-acquisition"
    insert_project(db, project, target_cl=6)
    service.initialize_for_project(project, target_cl=6, path_ids=[QI], method_id="METHOD-001")
    for path, error in ((BODY, "NS1R_PATH_SUBPATH_MISMATCH"), (QI, "NS1R_SUBPATH_CL3_REQUIRED")):
        with pytest.raises(FoundryError) as exc:
            service.select_subpath(project, path, PARENT)
        assert exc.value.code == error
    service.allocate_advancement(project, {QI: 5},
        evidence_id=ap_award(db, service, project, "METHOD-001", 6, 5), idempotency_key="painting-cl6")
    with pytest.raises(FoundryError) as exc:
        service.select_subpath(project, QI, PARENT)
    assert exc.value.code == "NS1R_RESTRICTED_TRADITION_ACCESS_REQUIRED"
    access = commit_authority_event(db, service, project, "subpath_access", {"selection_id": PARENT})
    state = service.select_subpath(project, QI, PARENT, access_source_records=[access])
    assert next(p for p in state["paths"] if p["path_id"] == QI)["subpath_or_tradition_id"] == PARENT
    record = service.project_locked_subpath_catalog_record(PARENT)
    assert FEATURE in str(record)


def setup(tmp_path, *, owns=True, bent=False):
    def opponent(bundles):
        bundles[2]["actor_template"]["armor_class"] = 0
        # An ordinary high save bonus makes the save result deterministic;
        # pounce eligibility is tested by whether the real save is offered.
        bundles[2]["actor_template"]["saving_throws"]["STR"] = 100
        bundles[2].pop("bundle_sha256", None)
        bundles[2]["bundle_sha256"] = canonical_sha256(bundles[2])
    return fixture(tmp_path, [], owner_features=[FEATURE] if owns else [], named=True, cl=6,
        bundle_transform=opponent, battlefield_transform=lambda arena: arena.update(terrain_regions=[]),
        positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 4, "y": 5},
            FOE: {"x": 9, "y": 7 if bent else 6}}, seed="LIVING-PAINTING")


def create(combat, table, mid, form, damage):
    turn(table, mid, OWNER)
    row = candidate(combat, mid, "Living Painting: " + form.title())
    before = canonical_sha256(combat._load_session(mid).engine.state.model_dump(mode="json"))
    preview = act(table, mid, row.candidate_id)
    assert preview["status"] == "REACTION_REQUIRED"
    assert canonical_sha256(combat._load_session(mid).engine.state.model_dump(mode="json")) == before
    prompts = settle(table, mid, row.candidate_id, {CHOICE: damage})
    asked = [p for p in prompts if p["context"]["reaction_source_id"] == CHOICE]
    assert len(asked) == 1
    assert {o["id"] for o in asked[0]["choice"]["options"]} == {"BLUDGEONING", "PIERCING", "SLASHING", "FORCE"}
    engine = combat._load_session(mid).engine
    painting = next(a for a in engine.state.actors.values()
                    if (a.summon or {}).get("group") == "living_painting_" + form)
    assert painting.active and painting.summon["painted_strike_damage_type"] == damage
    return painting.entity_id


@pytest.mark.parametrize("form,damage,speed,size,fly,climb", [
    ("tiger", "BLUDGEONING", 50, "Medium", 0, 0),
    ("crane", "PIERCING", 40, "Medium", 70, 0),
    ("tortoise", "SLASHING", 25, "Large", 0, 0),
    ("serpent", "FORCE", 40, "Medium", 0, 40),
])
def test_creation_choice_profile_cost_command_and_cold_replay(tmp_path, form, damage, speed, size, fly, climb):
    combat, table, mid = setup(tmp_path)
    turn(table, mid, OWNER)
    before = dict(combat._load_session(mid).engine.state.actors[OWNER].resources)
    aid = create(combat, table, mid, form, damage)
    engine = reload(tmp_path, mid)
    painting, owner = engine.state.actors[aid], engine.state.actors[OWNER]
    assert painting.speed_ft == speed and painting.size_category == size
    assert flight.profile(engine, painting).speed_ft == fly
    assert roof_movement.profile(engine, painting).speed_ft == climb
    assert flight.profile(engine, painting).hover == (form == "crane")
    assert engine._footprint(painting).width_cells == (2 if form == "tortoise" else 1)
    assert senses.of(engine, painting)["darkvision"]["range_ft"] == 60
    assert painting.maximum_hp == 24 and painting.armor_class == 13 + owner.proficiency_bonus + (2 if form == "tortoise" else 0)
    assert before["resource:core.qi"] - owner.resources["resource:core.qi"] == 4
    assert not owner.action_available and owner.concentration is not None
    assert engine.grid.distance_ft(owner.position, painting.position) <= 30
    assert painting.summon["painted_strike_damage_type"] == damage
    settle(table, mid, candidate(combat, mid, "Command Living Painting").candidate_id)
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    assert table.state(mid)["menu"]["actor_id"] == aid
    assert combat._load_session(mid).engine.state.actors[aid].action_available
    engine = reload(tmp_path, mid)
    if form == "crane":
        # A real native flight intent, not merely a field on a stat profile.
        fly_up = next(c for c in engine.legal_candidates() if c.metadata.get("movement_mode") == "fly"
                      and c.destination and c.destination.z == 1 and
                      (c.destination.x, c.destination.y) == (painting.position.x, painting.position.y))
        settle(table, mid, fly_up.candidate_id)
        engine = reload(tmp_path, mid)
        assert engine.state.actors[aid].position.z == 1
        assert flight.profile(engine, engine.state.actors[aid]).hover


@pytest.mark.parametrize("bent", [False, True])
def test_pouncing_stroke_uses_native_committed_path_and_creation_damage(tmp_path, bent):
    combat, table, mid = setup(tmp_path, bent=bent)
    aid = create(combat, table, mid, "tiger", "PIERCING")
    settle(table, mid, candidate(combat, mid, "Command Living Painting").candidate_id)
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    assert table.state(mid)["menu"]["actor_id"] == aid
    engine = combat._load_session(mid).engine
    assert (engine.state.actors[aid].position.x, engine.state.actors[aid].position.y) == (4, 6)
    move = next(c for c in engine.legal_candidates() if c.display_name.startswith("Move to")
                and c.destination and (c.destination.x, c.destination.y) == (8, 7 if bent else 6))
    settle(table, mid, move.candidate_id)
    count = len(combat._load_session(mid).engine.events)
    settle(table, mid, candidate(combat, mid, "Painted Strike", target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    events = engine.events[count:]
    hits = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids]
    assert hits and {e.payload["damage_type"] for e in hits} == {"PIERCING"}
    saves = [e for e in events if e.event_type == "SAVE_ROLLED" and e.actor_id == FOE]
    assert bool(saves) == (not bent)
    assert engine.state.actors[aid].summon["painted_strike_damage_type"] == "PIERCING"


def test_wrong_owner_has_no_painting_or_creation_choices(tmp_path):
    combat, table, mid = setup(tmp_path, owns=False)
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert not any((a.summon or {}).get("family") == "living_painting" for a in engine.state.actors.values())
    assert not any("Living Painting" in g["label"] for g in table.state(mid)["menu"]["actions"])


def test_uncommanded_dodge_and_replacement_get_a_fresh_creation_choice(tmp_path):
    combat, table, mid = setup(tmp_path)
    tiger = create(combat, table, mid, "tiger", "SLASHING")
    position = combat._load_session(mid).engine.state.actors[tiger].position
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[tiger].position == position
    assert any(e.event_type == "COMPANION_DEFAULT_APPLIED" and e.actor_id == tiger for e in engine.events)
    crane = create(combat, table, mid, "crane", "BLUDGEONING")
    engine = reload(tmp_path, mid)
    assert not engine.state.actors[tiger].active
    assert engine.state.actors[crane].summon["painted_strike_damage_type"] == "BLUDGEONING"
    assert sum(a.active for a in engine.state.actors.values() if (a.summon or {}).get("family") == "living_painting") == 1


def test_native_automatic_creator_chooses_without_a_player_prompt(tmp_path):
    from tests.test_a2_daemonic import select_native_primary

    combat, table, mid = setup(tmp_path)
    turn(table, mid, OWNER)
    select_native_primary(combat, mid, "Living Painting: Tiger", OWNER)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    prompts = settle(table, mid, None, auto=True)
    assert not any(p["context"]["reaction_source_id"] == CHOICE for p in prompts)
    engine = reload(tmp_path, mid)
    tiger = next(a for a in engine.state.actors.values() if (a.summon or {}).get("group") == "living_painting_tiger")
    assert tiger.active and tiger.summon["painted_strike_damage_type"] in {"BLUDGEONING", "PIERCING", "SLASHING", "FORCE"}
