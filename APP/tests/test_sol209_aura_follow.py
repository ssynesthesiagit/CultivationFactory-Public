"""Owner-centered emanations follow through accepted table actions and cold reloads."""
import pytest

from combat import zones
from combat.spatial_areas import zone_contains
from combat.gate5_service import CombatService
from tests.h1_support import ROOT, mechanics, sheet
from combat.factory_compiler import compile_character
from tests.r1i_service_support import fixture, candidate, OWNER, FOE, SECOND
from tests.r10_fixup_support import fixed_dice

COURT = "tianxia.talent.yang.yang_domain_court_of_unfinished_noon"
MIRROR = "tianxia.tradition.spirit.mirror_speaker.feature.world_behind_the_glass"
CANOPY = "TAL_VERDANT_GROWTH_CANOPY_OF_TEN_THOUSAND_LEAVES"
FOLD = "TAL_SPACE_FOLD_STEP"
ALL_EYES_OPEN = "tianxia.tradition.spirit.choir_of_the_unopened_eye.feature.all_eyes_open"
DUST_CLOUD = "tianxia.subpath.qi.dust_cultivator.feature.dust_cloud"


def fresh(tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"
    return session.engine


def turn(table, mid, commit, actor):
    for _ in range(20):
        menu = table.state(mid)["menu"]
        if menu["actor_id"] == actor:
            return
        assert commit(menu["end_turn"])["status"] == "COMMITTED"
    raise AssertionError("turn did not reach actor")


def owned_zone(engine, actor=OWNER):
    return next(z for z in zones.typed_zones(engine) if z.owner_id == actor)


def move(table, mid, commit, x, y):
    menu = table.state(mid)["menu"]
    option = next(m for m in menu["moves"] if m["destination"] == {"x": x, "y": y})
    assert commit(option["candidate_id"])["status"] == "COMMITTED"


def compiled_zone_specs(mid):
    """The zone specs the compiler stores for ``mid``; an instant effect stores none."""
    bundle = compile_character(sheet([mid], cl=20), actor_id="actor:guard")
    typed = [a.get("parameters", {}).get("typed", {}) for a in bundle["action_catalog"]]
    return [t["zone_spec"] for t in typed if t.get("source") == mid and t.get("zone_spec")]


@pytest.mark.parametrize("talent,expected", [
    (CANOPY, "vines"),
    ("TAL_LIGHTNING_CONDUCTIVE_FIELD", "lightning"),
    ("TAL_LIGHTNING_COURT_OF_CHARGED_PATHS", "lightning"),
    ("tianxia.talent.poison.toxic_cloud", "poison"),
    ("TAL_MAGMA_VOLCANIC_SMOKE", "smoke"),
])
def test_real_authority_zone_material_reaches_table_service(tmp_path, talent, expected):
    """Compile printed authority rows and check the material exposed by a committed table cast."""
    mechanic = mechanics()[talent]
    compiled = compile_character(sheet([talent], cl=17), actor_id="actor:factory.material_compile")
    action = next(action for action in compiled["action_catalog"]
                  if (action.get("parameters", {}).get("typed") or {}).get("source") == talent)
    assert action["parameters"]["typed"]["zone_spec"]["visual"]["material"] == expected

    combat, table, mid, _send, commit = fixture(tmp_path, [talent], wide=True)
    assert commit(candidate(table, mid, mechanic["name"]))["status"] == "COMMITTED"
    shown = table.state(mid)["presentation"]["zones"]
    assert shown, f"{mechanic['name']} did not reach the table zone presentation"
    assert {row["trigger_profile"]["visual"]["material"] for row in shown} == {expected}
    reloaded_zone = owned_zone(fresh(tmp_path, mid))
    assert reloaded_zone.trigger_profile["visual"]["material"] == expected


@pytest.mark.parametrize("talent,follows", [(COURT, True), ("TAL_FATE_CONSEQUENCE_EDICT", True),
    ("tianxia.talent.beauty.lotus_court_aura", True), ("ASH_BASE_ASHFALL", False),
    ("TAL_VERDANT_GROWTH_CANOPY_OF_TEN_THOUSAND_LEAVES", False)])
def test_owner_and_fixed_point_areas_walk_and_reload(tmp_path, talent, follows):
    radius = int((mechanics()[talent].get("area") or {}).get("size_ft") or 30) // 5
    combat, table, mid, send, commit = fixture(tmp_path, [talent], wide=True,
        positions={OWNER: {"x": 10, "y": 6}, FOE: {"x": 10 + radius, "y": 6}, SECOND: {"x": 9 - radius, "y": 6}})
    label = mechanics()[talent]["name"]
    assert commit(candidate(table, mid, label))["status"] == "COMMITTED"
    initial = fresh(tmp_path, mid)
    initial_zone = owned_zone(initial)
    initial_center = initial_zone.center
    if talent == "TAL_VERDANT_GROWTH_CANOPY_OF_TEN_THOUSAND_LEAVES":
        assert initial_center != initial.state.actors[OWNER].position
    initial_members = {a.entity_id for a in initial.state.actors.values() if zone_contains(initial, a, initial_zone)}
    for x in (9, 8):
        move(table, mid, commit, x, 6)
        engine = fresh(tmp_path, mid)
        zone = owned_zone(engine)
        assert zone.center == (engine.state.actors[OWNER].position if follows else initial_center)
        shown = next(z for z in table.state(mid)["presentation"]["zones"] if z["zone_id"] == zone.zone_id)
        assert shown["center"] == zone.center.model_dump(mode="json")
        members = {a.entity_id for a in engine.state.actors.values() if zone_contains(engine, a, zone)}
        if follows:
            assert members != initial_members
            assert SECOND in members and FOE not in members
        else:
            assert members == initial_members


def test_court_follows_native_shove_and_fold_step(tmp_path, monkeypatch):
    combat, table, mid, send, commit = fixture(tmp_path, [COURT, FOLD], wide=True,
        positions={OWNER: {"x": 10, "y": 6}, FOE: {"x": 11, "y": 6}, SECOND: {"x": 17, "y": 6}})
    assert commit(candidate(table, mid, "Court of Unfinished Noon"))["status"] == "COMMITTED"
    turn(table, mid, commit, FOE)
    fixed_dice(monkeypatch, [1] * 100)
    assert commit(candidate(table, mid, "Shove: Push 5 ft", target=OWNER))["status"] == "COMMITTED"
    engine = fresh(tmp_path, mid)
    assert engine.state.actors[OWNER].position.x == 9
    assert owned_zone(engine).center == engine.state.actors[OWNER].position
    assert any(e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == OWNER and e.payload.get("forced") for e in engine.events)
    turn(table, mid, commit, OWNER)
    group = next(g for g in table.state(mid)["menu"]["actions"] if g["label"] == "Fold Step")
    option = next(o for o in group["options"] if o.get("destination") == {"x": 13, "y": 6})
    assert commit(option["candidate_id"])["status"] == "COMMITTED"
    engine = fresh(tmp_path, mid)
    assert engine.state.actors[OWNER].position.x != 9
    assert owned_zone(engine).center == engine.state.actors[OWNER].position


def test_all_persistent_owner_emanations_compile_with_following():
    """Guard the entire typed authority, including rows absent from this playtest."""
    failures = []
    checked = 0
    for mid, row in mechanics().items():
        area = row.get("area") or {}
        if area.get("shape") != "emanation":
            continue
        bundle = compile_character(sheet([mid], cl=20), actor_id="actor:guard")
        for action in bundle["action_catalog"]:
            typed = action.get("parameters", {}).get("typed", {})
            spec = typed.get("zone_spec")
            if typed.get("source") != mid or not spec:
                continue
            explicit = next((e["follows_owner"] for e in row.get("effects", [])
                             if e.get("type") == "zone" and "follows_owner" in e), area.get("follows_owner"))
            if spec["shape"] != "emanation" or not spec["centered_on_self"]:
                continue  # a modifier may replace the aura with a separately aimed area
            expected = explicit if explicit is not None else True
            checked += 1
            if spec["follows_owner"] != expected:
                failures.append(mid)
    assert not failures, failures
    assert checked > 50, "the guard must actually cover the authority's compiled auras"


def test_creature_anchored_darkness_follows_its_bearer_not_its_caster(tmp_path):
    from tests.test_mmx110_darkness_visuals import DARKNESS_TALENTS, cast_darkness

    combat, table, mid, send, commit = fixture(tmp_path, DARKNESS_TALENTS, wide=True,
        allies=(SECOND,), positions={OWNER: {"x": 10, "y": 6}, FOE: {"x": 30, "y": 6}, SECOND: {"x": 13, "y": 6}})
    cast_darkness(table, mid, send, augment="Clinging Darkness", at={"x": 13, "y": 6})
    engine = fresh(tmp_path, mid)
    zone = owned_zone(engine)
    assert zone.trigger_profile["anchor_id"] == SECOND
    center = zone.center
    move(table, mid, commit, 9, 6)
    assert owned_zone(fresh(tmp_path, mid)).center == center
    turn(table, mid, commit, SECOND)
    for x in (14, 15):
        move(table, mid, commit, x, 6)
        engine = fresh(tmp_path, mid)
        assert owned_zone(engine).center == engine.state.actors[SECOND].position


@pytest.mark.parametrize("shape,centered,expected", [("emanation", True, True),
    ("emanation", False, False), ("sphere", True, False)])
def test_shared_anchoring_seam_distinguishes_owner_from_casting_point(shape, centered, expected):
    import copy
    from combat.factory_compiler import _zone_spec
    from combat.gate2_runtime_models import ActionDefinition

    bundle = compile_character(sheet([COURT]), actor_id=OWNER)
    action = copy.deepcopy(next(a for a in bundle["action_catalog"]
                                if a.get("parameters", {}).get("typed", {}).get("source") == COURT))
    typed = action["parameters"]["typed"]
    typed["area"] = {"shape": shape, "size_ft": 30, "centered_on_self": centered}
    typed["effects"] = [{"type": "zone"}]
    spec = _zone_spec(ActionDefinition.model_validate(action), mechanics()[COURT], {})
    assert spec["centered_on_self"] == centered
    assert spec["follows_owner"] == expected


def test_mirror_domain_stays_fixed_through_table_walk_and_reload(tmp_path):
    # World Behind the Glass is CL18 and paid in Resonance. Configure the
    # owner through the fixture's explicit fields, which now own these facts.
    # Printed: centered on you, and the center remains fixed. The square and the membership below are
    # hard-coded from that printed rule, not read back from the compiled zone.
    combat, table, mid, send, commit = fixture(tmp_path, [MIRROR], wide=True,
        owner_cl=18, owner_path="Spirit Awakening", owner_resource="Resonance",
        positions={OWNER: {"x": 10, "y": 6}, FOE: {"x": 16, "y": 6}, SECOND: {"x": 3, "y": 6}})
    assert commit(candidate(table, mid, mechanics()[MIRROR]["name"]))["status"] == "COMMITTED"
    initial = fresh(tmp_path, mid)
    initial_zone = owned_zone(initial)
    assert (initial_zone.center.x, initial_zone.center.y) == (10, 6)
    # Radius 6 squares: its owner and the foe at 6 squares are inside; the second creature at 7 squares is not.
    assert {a.entity_id for a in initial.state.actors.values() if zone_contains(initial, a, initial_zone)} == {OWNER, FOE}
    for x in (9, 8):
        move(table, mid, commit, x, 6)
        engine = fresh(tmp_path, mid)
        assert engine.state.actors[OWNER].position.x == x
        zone = owned_zone(engine)
        assert (zone.center.x, zone.center.y) == (10, 6)
        shown = next(z for z in table.state(mid)["presentation"]["zones"] if z["zone_id"] == zone.zone_id)
        assert shown["center"] == {"x": 10, "y": 6}
        members = {a.entity_id for a in engine.state.actors.values() if zone_contains(engine, a, zone)}
        assert members == {OWNER, FOE}


@pytest.mark.parametrize("mid,centered", [(MIRROR, True), (CANOPY, False)])
def test_printed_fixed_center_areas_compile_without_owner_follow(mid, centered):
    # The expectation is hard-coded from the printed rule: the center stays fixed, so the zone never follows its owner.
    specs = compiled_zone_specs(mid)
    assert specs, f"{mid} compiles no stored zone"
    assert {(spec["centered_on_self"], spec["follows_owner"]) for spec in specs} == {(centered, False)}


# Owner auras corrected by SOL209. Listed by hand so that a row losing its zone, its self-centering or its
# following fails here instead of being skipped by the survey above.
CORRECTED_OWNER_AURAS = [
    "tianxia.talent.yang.yang_domain_court_of_unfinished_noon",
    "TAL_IRON_FIST_COURT_OF_ONE_HUNDRED_FORMS",
    "tianxia.talent.beauty.domain_of_the_perfect_moment",
    "tianxia.talent.beauty.lotus_court_aura",
    "foundation.FOUNDATION_03_EMPTY_BOWL_SOUL_ANCHOR.empty_bowl_domain",
    "foundation.dream_mirror_soul_anchor_v0_2B.dream_mirror_domain",
    "tianxia.subpath.qi.nightmare_dream_qi_cultivator.feature.nightmare_sovereign",
]


@pytest.mark.parametrize("mid", CORRECTED_OWNER_AURAS)
def test_corrected_owner_aura_compiles_as_persistent_centered_follower(mid):
    specs = compiled_zone_specs(mid)
    assert specs, f"{mid} compiles no persistent zone"
    assert {(spec["centered_on_self"], spec["follows_owner"]) for spec in specs} == {(True, True)}


def _spirit_owner(bundles):
    """Give the owner a Spirit Awakening sheet with Resonance as its pool, so All Eyes Open can be paid for."""
    doc = sheet([ALL_EYES_OPEN], cl=17, primary="Resonance", key="WIS")
    doc["identity"].update(path="Spirit Awakening", display_name="Owner")
    bundles[0] = compile_character(doc, actor_id=OWNER)


@pytest.mark.parametrize("talent,label,expected,transform", [
    (ALL_EYES_OPEN, "All Eyes Open", "generic", _spirit_owner),
    (DUST_CLOUD, "Dust Cloud", "sand", None),
])
def test_identity_and_subpath_zone_material_reaches_table_and_reload(tmp_path, talent, label, expected, transform):
    """Identity-free rules text must not pick art; a subpath with no name word picks its own."""
    combat, table, mid, _send, commit = fixture(tmp_path, [talent], wide=True, bundle_transform=transform)
    assert commit(candidate(table, mid, label))["status"] == "COMMITTED"
    shown = table.state(mid)["presentation"]["zones"]
    assert {row["trigger_profile"]["visual"]["material"] for row in shown} == {expected}
    assert owned_zone(fresh(tmp_path, mid)).trigger_profile["visual"]["material"] == expected
