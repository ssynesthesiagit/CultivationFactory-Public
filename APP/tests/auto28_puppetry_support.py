"""Table-turn and three-fighter fixtures shared by the AUTO28 Puppetry regressions.

Ported from cloud worker 1's AUTO28 lane. The two helpers live in that lane's
``test_auto42_stars`` and ``test_auto62_destruction`` modules, which are Stars /
Destruction tests and are not part of this branch; keeping the few lines here
avoids importing another Sphere's whole test file. ``resolve`` drives a table
transaction to its committed answer (a fight that is waiting on a choice is
rolled back, so tests assert the state after the answer); ``turn`` advances the
table until the named actor is on move; ``triple_fight`` seals three independent
portable sheets before the match exists.
"""
from tests.hunt15_support import LEFT, RIGHT, act

OTHER = "actor:factory.h15-other"


def resolve(send, picks=None):
    answers, prompts = [], []
    for _ in range(12):
        result = send(answers)
        if result["status"] != "REACTION_REQUIRED":
            assert result["status"] == "COMMITTED", result
            return result, prompts
        p = result["reaction"]
        prompts.append(p)
        ids = [o["id"] for o in (p.get("choice") or {}).get("options", [])]
        chosen = (picks or {}).get(p["context"]["reaction_source_id"], ids[:1])
        answers.append({**p["context"], "selection": "USE" if chosen or not p.get("choice") else "DECLINE",
                        "option_ids": chosen})
    raise AssertionError("too many choices")


def turn(table, mid, actor_id):
    for _ in range(4):
        if table.state(mid)["menu"]["actor_id"] == actor_id:
            return
        resolve(lambda answers: act(table, mid, "end", answers))
    raise AssertionError("turn did not advance")


def cell_send(table, mid, label, xy):
    def send(answers):
        state = table.state(mid)
        menu = state["menu"]
        cid = next(o["candidate_id"] for g in menu["actions"] if g["label"] == label for o in g["options"]
                   if o.get("destination") == {"x": xy[0], "y": xy[1]})
        return table.act(mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"], answers)
    return send


def triple_fight(tmp_path, talents, *, spheres=(), cause_stun=False, third_ally=False,
                 left_score=14, bundle_edit=None):
    """Three independently compiled sheets, sealed before constructing the table."""
    import json, zipfile
    from combat.canonical import canonical_sha256
    from combat.factory_compiler import compile_character
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT, sheet
    from tests.test_carry import KIT
    bundles = []
    for aid, owned in [(LEFT, talents), (RIGHT, []), (OTHER, [])]:
        doc = sheet(list(owned), cl=15, dc=100, kit={"starting_kit": KIT},
                    score=left_score if aid == LEFT else 14)
        doc["identity"]["display_name"] = {LEFT: "Keeper", RIGHT: "Visitor", OTHER: "Second visitor"}[aid]
        doc.setdefault("spheres_and_talents", {})["sphere_record_ids"] = list(spheres)
        doc["spheres_and_talents"]["automatic_sphere_component_record_ids"] = []
        stats = doc["ability_scores_and_statistics"]
        stats["technique_attack_bonus"] = 100
        stats["primary_resource"]["maximum"] = 100
        stats["hit_points"]["maximum"] = 1000
        folder = tmp_path / "portable_characters" / aid.removeprefix("actor:factory.")
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as z:
            z.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
        b = compile_character(doc, actor_id=aid, reaction_plan={"ask": True})
        if cause_stun and aid == RIGHT:
            sid = "action:test.tether_stun"
            b["actor_template"]["action_ids"].append(sid)
            b["action_catalog"].append(dict(source_definition_id=sid, display_name="Cause", owner_id=aid,
                economy="NONE", resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=60, costs=[],
                parameters={"typed": {"effects": [{"type": "condition", "condition": "stunned", "applies_to": "target"}],
                "numbers": {}, "duration": {"kind": "instant"}, "riders": []}}))
        if bundle_edit is not None:
            bundle_edit(b)
        b.pop("bundle_sha256", None)
        b["bundle_sha256"] = canonical_sha256(b)
        bundles.append(b)
    c = CombatService(ROOT, tmp_path)
    m = c._finish_factory_match(bundles, [LEFT, RIGHT, OTHER],
                                {LEFT: "team:a", RIGHT: "team:b", OTHER: "team:a" if third_ally else "team:b"},
                                {LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 4, "y": 6},
                                 OTHER: {"x": 3 if third_ally else 4, "y": 5}},
                                c.factory_arenas()["battlefield:factory_pillar_arena"],
                                [LEFT, OTHER] if third_ally else [LEFT],
                                [RIGHT] if third_ally else [RIGHT, OTHER],
                                control_modes={a: "MANUAL" for a in [LEFT, RIGHT, OTHER]}, match_seed="worker1",
                                display_name="Puppetry regression", maximum_rounds=10)["match_id"]
    t = TabletopService(c, tmp_path)
    turn(t, m, LEFT)
    return c, t, m