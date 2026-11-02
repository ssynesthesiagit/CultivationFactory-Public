"""MGR-T14-ling-returning-field-clock-1: the Perfected Origin-Spirit Returning Field
runs its printed 1 minute through the native zone consumer's shared round clock.

The printed clause "Once per long rest, as an Action, establish an Origin-Spirit
Returning Field for 1 minute" typed the ability-level duration as ``instant``
(the foundation's printed fields carry no Duration line; "for 1 minute" lives in
the Effect text), so factory_compiler._zone_spec refused the area as not lasting
and the native zone consumer never placed the field. The reviewed final gives the
ability the documented structured minutes1 clock ({"kind": "minutes", "amount": 1}),
the same typing every other 1-minute emanation carries, and the field now compiles,
places, persists through a cold reload and ends at its own native deadline.
"""
import json
import zipfile

import pytest

from combat import zones
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.spatial_areas import zone_contains
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

FIELD = "foundation.origin_spirit_body_v0_2B.perfected_origin_spirit_returning_field"
LABEL = "Perfected: Origin-Spirit Returning Field"
OWNER, FOE, SECOND = "actor:r1i-owner", "actor:r1i-foe", "actor:r1i-second"


def compiled_field():
    """The compiled action and its stored zone_spec for the field (None before the clock fix)."""
    bundle = compile_character(sheet([FIELD], cl=17), actor_id="actor:factory.material_compile")
    for action in bundle["action_catalog"]:
        typed = action.get("parameters", {}).get("typed") or {}
        if typed.get("source") == FIELD:
            return action, typed.get("zone_spec")
    return None, None


def test_field_compiles_the_structured_minutes1_zone_clock():
    """Fail-before: the transient instant duration compiled no zone at all."""
    action, spec = compiled_field()
    assert action is not None, "the Perfected field is not compiled onto the sheet"
    assert action["economy"] == "ACTION"
    assert spec is not None, "the 1-minute field compiled no zone (duration typed instant)"
    assert spec["duration"] == {"kind": "minutes", "amount": 1, "concentration": False}
    assert spec["shape"] == "emanation" and spec["size_ft"] == 30
    assert spec["centered_on_self"] is True


def owned_zone(engine):
    return next(z for z in zones.typed_zones(engine) if z.owner_id == OWNER)


def fresh(combat, mid):
    """A cold reload: a new service reading the committed fight back off disk."""
    session = CombatService(ROOT, combat.userdata_root)._load_session(mid)
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"
    return session.engine


def match(tmp_path, *, maximum_rounds=10, seed="MGR-T14-RETURNING-FIELD"):
    """A real Factory match through the native table service, like tests/r1i_service_support."""
    docs = [sheet([FIELD], cl=17), sheet([], cl=17), sheet([], cl=17)]
    ids = [OWNER, FOE, SECOND]
    for aid, doc in zip(ids, docs):
        doc["identity"]["display_name"] = aid.split("r1i-")[-1].title()
        doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = 500
        doc["ability_scores_and_statistics"]["technique_attack_bonus"] = 100
        folder = tmp_path / "portable_characters" / aid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    bundles = [compile_character(doc, actor_id=aid) for aid, doc in zip(ids, docs)]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    saved = combat.tabletop_maps.save({"display_name": "MGR-T14 Wide", "width_squares": 40,
        "height_squares": 20, "walls": [], "terrain": [],
        "starts": {"team1": [[10, 6]], "team2": [[13, 6], [3, 6]]}})
    arena = combat.factory_arenas()["battlefield:map." + saved["map_id"]]
    mid = combat._finish_factory_match(
        bundles, ids, {aid: "team:a" if aid == OWNER else "team:b" for aid in ids},
        {OWNER: {"x": 10, "y": 6}, FOE: {"x": 13, "y": 6}, SECOND: {"x": 3, "y": 6}},
        arena, [OWNER], ids[1:],
        control_modes={aid: "MANUAL" for aid in ids}, match_seed=seed,
        display_name="MGR-T14 Returning Field", maximum_rounds=maximum_rounds)["match_id"]

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

    while table.state(mid)["menu"]["actor_id"] != OWNER:
        commit(table.state(mid)["menu"]["end_turn"])
    return combat, table, mid, commit


def field_candidate(table, mid):
    return next(o["candidate_id"] for g in table.state(mid)["menu"]["actions"] if LABEL in g["label"]
                for o in g["options"])


@pytest.mark.parametrize("maximum_rounds", [10])
def test_field_activation_places_the_owned_minute_zone_and_reloads(tmp_path, maximum_rounds):
    """Real activation through the table: owned 30-foot zone, minute clock, cold reload."""
    combat, table, mid, commit = match(tmp_path, maximum_rounds=maximum_rounds)
    assert commit(field_candidate(table, mid))["status"] == "COMMITTED"
    engine = fresh(combat, mid)
    zone = owned_zone(engine)
    # Initial owner-centered placement: the field stands where its owner stood when raised.
    assert (zone.center.x, zone.center.y) == (10, 6)
    assert zone.radius_cells == 6 and zone.trigger_profile["size_ft"] == 30
    # The structured minutes1 clock: 1 minute is 10 rounds on the shared round clock.
    assert zone.duration_rounds == 10
    assert zone.created_round == engine.state.round_number
    # Membership of the actual emanation: owner and the foe 3 squares away are in;
    # the second creature 7 squares away (35 feet) is out.
    assert {a.entity_id for a in engine.state.actors.values() if zone_contains(engine, a, zone)} == {OWNER, FOE}
    # The once-per-long-rest use was really paid: the fight-use counter is spent.
    uses = [rid for rid in engine.state.actors[OWNER].resource_maximums
            if rid.startswith("resource:uses.") and FIELD in rid]
    assert uses, "the field's once-per-fight use counter is missing"
    assert int(engine.state.actors[OWNER].resources[uses[0]]) == 0
    # The committed fight carries the zone through a cold reload, still on its clock.
    reloaded = fresh(combat, mid)
    again = owned_zone(reloaded)
    assert (again.center.x, again.center.y) == (10, 6)
    assert again.duration_rounds == 10 and again.created_round == zone.created_round
    assert {a.entity_id for a in reloaded.state.actors.values() if zone_contains(reloaded, a, again)} == {OWNER, FOE}


def test_field_zone_expires_at_the_native_minute_deadline(tmp_path):
    """Ten real rounds later the field ends itself at its owner's turn start -- no state deletion."""
    combat, table, mid, commit = match(tmp_path, maximum_rounds=40, seed="MGR-T14-RETURNING-FIELD-EXPIRY")
    assert commit(field_candidate(table, mid))["status"] == "COMMITTED"
    raised = fresh(combat, mid)
    raised_round = raised.state.round_number
    assert owned_zone(raised).duration_rounds == 10
    assert owned_zone(raised).created_round == raised_round
    # Walk the owner's turn starts: the field must still stand at each start through round
    # raised+9 and be gone at the start of round raised+10 (1 minute = 10 rounds).
    seen = []
    for _ in range(12):
        assert commit(table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
        while table.state(mid)["menu"]["actor_id"] != OWNER:
            assert commit(table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
        engine = combat._load_session(mid).engine
        standing = any(z.active and z.owner_id == OWNER for z in engine.state.zones.values())
        seen.append((engine.state.round_number, standing))
        if not standing:
            break
    assert seen == [(raised_round + k, True) for k in range(1, 10)] + [(raised_round + 10, False)]
    engine = fresh(combat, mid)
    assert not [z for z in engine.state.zones.values() if z.active and z.owner_id == OWNER]
    assert any(e.event_type == "ZONE_REMOVED" and e.payload.get("reason") == "DURATION_ENDED"
               for e in engine.events)
