"""Owned Ink base actions through real portable characters and cold table saves."""
import hashlib
import json

import pytest

from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.r1i_service_support import fixture, candidate, force_ai_candidate, OWNER, FOE, SECOND
from tests.test_r1i_round3 import resolve, reload

LASH = "INK_BASE_INK_LASH"
MARK = "INK_BASE_PRESS_MARK"


def test_exact_controlling_sources():
    text = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())
    for mid, digest in {
        MARK: "9fd6868f0da3b4350f74766d3115733a199171096ff35889a2004d4063e01212",
        LASH: "815dcb924de33a678ede379f9b44d350b4e0adb298d0148484b7689c84682495",
    }.items():
        assert hashlib.sha256(text[mid].encode()).hexdigest() == digest


def test_lash_and_mark_are_native_sphere_grants_not_learned_talent_choices(tmp_path):
    import zipfile

    combat, table, mid, send, commit = fixture(tmp_path, ["tianxia.talent.ink.binding_script"], seed="INK-BASE-DELIVERY")
    archive = tmp_path / "portable_characters" / OWNER.removeprefix("actor:factory.") / "current.zip"
    with zipfile.ZipFile(archive) as source:
        doc = json.loads(source.read("Tianxia_Owner_Character_Sheet_v1.json"))
    learned = doc["spheres_and_talents"]["learned_talent_record_ids"]
    assert LASH not in learned and MARK not in learned
    engine = reload(tmp_path, mid)
    sources = {(a.parameters.get("typed") or {}).get("source") for a in engine.action_catalog.values() if a.owner_id == OWNER}
    assert {LASH, MARK} <= sources
    resolve(combat, mid, send, candidate(table, mid, "Ink Lash", FOE),
            {"choice:needle.ink_lash_damage": "PSYCHIC"})
    assert any(e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids for e in reload(tmp_path, mid).events)


def map_objects(monkeypatch):
    original = CombatService.factory_arenas

    def arenas(service, *args, **kwargs):
        result = original(service, *args, **kwargs)
        arena = result["battlefield:factory_pillar_arena"]
        arena["map_objects"] = [
            {"id": 714, "kind": "crate", "x": 3, "y": 7,
             "ac": 1, "hp": 200, "unattended": True},
            {"id": 715, "kind": "crate", "x": 2, "y": 6,
             "ac": 1, "hp": 200, "unattended": False},
        ]
        return result

    monkeypatch.setattr(CombatService, "factory_arenas", arenas)


@pytest.mark.parametrize("cl,count", [(1, 1), (4, 1), (5, 2), (10, 2), (11, 3), (16, 3), (17, 4), (20, 4)])
def test_lash_printed_scaling_player_choice_and_cold_commit(tmp_path, cl, count):
    combat, table, mid, send, commit = fixture(tmp_path, [LASH], owner_cl=cl, seed="INK-BASE-DELIVERY")
    before, prompts = resolve(combat, mid, send, candidate(table, mid, "Ink Lash", FOE),
                              {"choice:needle.ink_lash_damage": "PSYCHIC"})
    prompt = next(p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.ink_lash_damage")
    assert all(word in str(prompt) for word in ("Ink Lash", "Foe", "Action", "no Cultivation Points"))
    engine = reload(tmp_path, mid)
    attacks = [e for e in engine.events if e.event_type == "ATTACK_ROLLED" and FOE in e.target_ids]
    assert attacks and attacks[-1].payload["provisional_hit"]
    damage = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids]
    assert damage and "PSYCHIC" in str(damage[-1].payload)
    rolls = [r for r in engine.rolls if str(r.reason).startswith("DAMAGE:")]
    assert rolls
    # Actual rolled dice, including the native key modifier, rather than just compilation metadata.
    assert rolls[-1].expression.startswith(f"{count}d8")
    assert len(rolls[-1].dice) == count
    assert rolls[-1].modifier == 2
    assert engine.state.actors[OWNER].resources == before["actors"][OWNER]["resources"]
    assert not engine.state.actors[OWNER].action_available
    assert not any(a.owner_id == SECOND and (a.parameters.get("typed") or {}).get("source") == LASH
                   for a in engine.action_catalog.values())


@pytest.mark.parametrize("kind", ["SLASHING", "PSYCHIC"])
@pytest.mark.parametrize("object_id", ["object:map.714", "object:map.715"])
def test_lash_object_delivery_choice_precedes_roll_and_keeps_defenses(tmp_path, monkeypatch, kind, object_id):
    map_objects(monkeypatch)
    combat, table, mid, send, commit = fixture(tmp_path, [LASH], seed="INK-BASE-DELIVERY")
    cid = candidate(table, mid, "Ink Lash", object_id)
    result = send(cid)
    assert result["status"] == "REACTION_REQUIRED"
    assert result["reaction"]["context"]["reaction_source_id"] == "choice:needle.ink_lash_damage"
    assert not any(e.event_type == "ATTACK_ROLLED" for e in reload(tmp_path, mid).events)
    before, prompts = resolve(combat, mid, send, cid, {"choice:needle.ink_lash_damage": kind})
    engine = reload(tmp_path, mid)
    attack = next(e for e in engine.events if e.event_type == "ATTACK_ROLLED" and object_id in e.target_ids)
    assert attack.payload["provisional_hit"]
    obj = engine.state.objects[object_id]
    assert (obj.current_hp < 200) == (kind == "SLASHING")  # Ordinary objects are Psychic immune.
    assert not obj.destroyed
    assert engine.state.actors[OWNER].resources == before["actors"][OWNER]["resources"]
    assert "GM decides" in str(prompts)


def test_lash_ai_declares_without_private_defense_choice(tmp_path):
    combat, table, mid, send, commit = fixture(tmp_path, [LASH], seed="INK-BASE-DELIVERY")
    cid = candidate(table, mid, "Ink Lash", FOE)
    force_ai_candidate(combat, mid, OWNER, cid)
    before, prompts = resolve(combat, mid, send, cid, {}, auto=True)
    assert not prompts
    engine = reload(tmp_path, mid)
    damage = next(e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids)
    assert "SLASHING" in str(damage.payload)


def test_lash_declares_before_a_miss_and_does_no_damage(tmp_path):
    combat, table, mid, send, commit = fixture(tmp_path, [LASH], foe_ac=1000, seed="INK-BASE-DELIVERY")
    before, prompts = resolve(combat, mid, send, candidate(table, mid, "Ink Lash", FOE),
                              {"choice:needle.ink_lash_damage": "PSYCHIC"})
    assert any(p["context"]["reaction_source_id"] == "choice:needle.ink_lash_damage" for p in prompts)
    engine = reload(tmp_path, mid)
    attack = next(e for e in engine.events if e.event_type == "ATTACK_ROLLED" and FOE in e.target_ids)
    assert not attack.payload["provisional_hit"]
    assert engine.state.actors[FOE].current_hp == before["actors"][FOE]["current_hp"]
    assert not any(e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids for e in engine.events)


def test_lash_range_boundary_is_native_for_both_types(tmp_path):
    combat, table, mid, send, commit = fixture(tmp_path, [LASH], wide=True,
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 15, "y": 6}, SECOND: {"x": 16, "y": 6}})
    engine = reload(tmp_path, mid)
    targets = {tid for c in engine.legal_candidates() if c.display_name == "Ink Lash" for tid in c.target_ids}
    assert FOE in targets
    assert SECOND not in targets


def test_lash_declaration_does_not_retype_additional_fixed_damage(tmp_path):
    """A separate packet is setup only; the shipped Lash row stays intact."""
    from combat.canonical import canonical_sha256

    def extra_packet(bundles):
        owner = next(b for b in bundles if b["actor_id"] == OWNER)
        lash = next(a for a in owner["action_catalog"] if a["display_name"] == "Ink Lash")
        lash["parameters"]["typed"]["effects"].append(
            {"type": "damage", "flat": 1, "damage_types": ["fire"], "applies_to": "target"})
        owner.pop("bundle_sha256", None)
        owner["bundle_sha256"] = canonical_sha256(owner)

    combat, table, mid, send, commit = fixture(tmp_path, [LASH], seed="INK-BASE-DELIVERY", bundle_transform=extra_packet)
    resolve(combat, mid, send, candidate(table, mid, "Ink Lash", FOE),
            {"choice:needle.ink_lash_damage": "PSYCHIC"})
    engine = reload(tmp_path, mid)
    packets = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids]
    assert len(packets) == 2
    assert "PSYCHIC" in str(packets[0].payload)
    assert "FIRE" in str(packets[1].payload)
