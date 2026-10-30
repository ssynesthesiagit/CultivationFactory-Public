"""Crown Soul Gate: Spiritual Truesight is live only while Crown Opening holds (MGR-T14).

The grant compiles into the bundle with every other always-on sense row; the shared
``sense_grant_allowed`` seam (combat/ext/inner_soul_gate.py) excludes it until the
owner's own Crown Opening is the live Gate Opening. This drives the real service and
table: the foe turns Invisible through its own committed action, the ally pays 9
Resonance for Crown Opening through a committed session intent, the table commits and
cold-reloads, and every assertion reads the reloaded engine's live sense queries --
owned but inactive, active, Opening removal, an independent Truesight source, and the
perception-cell and real-creature query shapes.
"""
import json
import zipfile
from pathlib import Path

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat import senses
from combat.ext.inner_soul_gate import OPENING, RESONANCE, has_gate
from combat.gate2_runtime_models import Position
from tests.cw2_service_support import add_action, seal
from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, ALLY, FOE, candidate, reload, settle, turn

SG = "tianxia.tradition.spirit.inner_soul_gate_ascetic.feature."
GATES = [SG + k for k in ("root_soul_gate", "sacral_soul_gate", "solar_soul_gate",
                          "heart_soul_gate", "crown_soul_gate")]
# Nine Heavens Gaze: a permanent Truesight 60 feet from a different record, so the
# Crown's gate can be shown to leave an independent Truesight source alone.
IMMORTAL_OF_QI = "tianxia.path.qi_cultivation.feature.immortal_of_qi"


def fight(tmp_path, *, seed="MGRT14CROWN"):
    """The owner keeps the independent permanent Truesight source; the ally owns the
    Soul Gates alone, so Spiritual Truesight is its only pinpointing sense."""
    ids = [OWNER, ALLY, FOE]
    docs = [sheet([IMMORTAL_OF_QI], cl=18), sheet(GATES, cl=18, primary="Resonance"), sheet([], cl=18)]
    bundles = []
    for aid, doc in zip(ids, docs):
        folder = tmp_path / "portable_characters" / aid.removeprefix("actor:factory.")
        folder.mkdir(parents=True)
        doc["ability_scores_and_statistics"]["primary_resource"]["maximum"] = 100
        doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = 300
        with zipfile.ZipFile(folder / "current.zip", "w") as z:
            z.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
        bundles.append(compile_character(doc, actor_id=aid, reaction_plan={"ask": True}))
    for bundle, init in zip(bundles, [100, -100, 0]):
        bundle["actor_template"]["initiative_bonus"] = init
        seal(bundle)
    owner, ally, foe = bundles
    # A sealed setup action: the foe turns Invisible through a real table transaction.
    add_action(foe, "Test: invisible", [{"type": "condition", "condition": "invisible",
                                         "applies_to": "self", "duration": "until_removed"}], target="SELF")
    seal(foe)
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(bundles, ids,
        {OWNER: "team:a", ALLY: "team:a", FOE: "team:b"},
        {OWNER: {"x": 3, "y": 6}, ALLY: {"x": 4, "y": 6}, FOE: {"x": 6, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"],
        [OWNER, ALLY], [FOE], control_modes={aid: "MANUAL" for aid in ids},
        match_seed=seed, display_name="Crown Opening sense gate", maximum_rounds=15)["match_id"]
    turn(table, mid, OWNER)
    return combat, table, mid


def use(combat, table, mid, name, target=None, picks=None):
    return settle(table, mid, candidate(combat, mid, name, target=target).candidate_id, picks)


def opening_of(engine, actor):
    return next((c for c in actor.conditions.values()
                 if c.condition_id == OPENING and c.source_actor_id == actor.entity_id), None)


def test_crown_soul_gate_spiritual_truesight_requires_a_live_crown_opening(tmp_path):
    c, t, mid = fight(tmp_path)

    # The foe turns Invisible on its own turn, before any Gate Opening exists.
    turn(t, mid, FOE)
    use(c, t, mid, "Test: invisible", FOE)

    # Owned but inactive: the ally owns the Crown Soul Gate, yet no Gate Opening is
    # live, so its Spiritual Truesight grant is excluded from every sense query and
    # the Invisible foe stays beyond every one of the ally's senses.
    turn(t, mid, ALLY)
    e = reload(tmp_path, mid)
    ally = e.state.actors[ALLY]
    assert has_gate(e, ally, "crown")
    assert opening_of(e, ally) is None
    assert "spiritual_truesight" not in senses.of(e, ally)
    assert not senses.pinpoints(e, ally, e.state.actors[FOE])
    assert senses.reach(e, ally, "spiritual_truesight", e.state.actors[FOE]) == 0
    assert e.state.actors[FOE].entity_id not in senses.perception(e, ally)["creatures"]
    # The owner's independent Truesight source is untouched by the Crown's gate.
    assert senses.of(e, e.state.actors[OWNER])["truesight"]["range_ft"] == 60

    # Activate through the service: Crown Opening is a Bonus Action costing 9 Resonance.
    before = ally.resources[RESONANCE]
    use(c, t, mid, "Crown Opening", ALLY)
    e = reload(tmp_path, mid)  # the paid Opening survives the table commit and a cold reload
    ally = e.state.actors[ALLY]
    held = opening_of(e, ally)
    assert held is not None and held.data["gate"] == "crown"
    assert ally.resources[RESONANCE] == before - 9
    assert senses.of(e, ally)["spiritual_truesight"]["range_ft"] == 30
    # Real-creature query: the live Opening pinpoints the Invisible foe within 30 feet,
    # and the Crown's own masked-conditions clause lets the ally perceive it.
    foe = e.state.actors[FOE]
    assert senses.pinpoints(e, ally, foe)
    assert senses.reach(e, ally, "spiritual_truesight", foe) == 30
    assert foe.entity_id in senses.perception(e, ally)["creatures"]
    # The owner's independent Truesight source is still untouched.
    assert senses.of(e, e.state.actors[OWNER])["truesight"]["range_ft"] == 60

    # Lightweight perception-cell query: the eligibility seam answers for a cell probe
    # exactly as for a creature, and ordinary cell sight is unchanged.
    probe = senses.cell_probe(Position(x=6, y=6))
    assert senses.of(e, ally, seen=probe)["spiritual_truesight"]["range_ft"] == 30
    assert senses.perceives_cell(e, ally, Position(x=6, y=6))

    # State removal: opening another Gate Opening on the ally's next turn ends the
    # Crown Opening and its Spiritual Truesight; the owner's Truesight remains.
    turn(t, mid, FOE)
    turn(t, mid, ALLY)
    use(c, t, mid, "Root Opening", ALLY)
    e = reload(tmp_path, mid)
    ally = e.state.actors[ALLY]
    assert opening_of(e, ally).data["gate"] == "root"
    assert "spiritual_truesight" not in senses.of(e, ally)
    assert senses.of(e, e.state.actors[OWNER])["truesight"]["range_ft"] == 60
