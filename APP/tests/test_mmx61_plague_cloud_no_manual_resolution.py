"""Hunt 79 (MMX61 review fix 1): Plague Cloud's printed effects are applied, so no line may ask the GM to apply them again.

The bug this closes: ``reviewed_final.d/martial.json`` typed Plague Cloud's paid modifier as a single
bare ``{"type": "rider"}`` effect whose evidence repeated all three printed outcomes. That rider was
appended to the compiled ability and emitted as a GM_RIDER, so the fight log told the GM to apply
"the area becomes lightly obscured, and enemies that fail their save ... also gain one Contagion
Token; at Core Formation, they also cannot regain more than half the normal Hit Points from healing"
while ``combat/ext/disease.py`` (added in 85cf9b3e) was already doing every one of them. The player
saw an effect both applied and outstanding, and a GM who believed the line applied it twice.

The rider is now gone from the typed data (the modifier's ``effects`` list is empty, with a note
recording that the plug-in applies it). The 2 extra CP, the "in Outbreak Mode" precondition and the
paid variant itself are unchanged: this test proves the option is still there, still costs 4 Qi, and
still runs its three effects exactly once each.

This is a table-feed test. It plays a real fight through ``TabletopService`` and reads the same
player-visible event feed the players read, and checks the raw recorded rider payloads as well as the
rendered lines, because the renderer strips a clause that says "the table" or "GM" -- the old payload
was contradicted by its own rendering, which is why only the recorded text can prove the defect.
"""

from __future__ import annotations

from combat.ext.disease import tokens
from tests.test_disease_plague_cloud import (
    FOE, PLACES, PLAGUE, VEIL, fight, fresh, turn_of, use_ability,
)

# The three printed outcomes, in the words the rules print them.
OBSCURES = "lightly obscured"
GAINS_TOKEN = "also gain one Contagion Token"
HEALING_CAP = "regain more than half the normal Hit Points from healing"


def _riders(table, mid):
    """Every rider the fight actually recorded, as the raw payload text."""
    return [str((row["raw"].get("payload") or {}).get("rider") or "")
            for row in table.events(mid, 0)["events"] if row["event_type"] == "GM_RIDER"]


def _summaries(table, mid):
    return [row["summary"] for row in table.events(mid, 0)["events"]]


def _played(tmp_path):
    """One Plague Cloud activation and the enemy's failed save against the veil it raised."""
    combat, table, mid = fight(tmp_path, cl=12)
    use_ability(table, mid, turn_of(table, mid, FOE), "Plague-Bearing Body")
    use_ability(table, mid, turn_of(table, mid, PLAGUE), VEIL, centre_on=PLACES[FOE])
    turn_of(table, mid, FOE)  # the veil's save resolves at the enemy's turn start
    return combat, table, mid


def test_the_paid_variant_still_exists_and_still_costs_its_two_extra_cp():
    """Removing the rider must not remove the option the player is buying."""
    from combat.factory_compiler import compile_character
    from tests.h1_support import sheet
    from tests.test_disease_plague_cloud import CLOUD, SOW, mechanics

    mechs = mechanics()
    bases = [k for k, m in mechs.items() if m.get("sphere_id") == mechs[SOW]["sphere_id"]
             and m.get("kind") == "base_ability"]
    bundle = compile_character(sheet(list(dict.fromkeys([*bases, SOW, CLOUD])), cl=12, dc=50), actor_id=PLAGUE)
    priced = {a["display_name"]: sum(amount for _pool, amount in a["costs"]) for a in bundle["action_catalog"]
              if "Quarantine Veil" in a.get("display_name", "")}
    assert priced[VEIL] == 4, priced  # 2 CP for the veil, 2 extra CP for Plague Cloud
    assert priced["Raise the Quarantine Veil: Outbreak Mode"] == 2, priced


def test_no_recorded_rider_asks_the_gm_to_apply_plague_clouds_effects_again(tmp_path):
    """The recorded rider text is the defect: it repeated all three applied outcomes."""
    _combat, table, mid = _played(tmp_path)
    for rider in _riders(table, mid):
        for printed in (OBSCURES, GAINS_TOKEN, HEALING_CAP):
            assert printed not in rider, f"still left for the GM to apply: {rider!r}"


def test_no_player_line_says_the_gm_must_resolve_a_plague_cloud_effect(tmp_path):
    """The same defect as the player reads it, in the shipped feed."""
    _combat, table, mid = _played(tmp_path)
    for line in _summaries(table, mid):
        if "the GM must resolve" not in line:
            continue
        for printed in ("the area becomes lightly obscured", "gain one Contagion Token",
                        "regains only half the Hit Points"):
            assert printed not in line, f"told to apply by hand: {line!r}"


def test_each_printed_effect_is_applied_exactly_once_not_twice(tmp_path):
    """One activation, one note per creature the veil caught, and one token and one cap each.

    The veil catches every enemy standing in it, so the count that matters is "one per creature the
    save actually failed against" -- twice that would be the GM line being applied a second time.
    """
    combat, table, mid = _played(tmp_path)
    lines = _summaries(table, mid)
    engine = fresh(combat, mid).engine
    maker = engine.state.actors[PLAGUE]

    # The area became lightly obscured once, for the single activation that paid the 2 extra CP.
    assert len([line for line in lines if "is lightly obscured" in line]) == 1, lines

    caught = [a for a in engine.state.actors.values() if tokens(engine, maker, a) > 0]
    assert caught, "the veil's failed save granted no Contagion Token at all"
    # One token note per creature, and exactly one token on each: a second application is the bug.
    # Other owned abilities can carry manual token reminders. Count this
    # activation's actual Plague Cloud notes, retaining the exact state count.
    assert len([line for line in lines if line.startswith("Plague Cloud:")
                and "gains one Contagion Token" in line]) == len(caught), lines
    for creature in caught:
        assert tokens(engine, maker, creature) == 1, creature.display_name

    capped = [a for a in engine.state.actors.values()
              if any((c.data or {}).get("rule", {}).get("healing_halved") for c in a.conditions.values())]
    assert capped, "Core Formation caps healing, and the cap was never applied"
    # The new condition log also describes its healing cap. Count the actual
    # Plague Cloud application notices, alongside exact stored condition counts.
    assert len([line for line in lines if line.startswith("Plague Cloud:")
                and "regains only half the Hit Points" in line]) == len(capped), lines
    for creature in capped:
        caps = [c for c in creature.conditions.values() if (c.data or {}).get("rule", {}).get("healing_halved")]
        assert len(caps) == 1, f"the healing cap was applied twice to {creature.display_name}"

    assert fresh(combat, mid).mechanical.replay()["status"] == "PASS"
