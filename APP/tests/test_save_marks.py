""""Failed Save: ... Gain one Depth Mark." marks the creature that failed (fight audit 2026-09-29: it was a resource for
the user, "Gain resource not identified")."""

import json
import pytest

from combat.factory_compiler import TYPED_AUTHORITY

MECH = json.loads(TYPED_AUTHORITY.read_bytes())["mechanics"]


def _fail_effects(key):
    # A reviewed Domain delivers its save on enter/start, not on creation.
    effects = MECH[key]["effects"]
    saves = [e for e in effects if e.get("type") == "save"]
    saves += [e for zone in effects if zone.get("type") == "zone"
              for trigger in zone.get("triggers", []) for e in trigger.get("effects", []) if e.get("type") == "save"]
    assert len(saves) == 1, key
    save = saves[0]
    return save["on_fail"]


def test_a_failed_save_mark_lands_on_the_saver():
    for key, mark in (("tianxia.subpath.qi.black_sea_leviathan_womb.feature.abyssal_maw", "Depth Mark"),
                      ("tianxia.subpath.qi.black_sea_leviathan_womb.feature.gate_of_the_inner_sea", "Depth Mark"),
                      ("tianxia.talent.poison.poison_domain", "Dose Mark")):
        effects = _fail_effects(key)
        marks = [e for e in effects if e.get("type") == "mark"]
        assert len(marks) == 1, key
        assert {"type": "mark", "mark": mark, "applies_to": "target"}.items() <= marks[0].items(), key
        assert not any(e.get("type") == "gain_resource" and "Mark" in str(e.get("evidence")) for e in effects), key


def _self_denials(node):
    if isinstance(node, dict):
        hit = node.get("applies_to") == "self" and (node.get("type") == "reaction_denied" or node.get("condition") == "reaction_denied")
        return [node] * hit + [row for value in node.values() for row in _self_denials(value)]
    if isinstance(node, list):
        return [row for value in node for row in _self_denials(value)]
    return []


def test_only_cannot_take_reactions_denies_the_users_own_reactions():
    """Fight audit 2026-09-29: Cauldron Guard's "you may use your Reaction" and ~30 "without provoking Opportunity Attacks"
    lines were typed as reaction_denied on the user and took its Reactions away."""
    left = [row for mechanic in MECH.values() for row in _self_denials(mechanic)]
    # A catalog with no self denials is safe too. Keep the evidence check on
    # every present row; the detector controls below prevent vacuous coverage.
    assert all("cannot take" in str(row.get("evidence")).lower() for row in left)
    forge = next(m for m in MECH.values() if m["name"] == "Heart of the Forge")
    assert any(e.get("type") == "movement" and e.get("no_opportunity_attacks") and e.get("distance_ft") == 10 for e in forge["effects"])


@pytest.mark.parametrize("condition_row", [False, True])
@pytest.mark.parametrize("evidence, permitted", [
    ("You cannot take Reactions until your next turn.", True),
    ("You may use your Reaction.", False),
    ("Move 10 feet without provoking Opportunity Attacks.", False),
])
def test_self_denial_guard_detects_both_shapes_and_rejects_unrelated_reaction_text(condition_row, evidence, permitted):
    row = {"type": "condition" if condition_row else "reaction_denied", "applies_to": "self", "evidence": evidence}
    if condition_row:
        row["condition"] = "reaction_denied"
    found = _self_denials({"effects": [{"on_hit": [row]}]})
    assert found == [row]
    assert all("cannot take" in str(item.get("evidence")).lower() for item in found) == permitted


def test_dust_to_dust_never_hits_a_creature_with_an_object_form():
    """Fight audit 2026-09-29: Crumble Matter's "5-foot cube of mundane cloth" became the whole ability's area, so the AI
    dealt 40 damage (no attack, no save) to creatures in a cube; Reduce Structure (Constructs and objects) did 6d8."""
    dust = MECH["tianxia.subpath.qi.dust_cultivator.feature.dust_to_dust"]
    options = {o["label"]: o for o in dust["options"]}
    assert not dust.get("area")
    # Sysv2 objects: both forms are object_damage, which acts on a placed object and on nothing else (a creature has none).
    assert [e["type"] for e in options["Crumble Matter"]["effects"]] == ["object_damage"]
    assert [e["type"] for e in options["Reduce Structure"]["effects"]] == ["object_damage"]
    assert [e["type"] for e in options["Erode Defense"]["effects"]] == ["save"]
