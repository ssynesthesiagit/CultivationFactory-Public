"""Imbuement property systems: accepted table actions, cold reload and replay."""
import copy
import json
from pathlib import Path

import pytest

from combat.canonical import canonical_sha256
from combat.gate2_rolls import DeterministicRollAuthority
from combat.gate5_service import CombatService
from tests import r1i_service_support as S
from tests.h1_support import ROOT

IMB = "tianxia.talent.imbuement."
PROBE = "action:test.property_probe"
DAO = {"item_id": "tianxia.mortal.weapon.dao", "name": "Dao", "quantity": 1}
# The sheet's default STR 14 is +2, and a Dao attack adds the attacker's STR modifier to its d8 (a fixed roll of 8).
STR_MOD = 2
DAO_HIT = 8 + STR_MOD


def cold(tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.mechanical.replay()["status"] == "PASS"
    return session.engine


def armor_class(engine, actor_id):
    actor = engine.state.actors[actor_id]
    return actor.armor_class + engine._ac_modifier(actor)


def fixed(monkeypatch, value=10):
    def die(self, sides):
        counter = self.counter
        self.counter += 1
        return min(value, sides), counter
    monkeypatch.setattr(DeterministicRollAuthority, "_die", die)


def act(combat, table, mid, send, source_suffix, target, choices=None, actor=S.OWNER):
    engine = combat._load_session(mid).engine
    action = next(a for a in engine.action_catalog.values()
                  if a.owner_id == actor and a.source_definition_id.endswith(source_suffix))
    try:
        cid = S.candidate(table, mid, action.display_name, target)
    except StopIteration:
        raise AssertionError(f"{action.display_name!r} is not offered to {actor} against {target}") from None
    answers, prompts = [], []
    for _ in range(20):
        response = send(cid, answers)
        if response["status"] == "COMMITTED":
            return action.source_definition_id, prompts
        assert response["status"] == "REACTION_REQUIRED", response
        prompt = response["reaction"]
        prompts.append(prompt)
        key = prompt["context"]["reaction_source_id"]
        answer = {**prompt["context"], "selection": "DECLINE"}
        choice = prompt.get("choice")
        if choice:
            options = [o["id"] for o in choice["options"]]
            wanted = (choices or {}).get(key)
            if wanted is None and key != "choice:needle.d20_floor_keep" and not choice.get("allow_decline"):
                wanted = options[:1]
            if wanted is not None:
                assert set(wanted) <= set(options)
                answer.update(selection="USE", option_ids=wanted)
        answers.append(answer)
    raise AssertionError("unresolved choices")


def setup(monkeypatch, tmp_path, talent, *, proficient=False, probe="save", material=None,
          magic=0, bearer_pb=6, probe_actor=S.OWNER, mundane_resistance=False, armor_magic=None,
          unrelated_resistance=False):
    sheet = S.sheet
    def document(*args, **kwargs):
        doc = sheet(*args, **kwargs)
        kit = {"items": [DAO]}
        if armor_magic is not None:
            from combat import armour
            kit["resolved_treasure_armor"] = {
                "chassis": dict(armour.catalog()["tianxia.mortal.armor.imperial_plate_battle_dress"]),
                "refinement_bonus": armor_magic, "enhancements": []}
            doc["proficiencies"] = {"armor": ["Heavy Armor", "Shield"]}
        doc["equipment"] = [{"starting_kit": kit}]
        stats = doc["ability_scores_and_statistics"]
        stats["saving_throw_proficiencies"] = ["WIS"] if proficient else []
        if not args[0]:
            doc["identity"]["proficiency_bonus"] = bearer_pb
        if proficient:
            wisdom = next(a["score"] for a in stats["abilities"] if a["ability"] == "WIS")
            stats["saving_throws"] = {"WIS": (wisdom - 10) // 2 + doc["identity"]["proficiency_bonus"]}
        return doc
    monkeypatch.setattr(S, "sheet", document)

    def transform(bundles):
        owner = next(b for b in bundles if b["actor_id"] == probe_actor)
        action = copy.deepcopy(owner["action_catalog"][0])
        action.update(source_definition_id=PROBE, display_name="Property probe", economy="NONE",
                      target_kind="ANY_CREATURE", concentration=False, costs=[], save=None,
                      damage=None, damage_type=None, resolution_kind="TYPED", range_ft=120)
        typed = {"source": PROBE, "range_ft": 120, "numbers": {"save_dc": 50},
                 "duration": {"kind": "instant"}, "riders": []}
        native_wield = None
        if probe == "native_attack":
            # A legacy native stat block: no typed packet at all, only the physical weapon its attack delivers.
            native_wield = DAO["item_id"]
            action.update(resolution_kind="ATTACK", attack_bonus=100, range_ft=5, economy="BONUS_ACTION",
                          damage={"count": 1, "sides": 8, "modifier": 0}, damage_type="SLASHING")
            typed = {}
            if material:
                foe = next(b for b in bundles if b["actor_id"] == S.FOE)
                foe["typed_passives"].append({"block": "defense", "feature_id": "test:material_defense",
                    "kind": material, "damage_types": ["SLASHING"], "bypass_materials": ["silvered"]})
        elif probe in ("save", "native_save"):
            typed["effects"] = [{"type": "save", "ability": "WIS", "dc": 50,
                                 "applies_to": "target", "on_success": [], "on_fail": []}]
            if probe == "native_save":
                action.update(resolution_kind="SAVE_DAMAGE", save={"ability": "WIS", "dc": 50},
                              damage={"count": 1, "sides": 2, "modifier": 0}, damage_type="FORCE")
                typed = {}
        elif probe == "check":
            typed["effects"] = [{"type": "contest_against",
                "actor_check": {"kind": "check", "ability": "WIS"},
                "target_check": {"kind": "check", "ability": "STR"},
                "on_success": [], "on_fail": []}]
        else:
            weapon = next(a for a in owner["action_catalog"] if ".weapon.dao" in a["source_definition_id"]
                          and "#" not in a["source_definition_id"])
            wt = weapon["parameters"]["typed"]
            wt["magic_bonus"] = magic
            wt["mundane"] = not magic
            wt["numbers"]["attack_bonus"] = 100 + magic
            wt["weapon"]["damage"] = {"count": 1, "sides": 8, "modifier": magic}
            wt["effects"] = [{"type": "attack", "attack_kind": "weapon",
                             "on_hit": [{"type": "damage", "weapon_damage": True}]}]
            action["parameters"] = {"typed": copy.deepcopy(wt), "variant_of": weapon["source_definition_id"]}
            typed = action["parameters"]["typed"]
            action["range_ft"] = None
            if material or mundane_resistance:
                foe = next(b for b in bundles if b["actor_id"] == S.FOE)
                foe["typed_passives"].append({"block": "defense", "feature_id": "test:material_defense",
                    "kind": material or "resistance", "damage_types": ["SLASHING"],
                    **({"bypass_materials": ["silvered"]} if material else {"mundane_only": True})})
                if unrelated_resistance:
                    foe["typed_passives"].append({"block": "defense", "feature_id": "test:unrelated_defense",
                        "kind": "resistance", "damage_types": ["SLASHING"]})
        # Probes are setup actions outside the turn economy: the gate needs the explicit free_primary declaration.
        action["parameters"] = ({"delivered_by": native_wield, "free_primary": True} if native_wield
                                else {**action.get("parameters", {}), "typed": typed, "free_primary": True})
        owner["action_catalog"].append(action)
        owner["actor_template"]["action_ids"].append(PROBE)
        for bundle in bundles:
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)

    return S.fixture(tmp_path, [IMB + talent], allies=[S.SECOND], owner_kit={"starting_kit": {"items": [DAO]}},
                     bundle_transform=transform, wide=True)


@pytest.mark.parametrize("proficient", [False, True])
@pytest.mark.parametrize("native", [False, True])
def test_fortify_grants_recipient_proficiency_not_caster_bonus(monkeypatch, tmp_path, proficient, native):
    combat, table, mid, send, _ = setup(monkeypatch, tmp_path, "fortify_and_expose", proficient=proficient,
                                       probe="native_save" if native else "save")
    before = cold(tmp_path, mid).state.actors[S.SECOND]
    source, _ = act(combat, table, mid, send, ".mandate.imbue.fortify", S.SECOND,
                    {"choice:needle.mandate_choice": ["WIS"]})
    fixed(monkeypatch)
    act(combat, table, mid, send, PROBE, S.SECOND)
    engine = cold(tmp_path, mid)
    roll = next(r for r in reversed(engine.rolls) if r.reason.startswith("SAVE:") and PROBE in r.reason)
    bonus = 1 if proficient else before.proficiency_bonus
    assert roll.modifier == before.saving_throws["WIS"] + (bonus if native else 0)
    saved = next(e for e in reversed(engine.events) if e.event_type == "SAVE_ROLLED" and e.source_definition_id == PROBE)
    assert saved.payload["dc"] == 50 - (0 if native else bonus)
    assert any(c.source_definition_id == source for c in engine.state.actors[S.SECOND].conditions.values())


def test_clarify_bare_ability_check_uses_floor_and_asks_bearer_and_caster(monkeypatch, tmp_path):
    combat, table, mid, send, _ = setup(monkeypatch, tmp_path, "clarify_and_cloud", probe="check")
    source, _ = act(combat, table, mid, send, ".mandate.imbue.clarify", S.OWNER,
                    {"choice:needle.mandate_choice": ["WIS"]})
    fixed(monkeypatch, 1)
    _, prompts = act(combat, table, mid, send, PROBE, S.FOE,
                    {"choice:needle.d20_floor_use": ["use"]})
    engine = cold(tmp_path, mid)
    roll = next(r for r in reversed(engine.rolls) if r.reason == "CHECK:" + PROBE and r.actor_id == S.OWNER)
    assert roll.total - roll.modifier == 10
    assert any(p["context"]["reaction_source_id"] == "choice:needle.d20_floor_use" for p in prompts)
    assert not any(c.source_definition_id == source for c in engine.state.actors[S.OWNER].conditions.values()
                   if c.condition_id == "condition:typed.d20_floor")


@pytest.mark.parametrize("kind", ["resistance", "immunity"])
@pytest.mark.parametrize("unrelated", [False, True])
def test_sharpen_material_bypasses_only_matching_defense(monkeypatch, tmp_path, kind, unrelated):
    combat, table, mid, send, _ = setup(monkeypatch, tmp_path, "sharpen_and_dull", probe="attack", material=kind,
                                       unrelated_resistance=unrelated)
    fixed(monkeypatch)
    before = cold(tmp_path, mid).state.actors[S.FOE].current_hp
    act(combat, table, mid, send, PROBE, S.FOE)
    first = cold(tmp_path, mid).state.actors[S.FOE].current_hp
    assert before - first == ((DAO_HIT // 2) if kind == "resistance" else 0)
    source, _ = act(combat, table, mid, send, ".mandate.imbue.sharpen", S.OWNER,
                    {"choice:needle.mandate_choice": ["silvered"]})
    act(combat, table, mid, send, PROBE, S.FOE)
    engine = cold(tmp_path, mid)
    assert first - engine.state.actors[S.FOE].current_hp == ((DAO_HIT // 2) if unrelated else DAO_HIT)
    assert any(c.source_definition_id == source for c in engine.state.actors[S.OWNER].conditions.values())


@pytest.mark.parametrize("silvered", [False, True])
def test_sharpen_material_reaches_a_native_stat_blocks_own_weapon(monkeypatch, tmp_path, silvered):
    """Sharpen's material choice is a property of the weapon the attack is made with, native or typed.

    The probe is a legacy packet: no typed effects, one declaration that its attacks are made with the dao. The defense
    halves slashing damage unless the weapon is silvered, so the same attack must be halved without the choice and whole
    with it -- the material query follows the stat block's declared weapon through the shared packet_weapon seam.
    """
    combat, table, mid, send, _ = setup(monkeypatch, tmp_path, "sharpen_and_dull", probe="native_attack",
                                       material="resistance")
    fixed(monkeypatch)
    act(combat, table, mid, send, ".mandate.imbue.sharpen", S.OWNER,
        {"choice:needle.mandate_choice": ["silvered" if silvered else "critical"]})
    before = cold(tmp_path, mid).state.actors[S.FOE].current_hp
    act(combat, table, mid, send, PROBE, S.FOE)
    engine = cold(tmp_path, mid)
    assert before - engine.state.actors[S.FOE].current_hp == (DAO_HIT if silvered else DAO_HIT // 2)


@pytest.mark.parametrize("magic,expected", [(0, 2), (1, 2), (3, 3)])
def test_temper_uses_higher_magical_bonus(monkeypatch, tmp_path, magic, expected):
    combat, table, mid, send, _ = setup(monkeypatch, tmp_path, "tempered_equipment", probe="attack", magic=magic)
    fixed(monkeypatch)
    act(combat, table, mid, send, ".mandate.imbue.temper_weapon", S.OWNER)
    before = cold(tmp_path, mid).state.actors[S.FOE].current_hp
    act(combat, table, mid, send, PROBE, S.FOE)
    engine = cold(tmp_path, mid)
    assert before - engine.state.actors[S.FOE].current_hp == DAO_HIT + expected


def test_completed_records_have_no_top_level_riders():
    authority = json.loads((Path(__file__).parents[1] / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())
    for name in ("clarify_and_cloud", "fortify_and_expose", "sharpen_and_dull", "tempered_equipment"):
        record = authority["mechanics"][IMB + name]
        assert record["riders"] == []
        assert record["coverage"] == "FULL"


def test_temper_counts_as_magical_only_for_named_weapon(monkeypatch, tmp_path):
    combat, table, mid, send, _ = setup(monkeypatch, tmp_path, "tempered_equipment", probe="attack",
                                       mundane_resistance=True)
    fixed(monkeypatch)
    before = cold(tmp_path, mid).state.actors[S.FOE].current_hp
    act(combat, table, mid, send, PROBE, S.FOE)
    first = cold(tmp_path, mid).state.actors[S.FOE].current_hp
    assert before - first == DAO_HIT // 2
    act(combat, table, mid, send, ".mandate.imbue.temper_weapon", S.OWNER)
    act(combat, table, mid, send, PROBE, S.FOE)
    assert first - cold(tmp_path, mid).state.actors[S.FOE].current_hp == DAO_HIT + 2


def test_suppress_temper_removes_only_magical_attack_and_damage_bonus(monkeypatch, tmp_path):
    combat, table, mid, send, commit = setup(monkeypatch, tmp_path, "tempered_equipment", probe="attack",
                                            magic=3, probe_actor=S.FOE)
    fixed(monkeypatch, 1)
    source, _ = act(combat, table, mid, send, ".mandate.fray.suppress_temper_weapon", S.FOE)
    engine = cold(tmp_path, mid)
    assert any(c.source_definition_id == source and c.condition_id == "condition:typed.mandate_vessel"
               for c in engine.state.actors[S.FOE].conditions.values())
    while table.state(mid)["menu"]["actor_id"] != S.FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    fixed(monkeypatch)
    before = cold(tmp_path, mid).state.actors[S.OWNER].current_hp
    act(combat, table, mid, send, PROBE, S.OWNER, actor=S.FOE)
    engine = cold(tmp_path, mid)
    assert before - engine.state.actors[S.OWNER].current_hp == DAO_HIT
    roll = next(r for r in reversed(engine.rolls) if r.reason.startswith("ATTACK:") and PROBE in r.reason)
    assert roll.modifier == 100


@pytest.mark.parametrize("magic", [0, 3])
def test_temper_armor_uses_higher_existing_bonus(monkeypatch, tmp_path, magic):
    combat, table, mid, send, _ = setup(monkeypatch, tmp_path, "tempered_equipment", armor_magic=magic)
    engine = cold(tmp_path, mid)
    before = armor_class(engine, S.SECOND)
    bundle = next(b for b in engine.typed_bundle_documents if b["actor_id"] == S.SECOND)
    assert bundle.get("equipment_magic", {}).get("body", 0) == magic
    act(combat, table, mid, send, ".mandate.imbue.temper_armor", S.SECOND)
    engine = cold(tmp_path, mid)
    assert armor_class(engine, S.SECOND) == before + max(0, 2 - magic)


def test_suppress_temper_armor_removes_existing_bonus(monkeypatch, tmp_path):
    combat, table, mid, send, _ = setup(monkeypatch, tmp_path, "tempered_equipment", armor_magic=3)
    engine = cold(tmp_path, mid)
    before = armor_class(engine, S.FOE)
    fixed(monkeypatch, 1)
    act(combat, table, mid, send, ".mandate.fray.suppress_temper_armor", S.FOE)
    engine = cold(tmp_path, mid)
    assert armor_class(engine, S.FOE) == before - 3


def test_unarmed_and_improvised_vessels_remain_reachable(monkeypatch, tmp_path):
    combat, table, mid, send, _ = setup(monkeypatch, tmp_path, "sharpen_and_dull")
    _, prompts = act(combat, table, mid, send, ".mandate.imbue.sharpen", S.OWNER)
    weapon_prompt = next(p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.mandate_vessel")
    ids = [o["id"] for o in weapon_prompt["choice"]["options"]]
    engine = cold(tmp_path, mid)
    # Every available typed physical attack is reachable, including natural and
    # improvised attacks; a spell without physical delivery is not introduced.
    from combat.weapon_delivery import available_weapons
    assert set(ids) == set(available_weapons(engine, engine.state.actors[S.OWNER]))
    assert any(".natural." in key for key in ids)


def test_sharpen_once_bonus_uses_casters_proficiency(monkeypatch, tmp_path):
    combat, table, mid, send, commit = setup(monkeypatch, tmp_path, "sharpen_and_dull", probe="attack",
                                            probe_actor=S.SECOND)
    act(combat, table, mid, send, ".mandate.imbue.sharpen", S.SECOND,
        {"choice:needle.mandate_choice": ["damage"]})
    engine = cold(tmp_path, mid)
    bonus = engine.state.actors[S.OWNER].proficiency_bonus
    assert bonus != engine.state.actors[S.SECOND].proficiency_bonus
    while table.state(mid)["menu"]["actor_id"] != S.SECOND:
        commit(table.state(mid)["menu"]["end_turn"])
    fixed(monkeypatch)
    before = cold(tmp_path, mid).state.actors[S.FOE].current_hp
    act(combat, table, mid, send, PROBE, S.FOE, actor=S.SECOND)
    first = cold(tmp_path, mid).state.actors[S.FOE].current_hp
    assert before - first == DAO_HIT + bonus
    act(combat, table, mid, send, PROBE, S.FOE, actor=S.SECOND)
    assert first - cold(tmp_path, mid).state.actors[S.FOE].current_hp == 8
