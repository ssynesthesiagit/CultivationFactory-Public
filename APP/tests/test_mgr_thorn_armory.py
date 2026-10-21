"""CL3/common Black Thorn through native table commits, cold load and replay.

All characters, maps and setup actions are synthetic. Setup actions have real
Action economy; they never grant Spines, ownership, free primary activations or
damage-provenance tags. Source/consent choices use the normal table interface.
"""
import json
import zipfile
from pathlib import Path

import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionDefinition
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService

ROOT = Path(__file__).resolve().parents[1]
PARENT = "tianxia.subpath.body.black_thorn_demon_body"
ARMORY = PARENT + ".feature.thorn_flesh_armory"
BODY = "tianxia.path.body_refining"
SPINE = "resource:named.demon_spine"
OWNER, FOE, ALLY = ("actor:factory.thorn-owner", "actor:factory.thorn-foe", "actor:factory.thorn-ally")
HOSTILITY = "choice:needle.fact_admission.demon_spine_hostility"
SPEND = "choice:needle.thorn_flesh_armory"
TYPE = "choice:needle.thorn_flesh_armory_type"
BASE_TYPE = "choice:needle.thorn_strike_type"


def sheet(*, owns=False, cl=9, effective=None, path="Body Refining", ac=10, dc=60, features=()):
    identity = {"name": "Thorn cultivator" if owns else "Sparring partner", "path": path,
                "cultivation_level": cl, "proficiency_bonus": 2 + max(0, cl - 1) // 4, "key_ability": "CON"}
    if effective is not None:
        identity["effective_cultivation_level"] = effective
    return {"identity": identity,
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": 14, "modifier": 2} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
            "primary_resource": {"name": "Stamina", "maximum": 30},
            "armor_class": {"base_value": ac}, "hit_points": {"maximum": 300},
            "speed": {"walking_ft": 30}, "technique_save_dc": dc, "technique_attack_bonus": 100},
        "path_and_subpath": {"path_feature_record_ids": [*([ARMORY] if owns else []), *features]},
        "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.iron_fist"],
            "automatic_sphere_component_record_ids": ["TAL_IRON_FIST_IRON_FIST_TRAINING"]}}


def add_action(bundle, name, effects, *, target="ANY_CREATURE", source=None, economy="ACTION", range_ft=120):
    source = source or "action:test.thorn." + bundle["actor_id"].rsplit(":", 1)[-1] + "." + name.lower().replace(" ", "_")
    action = ActionDefinition(source_definition_id=source, display_name=name,
        owner_id=bundle["actor_id"], economy=economy, resolution_kind="TYPED", target_kind=target,
        range_ft=range_ft, parameters={"player_only": True, "typed": {
            "source": source, "effects": effects, "numbers": {"cl": 9, "pb": 4, "key_mod": 2, "save_dc": 60},
            "duration": {"kind": "instant"}, "riders": []}})
    bundle["action_catalog"].append(action.model_dump(mode="json"))
    bundle["actor_template"]["action_ids"].append(source)


def fixture(root, *, owns=True, owner_doc=None, foe_doc=None, near=True, ally_same_side=True, modes=None, ally_position=None, objects=()):
    docs = [owner_doc or sheet(owns=owns), foe_doc or sheet(), sheet()]
    bundles = []
    for aid, doc in zip((OWNER, FOE, ALLY), docs):
        folder = root / "portable_characters" / aid.removeprefix("actor:factory.")
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
        bundle = compile_character(doc, actor_id=aid, reaction_plan={"ask": True})
        for name, amount, kind in (("Pierce", 3, "piercing"), ("Slash", 3, "slashing"),
                                   ("Burn", 3, "fire"), ("Zero", 0, "piercing"), ("End scene", 1000, "force")):
            add_action(bundle, name, [{"type": "damage", "applies_to": "target", "flat": amount,
                                       "damage_types": [kind]}])
        add_action(bundle, "Two packets", [{"type": "damage", "applies_to": "target", "flat": 3,
                                            "damage_types": [k]} for k in ("piercing", "slashing")])
        for amount in (0, 1, 3, 12):
            add_action(bundle, "Heal " + str(amount), [{"type": "healing", "applies_to": "target", "flat": amount}])
        add_action(bundle, "Rolled healing", [{"type": "healing", "applies_to": "target", "dice": {"count": 3, "sides": 6}}])
        add_action(bundle, "Temporary HP", [{"type": "temp_hp", "applies_to": "target", "flat": 12}])
        add_action(bundle, "Be paralyzed", [{"type": "condition", "condition": "paralyzed", "applies_to": "self",
            "expires_on": "UNTIL_REMOVED"}], target="SELF")
        add_action(bundle, "Be unconscious", [{"type": "condition", "condition": "unconscious", "applies_to": "self"}], target="SELF")
        add_action(bundle, "Lie prone", [{"type": "condition", "condition": "prone", "applies_to": "self"}],
                   target="SELF", economy="BONUS_ACTION")
        add_action(bundle, "Push", [{"type": "forced_movement", "applies_to": "target", "distance_ft": 10, "direction": "away"}])
        add_action(bundle, "Teleport", [{"type": "teleport", "applies_to": "self", "distance_ft": 10}], target="SELF", range_ft=10)
        add_action(bundle, "Piercing immunity", [{"type": "immunity", "applies_to": "self",
            "damage_types": ["piercing"]}], target="SELF")
        add_action(bundle, "Suppress bleeding", [{"type": "suppress_named_condition", "applies_to": "self",
            "conditions": ["bleeding"]}], target="SELF", economy="BONUS_ACTION")
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)
        bundles.append(bundle)
    combat = CombatService(ROOT, root)
    table = TabletopService(combat, root)
    # Use the shipped public map converter, exactly as native user maps do.
    from combat.tabletop import normalize_map, to_battlefield
    arena = to_battlefield(normalize_map({"display_name": "Thorn test court", "width_squares": 14,
        "height_squares": 12, "walls": [], "objects": list(objects),
        "starts": {"team1": [[3, 4]], "team2": [[4, 4]]}}))
    teams = {OWNER: "team:a", FOE: "team:b", ALLY: "team:a" if ally_same_side else "team:b"}
    result = combat._finish_factory_match(bundles, [OWNER, FOE, ALLY], teams,
        {OWNER: {"x": 3, "y": 4}, FOE: {"x": 4 if near else 8, "y": 4}, ALLY: ally_position or {"x": 3, "y": 5}},
        arena, [OWNER, ALLY], [FOE], control_modes=modes or {a: "MANUAL" for a in teams},
        match_seed="THORN-ARMORY-NATIVE", display_name="Thorn court", maximum_rounds=25)
    return combat, table, result["match_id"]


def engine(combat, mid):
    return combat._load_session(mid).engine


def cold(root, combat, mid):
    old = engine(combat, mid)
    fresh = CombatService(ROOT, root)
    session = fresh._load_session(mid)
    assert session.engine.state.model_dump(mode="json") == old.state.model_dump(mode="json")
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"
    return session.engine


def settle(table, mid, cid, choices=None, audit_engine=None):
    choices = choices or {}
    menu = table.state(mid)["menu"]
    before = canonical_sha256(audit_engine().state.model_dump(mode="json")) if audit_engine else None
    answers, prompts = [], []
    for _ in range(30):
        reply = table.act(mid, cid, menu["decision_id"], menu["state_version"], 0, answers)
        if reply["status"] != "REACTION_REQUIRED":
            assert reply["status"] == "COMMITTED", reply
            return prompts
        prompt = reply["reaction"]
        if audit_engine:
            assert canonical_sha256(audit_engine().state.model_dump(mode="json")) == before
        prompts.append(prompt)
        source = prompt["context"]["reaction_source_id"]
        spec = prompt.get("choice") or {}
        options = [o["id"] for o in spec.get("options", [])]
        if source in choices:
            selected = choices[source]
        elif choices.get("accept_opportunity") and "opportunity" in source:
            selected = options[:1]
        elif source == HOSTILITY:
            selected = ["hostile"]
        elif source == SPEND:
            selected = None
        else:
            selected = options[:spec.get("minimum_selections", 1)] if options else None
        if isinstance(selected, str):
            selected = [selected]
        answers.append({**prompt["context"], "selection": "DECLINE" if selected is None else "USE",
                        "option_ids": selected or []})
    raise AssertionError("Too many native choices")


def turn(combat, table, mid, actor):
    for _ in range(9):
        if engine(combat, mid).state.current_actor_id == actor:
            return
        settle(table, mid, table.state(mid)["menu"]["end_turn"])
    raise AssertionError("Turn did not reach " + actor)


def next_turn(combat, table, mid, actor):
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    turn(combat, table, mid, actor)


def act(combat, table, mid, actor, name, target=None, choices=None):
    turn(combat, table, mid, actor)
    e = engine(combat, mid)
    c = next(c for c in e.legal_candidates() if (c.display_name == name or
             (e.action_catalog.get(c.source_definition_id) is not None and
              e.action_catalog[c.source_definition_id].display_name == name))
             and (target is None or target in c.target_ids))
    return settle(table, mid, c.candidate_id, choices)


def earn(combat, table, mid, count=1, *, source=FOE, kind="Pierce"):
    for n in range(count):
        if n:
            next_turn(combat, table, mid, source)
        act(combat, table, mid, source, kind, OWNER)


def unarmed(combat, mid, target=FOE):
    from combat.weapon_delivery import delivery_kind
    e = engine(combat, mid)
    candidates = e.legal_candidates()
    strikes = [c for c in candidates if target in c.target_ids
                and c.kind == "ACTION" and c.source_definition_id in e.action_catalog
                and any(row.get("type") == "attack" and delivery_kind(
                        e.action_catalog[c.source_definition_id].parameters.get("typed") or {}, row,
                        e.action_catalog[c.source_definition_id].parameters) == "unarmed"
                        for row in (e.action_catalog[c.source_definition_id].parameters.get("typed") or {}).get("effects", []))]
    assert strikes, {"actor": e.state.current_actor_id, "action_available": e.state.actors[e.state.current_actor_id].action_available,
                     "actions": [(c.display_name, c.source_definition_id) for c in candidates if c.kind == "ACTION"]}
    return max(strikes, key=lambda c: max(int(row.get("count") or 1) for row in
        e.action_catalog[c.source_definition_id].parameters["typed"]["effects"] if row.get("type") == "attack"))


def hit(combat, table, mid, *, damage="slashing", decline=False, target=FOE, audit_engine=None):
    turn(combat, table, mid, OWNER)
    for _ in range(6):
        c = unarmed(combat, mid, target)
        prompts = settle(table, mid, c.candidate_id,
                         {SPEND: None if decline else ["spend"], TYPE: [damage], BASE_TYPE: ["PIERCING"]}, audit_engine)
        if any(p["context"]["reaction_source_id"] == SPEND for p in prompts):
            return prompts
        next_turn(combat, table, mid, OWNER)
    raise AssertionError("No real unarmed hit in six turns")


def bleeding(actor):
    return [c for c in actor.conditions.values() if c.data.get("thorn_bleeding")]


def test_source_commitment_and_printed_native_entry(tmp_path):
    # Compare source commitments, not private printed prose (public CI scrambles prose).
    typed = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())["mechanics"][ARMORY]
    index = json.loads((ROOT / "non_sphere_authority/authority/Tianxia_Subpath_Tradition_Index_Master_P2B.json").read_text())
    entry = next(e for e in index["entries"] if e["canonical_id"] == PARENT)
    assert typed["source"]["text_sha256"] == entry["feature_progression"][0]["source"]["section_sha256"]
    from app.core import Database, Settings, FoundryError, canonical_json, utcnow
    from non_sphere_authority.service import NonSphereAuthorityService
    # Pure synthetic evidence builders; no fixture/test imports or private data.
    from tests.ns1r_evidence_helpers import install_authority_test_pack, lock_authority_test_pack, commit_authority_event, ap_award
    settings = Settings.from_env(ROOT, tmp_path / "authority")
    settings.ensure_dirs()
    db = Database(settings)
    db.migrate()
    service = NonSphereAuthorityService(db)
    install_authority_test_pack(db, service)
    project = "thorn-native-entry"
    now = utcnow()
    with db.transaction() as conn:
        conn.execute("""INSERT INTO projects(project_id,working_name,status,revision,created_at,updated_at,
            target_factory_version,target_candidate_schema_version,target_gm_screen_version,catalog_build_hash,
            quality_target,project_json,compatibility_projection_status,compile_status,consumer_verification_status,
            legacy_project_json,canonical_project_hash,canonical_schema_version,contract_status)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (project, project, "DRAFT", 0, now, now, "HF05ZVK-R1H", "HF05ZVK-R1F", "HF05ZUI-R2K.3-HF3-W1", None,
             "rival/boss", canonical_json({"project_id": project, "working_name": project,
             "user_locks": [{"field": "target_cl", "value": 3}], "events": []}), "NOT_BUILT", "NOT_COMPILED", "NOT_VERIFIED",
             None, "0" * 64, "Tianxia.CharacterProject.v3", "legacy-unverified"))
    lock_authority_test_pack(db, project, 3)
    access = commit_authority_event(db, service, project, "method_access", {"method_id": "METHOD-002"})
    service.initialize_for_project(project, target_cl=3, path_ids=[BODY], method_id="METHOD-002", access_source_records=[access])
    with pytest.raises(FoundryError) as exc:
        service.select_subpath(project, BODY, PARENT)
    assert exc.value.code == "NS1R_SUBPATH_CL3_REQUIRED"
    service.allocate_advancement(project, {BODY: 2},
        evidence_id=ap_award(db, service, project, "METHOD-002", 3, 2), idempotency_key="thorn-cl3")
    with pytest.raises(FoundryError) as exc:
        service.select_subpath(project, "tianxia.path.qi_cultivation", PARENT)
    assert exc.value.code == "NS1R_PATH_SUBPATH_MISMATCH"
    with pytest.raises(FoundryError) as exc:
        service.select_subpath(project, BODY, PARENT)
    assert exc.value.code == "NS1R_RESTRICTED_TRADITION_ACCESS_REQUIRED"
    access = commit_authority_event(db, service, project, "subpath_access", {"selection_id": PARENT})
    selected = service.select_subpath(project, BODY, PARENT, access_source_records=[access])
    assert next(p for p in selected["paths"] if p["path_id"] == BODY)["subpath_or_tradition_id"] == PARENT
    record = service.project_locked_subpath_catalog_record(PARENT)
    assert ARMORY in json.dumps(record)
    combat, table, mid = fixture(tmp_path / "acquired", owner_doc=sheet(owns=True, cl=3))
    earn(combat, table, mid)
    assert cold(tmp_path / "acquired", combat, mid).state.actors[OWNER].resources[SPINE] == 1


@pytest.mark.parametrize("kind,near,expected", [("Pierce", False, 1), ("Slash", False, 1), ("Burn", False, 0),
    ("Burn", True, 1), ("Zero", True, 0), ("Two packets", True, 1)])
def test_hp_receipts_gain_once_from_qualifying_damage_and_replay(tmp_path, kind, near, expected):
    combat, table, mid = fixture(tmp_path, near=near)
    assert engine(combat, mid).state.actors[OWNER].resources[SPINE] == 0
    earn(combat, table, mid, kind=kind)
    e = cold(tmp_path, combat, mid)
    assert e.state.actors[OWNER].resources[SPINE] == expected
    assert len([ev for ev in e.events if ev.event_type == "RESOURCE_GAINED"
                and ev.actor_id == OWNER and ev.payload.get("resource_id") == SPINE]) == expected
    next_turn(combat, table, mid, FOE)
    act(combat, table, mid, FOE, "Pierce", OWNER)
    assert cold(tmp_path, combat, mid).state.actors[OWNER].resources[SPINE] == expected + 1


def test_same_team_hostility_is_controller_owned_and_training_is_excluded(tmp_path):
    combat, table, mid = fixture(tmp_path)
    prompts = act(combat, table, mid, ALLY, "Pierce", OWNER, {HOSTILITY: ["excluded"]})
    assert any(p["context"]["reaction_source_id"] == HOSTILITY for p in prompts)
    assert cold(tmp_path, combat, mid).state.actors[OWNER].resources[SPINE] == 0
    next_turn(combat, table, mid, ALLY)
    act(combat, table, mid, ALLY, "Pierce", OWNER, {HOSTILITY: ["hostile"]})
    assert cold(tmp_path, combat, mid).state.actors[OWNER].resources[SPINE] == 1
    # Opposing team alone cannot override consensual training.
    act(combat, table, mid, FOE, "Pierce", OWNER, {HOSTILITY: ["excluded"]})
    assert cold(tmp_path, combat, mid).state.actors[OWNER].resources[SPINE] == 1


def test_temporary_hp_never_mints_spines(tmp_path):
    combat, table, mid = fixture(tmp_path)
    act(combat, table, mid, OWNER, "Temporary HP", OWNER)
    earn(combat, table, mid, kind="Two packets")
    assert cold(tmp_path, combat, mid).state.actors[OWNER].resources[SPINE] == 0
    assert engine(combat, mid).state.actors[OWNER].temporary_hp == 6


def test_actual_damage_immunity_never_mints_spines(tmp_path):
    combat, table, mid = fixture(tmp_path)
    act(combat, table, mid, OWNER, "Piercing immunity")
    hp = engine(combat, mid).state.actors[OWNER].current_hp
    earn(combat, table, mid)
    e = cold(tmp_path, combat, mid)
    assert e.state.actors[OWNER].current_hp == hp
    assert e.state.actors[OWNER].resources[SPINE] == 0


@pytest.mark.parametrize("doc", [sheet(), sheet(owns=True, path="Qi Cultivation"), sheet(owns=True, cl=2)])
def test_nonowner_wrong_path_and_underlevel_are_inert(tmp_path, doc):
    combat, table, mid = fixture(tmp_path, owner_doc=doc)
    earn(combat, table, mid)
    e = cold(tmp_path, combat, mid)
    assert e.state.actors[OWNER].resources.get(SPINE, 0) == 0
    assert not any(ev.source_definition_id == "system:black_thorn_damage" for ev in e.events)


def test_cap_round_ledger_and_scene_cleanup(tmp_path):
    combat, table, mid = fixture(tmp_path)
    earn(combat, table, mid, 5)
    e = cold(tmp_path, combat, mid)
    owner = e.state.actors[OWNER]
    assert owner.resources[SPINE] == owner.resource_maximums[SPINE] == 4
    assert type(owner.turn_flags["_round_pool_gain:" + SPINE]) is int
    next_turn(combat, table, mid, OWNER)
    act(combat, table, mid, OWNER, "End scene", FOE)
    e = cold(tmp_path, combat, mid)
    assert e.state.terminal_result is not None
    assert e.state.actors[OWNER].resources[SPINE] == 0


@pytest.mark.parametrize("amount,expected", [(0, 0), (1, 1), (3, 1), (12, 8)])
def test_healing_reduces_each_positive_instance_once_with_minimum_one(tmp_path, amount, expected):
    combat, table, mid = fixture(tmp_path)
    earn(combat, table, mid, 3)
    e = cold(tmp_path, combat, mid)
    before = e.state.actors[OWNER].current_hp
    act(combat, table, mid, ALLY, "Heal " + str(amount), OWNER)
    e = cold(tmp_path, combat, mid)
    assert e.state.actors[OWNER].current_hp - before == min(expected, e.state.actors[OWNER].maximum_hp - before)


def test_own_healing_temporary_hp_and_real_multi_die_instance_remain_distinct(tmp_path):
    combat, table, mid = fixture(tmp_path)
    earn(combat, table, mid, 3)
    before = engine(combat, mid).state.actors[OWNER].current_hp
    act(combat, table, mid, OWNER, "Heal 3", OWNER)
    assert cold(tmp_path, combat, mid).state.actors[OWNER].current_hp == before + 3
    act(combat, table, mid, ALLY, "Temporary HP", OWNER)
    assert cold(tmp_path, combat, mid).state.actors[OWNER].temporary_hp == 12
    next_turn(combat, table, mid, ALLY)
    start = len(engine(combat, mid).events)
    before = engine(combat, mid).state.actors[OWNER].current_hp
    act(combat, table, mid, ALLY, "Rolled healing", OWNER)
    e = cold(tmp_path, combat, mid)
    heals = [ev for ev in e.events[start:] if ev.event_type == "HEALING_APPLIED"]
    assert len(heals) == 1
    rolled = next(r for r in reversed(e.rolls) if r.reason == "HEALING:" + heals[0].source_definition_id)
    assert heals[0].payload["offered"] == max(1, rolled.total - 4)
    assert e.state.actors[OWNER].current_hp - before == min(heals[0].payload["offered"], 300 - before)


def test_real_hit_optional_payment_type_save_and_first_missed_attack(tmp_path):
    combat, table, mid = fixture(tmp_path, owner_doc=sheet(owns=True, ac=1000))
    earn(combat, table, mid)
    turn(combat, table, mid, OWNER)
    before = engine(combat, mid).state.actors[OWNER].resources[SPINE]
    start = len(engine(combat, mid).events)
    prompts = hit(combat, table, mid)
    e = cold(tmp_path, combat, mid)
    assert e.state.actors[OWNER].resources[SPINE] == before - 1
    assert len([p for p in prompts if p["context"]["reaction_source_id"] == TYPE]) == 1
    assert {o["id"] for p in prompts if p["context"]["reaction_source_id"] == BASE_TYPE
            for o in p["choice"]["options"]} >= {"BLUDGEONING", "PIERCING", "SLASHING"}
    saves = [ev for ev in e.events[start:] if ev.event_type == "SAVE_ROLLED" and ev.source_definition_id == ARMORY]
    assert len(saves) == 1 and str(saves[0].payload["reason"]).upper().endswith(":CON")
    records = bleeding(e.state.actors[FOE])
    assert len(records) == 1 and records[0].source_actor_id == OWNER
    assert records[0].data["thorn_bleeding"]["damage_type"] == "SLASHING"
    before_hp = e.state.actors[FOE].current_hp
    turn(combat, table, mid, FOE)
    c = unarmed(combat, mid, OWNER)
    start = len(engine(combat, mid).events)
    settle(table, mid, c.candidate_id)
    e = cold(tmp_path, combat, mid)
    assert e.state.actors[FOE].current_hp == before_hp - 4
    assert not bleeding(e.state.actors[FOE])
    rows = e.events[start:]
    assert any(ev.event_type == "ATTACK_ROLLED" and ev.actor_id == FOE
               and ev.payload.get("provisional_hit") is False for ev in rows), [
        (ev.event_type, ev.payload) for ev in rows if ev.event_type.startswith("ATTACK")]
    assert not any(ev.event_type == "GM_RIDER" and ev.source_definition_id == ARMORY for ev in rows)


def test_decline_miss_no_funds_and_owner_start_expiry(tmp_path):
    combat, table, mid = fixture(tmp_path, foe_doc=sheet(ac=1000))
    turn(combat, table, mid, OWNER)
    prompts = settle(table, mid, unarmed(combat, mid).candidate_id)
    assert not any(p["context"]["reaction_source_id"] == SPEND for p in prompts)
    assert cold(tmp_path, combat, mid).state.actors[OWNER].resources[SPINE] == 0
    # A second native table with hittable target exercises an actual decline.
    combat, table, mid = fixture(tmp_path / "decline")
    earn(combat, table, mid)
    hit(combat, table, mid, decline=True)
    assert cold(tmp_path / "decline", combat, mid).state.actors[OWNER].resources[SPINE] == 1
    next_turn(combat, table, mid, OWNER)
    hit(combat, table, mid)
    assert bleeding(cold(tmp_path / "decline", combat, mid).state.actors[FOE])
    next_turn(combat, table, mid, OWNER)
    assert not bleeding(cold(tmp_path / "decline", combat, mid).state.actors[FOE])


def test_two_committed_five_foot_moves_deal_one_native_packet_after_movement(tmp_path):
    combat, table, mid = fixture(tmp_path)
    earn(combat, table, mid)
    hit(combat, table, mid)
    turn(combat, table, mid, FOE)
    before = engine(combat, mid).state.actors[FOE].current_hp
    for x in (5, 6):
        c = next(c for c in engine(combat, mid).legal_candidates()
                 if c.kind == "MOVE" and c.destination.x == x and c.destination.y == 4 and c.destination.z == 0)
        settle(table, mid, c.candidate_id)
        e = cold(tmp_path, combat, mid)
        if x == 5:
            assert e.state.actors[FOE].current_hp == before
            assert bleeding(e.state.actors[FOE])[0].data["thorn_bleeding"]["moved_ft"] == 5
    assert e.state.actors[FOE].current_hp == before - 4
    assert not bleeding(e.state.actors[FOE])
    packet = next(ev for ev in reversed(e.events) if ev.event_type == "DAMAGE_COMMITTED" and ev.source_definition_id == ARMORY)
    move = next(ev for ev in reversed(e.events) if ev.event_type == "MOVEMENT_COMMITTED" and ev.actor_id == FOE)
    assert packet.sequence > move.sequence
    assert not any(ev.event_type == "GM_RIDER" and ev.source_definition_id == ARMORY for ev in e.events)


def test_forced_movement_does_not_trigger_and_record_expires(tmp_path):
    combat, table, mid = fixture(tmp_path)
    earn(combat, table, mid)
    hit(combat, table, mid)
    before = engine(combat, mid).state.actors[FOE].current_hp
    act(combat, table, mid, ALLY, "Push", FOE)
    e = cold(tmp_path, combat, mid)
    assert e.state.actors[FOE].current_hp == before
    assert bleeding(e.state.actors[FOE])[0].data["thorn_bleeding"]["moved_ft"] == 0


def test_body_profile_cannot_borrow_qi_level_or_save_dc(tmp_path):
    doc = sheet(owns=True, cl=18, path="Qi Cultivation")
    doc["path_and_subpath"]["paths"] = [{"path_id": BODY, "attainment": 3, "effective_cl": 3,
        "key_ability": "CON", "proficiency_bonus": 2}]
    combat, table, mid = fixture(tmp_path, owner_doc=doc)
    earn(combat, table, mid, 3)
    e = cold(tmp_path, combat, mid)
    assert e.state.actors[OWNER].resource_maximums[SPINE] == 2
    assert e.state.actors[OWNER].resources[SPINE] == 2
    assert next(r["numbers"] for r in e.typed_passive_rows[OWNER] if r.get("block") == "black_thorn_profile") == {
        "pb": 2, "cl": 3, "key_mod": 2, "con_mod": 2, "attack_bonus": 4, "save_dc": 12}


def test_paid_hit_uses_native_critical_dice_and_only_one_save(tmp_path):
    combat, table, mid = fixture(tmp_path)
    earn(combat, table, mid, 2)
    next_turn(combat, table, mid, FOE)
    act(combat, table, mid, FOE, "Be paralyzed")
    turn(combat, table, mid, OWNER)
    assert any(c.condition_id == "condition:typed.paralyzed" for c in engine(combat, mid).state.actors[FOE].conditions.values())
    start = len(engine(combat, mid).rolls)
    event_start = len(engine(combat, mid).events)
    hit(combat, table, mid)
    e = cold(tmp_path, combat, mid)
    expressions = [r.expression for r in e.rolls[start:] if str(r.reason).startswith("DAMAGE")]
    assert any(s.startswith("4d6") for s in expressions), expressions
    assert len([ev for ev in e.events[event_start:] if ev.event_type == "SAVE_ROLLED" and ev.source_definition_id == ARMORY]) == 1
    assert len([ev for ev in e.events[event_start:] if ev.event_type == "RESOURCE_SPENT"
                and ev.payload.get("resource_id") == SPINE]) == 1


def test_ordinary_bleeding_immunity_uses_actual_crown_source(tmp_path):
    crown = PARENT + ".feature.crown_of_black_thorns"
    combat, table, mid = fixture(tmp_path, foe_doc=sheet(cl=14, features=[crown]))
    earn(combat, table, mid)
    hit(combat, table, mid)
    e = cold(tmp_path, combat, mid)
    from combat.typed_executor import condition_immune
    assert condition_immune(e, e.state.actors[FOE], "bleeding")
    assert len(bleeding(e.state.actors[FOE])) == 1


def test_suppressed_bleeding_does_not_consume_or_damage_on_attack(tmp_path):
    combat, table, mid = fixture(tmp_path)
    earn(combat, table, mid)
    hit(combat, table, mid)
    turn(combat, table, mid, FOE)
    act(combat, table, mid, FOE, "Suppress bleeding")
    e = cold(tmp_path, combat, mid)
    assert not bleeding(e.state.actors[FOE])
    before = e.state.actors[FOE].current_hp
    settle(table, mid, unarmed(combat, mid, OWNER).candidate_id)
    e = cold(tmp_path, combat, mid)
    assert e.state.actors[FOE].current_hp == before


def test_teleporting_and_standing_never_count_as_willing_distance(tmp_path):
    combat, table, mid = fixture(tmp_path)
    earn(combat, table, mid)
    hit(combat, table, mid)
    turn(combat, table, mid, FOE)
    before = engine(combat, mid).state.actors[FOE].current_hp
    standing_start = len(engine(combat, mid).events)
    act(combat, table, mid, FOE, "Lie prone")
    e = engine(combat, mid)
    stands = [c for c in e.legal_candidates() if c.source_definition_id == "system:combat.stand_up"]
    if stands:
        settle(table, mid, stands[0].candidate_id)
    e = engine(combat, mid)
    assert any(ev.event_type == "STOOD_UP" and ev.actor_id == FOE for ev in e.events[standing_start:]), {
        "life_state": e.state.actors[FOE].life_state, "movement": e.state.actors[FOE].movement_remaining_ft,
        "conditions": [(c.condition_id, c.expires_on) for c in e.state.actors[FOE].conditions.values()],
        "events": [(ev.event_type, ev.source_definition_id) for ev in e.events[-10:]]}
    assert bleeding(cold(tmp_path, combat, mid).state.actors[FOE])[0].data["thorn_bleeding"]["moved_ft"] == 0
    act(combat, table, mid, FOE, "Teleport")
    e = cold(tmp_path, combat, mid)
    assert e.state.actors[FOE].current_hp == before
    assert bleeding(e.state.actors[FOE])[0].data["thorn_bleeding"]["moved_ft"] == 0


def test_involuntary_fall_does_not_complete_ten_feet_of_willing_movement(tmp_path):
    flight = "tianxia.subpath.body.sky_treading_tendon_school.feature.body_crosses_heaven"
    combat, table, mid = fixture(tmp_path, foe_doc=sheet(features=[flight]))
    earn(combat, table, mid)
    hit(combat, table, mid)
    turn(combat, table, mid, FOE)
    c = next(c for c in engine(combat, mid).legal_candidates()
             if c.kind == "MOVE" and (c.destination.x, c.destination.y, c.destination.z) == (4, 4, 1))
    settle(table, mid, c.candidate_id)
    e = cold(tmp_path, combat, mid)
    assert bleeding(e.state.actors[FOE])[0].data["thorn_bleeding"]["moved_ft"] == 5
    before = e.state.actors[FOE].current_hp
    act(combat, table, mid, FOE, "Be unconscious")
    e = cold(tmp_path, combat, mid)
    assert e.state.actors[FOE].position.z == 0
    assert e.state.actors[FOE].current_hp == before
    assert bleeding(e.state.actors[FOE])[0].data["thorn_bleeding"]["moved_ft"] == 5


def test_repeated_real_hits_have_one_paid_rider_per_turn(tmp_path):
    extra_attack = "tianxia.path.body_refining.feature.extra_attack"
    iron_fist = "tianxia.path.body_refining.feature.iron_fist"
    combat, table, mid = fixture(tmp_path, owner_doc=sheet(owns=True, features=[iron_fist, extra_attack]))
    earn(combat, table, mid, 3)
    turn(combat, table, mid, OWNER)
    c = unarmed(combat, mid)
    attacks = engine(combat, mid).action_catalog[c.source_definition_id].parameters["typed"]["effects"]
    assert next(row for row in attacks if row.get("type") == "attack").get("count", 1) == 2
    start = len(engine(combat, mid).events)
    prompts = hit(combat, table, mid)
    e = cold(tmp_path, combat, mid)
    assert len([p for p in prompts if p["context"]["reaction_source_id"] == SPEND]) == 1
    assert len([ev for ev in e.events[start:] if ev.event_type == "RESOURCE_SPENT" and ev.payload.get("resource_id") == SPINE]) == 1
    assert len(bleeding(e.state.actors[FOE])) == 1


@pytest.mark.parametrize("name", ["Grapple", "Shove: Prone", "Shove: Push 5 ft"])
def test_real_saving_throw_unarmed_attack_consumes_bleeding_after_completion(tmp_path, name):
    combat, table, mid = fixture(tmp_path, foe_doc=sheet(cl=3))
    earn(combat, table, mid)
    hit(combat, table, mid)
    turn(combat, table, mid, FOE)
    before = engine(combat, mid).state.actors[FOE].current_hp
    start = len(engine(combat, mid).events)
    act(combat, table, mid, FOE, name, OWNER)
    e = cold(tmp_path, combat, mid)
    rows = e.events[start:]
    saves = [ev for ev in rows if ev.event_type == "SAVE_ROLLED"]
    packets = [ev for ev in rows if ev.event_type == "DAMAGE_COMMITTED" and ev.source_definition_id == ARMORY]
    assert saves and len(packets) == 1 and packets[0].sequence > saves[-1].sequence
    assert not any(ev.event_type == "ATTACK_ROLLED" and ev.actor_id == FOE for ev in rows)
    assert e.state.actors[FOE].current_hp == before - 4
    assert not bleeding(e.state.actors[FOE])


def test_real_object_attack_consumes_bleeding_even_without_creature_attack_hook(tmp_path):
    combat, table, mid = fixture(tmp_path, foe_doc=sheet(cl=3),
        objects=[{"id": 1, "kind": "door", "x": 5, "y": 4,
                  "material": "wood", "size": "medium", "resilient": True, "ac": 10, "hp": 30,
                  "blocks": False}])
    earn(combat, table, mid)
    hit(combat, table, mid)
    turn(combat, table, mid, FOE)
    e = engine(combat, mid)
    door = next(o for o in e.state.objects.values() if (o.position.x, o.position.y) == (5, 4))
    candidates = [c for c in e.legal_candidates() if door.object_id in c.target_ids
                  and e.action_catalog[c.source_definition_id].parameters.get("object_attack")]
    assert candidates, {"object": door.model_dump(mode="json"),
        "actor": e.state.current_actor_id,
        "object_actions": [(a.source_definition_id, a.range_ft) for a in e.action_catalog.values()
                           if a.owner_id == FOE and a.parameters.get("object_attack")],
        "candidates": [(c.display_name, c.target_ids) for c in e.legal_candidates()]}
    c = candidates[0]
    before = e.state.actors[FOE].current_hp
    start = len(e.events)
    settle(table, mid, c.candidate_id)
    e = cold(tmp_path, combat, mid)
    rows = e.events[start:]
    assert any(ev.event_type == "ATTACK_ROLLED" and ev.payload.get("object_id") == door.object_id for ev in rows)
    assert e.state.actors[FOE].current_hp == before - 4
    assert not bleeding(e.state.actors[FOE])


@pytest.mark.parametrize("first_five_feet", [False, True])
def test_off_turn_hit_can_pay_once_and_refreshes_one_source_record(tmp_path, first_five_feet):
    combat, table, mid = fixture(tmp_path)
    earn(combat, table, mid, 2)
    hit(combat, table, mid, damage="slashing")
    e = cold(tmp_path, combat, mid)
    old = bleeding(e.state.actors[FOE])[0].instance_id
    turn(combat, table, mid, FOE)
    if first_five_feet:
        step = next(c for c in engine(combat, mid).legal_candidates()
                    if c.kind == "MOVE" and (c.destination.x, c.destination.y, c.destination.z) == (4, 5, 0))
        settle(table, mid, step.candidate_id)
        assert bleeding(cold(tmp_path, combat, mid).state.actors[FOE])[0].data["thorn_bleeding"]["moved_ft"] == 5
    destination = (5, 5, 0) if first_five_feet else (5, 4, 0)
    start = len(engine(combat, mid).events)
    move = next(c for c in engine(combat, mid).legal_candidates()
                if c.kind == "MOVE" and (c.destination.x, c.destination.y, c.destination.z) == destination)
    prompts = settle(table, mid, move.candidate_id,
                     {"accept_opportunity": True, SPEND: ["spend"], TYPE: ["piercing"], BASE_TYPE: ["SLASHING"]})
    assert any(p["context"]["reaction_source_id"] == SPEND and p["context"]["reactor_id"] == OWNER for p in prompts)
    e = cold(tmp_path, combat, mid)
    held = bleeding(e.state.actors[FOE])
    if first_five_feet:
        assert not held
        paid_packets = [ev for ev in e.events[start:] if ev.event_type == "DAMAGE_COMMITTED"
                        and ev.source_definition_id == ARMORY]
        assert len(paid_packets) == 2  # Paid hit, then one delayed PB packet after the second step.
        assert paid_packets[-1].payload["hp_damage"] == 4
    else:
        assert len(held) == 1 and held[0].instance_id != old and held[0].source_actor_id == OWNER
        assert held[0].data["thorn_bleeding"] == {"pb": 4, "damage_type": "PIERCING", "moved_ft": 5}
    assert e.state.actors[OWNER].resources[SPINE] == 0


def auto_settle(table, mid, choices):
    answers, prompts = [], []
    for _ in range(30):
        reply = table.auto_step(mid, 0, answers)
        if reply["status"] != "REACTION_REQUIRED":
            assert reply["status"] == "COMMITTED", reply
            return prompts
        prompt = reply["reaction"]
        prompts.append(prompt)
        source = prompt["context"]["reaction_source_id"]
        spec = prompt.get("choice") or {}
        value = choices.get(source)
        if "counter_palm" in source.lower():
            value = []
        elif source not in choices and spec.get("options"):
            minimum = int(spec.get("minimum_selections", spec.get("minimum", 1)))
            if minimum:
                value = [o["id"] for o in spec["options"]][:minimum]
        answers.append({**prompt["context"], "selection": "USE" if value is not None else "DECLINE",
                        "option_ids": value or []})
    raise AssertionError("Too many automatic-turn choices")


def test_manual_owner_gets_paid_hit_choice_on_actual_ai_turn(tmp_path):
    doc = sheet(owns=True, ac=14, features=["tianxia.path.body_refining.feature.iron_fist"])
    # Give the AI a useful damaging attack, with real hit/miss outcomes, rather
    # than an easier Grapple/Shove. An unreachable AC makes it prefer defense.
    doc["ability_scores_and_statistics"]["saving_throws"] = {"STR": 1000, "DEX": 1000}
    doc["spheres_and_talents"]["learned_talent_record_ids"] = ["TAL_IRON_FIST_COUNTER_PALM"]
    foe_doc = sheet(ac=1)  # Keep the actual Counter Palm hit, not its accuracy, under test.
    foe_doc["identity"]["size"] = "Tiny"  # Its observed size forbids Grapple/Shove against a Medium target.
    combat, table, mid = fixture(tmp_path, owner_doc=doc, foe_doc=foe_doc, ally_position={"x": 12, "y": 10})
    earn(combat, table, mid, 2)
    next_turn(combat, table, mid, OWNER)
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode="LOCAL_AUTO")
    prompts = []
    start = len(engine(combat, mid).events)
    for _ in range(18):
        if engine(combat, mid).state.current_actor_id == FOE:
            prompts += auto_settle(table, mid, {SPEND: ["spend"], TYPE: ["piercing"], BASE_TYPE: ["PIERCING"]})
        else:
            settle(table, mid, table.state(mid)["menu"]["end_turn"])
        if any(p["context"]["reaction_source_id"] == SPEND for p in prompts):
            break
    assert any(p["context"]["reaction_source_id"] == SPEND and p["context"]["reactor_id"] == OWNER for p in prompts), {
        "prompts": [p["context"]["reaction_source_id"] for p in prompts],
        "spines": engine(combat, mid).state.actors[OWNER].resources[SPINE],
        "owner_attacks": [ev.payload for ev in engine(combat, mid).events[start:]
                          if ev.event_type == "ATTACK_ROLLED" and ev.actor_id == OWNER],
        "events": [(ev.event_type, ev.source_definition_id) for ev in engine(combat, mid).events[start:]]}
    e = cold(tmp_path, combat, mid)
    assert any(ev.event_type == "RESOURCE_SPENT" and ev.actor_id == OWNER
               and ev.payload.get("resource_id") == SPINE for ev in e.events[start:])


def test_automatic_owner_resolves_its_choices_without_human_prompts(tmp_path):
    combat, table, mid = fixture(tmp_path)
    earn(combat, table, mid, 2)
    turn(combat, table, mid, OWNER)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    start = len(engine(combat, mid).events)
    prompts = auto_settle(table, mid, {})
    assert not any(p["context"]["reactor_id"] == OWNER for p in prompts)
    e = cold(tmp_path, combat, mid)
    assert any(ev.event_type == "RESOURCE_SPENT" and ev.actor_id == OWNER
               and ev.payload.get("resource_id") == SPINE for ev in e.events[start:])


def test_hit_choice_previews_do_not_consume_spines_hp_or_roll_state(tmp_path):
    combat, table, mid = fixture(tmp_path)
    earn(combat, table, mid)
    prompts = hit(combat, table, mid, audit_engine=lambda: engine(combat, mid))
    assert any(p["context"]["reaction_source_id"] == SPEND for p in prompts)
    assert any(p["context"]["reaction_source_id"] == TYPE for p in prompts)
    assert cold(tmp_path, combat, mid).state.actors[OWNER].resources[SPINE] == 0
