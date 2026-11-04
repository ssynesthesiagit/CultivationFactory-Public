"""Destruction object payloads and refinement choices through committed table intents."""
import pytest

from tests.auto_worker1_support import LEFT, RIGHT, act, fight, settle, turn
from tests.test_a2_destruction_service import verify

P = "tianxia.talent.destruction."
BASE = "TAL_DESTRUCTION_DESTRUCTIVE_BLAST"
SPHERE = "tianxia.sphere.destruction"
OBJ = "object:map.600"


def arena(doc):
    doc["map_objects"] = [{"id": 600, "kind": "crate", "x": 3, "y": 7,
                           "hp": 500, "ac": 1, "material": "wood", "structure": True}]


def object_send(t, m, label="Destructive Blast (at an object)"):
    return lambda answers: act(t, m, label, answers, target_id=OBJ)


def damage(e):
    return [v for v in e.events if v.event_type == "OBJECT_UPDATED"
            and v.target_ids == (OBJ,) and "damage" in v.payload]


@pytest.mark.parametrize("breaching", [False, True])
def test_blast_object_hit_uses_selected_dice_and_breaching_proof(tmp_path, breaching):
    c,t,m = fight(tmp_path, [BASE] + ([P+"breaching_proof"] if breaching else []),
        spheres=[SPHERE], cl=5, left_attack_bonus=100, arena_edit=arena)
    settle(object_send(t,m))
    e = verify(c,m)
    hit = next(v for v in e.events if v.event_type == "ATTACK_ROLLED" and v.target_ids == (OBJ,))
    rolls = [r for r in e.rolls if str(r.reason).startswith("DAMAGE:") and "DESTRUCTIVE_BLAST" in r.reason]
    assert len(rolls) == 1
    assert len(rolls[0].dice) == (2 + int(breaching)) * (2 if hit.payload["natural_result"] == 20 else 1)
    assert damage(e)[-1].payload["damage"]["taken"] == rolls[0].total
    assert e.state.objects[OBJ].current_hp == 500 - rolls[0].total


@pytest.mark.parametrize("kind,consume", [("FIRE", False), ("BLUDGEONING", True), ("THUNDER", True), ("FORCE", True)])
def test_fracturing_mark_survives_reload_and_only_next_eligible_damage_consumes(tmp_path, kind, consume):
    c,t,m = fight(tmp_path, [BASE,P+"fracturing_break"], spheres=[SPHERE], cl=1,
        left_attack_bonus=100, arena_edit=arena,
        extra_actions=[("Probe", {"target_kind": "OBJECT",
            "effects": [{"type":"object_damage", "flat":10, "damage_types":[kind]}]})])
    settle(lambda a: act(t,m,"Blast Type: Fracturing Break",a))
    settle(object_send(t,m))
    before = verify(c,m)
    marks = before.state.objects[OBJ].component.get("damage_marks", {})
    assert len(marks) == 1
    mark = next(iter(marks.values()))
    assert mark["owner"] == LEFT and mark["sides"] == 8 and mark["count"] == 1
    settle(object_send(t,m,"Probe"))
    e = verify(c,m)
    assert bool(e.state.objects[OBJ].component.get("damage_marks")) != consume
    taken = damage(e)[-1].payload["damage"]["taken"]
    assert (10 < taken <= 18) if consume else taken == 10
    settle(object_send(t,m,"Probe"))
    e2 = verify(c,m)
    assert damage(e2)[-1].payload["damage"]["taken"] == 10


def test_fracturing_mark_expires_on_source_next_turn(tmp_path):
    c,t,m = fight(tmp_path,[BASE,P+"fracturing_break"],spheres=[SPHERE],cl=1,
        left_attack_bonus=100,arena_edit=arena)
    settle(lambda a:act(t,m,"Blast Type: Fracturing Break",a))
    settle(object_send(t,m))
    assert verify(c,m).state.objects[OBJ].component["damage_marks"]
    settle(lambda a:act(t,m,"end",a));turn(t,m,LEFT)
    assert not verify(c,m).state.objects[OBJ].component.get("damage_marks")


@pytest.mark.parametrize("blocked", ["miss", "immune", "threshold"])
def test_no_object_damage_means_no_fracturing_mark(tmp_path, blocked):
    def objects(doc):
        arena(doc)
        row=doc["map_objects"][0]
        if blocked=="immune":row["immune"]=["FORCE"]
        if blocked=="threshold":row["threshold"]=999
        if blocked=="miss":row["ac"]=999
    c,t,m=fight(tmp_path,[BASE,P+"fracturing_break"],spheres=[SPHERE],cl=1,
        left_attack_bonus=100,arena_edit=objects)
    settle(lambda a:act(t,m,"Blast Type: Fracturing Break",a))
    settle(object_send(t,m))
    e=verify(c,m)
    assert not e.state.objects[OBJ].component.get("damage_marks")
    assert e.state.objects[OBJ].current_hp==500


@pytest.mark.parametrize("talent", ["breaching_proof","fracturing_break","break_the_guard","hammer_through_the_line"])
def test_reviewed_records_have_no_unresolved_top_level_riders(talent):
    import json
    from tests.h1_support import ROOT
    authority=json.loads((ROOT/"authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())
    assert authority["mechanics"][P+talent]["riders"]==[]


def test_effect_owned_object_payload_is_not_specific_to_destruction(tmp_path):
    c,t,m=fight(tmp_path,arena_edit=arena,extra_actions=[("Delegated", {
        "target_kind":"OBJECT", "effects":[
            {"type":"condition","condition":"payload_prepared","applies_to":"self"},
            {"type":"attack","object_target":"any", "object_before_effects":["condition"],
             "object_on_hit_effects":["object_damage"],
             "on_hit":[{"type":"object_damage","flat":9,"damage_types":["FIRE"]}]}]})],
        bundle_edit=lambda b: [a["parameters"]["typed"]["numbers"].update(attack_bonus=100)
            for a in b["action_catalog"] if a["display_name"]=="Delegated"])
    settle(object_send(t,m,"Delegated"))
    e=verify(c,m)
    assert damage(e)[-1].payload["damage"]["taken"]==9
    assert any(v.condition_id.endswith("payload_prepared") for v in e.state.actors[LEFT].conditions.values())


def test_breaching_destroyed_barrier_opens_its_square(tmp_path):
    def wall(doc):
        arena(doc)
        doc["map_objects"][0].update(hp=1,blocks=True)
    c,t,m=fight(tmp_path,[BASE,P+"breaching_proof"],spheres=[SPHERE],
        left_attack_bonus=100,arena_edit=wall)
    settle(object_send(t,m))
    e=verify(c,m)
    assert e.state.objects[OBJ].destroyed
    assert (3,7) not in e.grid.blocked


def test_deepened_object_blast_pays_one_cp_and_rolls_the_deepened_dice(tmp_path):
    # Deepen the Calamity is paid once per activation where a plain Destructive Blast pays it, and an object blast uses the
    # same Deepened dice count (1 + 1 per 2 Cultivation Levels; CL 5 -> 3 dice, against the ordinary 2) as a creature blast.
    c,t,m=fight(tmp_path,[BASE],spheres=[SPHERE],cl=5,left_attack_bonus=100,arena_edit=arena)
    settle(lambda a:act(t,m,"Deepen the Calamity: more dice (1 CP a blast: 1 + 1 per 2 Cultivation Levels)",a))
    settle(object_send(t,m))
    e=verify(c,m)
    assert e.state.actors[LEFT].resources["resource:core.qi"]==99
    rolls=[r for r in e.rolls if str(r.reason).startswith("DAMAGE:") and "DESTRUCTIVE_BLAST" in r.reason]
    assert len(rolls)==1 and len(rolls[0].dice)==3
    assert damage(e)[-1].payload["damage"]["taken"]==rolls[0].total


@pytest.mark.parametrize("option", ["ac","advantage","cover"])
def test_break_the_guard_choice_is_asked_after_failure_not_fixed_by_old_setting(tmp_path, option):
    from combat.ext.destruction_blast import GUARD_ACTIVE
    c,t,m=fight(tmp_path,[BASE,P+"fracturing_break",P+"break_the_guard"],spheres=[SPHERE],left_attack_bonus=100)
    settle(lambda a:act(t,m,"Blast Type: Fracturing Break",a))
    def choose(prompt):
        if prompt["context"]["reaction_source_id"]=="choice:needle.destruction_guard":return [option]
        return [o["id"] for o in prompt.get("choice",{}).get("options",[])][:1]
    _,prompts=settle(lambda a:act(t,m,"Destructive Blast",a,target_id=RIGHT),choose)
    e=verify(c,m)
    assert any(p["context"]["reaction_source_id"]=="choice:needle.destruction_guard" for p in prompts)
    active=next(c for c in e.state.actors[RIGHT].conditions.values() if c.condition_id==GUARD_ACTIVE)
    assert active.data["option"]==option
    settle(lambda a:act(t,m,"end",a));turn(t,m,LEFT)
    assert not any(c.condition_id==GUARD_ACTIVE for c in verify(c,m).state.actors[RIGHT].conditions.values())


def test_tether_pulse_keeps_the_frozen_crushing_type_after_live_choice_changes(tmp_path):
    c,t,m=fight(tmp_path,[P+"ruin_binding_tether",P+"crushing_break",P+"fracturing_break",P+"hammer_through_the_line"],
        spheres=[SPHERE],left_attack_bonus=100,positions={LEFT:{"x":7,"y":6},RIGHT:{"x":8,"y":6}})
    settle(lambda a:act(t,m,"Blast Type: Crushing Break",a))
    settle(lambda a:act(t,m,"Ruin-Binding Tether",a,target_id=RIGHT))
    before=verify(c,m)
    settle(lambda a:act(t,m,"Blast Type: Fracturing Break",a))
    settle(lambda a:act(t,m,"Ruin-Binding Tether: Pulse",a,target_id=RIGHT))
    e=verify(c,m)
    hits=[v for v in e.events[len(before.events):] if v.event_type=="DAMAGE_COMMITTED" and RIGHT in v.target_ids]
    assert hits and all(v.payload["damage_type"]=="BLUDGEONING" for v in hits)


def test_same_guard_option_from_another_release_refreshes_instead_of_stacking(tmp_path):
    def reliable(bundle):
        for action in bundle["action_catalog"]:
            if action["display_name"]=="Follow-up blast":
                action["parameters"]["typed"]["numbers"]["attack_bonus"]=100
    c,t,m=fight(tmp_path,[BASE,P+"scouring_break",P+"break_the_guard"],spheres=[SPHERE],
        left_attack_bonus=100,bundle_edit=reliable,
        extra_actions=[("Follow-up blast",{"target_kind":"HOSTILE_ENTITY","effects":[
            {"type":"attack","attack_kind":"cultivation","on_hit":[{"type":"destructive_blast_damage","damage_required":True}]}]})])
    settle(lambda a:act(t,m,"Blast Type: Scouring Break",a))
    settle(lambda a:act(t,m,"Destructive Blast",a,target_id=RIGHT))
    settle(lambda a:act(t,m,"Follow-up blast",a,target_id=RIGHT))
    e=verify(c,m)
    penalties=[v for v in e.state.actors[RIGHT].modifiers.values()
               if v.target_field=="armor_class" and v.value==-1]
    assert len(penalties)==1
    assert penalties[0].source_actor_id==LEFT
