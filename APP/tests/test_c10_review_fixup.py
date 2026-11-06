"""C10 review regressions at the table transaction and persisted-fight boundary.

Compiled through tests/rider_sheet_support against the authority this checkout ships: this file reads no repository
history and does not follow test_riders_c10's C10_OLD=1 base typing, so it can run on public CI.
"""
import json
import zipfile

import pytest

from combat.gate2_rolls import DeterministicRollAuthority
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX as PREFIX
from combat.tabletop import ButtonStore
from combat.tabletop_service import TabletopService
from tests.rider_sheet_support import ROOT, sheet, BOW, JIAN, DAGGER, SHORTSWORD


def make_table(tmp_path, ids, sphere, mode, *, foes=1, items=(BOW,), body=False, objects=()):
    projects = ["aaaaaaaa", *[f"{i:08x}" for i in range(foes)]]
    for project in projects:
        doc = sheet(ids if project == "aaaaaaaa" else [], sphere=sphere if project == "aaaaaaaa" else None,
                    items=items if project == "aaaaaaaa" else (JIAN,), ac=1)
        doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = 1000
        if body and project == "aaaaaaaa":
            doc["identity"]["path"] = "Body Refining"
            doc["spheres_and_talents"]["learned_talent_record_ids"].append("tianxia.path.body_refining.feature.extra_attack")
        if sphere == "tianxia.sphere.dual_wielding" and project == "aaaaaaaa":
            doc["spheres_and_talents"]["sphere_record_ids"].append("tianxia.sphere.the_hidden_eye")
            doc["spheres_and_talents"]["learned_talent_record_ids"].append("TAL_THE_HIDDEN_EYE_BASE_SPHERE_FEATURES")
        folder = tmp_path / "portable_characters" / project
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    ButtonStore(tmp_path / "tabletop_buttons").save_reactions("aaaaaaaa", {"mode": "ask"}, set())
    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save({"display_name": "C10 Review", "width_squares": 10, "height_squares": 10,
                               "walls": [], "objects": list(objects), "starts": {"team1": [[3, 3]],
                               "team2": [[4, 3], [5, 3], [6, 3], [7, 3]]}})
    mid = service.create_factory_match(project_ids=["aaaaaaaa"], opponent_actor_ids=[PREFIX + p for p in projects[1:]],
          control_modes={PREFIX + p: mode if p == "aaaaaaaa" else "MANUAL" for p in projects},
          arena_id="battlefield:map.c10-review", match_seed="C10-REVIEW")["match_id"]
    return service, TabletopService(service, tmp_path), mid


def end_until_hero(table, mid):
    for _ in range(10):
        state = table.state(mid)
        if state["menu"]["actor_id"] == PREFIX + "aaaaaaaa":
            return state
        menu = state["menu"]
        result = table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], state["last_sequence"])
        assert result["status"] == "COMMITTED"
    raise AssertionError("hero turn not reached")


def act(service, table, mid, mode, monkeypatch, name):
    state = table.state(mid)
    selected = [c for c in service._load_session(mid).engine.legal_candidates() if c.display_name == name]
    assert selected, name
    candidate = selected[0]
    prompts, answers = [], []
    if mode == "LOCAL_AUTO":
        original = service.controller.choose_primary_action
        def choose(context):
            return original(context.model_copy(update={"legal_candidates": tuple(
                c for c in context.legal_candidates if c.candidate_id == candidate.candidate_id)}))
        monkeypatch.setattr(service.controller, "choose_primary_action", choose)
    for _ in range(10):
        if mode == "LOCAL_AUTO":
            result = table.auto_step(mid, state["last_sequence"], answers)
        else:
            result = table.act(mid, candidate.candidate_id, candidate.decision_id, candidate.state_version,
                               state["last_sequence"], answers)
        if result["status"] != "REACTION_REQUIRED":
            assert result["status"] in {"COMMITTED", "STEPPED"}, result
            if mode == "LOCAL_AUTO":
                monkeypatch.setattr(service.controller, "choose_primary_action", original)
            return prompts
        reaction = result["reaction"]
        prompts.append(reaction)
        choices = reaction.get("choice", {}).get("options", [])
        answers.append({**reaction["context"], "selection": "USE" if choices else "DECLINE",
                        "option_ids": [choices[0]["id"]] if choices else []})
    raise AssertionError("unresolved prompts")


def reload_check(service, mid):
    session = service._load_session(mid)
    assert session.mechanical.replay()["status"] == "PASS"
    return session.engine


@pytest.mark.parametrize("mode", ["MANUAL", "LOCAL_AUTO"])
def test_extra_attack_spinning_shot_uses_four_distinct_creatures(tmp_path, monkeypatch, mode):
    service, table, mid = make_table(tmp_path, ["TAL_BARRAGE_SPINNING_SHOT"], "tianxia.sphere.barrage", mode,
                                     foes=4, body=True)
    end_until_hero(table, mid)
    bow = "Gong Jian (Bow and Arrow)"
    prompts = act(service, table, mid, mode, monkeypatch, f"Barrage: {bow} + Spinning Shot")
    engine = reload_check(service, mid)
    attacks = [e for e in engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == PREFIX + "aaaaaaaa"]
    assert len(attacks) == 2 and len({e.target_ids[0] for e in attacks}) == 2
    assert bool(prompts) is (mode == "MANUAL")
    if prompts:
        assert "Spinning Shot" in prompts[0]["moment"] and "Extra Attack" in prompts[0]["moment"]
    used = {e.target_ids[0] for e in attacks}
    assert all(not used.intersection(c.target_ids) for c in engine.legal_candidates() if c.display_name == f"Spinning Shot: {bow}")
    prompts = act(service, table, mid, mode, monkeypatch, f"Spinning Shot: {bow}")
    engine = reload_check(service, mid)
    attacks = [e for e in engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == PREFIX + "aaaaaaaa"]
    assert len(attacks) == 4 and len({e.target_ids[0] for e in attacks}) == 4
    assert bool(prompts) is (mode == "MANUAL")


def force_natural(monkeypatch, natural):
    original = DeterministicRollAuthority.d20
    def fixed(self, **kwargs):
        record = original(self, **kwargs)
        return record.model_copy(update={"natural_result": natural,
            "total": natural + int(kwargs.get("modifier") or 0), "dice": (natural,)})
    monkeypatch.setattr(DeterministicRollAuthority, "d20", fixed)


@pytest.mark.parametrize("mode", ["MANUAL", "LOCAL_AUTO"])
def test_spinning_extra_attack_restores_court_focus_before_any_bonus_hit(tmp_path, monkeypatch, mode):
    force_natural(monkeypatch, 15)
    from combat.ext.barrage_hits import COURT, COURT_CONDITION, FOCUS, STATE
    service, table, mid = make_table(tmp_path, ["TAL_BARRAGE_SPINNING_SHOT", COURT, "ATHLETICS_BASE_COORDINATED_MOVEMENT"],
                                    "tianxia.sphere.barrage", mode, foes=2, body=True)
    end_until_hero(table, mid)
    act(service, table, mid, mode, monkeypatch, "Court of Falling Stars")
    engine = reload_check(service, mid)
    assert engine.state.actors[PREFIX + "aaaaaaaa"].resources[FOCUS] == 0
    # Coordinated Movement supplies an evented recovery after Court's focus cost.
    act(service, table, mid, mode, monkeypatch, "Disengage")
    act(service, table, mid, mode, monkeypatch, "End turn")
    end_until_hero(table, mid)
    engine = reload_check(service, mid)
    hero = engine.state.actors[PREFIX + "aaaaaaaa"]
    assert hero.resources[FOCUS] == 1
    assert any(c.condition_id == COURT_CONDITION for c in hero.conditions.values())
    before = len(engine.events)
    bow = "Gong Jian (Bow and Arrow)"
    prompts = act(service, table, mid, mode, monkeypatch, f"Barrage: {bow} + Spinning Shot")
    engine = reload_check(service, mid)
    hero = engine.state.actors[PREFIX + "aaaaaaaa"]
    attacks = [e for e in engine.events[before:] if e.event_type == "ATTACK_ROLLED" and e.actor_id == hero.entity_id]
    assert len(attacks) == 2 and len({e.target_ids[0] for e in attacks}) == 2
    sequence, = hero.turn_flags[STATE].values()
    assert sequence["total"] == 2 and sorted(sequence["hits"].values()) == [1, 1]
    assert hero.resources[FOCUS] == 1 and hero.turn_flags["barrage_court_focus_used"]
    assert any(e.source_definition_id == COURT and e.event_type == "RESOURCE_GAINED"
               for e in engine.events[before:])
    assert not any(c.display_name == f"Spinning Shot: {bow}" for c in engine.legal_candidates())
    assert bool(prompts) is (mode == "MANUAL")


# The two action rows a fight saved before barrage_blitz.py changed carried, as they were serialized by that file at
# 60de1809. Inlined rather than kept under tests/fixtures/ so this test depends on no file the public export withholds.
LEGACY_SPINNING_ACTIONS = r"""[
  {
    "source_definition_id": "action:typed.76dcbeb324.weapon.gong_jian.barrage+TAL_BARRAGE_SPINNING_SHOT",
    "display_name": "Barrage: Gong Jian (Bow and Arrow) + Spinning Shot",
    "owner_id": "actor:factory.aaaaaaaa", "economy": "ACTION", "resolution_kind": "TYPED",
    "target_kind": "HOSTILE_ENTITY", "range_ft": 600, "reach_ft": null, "attack_bonus": null,
    "attack_count": 1, "damage": null, "damage_type": null, "save": null,
    "costs": [["resource:core.martial_focus", 1]], "concentration": false, "radius_ft": null,
    "parameters": {
      "expected_damage": 6,
      "typed": {
        "effects": [{"type": "attack", "attack_kind": "weapon", "count": 1, "on_hit": [{"type": "damage", "weapon_damage": true}]}],
        "numbers": {"pb": 4, "save_dc": 14, "attack_bonus": 2, "key_mod": 2, "con_mod": 2, "cl": 10},
        "weapon": {"damage": {"count": 1, "sides": 8, "modifier": 2}, "damage_type": "PIERCING", "damage_types": ["PIERCING"], "ability_modifier": 2, "properties": "Ammunition, Range 150/600, Two-Handed Method", "omits_ability_damage": false},
        "duration": {"kind": "instant"}, "range_ft": 150, "long_range_ft": 600, "riders": [],
        "source": "tianxia.mortal.weapon.gong_jian", "proficient": false, "mastery": null, "magic_bonus": 0, "mundane": true,
        "maneuver": "barrage", "maneuver_of": "action:typed.76dcbeb324.weapon.gong_jian",
        "opens": ["barrage_spin:action:typed.76dcbeb324.weapon.gong_jian"],
        "barrage_owned": ["TAL_BARRAGE_MARTIAL_FOCUS", "TAL_BARRAGE_SPINNING_SHOT"],
        "modifier": {"id": "TAL_BARRAGE_SPINNING_SHOT", "name": "Spinning Shot", "precondition": ""}
      },
      "barrage_blitz": "TAL_BARRAGE_SPINNING_SHOT"
    }
  },
  {
    "source_definition_id": "action:typed.76dcbeb324.weapon.gong_jian.barrage_spinning",
    "display_name": "Spinning Shot: Gong Jian (Bow and Arrow)",
    "owner_id": "actor:factory.aaaaaaaa", "economy": "BONUS_ACTION", "resolution_kind": "TYPED",
    "target_kind": "HOSTILE_ENTITY", "range_ft": 600, "reach_ft": null, "attack_bonus": null,
    "attack_count": 1, "damage": null, "damage_type": null, "save": null,
    "costs": [], "concentration": false, "radius_ft": null,
    "parameters": {
      "typed": {
        "effects": [
          {"type": "attack", "attack_kind": "weapon", "count": 1, "on_hit": [{"type": "damage", "weapon_damage": true}]},
          {"type": "barrage_spinning_second", "weapon": "action:typed.76dcbeb324.weapon.gong_jian", "evidence": "Make two Bonus Action attacks instead of one. Every attack in the Barrage must target a different creature."}
        ],
        "numbers": {"pb": 4, "save_dc": 14, "attack_bonus": 2, "key_mod": 2, "con_mod": 2, "cl": 10},
        "weapon": {"damage": {"count": 1, "sides": 8, "modifier": 0}, "damage_type": "PIERCING", "damage_types": ["PIERCING"], "ability_modifier": 2, "properties": "Ammunition, Range 150/600, Two-Handed Method", "omits_ability_damage": false},
        "duration": {"kind": "instant"}, "range_ft": 150, "long_range_ft": 600, "riders": [],
        "source": "tianxia.mortal.weapon.gong_jian", "proficient": false, "mastery": null, "magic_bonus": 0, "mundane": true,
        "maneuver": "barrage_follow_up", "maneuver_of": "action:typed.76dcbeb324.weapon.gong_jian",
        "uses": ["barrage_spin:action:typed.76dcbeb324.weapon.gong_jian"],
        "barrage_owned": ["TAL_BARRAGE_MARTIAL_FOCUS", "TAL_BARRAGE_SPINNING_SHOT"],
        "spinning_of": "action:typed.76dcbeb324.weapon.gong_jian"
      },
      "expected_damage": 6, "requires_turn_flag": "barrage_spin:action:typed.76dcbeb324.weapon.gong_jian",
      "description": "After Barrage: Gong Jian (Bow and Arrow) + Spinning Shot, spend your Bonus Action on two Gong Jian (Bow and Arrow) attacks, each at a different creature, neither the one the Barrage's first attack targeted. They add no positive ability modifier to damage."
    }
  }
]
"""


@pytest.mark.parametrize("mode", ["MANUAL", "LOCAL_AUTO"])
@pytest.mark.parametrize("natural", [1, 15])
def test_prechange_saved_spinning_primary_excludes_its_target_after_reload(tmp_path, monkeypatch, mode, natural):
    from combat import factory_compiler
    from combat.ext.barrage_blitz import SPIN_TARGET
    from combat.gate3_storage import TYPED_BUNDLES_FILE
    # Rows are LEGACY_SPINNING_ACTIONS above, independent of Git/history and today's action builder.
    legacy = json.loads(LEGACY_SPINNING_ACTIONS)
    legacy_ids = {a["source_definition_id"] for a in legacy}
    original = factory_compiler.compile_character
    def compile_legacy(*args, **kwargs):
        bundle = original(*args, **kwargs)
        if bundle["actor_id"] == PREFIX + "aaaaaaaa":
            bundle["action_catalog"] = [a for a in bundle["action_catalog"] if a["source_definition_id"] not in legacy_ids] + legacy
        return bundle
    # Only fixture creation uses the old rows; the service persists the bundle
    # normally, then current code loads it without recompiling the catalog.
    with monkeypatch.context() as setup:
        setup.setattr(factory_compiler, "compile_character", compile_legacy)
        service, table, mid = make_table(tmp_path, ["TAL_BARRAGE_SPINNING_SHOT"],
                                        "tianxia.sphere.barrage", mode, foes=3)
    force_natural(monkeypatch, natural)
    bundle_path = service._match_dir(mid) / TYPED_BUNDLES_FILE
    saved_bytes = bundle_path.read_bytes()
    saved = next(b for b in json.loads(saved_bytes) if b["actor_id"] == PREFIX + "aaaaaaaa")
    assert [a for a in saved["action_catalog"] if a["source_definition_id"] in legacy_ids] == legacy
    end_until_hero(table, mid)
    bow = "Gong Jian (Bow and Arrow)"
    act(service, table, mid, mode, monkeypatch, f"Barrage: {bow} + Spinning Shot")
    engine = reload_check(service, mid)
    primary = [e for e in engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == PREFIX + "aaaaaaaa"]
    assert len(primary) == 1
    target = primary[0].target_ids[0]
    hero = engine.state.actors[PREFIX + "aaaaaaaa"]
    weapon = legacy[0]["parameters"]["typed"]["maneuver_of"]
    assert hero.turn_flags[SPIN_TARGET + weapon] == target
    candidates = [c for c in engine.legal_candidates() if c.display_name == f"Spinning Shot: {bow}"]
    assert candidates and all(target not in c.target_ids for c in candidates)
    act(service, table, mid, mode, monkeypatch, f"Spinning Shot: {bow}")
    engine = reload_check(service, mid)
    attacks = [e for e in engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == hero.entity_id]
    assert len(attacks) == 3 and len({e.target_ids[0] for e in attacks}) == 3
    assert bundle_path.read_bytes() == saved_bytes  # no migration or recompilation


@pytest.mark.parametrize("mode", ["MANUAL", "LOCAL_AUTO"])
def test_two_critical_ranges_double_the_native_dice_only_once_at_table(tmp_path, monkeypatch, mode):
    original = DeterministicRollAuthority.d20
    def natural19(self, **kwargs):
        record = original(self, **kwargs)
        return record.model_copy(update={"natural_result": 19, "total": 19 + int(kwargs.get("modifier") or 0), "dice": (19,)})
    monkeypatch.setattr(DeterministicRollAuthority, "d20", natural19)
    service, table, mid = make_table(tmp_path, ["TAL_DUAL_WIELDING_CRITICAL_FOLLOW_UP", "TAL_THE_HIDDEN_EYE_FIND_GAP"],
                                     "tianxia.sphere.dual_wielding", mode, items=(DAGGER, SHORTSWORD))
    end_until_hero(table, mid)
    act(service, table, mid, mode, monkeypatch, "Analyze")
    reload_check(service, mid)
    state = table.state(mid)
    if mode == "MANUAL":
        menu = state["menu"]
        table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], state["last_sequence"])
    else:
        act(service, table, mid, mode, monkeypatch, "End turn")
    end_until_hero(table, mid)
    act(service, table, mid, mode, monkeypatch, "Bi Shou (Dagger) attack")
    engine = reload_check(service, mid)
    before = len(engine.events)
    act(service, table, mid, mode, monkeypatch, "Duan Jian (Short Sword) off-hand attack")
    engine = reload_check(service, mid)
    packets = [e for e in engine.events[before:] if e.event_type == "DAMAGE_COMMITTED"]
    # Reviewed native criticals (031d3e69) double the weapon dice in one packet,
    # before mitigation. Overlapping widened ranges still upgrade only once.
    assert len(packets) == 1
    rolls = [e.payload for e in engine.events[before:] if e.event_type == "DAMAGE_ROLLED"]
    assert len(rolls) == 1 and rolls[0]["critical"]
    assert rolls[0]["expression"] == "2d6+0" and len(rolls[0]["dice"]) == 2
    assert packets[0].payload["rolled_or_pending_damage"] == rolls[0]["total"]
    upgrades = [e.payload for e in engine.events[before:] if e.event_type == "ATTACK_CRITICAL_RESOLVED"]
    assert len(upgrades) == 1 and upgrades[0]["critical_threshold"] == 19
    assert upgrades[0]["critical"] and not upgrades[0]["cancelled"]


@pytest.mark.parametrize("mode", ["MANUAL", "LOCAL_AUTO"])
@pytest.mark.parametrize("sphere,ids", [
    ("tianxia.sphere.drunken_style", ["TAL_DRUNKEN_STYLE_SLEEVE_BOWL_AND_BOOT"]),
    ("tianxia.sphere.barrage", ["TAL_BARRAGE_VIGILANT_SHARPSHOOTER"])])
def test_unsupported_riders_do_not_overgrant_after_commit_reload(tmp_path, monkeypatch, mode, sphere, ids):
    service, table, mid = make_table(tmp_path, ids, sphere, mode,
                                    items=() if sphere == "tianxia.sphere.drunken_style" else (BOW, JIAN))
    end_until_hero(table, mid)
    engine = service._load_session(mid).engine
    assert not any(c.display_name.startswith("Reeling Step + Sleeve") for c in engine.legal_candidates())
    act(service, table, mid, mode, monkeypatch, "Dodge")
    engine = reload_check(service, mid)
    assert not any(c.condition_id == "condition:typed.improvised" for c in engine.state.actors[PREFIX + "aaaaaaaa"].conditions.values())
    from combat.typed_reactions import opportunity_reach
    assert opportunity_reach(engine, engine.state.actors[PREFIX + "aaaaaaaa"]) == 5
    if sphere == "tianxia.sphere.drunken_style" and mode == "MANUAL":
        # Picking up an object by the ordinary interaction is real possession;
        # the withdrawn Sleeve permission must never discard it at turn end.
        act(service, table, mid, mode, monkeypatch, "Grab an improvised weapon")
        engine = reload_check(service, mid)
        assert any(c.condition_id == "condition:typed.improvised" for c in engine.state.actors[PREFIX + "aaaaaaaa"].conditions.values())
        state = table.state(mid)
        if mode == "MANUAL":
            menu = state["menu"]
            table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], state["last_sequence"])
        else:
            act(service, table, mid, mode, monkeypatch, "End turn")
        end_until_hero(table, mid)
        engine = reload_check(service, mid)
        assert any(c.condition_id == "condition:typed.improvised" for c in engine.state.actors[PREFIX + "aaaaaaaa"].conditions.values())


def test_shared_spotlight_descriptions_explain_the_option_benefit():
    from tests.rider_sheet_support import bundle
    actions = bundle(["tianxia.talent.beauty.shared_spotlight"], sphere="tianxia.sphere.beauty",
                     actor_id=PREFIX + "riders_c10")["action_catalog"]
    shared = [a for a in actions if "Shared Spotlight" in a["display_name"]]
    assert len(shared) == 2
    for action in shared:
        description = action["parameters"]["description"]
        assert "Bonus Action (0 CP)" in description and "1 minute" in description and "30 feet" in description
        assert "Advantage" in description and "you both get it" not in description
