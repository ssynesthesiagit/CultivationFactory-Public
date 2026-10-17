"""Synthetic table fixtures for worker 1; all setup effects commit through the service.

No retained owner data or mutation of a running/sealed engine is used. A small
test action supplies prerequisites; the ability under test comes from authority.

Shared table helpers (`resolve`, `cell_send`, `ascend`, `triple_fight`, `OTHER`)
live here because several sphere regression files need the same three: answering a
run of questions through the real table, picking a named destination cell, making
one flight move, and a three-creature duel with a named third actor.
"""
import json
import zipfile

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.hunt15_support import act, reload, action_sender
from tests.hunt15_support import LEFT, RIGHT, ALLY
from tests.test_carry import KIT


def fight(tmp_path, talents=(), *, prepare=(), cause=(), right_talents=(),
          prepare_target="HOSTILE_ENTITY", cause_target="HOSTILE_ENTITY", cl=15, left_kit=None, positions=None,
          left_score=14, right_score=14, spheres=(), maximum_rounds=10, prepare_source=None, prepare_sphere=None,
          left_attack_bonus=8, cause_name='Cause', left_save_dc=100, prepare_costs=(), prepare_attack_bonus=None,
          prepare_zone_spec=None, bundle_edit=None, right_spheres=(), left_resource="Qi", arena_edit=None,
          right_kit=None, right_team="team:opponents", extra_witness=False, witness_position=None,
          witness_team="team:opponents", map_terrain=None, ally=None,
          cause_save_dc=100, left_pb=4, right_pb=None, reaction_options=None, extra_actions=(), sheet_edit=None,
          ally_team="team:factory", reaction_ask=True):
    right_pb = left_pb if right_pb is None else right_pb
    bundles = []
    for aid, owned, label, effects, target in (
        (LEFT, talents, "Prepare", prepare, prepare_target),
        (RIGHT, right_talents, cause_name, cause, cause_target),
    ) + (((ALLY, (), "Ally", (), "HOSTILE_ENTITY"),) if ally is not None else ()):
        kit = left_kit if aid == LEFT else right_kit
        if kit is None:
            kit = KIT
        doc = sheet(list(owned), cl=cl, dc=left_save_dc if aid == LEFT else 100, kit={"starting_kit": kit},
                    score=left_score if aid == LEFT else right_score)
        doc.setdefault("spheres_and_talents", {})
        pb = left_pb if aid == LEFT else right_pb
        doc["identity"]["proficiency_bonus"] = pb
        doc["spheres_and_talents"]["sphere_record_ids"] = list(spheres if aid == LEFT else right_spheres)
        doc["spheres_and_talents"]["automatic_sphere_component_record_ids"] = []
        stats = doc["ability_scores_and_statistics"]
        if aid == LEFT:
            stats["technique_attack_bonus"] = left_attack_bonus
        stats["primary_resource"]["maximum"] = 100
        if aid == LEFT:
            stats["primary_resource"]["name"] = left_resource
        stats["hit_points"]["maximum"] = 1000
        stats["armor_class"]["base_value"] = 1
        if sheet_edit is not None:
            sheet_edit(doc, aid)
        doc["identity"]["display_name"] = "Keeper" if aid == LEFT else "Visitor"
        folder = tmp_path / "portable_characters" / aid.removeprefix("actor:factory.")
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
        bundle = compile_character(doc, actor_id=aid, reaction_plan={"ask": reaction_ask, **({"options": reaction_options} if reaction_options else {})})
        if effects:
            action_id = "action:test.worker1." + aid
            bundle["actor_template"]["action_ids"].append(action_id)
            bundle["action_catalog"].append({
                "source_definition_id": action_id, "display_name": label, "owner_id": aid,
                "economy": "NONE", "resolution_kind": "TYPED", "target_kind": target,
                "range_ft": 60, "costs": list(prepare_costs) if aid == LEFT else [],
                # These synthetic setup actions intentionally repeat without
                # spending turn economy. NONE alone is not primary permission;
                # use the same explicit free-action contract as real builders.
                "parameters": {"free_primary": True, "typed": {"effects": list(effects),
                    **({"source": prepare_source} if aid == LEFT and prepare_source else {}),
                    **({"sphere": prepare_sphere} if aid == LEFT and prepare_sphere else {}),
                    **({"zone_spec": prepare_zone_spec} if aid == LEFT and prepare_zone_spec is not None else {}),
                    "numbers": {"cl": cl, "pb": pb, "key_mod": 3, "save_dc": left_save_dc if aid == LEFT else cause_save_dc,
                                **({"attack_bonus": prepare_attack_bonus}
                                   if aid == LEFT and prepare_attack_bonus is not None else {})},
                    "duration": {"kind": "instant"}, "riders": []}},
            })
        for extra_label, extra_params in (extra_actions if aid == LEFT else ()):
            # Synthetic actions for shared-seam checks; flags live at the same
            # parameter level as actual actions from the owning sphere.
            extra_id = "action:test.worker1.extra." + extra_label.replace(" ", "_")
            extra = dict(extra_params)
            extra_effects = extra.pop("effects", [])
            extra_sphere = extra.pop("sphere", None)
            extra_area = extra.pop("area", None)
            bundle["actor_template"]["action_ids"].append(extra_id)
            bundle["action_catalog"].append({
                "source_definition_id": extra_id, "display_name": extra_label, "owner_id": aid,
                "economy": extra.pop("economy", "NONE"), "resolution_kind": "TYPED",
                "target_kind": extra.pop("target_kind", "SELF"), "range_ft": 60, "costs": [],
                "parameters": {"free_primary": True, **extra, "typed": {"effects": list(extra_effects),
                    **({"sphere": extra_sphere} if extra_sphere else {}),
                    **({"area": extra_area} if extra_area else {}),
                    "numbers": {"cl": cl, "pb": pb, "key_mod": 3, "save_dc": left_save_dc},
                    "duration": {"kind": "instant"}, "riders": []}},
            })
        if bundle_edit is not None:
            bundle_edit(bundle)
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)
        bundles.append(bundle)
    combat = CombatService(ROOT, tmp_path)
    roster, teams, spots = [LEFT, RIGHT], {LEFT: "team:factory", RIGHT: right_team}, dict(
        positions or {LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 4, "y": 6}})
    if ally is not None:
        roster.append(ALLY)
        teams[ALLY] = ally_team
        spots.setdefault(ALLY, {"x": 3, "y": 5})
    if extra_witness:
        witness = "actor:factory.auto111-witness"
        doc = sheet([], cl=cl, dc=100, kit={"starting_kit": KIT}, score=14)
        stats = doc["ability_scores_and_statistics"]
        stats["primary_resource"]["maximum"] = 100
        stats["hit_points"]["maximum"] = 1000
        stats["armor_class"]["base_value"] = 1
        doc["identity"]["display_name"] = "Bystander"
        folder = tmp_path / "portable_characters" / witness.removeprefix("actor:factory.")
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
        bundle = compile_character(doc, actor_id=witness, reaction_plan={"ask": True})
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)
        bundles.append(bundle)
        roster.append(witness)
        teams[witness] = witness_team
        spots[witness] = dict(witness_position or {"x": 3, "y": 5})
    arena = combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"]
    if map_terrain is not None:
        import copy
        arena = copy.deepcopy(arena)
        arena["map_terrain"] = map_terrain
    if arena_edit is not None:
        arena_edit(arena)
    mid = combat._finish_factory_match(
        bundles, roster, teams, spots,
        arena, [LEFT] + ([ALLY] if ally is not None else []), [RIGHT],
        control_modes={aid: "MANUAL" for aid in roster}, match_seed="worker1",
        display_name="Worker 1 regression", maximum_rounds=maximum_rounds,
    )["match_id"]
    table = TabletopService(combat, tmp_path)
    turn(table, mid, LEFT)
    return combat, table, mid


OTHER = "actor:factory.h15-other"


def turn(table, mid, aid, picks=None):
    """Advance initiative while answering player choices raised between turns."""
    for _ in range(12):
        if table.state(mid)["menu"]["actor_id"] == aid:
            return
        resolve(lambda answers: act(table, mid, "end", answers), picks)
    raise AssertionError("turn did not advance")


def settle(send, picker=None, *, choose=None, limit=20):
    """Drive Destruction's table action through its choices using the prompt minimum."""
    answers, prompts = [], []
    for _ in range(limit):
        result = send(answers)
        if result["status"] != "REACTION_REQUIRED":
            assert result["status"] == "COMMITTED", result
            return result, prompts
        prompt = result["reaction"]
        prompts.append(prompt)
        choice = prompt.get("choice") or {}
        ids = [option["id"] for option in choice.get("options", [])]
        selector = choose if choose is not None else picker
        chosen = selector(prompt) if selector else ids[:max(1, choice.get("minimum", 1))]
        decline = not chosen and choice.get("allow_decline", True)
        answers.append({**prompt["context"], "selection": "DECLINE" if decline else "USE", "option_ids": chosen})
    raise AssertionError("too many choices")


def resolve(send, picks=None):
    """Answer a run of table questions, choosing ``picks[reaction_source_id]`` or the first option."""
    answers, prompts = [], []
    for _ in range(12):
        result = send(answers)
        if result["status"] != "REACTION_REQUIRED":
            assert result["status"] == "COMMITTED", result
            return result, prompts
        prompt = result["reaction"]
        prompts.append(prompt)
        ids = [o["id"] for o in (prompt.get("choice") or {}).get("options", [])]
        chosen = (picks or {}).get(prompt["context"]["reaction_source_id"], ids[:1])
        answers.append({**prompt["context"], "selection": "USE" if chosen or not prompt.get("choice") else "DECLINE",
                        "option_ids": chosen})
    raise AssertionError("too many choices")


def cell_send(table, mid, label, xy):
    """A sender that casts ``label`` at the exact destination cell ``xy``."""
    def send(answers):
        state = table.state(mid)
        menu = state["menu"]
        engine = table.combat._load_session(mid).engine
        cid = next(c.candidate_id for c in engine.legal_candidates()
                   if c.display_name.startswith(label) and c.destination is not None
                   and (c.destination.x, c.destination.y) == tuple(xy))
        return table.act(mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"], answers)
    return send


def prefix_send(table, mid, label_prefix, xy, *, exact=False):
    """Shared menu sender for labels with cost or option suffixes (Pressure Points Study setup)."""
    def send(answers):
        state = table.state(mid)
        menu = state['menu']
        hit = (lambda label: label == label_prefix) if exact else (lambda label: label.startswith(label_prefix))
        cid = next(o['candidate_id'] for g in menu['actions'] if hit(g['label']) for o in g['options']
                   if o.get('destination') == {'x': xy[0], 'y': xy[1]})
        return table.act(mid, cid, menu['decision_id'], menu['state_version'], state['last_sequence'], answers)
    return send


def ascend(combat, table, mid, actor_id):
    """One native flight move of ``actor_id`` to the cell directly above it."""
    state = table.state(mid)
    actor = reload(combat, mid).state.actors[actor_id]
    candidate = next(c for c in combat._load_session(mid).engine.legal_candidates()
                     if c.destination is not None and c.metadata.get("movement_mode") == "fly"
                     and (c.destination.x, c.destination.y, c.destination.z)
                     == (actor.position.x, actor.position.y, 1))
    menu = state["menu"]
    return table.act(mid, candidate.candidate_id, menu["decision_id"], menu["state_version"], state["last_sequence"], [])


def triple_fight(tmp_path, talents=(), *, spheres=(), third_ally=False, left_score=14,
                 bundle_edit=None, cause_stun=False, display_name="Worker 1 three-creature regression",
                 positions=None, left_kit=None):
    """``fight`` plus a third sheet at ``OTHER``; optional kit/positions keep authored scenarios."""
    bundles = []
    for aid, owned in ((LEFT, talents), (RIGHT, []), (OTHER, [])):
        kit = left_kit if aid == LEFT and left_kit is not None else KIT
        doc = sheet(list(owned), cl=15, dc=100, kit={"starting_kit": kit},
                    score=left_score if aid == LEFT else 14)
        doc.setdefault("spheres_and_talents", {})["sphere_record_ids"] = list(spheres)
        doc["spheres_and_talents"]["automatic_sphere_component_record_ids"] = []
        stats = doc["ability_scores_and_statistics"]
        stats["technique_attack_bonus"] = 100
        stats["primary_resource"]["maximum"] = 100
        stats["hit_points"]["maximum"] = 1000
        stats["armor_class"]["base_value"] = 1
        doc["identity"]["display_name"] = {LEFT: "Keeper", RIGHT: "Visitor", OTHER: "Second visitor"}[aid]
        folder = tmp_path / "portable_characters" / aid.removeprefix("actor:factory.")
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
        bundle = compile_character(doc, actor_id=aid, reaction_plan={"ask": True})
        if cause_stun and aid == RIGHT:
            action_id = "action:test.worker1.third_stun"
            bundle["actor_template"]["action_ids"].append(action_id)
            bundle["action_catalog"].append({
                "source_definition_id": action_id, "display_name": "Cause", "owner_id": aid,
                "economy": "NONE", "resolution_kind": "TYPED", "target_kind": "HOSTILE_ENTITY",
                "range_ft": 60, "costs": [],
                "parameters": {"typed": {"effects": [{"type": "condition", "condition": "stunned", "applies_to": "target"}],
                                         "numbers": {}, "duration": {"kind": "instant"}, "riders": []}}})
        if bundle_edit is not None:
            bundle_edit(bundle)
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)
        bundles.append(bundle)
    ally = third_ally
    combat = CombatService(ROOT, tmp_path)
    mid = combat._finish_factory_match(
        bundles, [LEFT, RIGHT, OTHER],
        {LEFT: "team:factory", RIGHT: "team:opponents", OTHER: "team:factory" if ally else "team:opponents"},
        positions if positions is not None else {
            LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 4, "y": 6}, OTHER: {"x": 3 if ally else 4, "y": 5}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"],
        [LEFT, OTHER] if ally else [LEFT], [RIGHT] if ally else [RIGHT, OTHER],
        control_modes={a: "MANUAL" for a in (LEFT, RIGHT, OTHER)}, match_seed="worker1",
        display_name=display_name, maximum_rounds=10,
    )["match_id"]
    table = TabletopService(combat, tmp_path)
    turn(table, mid, LEFT)
    return combat, table, mid
