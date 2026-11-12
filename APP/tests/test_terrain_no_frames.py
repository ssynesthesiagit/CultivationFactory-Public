"""Terrain and object art must not draw a frame round its square (owner 2026-10-03, lane MMX111).

Owner, round 24: "there's still some surrounding grids around various terrain, I think it was loose gravel?"
His standing art rule: immersive top-down objects and natural terrain WITHOUT frames, outlines or hatching;
rules markings only on hover or an opt-in overlay.

Two separate things were drawing those frames, and this is the guard for both:

* the per-square washes the board lays over cover, hazard and difficult ground
  (board.js ``drawCells`` writes one ``<rect>`` per square; tabletop.css painted a ``stroke`` round every one of
  them, so a patch of ground came out looking like a grid laid over the map), and
* the edge board.js drew round a zone, which was drawn round *every* painted terrain and not just the effects a
  character cast -- because only bamboo was recognised as map scenery (``SCENERY`` in board.js, keyed on the
  material's name).  ``zones.js paintedGround`` now decides that from the map's own painted-terrain provenance
  (``source_definition_id`` ``system:battlefield.terrain``, which only combat/zones.py ``map_zones`` stamps), so no
  terrain has to be named for it to count as natural ground -- and an ability that paints flat ground art (Guarded
  Threshold, Grove Domain's Living Claims) is no longer mistaken for the landscape and keeps its edge.

The guard reads the real stylesheets and the real art source, so a material that grows a border again fails here
instead of shipping.  The allow-list below is the whole of what may still draw a border, each with the reason it
is not a frame round a square; a new entry has to be justified here in the same place.
"""
import re
import subprocess
from pathlib import Path

from tests.test_builtin_arenas import ROOT

TABLETOP = ROOT / "static/tabletop"

# The properties that put a line round something.
BORDER_PROPS = ("border", "outline", "stroke")


def css_rules(text: str) -> list[tuple[str, set[str]]]:
    """(selector, {property, ...}) for every declaration block, including those inside @media.

    A block whose body holds no braces is a declaration block; @media and @keyframes nest, and because neither
    prelude nor body may contain a brace at this level, the innermost blocks are the ones that match -- which is
    what we want to read.  @keyframes step selectors ("to", "from") come out as ordinary selectors and are
    ignored below, since none of them names map art.
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return [(" ".join(selector.split()),
             {piece.split(":")[0].strip() for piece in body.split(";") if ":" in piece})
            for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", text)]


def _borders(declarations: set[str]) -> set[str]:
    return {name for name in declarations if name.startswith(BORDER_PROPS)}


# Every map-art style family, so a new one cannot quietly start drawing frames.
ART_FAMILIES = (
    ".tt-cell-",        # the per-square ground washes
    ".tt-mat-",         # a zone's material ground
    ".tt-zone-ground",
    ".tt-tree",         # a tree seen from above
    ".tt-object-art",   # a placed object
    ".tt-wall",         # a wall
    ".tt-stone-",       # the masonry pattern inside a wall
    ".tt-mark-",        # targeting / movement overlays
    ".tt-zone-halo",    # the edge of an effect someone cast
    ".tt-zone-outline",
    ".tt-zone-hatch",   # the difficult-terrain marking on a cast effect
    ".tt-draft-shape",  # the wall being drawn in the map editor
    ".tt-flash",        # a hit or heal flash
)

# The whole of what may still draw a border, and why it is not a frame round a square.  Nothing else may.
ALLOWED_BORDER = {
    ".tt-wall": "A wall is a structure that stops you, not natural ground; the rim says which kind (a hard dark one "
                "where nobody walks through, a broken one where it only hides or only shelters).",
    ".tt-stone-": "The masonry pattern inside a wall, not a frame round a square.",
    ".tt-mark-": "A rules overlay, on screen only while the player is choosing a move or a target.",
    ".tt-flash": "Hit and heal feedback, gone in under a second.",
    ".tt-zone-halo": "The edge of an effect a character cast, in their colour: it says whose it is and where it "
                     "stops. Never drawn on ground the map itself painted (zones.js paintedGround).",
    ".tt-zone-outline": "As tt-zone-halo: the coloured edge of a cast effect, not a frame round the landscape.",
    ".tt-zone-hatch": "The difficult-terrain marking on a cast effect, continuous across neighbouring squares.",
    ".tt-draft-shape": "The wall being drawn right now in the map editor; a live tool preview, not saved art.",
    ".tt-object-art": "Strokes that draw the object's own silhouette and its fittings (hoops, bars, hinges). They "
                      "follow the object's shape, never its square; test_object_art_draws_no_square_cell_frame "
                      "holds them to that.",
}


def _family(selector: str) -> str | None:
    for family in ART_FAMILIES:
        if selector.startswith(family) or family in selector.split(",")[0].strip():
            return family
    return None


def test_ground_washes_draw_no_border():
    """The washes board.js draws one-per-square must be washes, not boxes.

    This is the regression for the owner's "surrounding grids around various terrain": a stroke here puts a border
    round every single square, so a patch of ground reads as a grid laid over the map.
    """
    rules = {selector: declarations for selector, declarations in
             css_rules((TABLETOP / "tabletop.css").read_text())}
    for selector in (".tt-cell-cover", ".tt-cell-hazard", ".tt-cell-difficult"):
        assert selector in rules, f"{selector} went missing; the ground washes are what the owner is looking at"
        borders = _borders(rules[selector])
        assert not borders, (f"{selector} draws {sorted(borders)}: that is the per-square frame the owner asked "
                             f"to lose (owner 2026-10-03, loose rubble)")

    # The classes must keep saying something, or the guard passes on empty rules.
    for selector in (".tt-cell-cover", ".tt-cell-hazard", ".tt-cell-difficult"):
        assert rules[selector] & {"fill"}, f"{selector} no longer fills its square"


def test_shipped_terrain_art_node_regressions():
    result = subprocess.run(
        ["node", str(TABLETOP / "terrain-art.test.mjs")],
        cwd=ROOT, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_only_allow_listed_map_art_draws_a_border():
    """No map-art style draws a border unless it is on the allow-list above, and the list stays honest.

    Reading every stylesheet (so the map editor is covered too) and every map-art family (so a new material
    cannot start drawing frames quietly) is what makes this more than a check on today's three classes.
    """
    used: set[str] = set()
    for name in ("tabletop.css", "mapeditor.css"):
        for selector, declarations in css_rules((TABLETOP / name).read_text()):
            if not _borders(declarations):
                continue
            for part in selector.split(","):
                part = part.strip()
                family = _family(part)
                if family is None:
                    continue  # UI chrome around the board is a different thing; not map art
                assert family in ALLOWED_BORDER, (
                    f"{name}: {part} draws a border ({', '.join(sorted(_borders(declarations)))}) but {family} is not "
                    f"on the allow-list. Natural ground and loose objects get no frames; add the entry here with its "
                    f"reason if this is a rules overlay.")
                used.add(family)
    # Nothing on the allow-list may rot into dead weight: a stale entry would quietly widen the guard.
    stale = set(ALLOWED_BORDER) - used
    assert not stale, f"allow-list entries nothing uses any more: {sorted(stale)}"


def test_object_art_draws_no_square_cell_frame():
    """Object strokes follow the object's shape; none of them traces its square.

    A stroke on a rect covering the whole 64x64 cell would be a frame round the square, which is what the owner
    is reporting -- the barrel's hoops and the gate's bars are the drawing itself and stay.
    """
    art = (TABLETOP / "object-art.js").read_text()
    assert "viewBox=\"0 0 64 64\"" in art
    whole_cell = re.findall(r'<rect[^>]*\bx="0"[^>]*\by="0"[^>]*width="64"', art)
    assert not whole_cell, f"object art strokes a full-cell rect: {whole_cell}"


def test_the_table_grid_and_its_toggle_are_untouched():
    """The owner keeps the general table grid: this change is about frames round terrain, not the grid.

    The grid is drawn as SVG strokes in board.js rather than from the stylesheet, so it is not in the allow-list
    above -- it is checked here instead, together with the map editor's slider that sets it.
    """
    board = (TABLETOP / "board.js").read_text()
    assert "tt-grid-cell" in board, "the table grid is gone"
    assert "display.gridOpacity" in board, "the grid's strength is no longer read from the map's display settings"
    editor = (TABLETOP / "mapeditor.html").read_text()
    assert 'id="meGrid"' in editor, "the map editor lost its grid strength slider"
    assert "#meGrid" in (TABLETOP / "mapeditor.js").read_text(), "the grid slider is no longer wired to the map"


def test_painted_natural_ground_is_drawn_without_a_frame():
    """Ground the map itself painted gets no edge; an effect a character cast keeps its own.

    Checked as real behaviour (zones.js paintedGround, in node, the same module board.js uses) and as the one
    place board.js decides to draw the frame, so neither half can drift on its own.

    The negative examples are the two that matter and were missed the first time round (review MMX111 finding 2):
    Guarded Threshold (combat/ext/vermilion_gate.py) and Grove Domain's Living Claims
    (combat/ext/verdant_chassis.py) both declare shape "painted" and paint flat ground art, because they were
    written to look like ground.  A classifier that reads the shape alone swallows their team-coloured edge and
    makes those squares indistinguishable from ordinary terrain.
    """
    subprocess.run(["node", "--input-type=module", "-e", """
      import assert from 'node:assert/strict';
      const {paintedGround, MAP_TERRAIN_SOURCE} = await import(process.argv[1]);
      // combat/zones.py map_zones builds the map's own terrain areas from the arena's "map_terrain" rows and
      // stamps them with this one source.  Every terrain a map may be painted with is covered by that alone.
      assert.equal(MAP_TERRAIN_SOURCE, 'system:battlefield.terrain');
      for (const name of ['loose rubble', 'courtyard mist', 'mountain mist', 'bamboo thicket', 'sand terrain']) {
        const zone = {source_definition_id: MAP_TERRAIN_SOURCE,
                      trigger_profile: {shape: 'painted', name, map: true, terrain: [name]}};
        assert.equal(paintedGround(zone), true, name);
      }
      // A cast area effect is not the landscape, whatever shape it uses.
      for (const source of ['action:typed.factory.spores.BASE_SPORECLOUD', 'TAL_SOME_COURT', undefined]) {
        for (const shape of ['sphere', 'cone', 'line', 'painted', undefined]) {
          const profile = {kind: 'TYPED', visual: {material: 'poison'}, ...(shape ? {shape} : {})};
          assert.equal(paintedGround({source_definition_id: source, trigger_profile: profile}), false,
            `${source} / ${shape}: a cast effect is never the map's own ground`);
        }
      }
      // The two painted abilities this lane once mistook for terrain, exactly as their plug-ins declare them.
      const guardedThreshold = {source_definition_id: 'tianxia.subpath.body.vermilion_gate_guardian_body.feature.guardian_at_the_gate',
        trigger_profile: {kind: 'TYPED', shape: 'painted', difficult: 'hostile', visual: {material: 'sealed'},
                          gate_threshold: true}};
      const livingClaims = {source_definition_id: 'TAL_VERDANT_GROWTH_GROVE_DOMAIN_COURT_OF_ROOT_AND_BRANCH',
        trigger_profile: {kind: 'TYPED', shape: 'painted', difficult: 'hostile', aura: true, visual: {material: 'foliage'}}};
      assert.equal(paintedGround(guardedThreshold), false, 'Guarded Threshold keeps its edge');
      assert.equal(paintedGround(livingClaims), false, "Grove Domain's Living Claims keep their edge");
      // And nothing about the shape or the map flag alone may decide it, in either direction.
      assert.equal(paintedGround({trigger_profile: {shape: 'painted', map: true}}), false,
        'the shape and map flags alone must not make something read as the map');
      assert.equal(paintedGround({}), false);
      assert.equal(paintedGround(null), false);
    """, (TABLETOP / "zones.js").as_uri()], check=True, timeout=30)

    board = (TABLETOP / "board.js").read_text()
    assert "paintedGround" in board, "board.js must decide the frame from zones.js paintedGround"
    # The frame is the one thing gated on it: a bare `if (scenery)` guard only covered bamboo.
    assert re.search(r"if \(!painted\) \{\s*\n\s*const outline = outlinePath\(cellOutline\(cells\)\)", board), (
        "board.js draws the zone edge unconditionally again; painted ground needs no frame")
    # No terrain is named to get this treatment.
    assert "const painted = paintedGround(zone)" in board


def test_only_the_map_owns_its_painted_terrain_provenance():
    """The client's classifier trusts one thing: which definition the area came from.  Only the map may claim it.

    zones.js paintedGround asks for source_definition_id "system:battlefield.terrain" and nothing else, so this
    is the guard that keeps that safe: exactly one place in combat/ may stamp it, and the plug-ins that paint
    flat ground art must not start doing so.  Their profiles are copied into
    static/tabletop/board-frames.test.mjs, so if one of them changes this fails rather than letting the copy rot.
    """
    provenance = 'source_definition_id="system:battlefield.terrain"'
    producers = [path for path in sorted((ROOT / "combat").rglob("*.py"))
                 if provenance in path.read_text() and path.name != "zones.py"]
    assert not producers, (f"only combat/zones.py map_zones may stamp map-terrain provenance; also in "
                           f"{[str(path.relative_to(ROOT)) for path in producers]}")
    assert provenance in (ROOT / "combat/zones.py").read_text(), "map_zones stopped stamping the map's own provenance"

    painted_cast_areas = {
        "ext/vermilion_gate.py": ["sealed", "gate_threshold"],       # Guardian at the Gate: Guarded Threshold
        "ext/verdant_chassis.py": ["foliage", "aura"],              # Grove Domain: Living Claims
    }
    for name, markers in painted_cast_areas.items():
        source = (ROOT / "combat" / name).read_text()
        for marker in markers:
            assert marker in source, f"{name} no longer declares {marker}; update the copied profile in board-frames"
        assert 'source_definition_id="system:battlefield.terrain"' not in source, (
            f"{name} claims the map's own painted-terrain provenance, so the table would stop drawing its edge")


def test_the_board_really_draws_no_frame_round_terrain_and_keeps_effect_edges():
    """Run the board, look at the nodes it drew (checklist 7: the level the bug showed, not the source text).

    static/tabletop/board-frames.test.mjs builds the real board through createBoard and asserts, on the nodes that
    come out: fight terrain and real editor rubble previews have no halo and no outline; editor bamboo keeps
    its ground art without haze, hatch, frame or label; a cast area keeps both (including the two painted abilities
    the first round lost them), the table grid the owner kept is still drawn, and the per-square ground washes
    still fill and carry no border of their own.
    """
    import os

    rendered = subprocess.run(
        ["node", "--test", str(ROOT / "static/tabletop/board-frames.test.mjs")],
        env={**os.environ}, capture_output=True, text=True, cwd=str(ROOT.parent), timeout=180)
    assert rendered.returncode == 0, rendered.stdout + rendered.stderr
