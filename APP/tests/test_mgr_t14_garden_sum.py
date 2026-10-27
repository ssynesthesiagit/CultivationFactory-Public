"""MGR-T14-ling-garden-sum-1: Perfected Ninefold Red Lotus Ash Garden activation temp HP.

The printed clause "You gain temporary Hit Points equal to your Cultivation Level + your
Path key ability modifier" is one signed aggregate (CL5 with a -1 key modifier gives 4),
granted once per activation -- not one grant per typed row.
"""
import pytest
from combat.factory_compiler import compile_character
from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, fixture, candidate, settle, turn, reload

GARDEN = "foundation.red_lotus_ash_returning_v0_2B.perfected_ninefold_red_lotus_ash_garden"
GARDEN_NAME = "Perfected: Ninefold Red Lotus Ash Garden"
FOUNDATION = "red_lotus_ash_returning_v0_2B"

# Native loaders discover these split rows dynamically. Name the exact fixture
# inputs so a public snapshot retains Funeral Ash generation and Close Quarters
# ownership instead of silently exercising an incomplete combat ruleset.
FIXTURE_INPUTS = (
    "combat/rules/feature_blocks.d/foundations3.json",
    "combat/rules/feature_blocks.d/auto_lane3.json",
    "combat/rules/feature_blocks.d/auto8-athletics.json",
)


def test_garden_native_fixture_inputs_are_shipped():
    for relative in FIXTURE_INPUTS:
        assert (ROOT / relative).is_file(), f"Garden fixture requires shipped input: {relative}"


def garden_bundle(cl=5, key_score=8, stage="Perfected", actor_id=OWNER):
    """A Perfected Ash-Returning character: CL ``cl``, CON ``key_score`` (8 -> -1)."""
    doc = sheet([GARDEN], cl=cl, key="CON", score=key_score, foundation={
        "foundation_id": FOUNDATION, "stage": stage})
    return compile_character(doc, actor_id=actor_id, reaction_plan={"ask": True})


def setup(tmp_path, cl=5, key_score=8):
    return fixture(tmp_path, [], seed="MGRT14GSUM1",
                   owner_bundle=garden_bundle(cl, key_score), bundle_transform=lambda bundles: None)


def use(combat, table, mid, name, target=None):
    settle(table, mid, candidate(combat, mid, name, target=target).candidate_id)


def grants(engine, actor=OWNER):
    return [e for e in engine.events if e.event_type == "TEMP_HP_GRANTED"
            and e.actor_id == actor]


@pytest.mark.parametrize("cl,key_score,expected", [
    (5, 8, 4),    # CL5 + (-1): the signed aggregate acceptance case
    (5, 14, 7),   # positive control: CL5 + (+2)
    (11, 16, 14), # independent higher temp-HP control: CL11 + (+3)
    (1, 2, 0),    # the single signed sum floors only after CL1 + (-4)
])
def test_garden_activation_grants_signed_aggregate_once(tmp_path, cl, key_score, expected):
    combat, table, mid = setup(tmp_path, cl, key_score)
    use(combat, table, mid, GARDEN_NAME, OWNER)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert actor.temporary_hp == expected
    rows = grants(engine)
    assert len(rows) == 1, [(e.payload) for e in rows]
    assert rows[0].payload["offered"] == expected


def test_garden_activation_is_once_per_long_rest(tmp_path):
    combat, table, mid = setup(tmp_path, 5, 8)
    use(combat, table, mid, GARDEN_NAME, OWNER)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].temporary_hp == 4
    # Once per long rest: the activation is no longer a legal candidate.
    assert not [c for c in engine.legal_candidates()
                if getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', None) == GARDEN_NAME]
    assert [e.payload["offered"] for e in grants(engine)] == [4]


# --- MGR-T14-ling-garden-clock-1: the printed 1-minute Emanation runs the
# native zone consumer's shared round clock (the structured minutes1 duration). ---

import json
import zipfile

from combat import zones
from combat.gate5_service import CombatService
from combat.spatial_areas import zone_contains
from combat.tabletop_service import TabletopService

G_OWNER, G_FOE, G_SECOND = "actor:mgrt14-owner", "actor:mgrt14-foe", "actor:mgrt14-second"


def compiled_garden():
    """The compiled Perfected Garden action and its stored zone_spec (None before the clock fix)."""
    doc = sheet([GARDEN], cl=5, key="CON", score=8, foundation={
        "foundation_id": FOUNDATION, "stage": "Perfected"})
    bundle = compile_character(doc, actor_id="actor:factory.material_compile")
    for action in bundle["action_catalog"]:
        typed = action.get("parameters", {}).get("typed") or {}
        if typed.get("source") == GARDEN:
            return action, typed.get("zone_spec")
    return None, None


def test_garden_compiles_the_structured_minutes1_zone_clock():
    """Fail-before: the transient instant duration compiled no zone at all."""
    action, spec = compiled_garden()
    assert action is not None, "the Perfected Garden is not compiled onto the sheet"
    assert action["economy"] == "ACTION"
    # The once-per-long-rest cost compiles to the garden's own use counter.
    costs = [row[0] for row in action.get("costs") or []
             if str(row[0]).startswith("resource:uses.") and GARDEN in str(row[0])]
    assert costs, "the garden's once-per-long-rest use counter is missing"
    assert spec is not None, "the 1-minute Emanation compiled no zone (duration typed instant)"
    assert spec["duration"] == {"kind": "minutes", "amount": 1, "concentration": False}
    assert spec["shape"] == "emanation" and spec["size_ft"] == 30
    assert spec["centered_on_self"] is True
    assert spec["source_profile"]["mechanic_id"] == GARDEN


def garden_zone(engine):
    return next(z for z in zones.typed_zones(engine) if z.owner_id == G_OWNER)


def fresh(combat, mid):
    """A cold reload: a new service reading the committed fight back off disk."""
    session = CombatService(ROOT, combat.userdata_root)._load_session(mid)
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"
    return session.engine


def garden_match(tmp_path, *, maximum_rounds=10, seed="MGR-T14-GARDEN-CLOCK"):
    """A real Factory match through the native table service, like tests/r1i_service_support."""
    docs = [sheet([GARDEN], cl=5, key="CON", score=8, foundation={
        "foundation_id": FOUNDATION, "stage": "Perfected"}), sheet([], cl=5), sheet([], cl=5)]
    ids = [G_OWNER, G_FOE, G_SECOND]
    for aid, doc in zip(ids, docs):
        doc["identity"]["display_name"] = aid.split("mgrt14-")[-1].title()
        doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = 500
        doc["ability_scores_and_statistics"]["technique_attack_bonus"] = 100
        folder = tmp_path / "portable_characters" / aid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    bundles = [compile_character(doc, actor_id=aid) for aid, doc in zip(ids, docs)]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    saved = combat.tabletop_maps.save({"display_name": "MGR-T14 Garden Wide", "width_squares": 40,
        "height_squares": 20, "walls": [], "terrain": [],
        "starts": {"team1": [[10, 6]], "team2": [[13, 6], [3, 6]]}})
    arena = combat.factory_arenas()["battlefield:map." + saved["map_id"]]
    mid = combat._finish_factory_match(
        bundles, ids, {aid: "team:a" if aid == G_OWNER else "team:b" for aid in ids},
        {G_OWNER: {"x": 10, "y": 6}, G_FOE: {"x": 13, "y": 6}, G_SECOND: {"x": 3, "y": 6}},
        arena, [G_OWNER], ids[1:],
        control_modes={aid: "MANUAL" for aid in ids}, match_seed=seed,
        display_name="MGR-T14 Garden Clock", maximum_rounds=maximum_rounds)["match_id"]

    def commit(candidate_id):
        answers = []
        for _ in range(16):
            menu = table.state(mid)["menu"]
            result = table.act(mid, candidate_id, menu["decision_id"], menu["state_version"], 0, list(answers))
            if result["status"] == "COMMITTED":
                return result
            assert result["status"] == "REACTION_REQUIRED", result
            prompt = result["reaction"]
            answers.append({**prompt["context"], "selection": "DECLINE"})
        raise AssertionError("too many prompts")

    while table.state(mid)["menu"]["actor_id"] != G_OWNER:
        commit(table.state(mid)["menu"]["end_turn"])
    return combat, table, mid, commit


def garden_candidate(table, mid):
    return next(o["candidate_id"] for g in table.state(mid)["menu"]["actions"] if GARDEN_NAME in g["label"]
                for o in g["options"])


@pytest.mark.parametrize("maximum_rounds", [10])
def test_garden_activation_places_the_owned_minute_zone_and_reloads(tmp_path, maximum_rounds):
    """Real activation through the table: owned 30-foot zone, minute clock, cold reload."""
    combat, table, mid, commit = garden_match(tmp_path, maximum_rounds=maximum_rounds)
    assert commit(garden_candidate(table, mid))["status"] == "COMMITTED"
    engine = fresh(combat, mid)
    zone = garden_zone(engine)
    # Initial owner-centered placement: the garden stands where its owner stood when raised.
    assert (zone.center.x, zone.center.y) == (10, 6)
    assert zone.radius_cells == 6 and zone.trigger_profile["size_ft"] == 30
    # The structured minutes1 clock: 1 minute is 10 rounds on the shared round clock.
    assert zone.duration_rounds == 10
    assert zone.created_round == engine.state.round_number
    # Membership of the actual emanation: owner and the foe 3 squares away are in;
    # the second creature 7 squares away (35 feet) is out.
    assert {a.entity_id for a in engine.state.actors.values() if zone_contains(engine, a, zone)} == {G_OWNER, G_FOE}
    # The once-per-long-rest use was really paid: the fight-use counter is spent.
    uses = [rid for rid in engine.state.actors[G_OWNER].resource_maximums
            if rid.startswith("resource:uses.") and GARDEN in rid]
    assert uses, "the garden's once-per-fight use counter is missing"
    assert int(engine.state.actors[G_OWNER].resources[uses[0]]) == 0
    # The committed fight carries the zone through a cold reload, still on its clock.
    reloaded = fresh(combat, mid)
    again = garden_zone(reloaded)
    assert (again.center.x, again.center.y) == (10, 6)
    assert again.duration_rounds == 10 and again.created_round == zone.created_round
    assert {a.entity_id for a in reloaded.state.actors.values() if zone_contains(reloaded, a, again)} == {G_OWNER, G_FOE}


def test_garden_zone_expires_at_the_native_minute_deadline(tmp_path):
    """Ten real rounds later the garden ends itself at its owner's turn start -- no state deletion."""
    combat, table, mid, commit = garden_match(tmp_path, maximum_rounds=40, seed="MGR-T14-GARDEN-CLOCK-EXPIRY")
    assert commit(garden_candidate(table, mid))["status"] == "COMMITTED"
    raised = fresh(combat, mid)
    zone = garden_zone(raised)
    assert zone.duration_rounds == 10
    deadline = zone.created_round + 10
    # Three living actors each take ten turns. Every committed state before
    # the owner's deadline must retain this specific zone, including other
    # creatures' turns in the deadline round when they precede the owner.
    for step in range(30):
        engine = fresh(combat, mid)
        assert engine.state.zones[zone.zone_id].active, (step, engine.state.round_number)
        assert not [e for e in engine.events if e.event_type == "ZONE_REMOVED"
                    and e.payload.get("zone_id") == zone.zone_id]
        assert commit(table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    engine = fresh(combat, mid)
    assert engine.state.round_number == deadline
    assert engine.state.current_actor_id == G_OWNER
    assert not engine.state.zones[zone.zone_id].active
    removals = [e for e in engine.events if e.event_type == "ZONE_REMOVED"
                and e.payload.get("zone_id") == zone.zone_id]
    assert len(removals) == 1
    assert removals[0].actor_id == G_OWNER
    assert removals[0].source_definition_id == zone.source_definition_id
    assert removals[0].payload["reason"] == "DURATION_ENDED"


def test_garden_follows_native_walk_and_changes_membership_after_reload(tmp_path):
    combat, table, mid, commit = garden_match(tmp_path)
    assert commit(garden_candidate(table, mid))["status"] == "COMMITTED"
    for x in (9, 8):
        menu = table.state(mid)["menu"]
        step = next(m for m in menu["moves"] if m["destination"] == {"x": x, "y": 6})
        assert commit(step["candidate_id"])["status"] == "COMMITTED"
        engine = fresh(combat, mid)
        zone = garden_zone(engine)
        assert zone.center == engine.state.actors[G_OWNER].position
        assert zone.duration_rounds == 10
        assert zone_contains(engine, engine.state.actors[G_SECOND], zone)
        shown = next(z for z in table.state(mid)["presentation"]["zones"] if z["zone_id"] == zone.zone_id)
        assert shown["center"] == {"x": x, "y": 6}
