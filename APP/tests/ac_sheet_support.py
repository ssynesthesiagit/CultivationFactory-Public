"""Synthetic sheet and armour helpers shared by the AC tests: real sheets, real fights and the table path."""
import json
from pathlib import Path
from zipfile import ZipFile

from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService

ROOT = Path(__file__).resolve().parents[1]


def install_sheet(tmp_path, sheet, pid="hero"):
    """Install a synthetic sheet as a portable character package."""
    folder = tmp_path / "portable_characters" / pid
    folder.mkdir(parents=True)
    with ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))


def projected_sheet(feature, *, armor=None, dex=14):
    """Use the real sheet's statistic producer and published provenance shape."""
    from tests.test_path_feature_statistics import BASELINE, _context
    from projector.path_feature_statistics import load_path_feature_statistic_formulas, resolve_armor_class
    sheet = _sheet(_kit(AXE, *([armor] if armor else [])), dex=dex, mids=[UNARMORED, feature])
    result = resolve_armor_class(load_path_feature_statistic_formulas(ROOT), [UNARMORED, feature],
        baseline_rule=BASELINE, baseline_value=10 + (dex - 10) // 2,
        baseline_trace={}, context=_context(con=3, dex=(dex - 10) // 2, pb=4))
    sheet['ability_scores_and_statistics']['armor_class'] = {
        'base_value': result['ac_base'], 'value': result['ac_active'], 'generation': result['ac_generation']}
    return sheet


def scratch_sheet_payload(tmp_path):
    """Compile the existing scratch sheet through the production sheet API."""
    sheet = json.loads((ROOT / "tests/fixtures/gm_sheet/scratch_owner_sheet_snapshot.fixture.json").read_text())
    install_sheet(tmp_path, sheet, "abcdef19")
    return TabletopService(CombatService(ROOT, tmp_path), tmp_path).sheet("abcdef19")


ME = "actor:factory.mmx34"
SHIELD = "tianxia.mortal.armor.shield"
AXE = "tianxia.mortal.weapon.fu"
MEDIUM = "tianxia.mortal.armor.beast_hide_harness"
LIGHT = "tianxia.mortal.armor.lacquered_leather"
HEAVY = "tianxia.mortal.armor.imperial_plate_battle_dress"  # "18", "Str 15"
STONE_SKIN = "tianxia.subpath.body.yamabushi.feature.stone_skin"
DRAGON_SCALES = "tianxia.subpath.body.ryujin.feature.dragon_scales"
TEMPERED_FLESH = "tianxia.subpath.body.iron_shirt.feature.tempered_flesh"
UNARMORED = "tianxia.path.body_refining.feature.unarmored_defense"
_NAMES = {SHIELD: "Shield", AXE: "Fu", MEDIUM: "Beast-Hide Harness", LIGHT: "Lacquered Leather",
          HEAVY: "Imperial Plate Battle Dress"}


def _kit(*item_ids):
    """A starting kit.  The printed name is what the Drop and Pick up buttons say."""
    return {"items": [{"item_id": i, "name": _NAMES.get(i, i.rsplit(".", 1)[-1]), "quantity": 1} for i in item_ids]}


def _sheet(kit=None, *, dex=16, strength=16, base_ac=14, value=None, speed=30, hp=80, mids=()):
    """A real sheet.  ``base_ac`` is the unarmored calculation; ``value`` is the sheet's active AC
    (``base_ac`` plus whatever always-on bonuses the sheet has folded in)."""
    stats = {"abilities": [{"ability": a, "score": s, "modifier": (s - 10) // 2}
                           for a, s in (("STR", strength), ("DEX", dex), ("CON", 16), ("INT", 12), ("WIS", 14), ("CHA", 10))],
             "primary_resource": {"name": "Stamina", "maximum": 60},
             "armor_class": {"base_value": base_ac, **({"value": value} if value is not None else {})},
             "speed": {"walking_ft": speed}, "technique_save_dc": 16, "technique_attack_bonus": 8}
    if hp is not None:
        stats["hit_points"] = {"maximum": hp}
    out = {"proficiencies": {"armor": ["Shield"]}, "identity": {"proficiency_bonus": 4, "cultivation_level": 10, "path": "Body Refining", "key_ability": "STR"},
           "ability_scores_and_statistics": stats,
           "path_and_subpath": {"path_feature_record_ids": list(mids)},
           "equipment": [{"starting_kit": kit or {"items": []}}],
           "spheres_and_talents": {"sphere_record_ids": [], "learned_talent_record_ids": [],
                                   "automatic_sphere_component_record_ids": []}}
    return out


def _bundle(sheet=None, actor_id=ME):
    return compile_character(sheet or _sheet(), actor_id=actor_id)


def _fight(sheet=None, seed="MMX34"):
    bundle = _bundle(sheet)
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


def _effective_ac(engine, actor_id=ME):
    """The AC a fight actually rolls against: the compiled number plus everything the ac hooks add."""
    actor = engine.state.actors[actor_id]
    return int(actor.armor_class) + int(engine._ac_modifier(actor))


def _do(engine, name):
    candidate = next(c for c in engine.legal_candidates() if c.display_name == name)
    engine.execute_intent(ActionIntent(intent_id=name, decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=ME, target_ids=candidate.target_ids))


def _shielded(extra=()):
    return _sheet(_kit(AXE, SHIELD, *extra))


def _table_match(tmp_path, bundle):
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    combat = CombatService(ROOT, tmp_path)
    mid = combat._finish_factory_match(
        [bundle], [ME, AN], {ME: "team:a", AN: "team:b"},
        {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [ME], [AN],
        control_modes={ME: "MANUAL", AN: "MANUAL"}, match_seed="EQUIPMENT-PERSISTENCE",
        display_name="Equipment regression", maximum_rounds=20)["match_id"]
    table = TabletopService(combat, tmp_path)
    state = table.state(mid)
    if state["menu"]["actor_id"] != ME:
        menu = state["menu"]
        assert table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], state["last_sequence"])["status"] == "COMMITTED"
    return combat, table, mid


def _table_do(table, mid, name):
    state = table.state(mid)
    option = next(o for g in state["menu"]["actions"] for o in g["options"]
                  if o["label"] == name)
    return table.act(mid, option["candidate_id"], state["menu"]["decision_id"],
                     state["menu"]["state_version"], state["last_sequence"])


def _do_on(engine, name, actor_id):
    candidate = next(c for c in engine.legal_candidates() if c.display_name == name and c.actor_id == actor_id)
    engine.execute_intent(ActionIntent(intent_id=name, decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=actor_id, target_ids=candidate.target_ids))
