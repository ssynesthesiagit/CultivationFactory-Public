"""Fog policy, persistence and demand/caching through table actions."""
import pytest

from combat import senses, target_knowledge
from combat.canonical import canonical_sha256
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h49_fog_support import assert_roundtrip, option, turn_to
from tests.r1i_service_support import OWNER, FOE, SECOND, candidate, fixture


def assert_fog_reload(combat, table, tmp_path, mid):
    assert_roundtrip(combat, tmp_path, mid)
    fresh = TabletopService(CombatService(combat.source_root, tmp_path), tmp_path)
    assert fresh.state(mid, fog=True)["fog_perception"] == table.state(mid, fog=True)["fog_perception"]


@pytest.mark.parametrize("directional", [False, True])
def test_inside_outward_cells_and_creatures_agree(tmp_path, directional):
    talents = ["DARK_BASE_DARKNESS"] + (["TAL_DARK_DIRECTIONAL_DARKNESS"] if directional else [])
    combat, table, mid, _, commit = fixture(tmp_path, talents, wide=True, allies=(SECOND,),
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 6, "y": 6}, SECOND: {"x": 12, "y": 6}})
    label = "Darkness + Directional Darkness" if directional else "Darkness"
    group = next(g for g in table.state(mid)["menu"]["actions"] if g["label"] == label)
    commit(next(o["candidate_id"] for o in group["options"] if o.get("destination") == {"x": 6, "y": 6}))
    engine = combat._load_session(mid).engine
    # Pick an inside non-owner with an outward ray crossing multiple area cells.
    zone = next(iter(engine.state.zones.values()))
    inside_cells = {(c.x, c.y) for c in zone.affected_cells}
    assert (6, 6) in inside_cells and (12, 6) not in inside_cells
    assert len(set(engine.grid.ray_cells(engine.state.actors[FOE].position,
                                        engine.state.actors[SECOND].position)[1:-1]) & inside_cells) >= 2
    viewer = engine.state.actors[FOE]
    target = engine.state.actors[SECOND]
    expected = target_knowledge.can_see(engine, viewer, target)
    assert expected == (not directional)
    projection = table.state(mid, fog=True)["fog_perception"][FOE]
    assert ([target.position.x, target.position.y] in projection["cells"]) == expected
    assert (SECOND in projection["creatures"]) == expected
    reverse = table.state(mid, fog=True)["fog_perception"][SECOND]
    assert ([6, 6] in reverse["cells"]) == directional
    assert (FOE in reverse["creatures"]) == directional
    assert_fog_reload(combat, table, tmp_path, mid)


def test_defeated_token_remains_a_visible_target(tmp_path):
    def fragile(bundles):
        foe = bundles[1]
        foe["actor_template"]["maximum_hp"] = 1
        foe.pop("bundle_sha256", None)
        foe["bundle_sha256"] = canonical_sha256(foe)

    combat, table, mid, _, commit = fixture(tmp_path, ["TAL_ILLUSION_PHANTOM_STING"], bundle_transform=fragile)
    commit(candidate(table, mid, "Phantom Sting", FOE))
    engine = combat._load_session(mid).engine
    assert not engine.state.actors[FOE].active
    projection = table.state(mid, fog=True)["fog_perception"]
    assert FOE in projection[OWNER]["creatures"]
    assert FOE not in projection  # fallen targets are not eligible viewers
    assert_fog_reload(combat, table, tmp_path, mid)


@pytest.mark.parametrize("kind", ["none", "blindsight", "spiritual_sense"])
def test_blinded_viewer_distinguishes_terrain_from_creature_senses(tmp_path, kind):
    talents = (["TAL_SOUND_SOUND_SOVEREIGN_INCARNATION"]
               if kind == "blindsight" else ["tianxia.path.spirit_awakening.feature.spiritual_sense"]
               if kind == "spiritual_sense" else [])
    combat, table, mid, send, commit = fixture(tmp_path, talents,
        foe_talents=["RADIANCE_TAL_BLINDING_FLASH"], wide=True)
    if kind == "blindsight":
        commit(candidate(table, mid, "Sound-Sovereign Incarnation"))
    turn_to(table, mid, commit, FOE)
    # Friendly-fire asks which creatures the caster chooses. The shared setup
    # helper chooses the first option (the caster); explicitly choose this
    # test's viewer so all blindness/sense/range assertions still exercise it.
    # Use the self-centered form; the first cone may face away from OWNER.
    cid = candidate(table, mid, "10-Foot Emanation")
    pending = send(cid)
    assert pending["status"] == "REACTION_REQUIRED"
    context = pending["reaction"]["context"]
    assert context["reaction_source_id"] == "choice:needle.area_recipients"
    assert OWNER in [row["id"] for row in pending["reaction"]["choice"]["options"]]
    assert send(cid, [{**context, "selection": "USE", "option_ids": [OWNER]}])["status"] == "COMMITTED"
    engine = combat._load_session(mid).engine
    assert any(c.condition_id == "condition:typed.blinded" for c in engine.state.actors[OWNER].conditions.values())
    projection = table.state(mid, fog=True)["fog_perception"][OWNER]
    assert ([4, 6] in projection["cells"]) == (kind == "blindsight")
    assert ([9, 6] in projection["cells"]) == (kind == "blindsight")  # 30-foot boundary
    assert [10, 6] not in projection["cells"]  # the active Blindsight is limited to 30 feet
    assert (FOE in projection["creatures"]) == (kind != "none")
    assert_fog_reload(combat, table, tmp_path, mid)


def test_fog_is_opt_in_cached_and_invalidated_after_commit(tmp_path, monkeypatch):
    combat, table, mid, _, commit = fixture(tmp_path, [])
    calls = []
    original = senses.perception
    def counted(engine, viewer):
        calls.append(viewer.entity_id)
        return original(engine, viewer)
    monkeypatch.setattr(senses, "perception", counted)
    assert table.state(mid)["fog_perception"] == {}
    assert not calls
    first = table.state(mid, fog=True)["fog_perception"]
    assert len(calls) == 3
    first[OWNER]["cells"].clear()  # callers cannot mutate the cached answer
    assert table.state(mid, fog=True)["fog_perception"][OWNER]["cells"]
    assert len(calls) == 3
    commit(table.state(mid)["menu"]["end_turn"])
    table.state(mid, fog=True)
    assert len(calls) == 6
    assert_fog_reload(combat, table, tmp_path, mid)
