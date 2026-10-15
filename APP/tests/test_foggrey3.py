"""Real board snapshots plus librsvg software pixels. No GUI or model servers."""
import base64
import io
import json
from pathlib import Path
import os
import subprocess

from PIL import Image, ImageChops
import pytest
from test_fogedge_frontier import _absolute_imports

STATIC = Path(__file__).resolve().parents[1] / 'static' / 'tabletop'


@pytest.mark.parametrize('pattern,message', [
    ('FOGGREY3 tree-only reconstruction', 'tree-only memory must allocate no wall library'),
    ('FOGGREY3 shared wall patterns', 'one wall library per remembered layer'),
])
def test_wall_allocation_regressions_reject_precorrection_board(tmp_path, pattern, message):
    before = subprocess.run(['git', 'show', 'fb4e8316:APP/static/tabletop/board.js'],
                            check=True, text=True, capture_output=True).stdout
    mutant = tmp_path / 'pre-allocation-fix-board.mjs'
    mutant.write_text(_absolute_imports(before, STATIC))
    source = _absolute_imports((STATIC / 'fog_memory_board.test.mjs').read_text(), STATIC)
    source = source.replace((STATIC / 'board.js').as_uri(), mutant.as_uri())
    check = tmp_path / 'pre-allocation-fix-check.mjs'
    check.write_text(source)
    result = subprocess.run(['node', '--test', '--test-isolation=none', '--test-reporter=tap',
                             f'--test-name-pattern={pattern}', str(check)],
                            text=True, capture_output=True, timeout=120)
    assert result.returncode != 0, 'the reviewed per-cell wall library unexpectedly passed'
    assert message in result.stdout, result.stdout + result.stderr


def board_data(check, pattern='FOGGREY3 saved scenery'):
    result = subprocess.run(['node', '--test', '--test-isolation=none', '--test-reporter=tap',
                             f'--test-name-pattern={pattern}', str(check)],
                            env={**os.environ, 'FOGGREY3_RASTER': '1'},
                            text=True, capture_output=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'FOGGREY3_RASTER:' in result.stdout, result.stdout + result.stderr
    line = next(line.split('FOGGREY3_RASTER:', 1)[1] for line in result.stdout.splitlines()
                if 'FOGGREY3_RASTER:' in line)
    return json.loads(line)


def raster_board(data):
    def uri(image):
        buf = io.BytesIO()
        image.save(buf, format='PNG')
        return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()
    markup = data['markup']
    for source in data['images']:
        image = Image.frombytes('RGBA', (source['width'], source['height']), bytes(source['pixels']))
        markup = markup.replace(source['href'], uri(image))
    size = data['width'], data['height']
    board_width, board_height = data['boardWidth'], data['boardHeight']
    assert size == (board_width * 64, board_height * 64), 'raster must use exactly 64 pixels per board cell'
    assert len(data['gridAlpha']) == len(data['fogAlpha']) == size[0] * size[1]
    def alpha_image(values, rgb):
        return uri(Image.frombytes('RGBA', size, bytes(
            channel for value in values for channel in (*rgb, round(value * 255)))))
    grid_mask = alpha_image(data['gridAlpha'], (255, 255, 255))
    # Serialize the actual board DOM; only PNG encoding and CSS mask projection
    # are supplied by the harness. The tree/prop shapes are the real painters.
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{size[0]}" height="{size[1]}" viewBox="0 0 {board_width} {board_height}">
    <defs><mask id="grid" mask-type="alpha"><image width="{board_width}" height="{board_height}" href="{grid_mask}"/></mask></defs>
    <style>.tt-remembered-tile{{fill:#07090e}} .tt-remembered-mark{{fill:#ddd;font:600 .3px sans-serif;text-anchor:middle}}</style>
    <rect width="{board_width}" height="{board_height}" fill="red"/>
    <g mask="url(#grid)">{data['grid']}</g>{markup}
    </svg>'''
    raster = subprocess.run(['rsvg-convert'], input=svg.encode(), capture_output=True, timeout=60)
    assert raster.returncode == 0, raster.stderr.decode()
    ground = Image.open(io.BytesIO(raster.stdout)).convert('RGBA')
    # Project the actual board fog buffer once, after all SVG ground art, just
    # as the canvas above the remembered layer does in Chromium. This also
    # avoids treating an SVG image element as a substitute for a canvas layer.
    wash = Image.frombytes('RGBA', size, bytes(channel for value in data['fogAlpha']
        for channel in (7, 9, 14, round(value * 255))))
    return Image.alpha_composite(ground, wash).convert('RGB')


def board_pixels(check):
    data = board_data(check)
    assert abs(data['fogAlpha'][96 * data['width'] + 160] - 0.4) < 0.01
    return raster_board(data)


@pytest.mark.parametrize('width,height', [(4, 2), (5, 3)])
def test_raster_projection_aligns_art_mask_and_wash_at_64_pixels_per_cell(width, height):
    """Known coordinates catch distortion independently of the production painter."""
    size = width * 64, height * 64
    grid = [0] * (size[0] * size[1])
    wash = grid.copy()
    for y in range((height - 1) * 64, height * 64):
        for x in range((width - 1) * 64, width * 64):
            grid[y * size[0] + x] = 1
            wash[y * size[0] + x] = 0.4
    data = dict(width=size[0], height=size[1], boardWidth=width, boardHeight=height,
                images=[], markup='', gridAlpha=grid, fogAlpha=wash,
                grid=f'<rect width="{width}" height="{height}" fill="#00ff00"/>')
    masked = raster_board(data)
    assert masked.getpixel((size[0] - 32, size[1] - 32)) == (3, 157, 6)
    assert masked.getpixel((size[0] - 65, size[1] - 32)) == (255, 0, 0)
    # Artwork in the same cell must cover the projected grid, then receive the
    # same 0.4 fog wash at precisely the same pixel coordinates.
    data['markup'] = (f'<svg viewBox="0 0 {width} {height}">'
                      f'<rect x="{width - 1}" y="{height - 1}" width="1" height="1" fill="white"/></svg>')
    painted = raster_board(data)
    assert painted.getpixel((size[0] - 32, size[1] - 32)) == (156, 157, 159)
    assert painted.getpixel((size[0] - 65, size[1] - 32)) == (255, 0, 0)


def test_offset_open_prop_crosses_changed_cells_without_order_dependent_clipping(capsys):
    data = board_data(STATIC / 'fog_memory_board.test.mjs', 'FOGGREY3 offset open prop')
    forward, reverse, without = (raster_board(data[key]) for key in ('forward', 'reverse', 'withoutProp'))
    assert ImageChops.difference(forward, reverse).getbbox() is None, 'ghost order cannot clip saved prop pixels'
    changed = ImageChops.difference(forward, without)
    for box in ((160, 64, 192, 112), (192, 64, 224, 112)):
        count = sum(pixel != (0, 0, 0) for pixel in changed.crop(box).getdata())
        assert count > 20, 'the real saved open-door artwork must remain on BOTH sides of the cell boundary'
        with capsys.disabled():
            print(f'FOGGREY3 saved open door crop={box}: {count} prop pixels', flush=True)


def test_prop_regression_rejects_precorrection_board(tmp_path):
    before = subprocess.run(['git', 'show', '9ae29fae:APP/static/tabletop/board.js'],
                            check=True, text=True, capture_output=True).stdout
    mutant = tmp_path / 'pre-correction-board.mjs'
    mutant.write_text(_absolute_imports(before, STATIC))
    source = _absolute_imports((STATIC / 'fog_memory_board.test.mjs').read_text(), STATIC)
    source = source.replace((STATIC / 'board.js').as_uri(), mutant.as_uri())
    check = tmp_path / 'pre-correction-check.mjs'
    check.write_text(source)
    result = subprocess.run(['node', '--test', '--test-isolation=none', '--test-reporter=tap',
                             '--test-name-pattern=FOGGREY3 offset open prop', str(check)],
                            text=True, capture_output=True, timeout=120)
    assert result.returncode != 0, 'per-cell prop painting unexpectedly passed'
    assert 'saved props must paint after ALL reconstructed ground' in result.stdout, result.stdout + result.stderr
    # Remove just the new structural checks so the actual pre-fix painter can
    # also demonstrate its order-dependent pixel loss across the shared edge.
    start = source.index("  const pictures = reloaded.board.element.querySelector('.tt-remembered-pictures');")
    end = source.index('  const reverse = draw(', start)
    check.write_text(source[:start] + source[end:])
    data = board_data(check, 'FOGGREY3 offset open prop')
    forward, reverse = (raster_board(data[key]) for key in ('forward', 'reverse'))
    assert ImageChops.difference(forward, reverse).getbbox() is not None, 'old prop clipping must depend on ghost order'


def test_remembered_scenery_pixels_and_no_cell_grid(capsys):
    image = board_pixels(STATIC / 'fog_memory_board.test.mjs')
    # Both saved cells retain the snowy pine, including its adjacent overhang.
    for x in (2, 3):
        colors = list(image.crop((x * 64 + 8, 72, x * 64 + 56, 120)).getdata())
        assert len(set(colors)) > 100, 'remembered map artwork must retain pixel variance'
        assert max(p[1] for p in colors) - min(p[1] for p in colors) > 35, 'tree shape must survive the wash'
        green = sum(g > r + 6 for r, g, b in colors)
        assert green > 20, 'saved pine colours must survive on both squares'
        with capsys.disabled():
            print(f'FOGGREY3 saved cell x={x}: {len(set(colors))} colours, green-range={max(p[1] for p in colors)-min(p[1] for p in colors)}, pine-pixels={green}', flush=True)
    # Check the mask itself at every pixel on the shared grid boundary. This
    # avoids counting a branch/shadow crossing the boundary as a grid stroke.
    # The board test also checks that current-sight grid coverage remains 1.


def test_regression_rejects_base_board(tmp_path, capsys):
    base = subprocess.run(['git', 'show', 'eddb793e:APP/static/tabletop/board.js'],
                          check=True, text=True, capture_output=True).stdout
    mutant = tmp_path / 'base-board.mjs'
    mutant.write_text(_absolute_imports(base, STATIC))
    source = (STATIC / 'fog_memory_board.test.mjs').read_text()
    source = _absolute_imports(source, STATIC).replace((STATIC / 'board.js').as_uri(), mutant.as_uri())
    # Allow a base board to run the new capture path, then measure its actual
    # remembered renderer. This shim supplies metadata only, never painting.
    source = source.replace('  const store = {getItem:',
                            '  board.sceneryRecordAt ||= () => null;\n  board.objectArtRecordAt ||= () => null;\n  const store = {getItem:')
    source = source.replace("  assert.ok(capturedObject.includes('rotate(90'), 'store the perceived object orientation as a string');", '')
    check = tmp_path / 'base-check.mjs'
    check.write_text(source)
    result = subprocess.run(['node', '--test', '--test-isolation=none', '--test-reporter=tap', '--test-name-pattern=FOGGREY3 saved scenery', str(check)],
                            text=True, capture_output=True, timeout=120)
    assert result.returncode != 0, 'the floor-only base renderer unexpectedly passed'
    assert 'floor isolation must restore' in result.stdout, result.stdout + result.stderr
    # After proving the real new regression fails on base, remove only its new
    # structural assertions to measure the old renderer's software pixels too.
    target = source.index("test('FOGGREY3 saved scenery survives")
    start = source.index("  assert.equal(layer.querySelectorAll('.tt-remembered-scenery')", target)
    end = source.index('  const markup = serializeBoardNode(layer);', start)
    source = source[:start] + source[end:]
    source = source.replace('const cut = alphaFromHref(grid.style.maskImage);',
                            'const cut = rasterCanvas(WIDTH * CELL, HEIGHT * CELL); cut.alpha.fill(1);')
    check.write_text(source)
    before = board_pixels(check)
    colors = list(before.crop((136, 72, 184, 120)).getdata())
    green = sum(g > r + 6 for r, g, b in colors)
    assert len(set(colors)) <= 100, 'base must fail the same remembered-art colour-variance regression'
    assert green <= 20, 'base must fail the same pine-colour pixel regression'
    with capsys.disabled():
        print(f'FOGGREY3 eddb793e: {len(set(colors))} colours, green-range={max(p[1] for p in colors)-min(p[1] for p in colors)}, pine-pixels={green}', flush=True)
