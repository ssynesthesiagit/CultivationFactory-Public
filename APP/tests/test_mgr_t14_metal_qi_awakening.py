"""Metal Qi Awakening (METAL_BASE_METAL_QI_AWAKENING), the Metal sphere's automatic base row, keeps its
three printed clauses honest: the automatic grant a table-gained Sphere hands out, the medium permission
that makes Metal talents usable, and the explicit non-grants.

Native producers and receipts only: TabletopService.add_advancement persisted through ButtonStore, the
CombatService owner-sheet path through combat/table_advance.py, compilation and _sorted_skipped in
combat/factory_compiler.py, the sheet's own features read-out in combat/tabletop_service.py, and the
definition label from combat/rules/feature_status.d/metal_qi_awakening.json. No browser, no model, no GPU.
"""
import copy
import hashlib
import json
import zipfile

import pytest

from canonical_catalog.service import CanonicalCatalogAuthorityService
from combat.factory_compiler import compile_character, feature_status
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, mechanics, sheet

ID = "METAL_BASE_METAL_QI_AWAKENING"
NAME = "Metal Qi Awakening"
METAL = "tianxia.sphere.metal"
NEEDLE = "TAL_METAL_NEEDLE_FLICK"
NEEDLE_NAME = "Needle Flick"
QI = "tianxia.path.qi_cultivation"
# ButtonStore ids must look like a finished character's (hex), so the table accepts them.
PLAYER, BYSTANDER = "a1140001", "a1140002"
P, O = FACTORY_ACTOR_PREFIX + PLAYER, FACTORY_ACTOR_PREFIX + BYSTANDER
MEDIUM_LINE = "mineral dust, ore-bearing ground"
NON_GRANT_LINE = "does not grant weapon proficiency, armor proficiency, Blacksmith tools"
RULES_SHA = "c0899a0f8c3416907e03daf7b8f33da6fa1669e1291f9f9a1ca7ccc5ef6f1114"


@pytest.fixture(scope="module")
def catalog():
    return CanonicalCatalogAuthorityService(ROOT)


def _install(tmp_path):
    """Two finished characters on disk; neither owns a Sphere yet."""
    for project, name in ((PLAYER, "Awakened"), (BYSTANDER, "Bystander")):
        doc = sheet([], cl=5, name=name)
        doc["identity"]["display_name"] = name
        doc["identity"]["path_ids"] = [QI]
        doc["path_and_subpath"] = {"path_record_id": QI, "path_record_ids": [QI]}
        doc["equipment"] = [{"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.jian", "quantity": 1}]}}]
        if project == PLAYER:
            doc["equipment"] = []  # use the body, with no supplied metal medium
        folder = tmp_path / "portable_characters" / project
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))


def _table(tmp_path, catalog):
    _install(tmp_path)
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    table.canonical_catalog = catalog
    return combat, table


def _field(row, key):
    return row.get(key) if isinstance(row, dict) else getattr(row, key)


def test_the_table_grants_the_awakening_and_the_sheet_calls_it_a_definition(tmp_path, catalog):
    """Clause 1 (awakening, automatic): gaining the Metal Sphere at the table grants the row, a cold service
    re-reads the grant from disk, and the sheet's receipt files it under "definitions" -- never under the
    unautomated "gm_passives" list that combat/rules/feature_status.d/metal_qi_awakening.json moves it out of."""
    combat, table = _table(tmp_path, catalog)
    table.add_advancement(PLAYER, "sphere", METAL)  # legal, not a GM override: Metal is primary for Qi Cultivation
    automatic = combat._factory_owner_sheet(PLAYER)["spheres_and_talents"]["automatic_sphere_component_record_ids"]
    assert ID in automatic  # table_advance.base_abilities() hands the row out with its Sphere

    cold = CombatService(ROOT, tmp_path)  # brand-new service: installed package and saved row re-read from disk
    cold_table = TabletopService(cold, tmp_path)
    cold_table.canonical_catalog = catalog
    cold_sheet = cold._factory_owner_sheet(PLAYER)
    assert ID in cold_sheet["spheres_and_talents"]["automatic_sphere_component_record_ids"]
    features = cold_table.sheet(PLAYER)["features"]
    assert NAME in features["definitions"]
    assert NAME not in features["gm_passives"]  # without the lane's topic file this lands in gm_passives instead
    assert feature_status()[ID]["status"] == "definition"

    # wrong owner: the bystander never gained a Sphere, so nothing metal reaches its receipt
    other = cold_table.sheet(BYSTANDER)["features"]
    assert NAME not in other["definitions"] + other["gm_passives"] + other["outside_fights"]

    # boundary: removing the Sphere's row at the table takes the grant away again
    table.remove_advancement(PLAYER, "sphere", METAL)
    after = CombatService(ROOT, tmp_path)._factory_owner_sheet(PLAYER)
    assert ID not in (after.get("spheres_and_talents") or {}).get("automatic_sphere_component_record_ids", [])


def test_a_metal_talent_fights_through_the_ordinary_action_path_with_no_medium_recorded(tmp_path, catalog):
    """Clause 2 (medium permission): the owner plays Needle Flick at the table although this sheet records no
    needle, held metal, mineral dust, ore ground or metal-qi projection -- the generic delivery needs no
    medium gate. The wrong owner never sees the button, and the committed fight replays from a cold service."""
    combat, table = _table(tmp_path, catalog)
    table.add_advancement(PLAYER, "sphere", METAL)
    table.add_advancement(PLAYER, "talent", NEEDLE)  # legal once the Sphere is known (its only prerequisite)
    # The same fixed geometry and service setup as the shipped R4 table fixture: both sheets compile
    # through the service's owner-sheet path, and the two fighters stand 3 squares apart (15 ft, well
    # inside the talent's printed 60-foot range).
    bundles = [compile_character(combat._factory_owner_sheet(project), actor_id=aid, reaction_plan={"ask": True})
               for project, aid in ((PLAYER, P), (BYSTANDER, O))]
    # No item of any material is supplied: the body is itself a permitted medium.
    # Check the persisted source and compiled inventory before testing delivery.
    assert combat._factory_owner_sheet(PLAYER)["equipment"] == []
    assert bundles[0]["carrying"]["items"] == []
    assert bundles[0]["weapons"] == []
    mid = combat._finish_factory_match(
        bundles, [P, O], {P: "team:factory", O: "team:opponents"},
        {P: {"x": 3, "y": 6}, O: {"x": 6, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"],
        [P], [O], control_modes={P: "MANUAL", O: "MANUAL"},
        match_seed="MGR-T14-METAL-AWAKENING", display_name="Metal Qi Awakening",
        maximum_rounds=10)["match_id"]

    def menu():
        return table.state(mid)["menu"]

    def send(cid, answers=()):
        current = menu()
        return table.act(mid, cid, current["decision_id"], current["state_version"], 0, list(answers))

    def settle(cid):
        result = send(cid)
        for _ in range(6):
            if result["status"] != "REACTION_REQUIRED":
                return result
            prompt = result["reaction"]
            result = send(cid, [{**prompt["context"], "selection": "DECLINE", "option_ids": []}])
        raise AssertionError("too many reaction prompts")

    def labels():
        current = menu()
        return [str(option.get("label") or group.get("label") or "")
                for group in current["actions"] for option in group["options"]]

    def candidate(name, target=None):
        current = menu()
        options = [(group.get("label"), option) for group in current["actions"] for option in group["options"]]
        found = [option["candidate_id"] for _label, option in options
                 if name in str(option.get("label") or _label or "")
                 and (target is None or target in (option.get("target_ids") or []))]
        assert found, options
        return found[0]

    acted = seen_bystander = False
    for _ in range(40):
        current = menu()
        if current["actor_id"] == O:
            assert not [text for text in labels() if NEEDLE_NAME in text]  # wrong owner has no metal talent
            seen_bystander = True
            result = settle(current["end_turn"])
        elif current["actor_id"] == P and not acted:
            result = settle(candidate(NEEDLE_NAME, target=O))
            acted = True
        else:
            result = settle(current["end_turn"])
        assert result["status"] == "COMMITTED", result
        if acted and seen_bystander:
            break
    assert acted and seen_bystander, (acted, seen_bystander)

    # cold commit/reload: a brand-new service reads the committed fight and it still replays
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.mechanical.replay()["status"] == "PASS"


def test_the_awakening_adds_no_button_pool_or_engine_row_and_keeps_both_printed_lines(tmp_path, catalog):
    """Clause 3 (non-grants): removing the row from the same owner's automatic list changes nothing it
    compiles to -- no new button, pool or runtime row, nothing whose name smells of proficiency, Blacksmith
    tools, crafting or control over metal -- while both printed clauses stay on the record, word for word,
    under the exact rules text the lane's controlling hash names."""
    combat, table = _table(tmp_path, catalog)
    table.add_advancement(PLAYER, "sphere", METAL)
    owner = combat._factory_owner_sheet(PLAYER)
    full = compile_character(owner, actor_id=P)
    control = copy.deepcopy(owner)
    control["spheres_and_talents"]["automatic_sphere_component_record_ids"] = [
        key for key in control["spheres_and_talents"]["automatic_sphere_component_record_ids"] if key != ID]
    bare = compile_character(control, actor_id=P)

    def buttons(bundle):
        rows = bundle["action_catalog"].values() if isinstance(bundle["action_catalog"], dict) else bundle["action_catalog"]
        return sorted(str(_field(row, "display_name")) for row in rows)

    def pools(bundle):
        rows = bundle["actor_template"].get("resources") or []
        return sorted(str(_field(row, "resource_id")) for row in rows)

    assert buttons(full) == buttons(bare)  # the row itself adds no button at all
    forbidden = ("proficien", "blacksmith", "craft", "control over", "forging")
    assert not [name for name in buttons(full) if any(word in name.lower() for word in forbidden)]
    assert pools(full) == pools(bare)  # and no new resource pool
    # nothing claims it as a runtime row: no plugin passives, reactions or applied modifiers
    for key in ("typed_passives", "typed_reactions", "modifiers"):
        assert ID not in [_field(row, "feature_id") or _field(row, "id") for row in full.get(key) or []]
        assert NAME not in [_field(row, "name") for row in full.get(key) or []]

    printed = mechanics()[ID]
    assert printed["riders"][0].startswith("You can use Metal talents through your body") and MEDIUM_LINE in printed["riders"][0]
    assert NON_GRANT_LINE in printed["riders"][1] and printed["riders"][1].endswith("in sight.")
    rules = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_bytes())[ID]
    assert hashlib.sha256(rules.encode("utf-8")).hexdigest() == RULES_SHA  # the lane's controlling record
    why = feature_status()[ID]["why"]
    assert "a touched metal object" in why
    assert "a touched object" not in why
    assert MEDIUM_LINE in why and "no weapon proficiency" in why \
        and "Blacksmith tools" in why and "permanent item crafting" in why and "broad control" in why
