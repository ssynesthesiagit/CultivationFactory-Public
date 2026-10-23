"""S1 acceptance 5/6: real service compilation, upgrade/reload and neutrality."""
from copy import deepcopy
import json

from combat.factory_compiler import compile_character, _typed_numbers, _modifiers
from combat.gate5_service import CombatService
from combat.save_dcs import save_dc
from combat import ext
from tests.body_refining_support import BODY, QI, DARK, PID, UPGRADE, ROOT, install, service, sheet

ACTOR = "actor:factory.body_student"


def numbers(bundle, source):
    return next(a["parameters"]["typed"]["numbers"] for a in bundle["action_catalog"]
                if (a.get("parameters", {}).get("typed") or {}).get("source") == source)


def compile_from_table(root):
    document = service(root).combat._factory_owner_sheet(PID)
    return compile_character(document, actor_id=ACTOR), document


def test_dark_rekeys_without_changing_other_sphere_or_sheet(tmp_path):
    # Fire already upgraded to normal: owning two Body Refining spheres without
    # upgrading either would correctly put BOTH on their printed CON versions.
    source = sheet(spheres=[DARK, "tianxia.sphere.fire"],
                   talents=["DARK_BASE_DARKNESS", "FIRE_BASE_IGNITE"],
                   insights=["insight.furnace-body"])
    before = deepcopy(source)
    install(tmp_path, source)
    bundle, document = compile_from_table(tmp_path)
    dark = numbers(bundle, "DARK_BASE_DARKNESS")
    fire = numbers(bundle, "FIRE_BASE_IGNITE")
    assert dark["key_mod"] == 4 and dark["save_dc"] == 14 and dark["attack_bonus"] == 6
    assert fire["key_mod"] == 1 and fire["save_dc"] == 11 and fire["attack_bonus"] == 3
    assert source == before
    assert document["identity"]["key_ability"] == "INT"
    assert _typed_numbers(document, _modifiers(document["ability_scores_and_statistics"]), 2)["key_mod"] == 1
    table = service(tmp_path)
    payload = table.sheet(PID)
    assert payload["summary"]["key_ability"] == "INT"
    assert not any(key.startswith("tianxia.brvariant.") for key in payload["features"]["automated_passives"])
    assert table.advancement(PID)["ability_panel"]["key_ability"] == "INT"


def test_rekey_preserves_recorded_dc_and_attack_bonuses(tmp_path):
    document = sheet(spheres=[DARK], talents=["DARK_BASE_DARKNESS"])
    document["ability_scores_and_statistics"]["technique_save_dc"] += 2
    document["ability_scores_and_statistics"]["technique_attack_bonus"] += 2
    install(tmp_path, document)
    bundle, _ = compile_from_table(tmp_path)
    scoped = numbers(bundle, "DARK_BASE_DARKNESS")
    assert scoped["key_mod"] == 4
    assert scoped["save_dc"] == 16  # 8 + PB 2 + CON 4, retaining the recorded +2.
    assert scoped["attack_bonus"] == 8  # PB 2 + CON 4, retaining the recorded +2.


def test_save_dc_only_scope_preserves_the_attack_and_key(tmp_path):
    install(tmp_path, sheet(spheres=["tianxia.sphere.thread"], talents=["THREAD_BASE_DRAW_THE_LINE"]))
    bundle, _ = compile_from_table(tmp_path)
    scoped = numbers(bundle, "THREAD_BASE_DRAW_THE_LINE")
    assert scoped["key_mod"] == 1 and scoped["attack_bonus"] == 3
    assert scoped["save_dc"] == 14


def test_scoped_reaction_rekeys_from_the_real_catalogue(tmp_path):
    source = "tianxia.talent.music.rhythmic_guard"
    install(tmp_path, sheet(spheres=["tianxia.sphere.music"], talents=[source]))
    bundle, _ = compile_from_table(tmp_path)
    reaction = next(r for r in bundle["typed_reactions"] if r["feature_id"] == source)
    assert reaction["numbers"]["key_mod"] == 4
    assert reaction["numbers"]["save_dc"] == 14


def test_upgrade_restores_normal_compiled_numbers_after_cold_reload(tmp_path):
    install(tmp_path, sheet(spheres=[DARK], talents=["DARK_BASE_DARKNESS"]))
    before, _ = compile_from_table(tmp_path)
    assert numbers(before, "DARK_BASE_DARKNESS")["key_mod"] == 4
    service(tmp_path).add_insight(PID, UPGRADE, note="Completed body training")
    after, document = compile_from_table(tmp_path)
    assert numbers(after, "DARK_BASE_DARKNESS")["key_mod"] == 1
    assert numbers(after, "DARK_BASE_DARKNESS")["save_dc"] == 11
    assert not any(r["block"] == "br_variant" for r in after["typed_passives"])
    assert document["identity"]["key_ability"] == "INT"


def test_unowned_variant_hooks_are_byte_identical(tmp_path, monkeypatch):
    document = sheet(paths=[QI], spheres=[DARK], talents=["DARK_BASE_DARKNESS"])
    install(tmp_path, document)
    before, _ = compile_from_table(tmp_path)
    # Remove only this plug-in's transforms, not other providers. This compares
    # the identical sheet/catalogue against pre-S1 behavior, rather than merely
    # comparing two calls to the new code.
    original = ext.transform
    def without_variants(name, value, *args, **kwargs):
        if name not in {"compile_passives", "compile_action", "compile_reaction"}:
            return original(name, value, *args, **kwargs)
        for provider in ext._HOOKS.get(name, []):
            if provider.__module__ == "combat.ext.br_variants":
                continue
            result = provider(value, *args, **kwargs)
            if result is not None:
                value = result
        return value
    monkeypatch.setattr(ext, "transform", without_variants)
    after, _ = compile_from_table(tmp_path)
    assert json.dumps(before["action_catalog"], sort_keys=True) == json.dumps(after["action_catalog"], sort_keys=True)
    assert before["typed_passives"] == after["typed_passives"]


def test_named_sphere_dc_is_owned_scoped_and_persistable(tmp_path):
    body_sheet = sheet(spheres=[DARK], talents=["DARK_BASE_DARKNESS"])
    body_sheet["ability_scores_and_statistics"]["technique_save_dc"] += 2
    install(tmp_path, body_sheet)
    other = "0badc0de-0000-4000-8000-000000000032"
    install(tmp_path, sheet(paths=[QI]), pid=other)
    table = service(tmp_path)
    combat = table.combat
    combat.tabletop_maps.save({"display_name": "Body yard", "width_squares": 12, "height_squares": 8,
                              "walls": [], "starts": {"team1": [[3, 4]], "team2": [[5, 4]]}})
    actor_id, foe = "actor:factory." + PID, "actor:factory." + other
    mid = combat.create_factory_match(project_ids=[PID], opponent_actor_ids=[foe],
        control_modes={actor_id: "MANUAL", foe: "MANUAL"},
        arena_id="battlefield:map.body-yard", match_seed="BRS1-NAMED-DC")["match_id"]
    state = table.state(mid)
    menu = state["menu"]
    assert table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"],
                     state["last_sequence"], [])["status"] == "COMMITTED"
    saved = CombatService(ROOT, tmp_path)._load_session(mid)
    assert saved.mechanical.replay()["status"] == "PASS"
    engine = saved.engine
    actor = engine.state.actors[actor_id]
    # Named Dark DC substitutes CON but retains the recorded +2 DC bonus.
    assert save_dc(engine, actor, "sphere", sphere_id=DARK) == 16
    assert save_dc(engine, actor, "sphere", sphere_id="tianxia.sphere.fire") == 13
    assert save_dc(engine, actor, "cultivation") == 13
    assert save_dc(engine, actor) == 13
    from combat.ability_checks import key_modifier
    from combat.ext.needle import numbers_of, save_dc as cultivation_dc
    assert numbers_of(engine, actor)["key_mod"] == key_modifier(engine, actor) == 1
    assert cultivation_dc(engine, actor) == 13
