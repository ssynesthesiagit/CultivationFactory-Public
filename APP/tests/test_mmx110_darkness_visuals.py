"""MMX110: each Darkness is drawn with its own look, decided by the typed rows that shaped it.

Owner 2026-10-03 03:38: "Can we do a more transparent darkness for regular darkness and still slightly transparent
but almost pitch black for pure darkness? Would be even cooler if for snagging/clinging darkness we could have dark
tentacles you can barely see waving in the area."

Before this, every area of magical darkness was drawn with one flat wash (static/tabletop/board.js), and nothing in
the zone payload said which of the Dark sphere's talents had shaped it. The look now travels on
``trigger_profile.visual.darkness_look``, written by the ``zone_visual`` hook in combat/ext/tabik_dark.py from the
area's own stored mechanic ids. This is drawing only: sight, fog and obscuration are untouched, and the test that
proves it is the fog test below plus the roundtrip in every case.
"""
from pathlib import Path
import subprocess

import pytest

from tests.h49_fog_support import assert_roundtrip
from tests.r1i_service_support import OWNER, SECOND, fixture

TABLETOP = Path(__file__).resolve().parents[1] / "static" / "tabletop"


def test_tentacle_loop_continuity_on_rendered_board():
    """Exercise the real board nodes and their CSS without launching a browser."""
    subprocess.run(["node", "--test", "--test-name-pattern=tentacle motion is continuous",
                    str(TABLETOP / "zones.test.mjs")], check=True, capture_output=True, text=True)

DARKNESS_TALENTS = [
    "DARK_BASE_DARKNESS",
    "TAL_DARK_PURE_DARKNESS",
    "TAL_DARK_SNAGGING_DARKNESS",
    "TAL_DARK_CLINGING_DARKNESS",
]


def _commit(send, candidate_id):
    answers = []
    for _ in range(16):
        result = send(candidate_id, answers)
        if result["status"] == "COMMITTED":
            return result
        prompt = result["reaction"]
        answer = {**prompt["context"], "selection": "DECLINE"}
        if prompt.get("choice"):
            answer.update(selection="USE", option_ids=(prompt["choice"].get("preferred") or [prompt["choice"]["options"][0]["id"]])[:1])
        answers.append(answer)
    raise AssertionError("too many prompts")


def cast_darkness(table, mid, send, *, shape=None, augment=None, at={"x": 6, "y": 6}):
    """Press the Shape/Augment choices, then cast, the way a player at the table would."""
    for prefix, wanted in (("Shape Darkness", shape), ("Augment Darkness", augment)):
        if not wanted:
            continue
        label = f"{prefix}: {wanted}"
        group = next(g for g in table.state(mid)["menu"]["actions"] if g["label"] == label)
        _commit(send, group["options"][0]["candidate_id"])
    groups = [g for g in table.state(mid)["menu"]["actions"] if g["label"].startswith("Darkness")]
    group = next(g for g in groups if not g["label"].startswith(("Shape ", "Augment ")) and g["label"] != "Darkness + Persistent Darkness") \
        if len(groups) > 1 else groups[0]
    option = next((o for o in group["options"] if o.get("destination") == at), group["options"][0])
    _commit(send, option["candidate_id"])
    return group


def darkness_zone(table, mid):
    for zone in table.state(mid)["presentation"]["zones"]:
        profile = zone.get("trigger_profile") or {}
        if profile.get("kind") == "TYPED" and (profile.get("visual") or {}).get("darkness"):
            return zone
    raise AssertionError("no Darkness was made")


def make_darkness(tmp_path, **kwargs):
    combat, table, mid, send, _commit_all = fixture(
        Path(tmp_path), DARKNESS_TALENTS, allies=(SECOND,), wide=True,
        positions={OWNER: {"x": 3, "y": 6}, "r1i-foe": {"x": 8, "y": 6}, SECOND: {"x": 12, "y": 6}},
    )
    cast_darkness(table, mid, send, **kwargs)
    return combat, table, mid


# Each variant of the printed talents, and the look the table must draw it with. The rule text is the owner's;
# the name is only ever the label a player reads, never what the engine decides on.
CASES = [
    pytest.param({}, "veil", False, id="plain Darkness is a veil you can see through"),
    pytest.param({"shape": "Pure Darkness"}, "pitch", False, id="Pure Darkness is almost pitch black"),
    pytest.param({"shape": "Snagging Darkness"}, "tentacles", True, id="Snagging Darkness waves tentacles"),
    pytest.param({"augment": "Clinging Darkness"}, "tentacles", True, id="Clinging Darkness waves tentacles"),
    pytest.param({"shape": "Pure Darkness", "augment": "Clinging Darkness"}, "pitch", True,
                 id="Pitch Black: pitch black, still waving"),
]


@pytest.mark.parametrize("choices,look,tentacles", CASES)
def test_each_darkness_is_drawn_with_its_own_look(tmp_path, choices, look, tentacles):
    combat, table, mid = make_darkness(tmp_path, **choices)
    visual = darkness_zone(table, mid)["trigger_profile"]["visual"]
    assert visual["darkness_look"] == look
    assert visual["darkness_tentacles"] is tentacles
    assert_roundtrip(combat, tmp_path, mid)


def _reclassify(zone):
    """What the table's own zone_visual hook makes of this row, through the registered dispatcher.

    The facts a saved row already carries are ignored on purpose: a classifier that read them back, or that read
    the area's display name, would pass a test that only copies them across.
    """
    from combat import ext

    merged: dict = {}
    for facts in ext.run("zone_visual", None, zone) or []:
        if isinstance(facts, dict):
            merged.update(facts)
    return merged


def test_the_look_comes_from_the_typed_rows_not_the_name(tmp_path):
    """The same typed rows under another area's name still draw as themselves, decided again from the row."""
    combat, table, mid, send, _ = fixture(
        Path(tmp_path), DARKNESS_TALENTS, allies=(SECOND,), wide=True,
        positions={OWNER: {"x": 3, "y": 6}, "r1i-foe": {"x": 8, "y": 6}, SECOND: {"x": 12, "y": 6}},
    )
    cast_darkness(table, mid, send, shape="Pure Darkness")
    zone = darkness_zone(table, mid)
    profile = zone["trigger_profile"]
    # The engine stored the mechanic id of what shaped it, and never matched on the words.
    assert "TAL_DARK_PURE_DARKNESS" in [row.get("id") for row in profile["inside"]]
    assert profile["augment_ids"] == [], "an unaugmented Darkness carries no augment ids"

    # Renamed, and with the facts already computed thrown away: the hook is asked again from the typed rows alone.
    renamed = {**zone, "trigger_profile": {
        **{key: value for key, value in profile.items() if key != "visual"},
        "name": "Somebody Else's Fog Bank", "visual": {"material": "darkness", "darkness": True}}}
    assert _reclassify(renamed) == {"darkness_look": "pitch", "darkness_tentacles": False}, \
        "renaming an area does not change what it is drawn as"

    # A name that claims a look it has no mechanic for is not that look: the words are never the evidence. With the
    # Pure Darkness row taken away, a Pure Darkness name leaves an ordinary veil, and a Clinging Darkness name with no
    # augment id waves nothing.
    kept = {key: value for key, value in profile.items() if key not in ("visual", "name", "augments", "inside")}
    for lie in ({"name": "Pure Darkness", "augments": ["Pure Darkness"]},
                {"name": "Clinging Darkness", "augments": ["Clinging Darkness"]},
                {"name": "Clinging Darkness", "augment_ids": []},
                {"inside": [], "name": "Fog Bank"}):
        assert _reclassify({**zone, "trigger_profile": {
            **kept, "visual": {"material": "darkness", "darkness": True}, **lie}}) == {
            "darkness_look": "veil", "darkness_tentacles": False}, f"a name claiming to be something else is ignored: {lie}"

    # And with no typed row at all, a Darkness named "Pure Darkness" is not Pure Darkness: it is drawn as it always was.
    bare = {"zone_id": "z", "trigger_profile": {"name": "Pure Darkness",
                                                "visual": {"material": "darkness", "darkness": True}}}
    assert _reclassify(bare) == {}, "a name with no mechanic behind it gets no look"


def test_an_area_saved_before_the_look_existed_is_not_guessed_at():
    """An old saved Darkness keeps the drawing it has always had; its provenance is never rebuilt from its name."""
    from combat.ext import tabik_dark

    # A Clinging Darkness cast before augment_ids were stored: the name is on the area, the id is not.
    legacy = {"trigger_profile": {"name": "Darkness", "augments": ["Clinging Darkness"],
                                  "visual": {"material": "darkness", "darkness": True},
                                  "source_profile": {"sphere_id": "tianxia.sphere.dark",
                                                     "mechanic_id": "DARK_BASE_DARKNESS"}}}
    assert _reclassify(legacy) == {"darkness_look": "veil", "darkness_tentacles": False}, \
        "an old area keeps the plain veil, because its stored rows are the only evidence there is"
    assert "augment_ids" not in legacy["trigger_profile"], "and the test row really is an old one"
    # An area with no provenance at all -- some other sphere's darkness -- gets nothing, so the table keeps drawing it
    # the way it always has. The client reads that as "no look", never as a default one.
    assert tabik_dark.darkness_look(None, {"trigger_profile": {"visual": {"material": "darkness", "darkness": True}}}) is None
    assert _reclassify({"trigger_profile": {"visual": {"material": "darkness", "darkness": True},
                                            "source_profile": {"sphere_id": "tianxia.sphere.radiance",
                                                               "mechanic_id": "SOMEBODY_ELSE"}}}) == {}


def test_a_clinging_darkness_records_its_augment_as_a_mechanic_id(tmp_path):
    """Clinging Darkness is an augment, so its id has to be stored or the table cannot tell it apart."""
    combat, table, mid, send, _ = fixture(
        Path(tmp_path), DARKNESS_TALENTS, allies=(SECOND,), wide=True,
        positions={OWNER: {"x": 3, "y": 6}, "r1i-foe": {"x": 8, "y": 6}, SECOND: {"x": 12, "y": 6}},
    )
    cast_darkness(table, mid, send, augment="Clinging Darkness")
    profile = darkness_zone(table, mid)["trigger_profile"]
    assert "TAL_DARK_CLINGING_DARKNESS" in profile["augment_ids"]
    assert profile["augments"] == ["Clinging Darkness"], "the name the player reads is unchanged"
    # Saved and reloaded, an area still says what it is.
    assert_roundtrip(combat, tmp_path, mid)


def test_areas_that_are_not_darkness_are_left_alone(tmp_path):
    """The plug-in is inert for anything that is not a Dark sphere Darkness (smoke, fog, a wall of cloud)."""
    from combat.ext import tabik_dark

    assert tabik_dark.darkness_look(None, {"trigger_profile": {"visual": {"material": "smoke", "obscured": "heavy"}}}) is None
    assert tabik_dark.darkness_look(None, {"trigger_profile": {"visual": {"material": "fog", "obscured": "light"}}}) is None
    assert tabik_dark.darkness_look(None, {"trigger_profile": {"visual": {"material": "darkness"}}}) is None, "a legacy area with no provenance"
    # Another sphere's darkness keeps the single look it has always had.
    other = {"trigger_profile": {"visual": {"material": "darkness", "darkness": True},
                                 "source_profile": {"sphere_id": "tianxia.sphere.radiance", "mechanic_id": "SOMEBODY_ELSE"}}}
    assert tabik_dark.darkness_look(None, other) is None
    # A Darkness with no shaping talent at all is an ordinary veil.
    plain = {"trigger_profile": {"visual": {"material": "darkness", "darkness": True},
                                 "source_profile": {"sphere_id": "tianxia.sphere.dark", "mechanic_id": "DARK_BASE_DARKNESS"}}}
    assert tabik_dark.darkness_look(None, plain) == {"darkness_look": "veil", "darkness_tentacles": False}


def test_the_replayed_boundary_draws_the_area_the_same_way_the_live_one_does(tmp_path):
    """A battle-history boundary is drawn by the same hook as the live table, so the look is there too.

    The darkness facts are presentation only, so they are not in the recorded journal; they are re-derived from
    the area's own stored ids each time a boundary is rebuilt.
    """
    combat, table, mid = make_darkness(Path(tmp_path), shape="Pure Darkness", augment="Clinging Darkness")
    live = darkness_zone(table, mid)["trigger_profile"]["visual"]
    assert (live["darkness_look"], live["darkness_tentacles"]) == ("pitch", True)

    boundaries = combat.history(mid)["boundaries"]
    assert boundaries, "the fight recorded at least one boundary"
    seen_at = []
    for index, boundary in enumerate(boundaries):
        dark = [zone for zone in boundary["state"].get("zones") or []
                if (zone.get("trigger_profile") or {}).get("visual", {}).get("darkness")]
        if not dark:
            continue  # a boundary from before the Darkness was cast, or after it ended
        seen_at.append(index)
        view = combat.presentation(mid, boundary_index=index)
        assert view["mode"] == "HISTORY" and view["boundary"]["boundary_index"] == index
        visual = [zone for zone in view["zones"]
                  if (zone.get("trigger_profile") or {}).get("visual", {}).get("darkness")][0]["trigger_profile"]["visual"]
        assert (visual["darkness_look"], visual["darkness_tentacles"]) == ("pitch", True), \
            f"boundary {index} draws the area as itself"
    assert seen_at, f"no boundary had the Darkness in it: {len(boundaries)} boundaries"


def test_the_table_still_draws_each_shade():
    """Real board commands check strand contrast, mask selection, and deterministic shade painting."""
    import subprocess

    subprocess.run(["node", str(TABLETOP / "zones.test.mjs")], check=True, cwd=str(TABLETOP))
