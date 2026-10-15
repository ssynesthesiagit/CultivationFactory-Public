"""Synthetic persisted tables for hunt 15; no private characters or live data."""
import copy
import json
import zipfile

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_carry import KIT

LEFT, RIGHT, ALLY = "actor:factory.h15-left", "actor:factory.h15-right", "actor:factory.h15-ally"


def fight(tmp_path, left=(), right=(), *, effects=None, target="SELF", seed="HUNT15", primary="Qi", ally=None, legacy_reactions=False, positions=None, typed_parameters=None, prepare_bundle=None):
    bundles = []
    actors = [(LEFT, left), (RIGHT, right)] + ([(ALLY, ally)] if ally is not None else [])
    for aid, mids in actors:
        document = sheet(list(mids), cl=15, primary=primary, kit={"starting_kit": KIT})
        document["identity"]["display_name"] = {LEFT: "River Keeper", RIGHT: "Visiting Fighter", ALLY: "Guarding Friend"}[aid]
        folder = tmp_path / "portable_characters" / aid.removeprefix("actor:factory.")
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))
        bundle = compile_character(document, actor_id=aid, reaction_plan={"ask": aid == LEFT})
        if legacy_reactions:
            # Recreate the old sealed row shape, before the compiler retained sight.
            for row in bundle["typed_reactions"]:
                row.pop("requires_sight", None)
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)
        if effects is not None:
            action = copy.deepcopy(next(a for a in bundle["action_catalog"] if a["resolution_kind"] == "TYPED"))
            action.update(source_definition_id=f"action:test.h15.{aid}", display_name="Test setup", economy="ACTION",
                          target_kind=target, costs=[], range_ft=60)
            action["parameters"] = {"typed": {"effects": effects, "numbers": {"cl": 15, "pb": 4, "save_dc": 100},
                                                "duration": {"kind": "instant"}, "riders": [], **(typed_parameters or {})}}
            bundle["action_catalog"].append(action)
            bundle["actor_template"]["action_ids"].append(action["source_definition_id"])
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)
        if prepare_bundle is not None:
            prepare_bundle(bundle)
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)
        bundles.append(bundle)
    combat = CombatService(ROOT, tmp_path)
    roster = [aid for aid, _ in actors]
    mid = combat._finish_factory_match(bundles, roster, {aid: "team:opponents" if aid == RIGHT else "team:factory" for aid in roster},
        positions or {LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 4, "y": 6}, **({ALLY: {"x": 3, "y": 5}} if ally is not None else {})},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [aid for aid in roster if aid != RIGHT], [RIGHT],
        control_modes={aid: "MANUAL" for aid in roster}, match_seed=seed,
        display_name="Hunt 15 regression", maximum_rounds=10)["match_id"]
    return combat, TabletopService(combat, tmp_path), mid


def act(table, mid, source, answers=(), *, target_id=None):
    state = table.state(mid)
    menu = state["menu"]
    cid = menu["end_turn"] if source == "end" else next(
        o["candidate_id"] for g in menu["actions"]
        if g["label"] == source or g["source_definition_id"].endswith(source) for o in g["options"]
        if target_id is None or target_id in o.get("target_ids", []))
    return table.act(mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"], list(answers))


def turn(table, mid, aid):
    for _ in range(3):
        if table.state(mid)["menu"]["actor_id"] == aid:
            return
        assert act(table, mid, "end")["status"] == "COMMITTED"
    raise AssertionError("turn did not advance")


def reload(combat, mid):
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    loaded = CombatService(ROOT, combat.userdata_root)._load_session(mid)
    assert loaded.engine.state.model_dump(mode="json") == before
    assert loaded.mechanical.replay()["status"] == "PASS"
    return loaded.engine


def action_sender(combat, table, mid, source, *, ai=False, target_id=None):
    """Choose an exact action from the controller's own legal AI context."""
    if not ai:
        return lambda answers: act(table, mid, source, answers, target_id=target_id)
    from combat.gate4_adapters import ManualControllerAdapter

    menu = table.state(mid)["menu"]
    real = combat.controller
    class Controller:
        def choose_primary_action(self, context):
            # Player menus intentionally hide legacy composed rider variants.
            # The actual AI context remains authoritative for AI selections.
            cid = next(c.candidate_id for c in context.legal_candidates
                       if c.display_name == source or c.source_definition_id.endswith(source)
                       if target_id is None or target_id in c.target_ids)
            return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)
        def __getattr__(self, name):
            return getattr(real, name)
    combat.controller = Controller()
    combat.set_controller_mode(mid, actor_id=menu["actor_id"], controller_mode="LOCAL_AUTO")
    return lambda answers: table.auto_step(mid, table.state(mid)["last_sequence"], answers)
