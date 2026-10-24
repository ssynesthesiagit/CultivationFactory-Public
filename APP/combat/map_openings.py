"""Opt-in placed wall openings, shared by map rasterization and arena export.

The editor stores integer hundredths for the wall coordinate. Legacy maps have
no mount metadata and retain precisely their previous rasterization.
"""

def opening_cells(wall, objects):
    cells = set()
    if wall.get('shape') != 'line':
        return cells
    for obj in objects:
        if obj.get('kind') not in {'door', 'gate', 'window'}:
            continue
        for a, b in zip(wall['points'], wall['points'][1:]):
            axis = 'h' if a[1] == b[1] else 'v' if a[0] == b[0] else None
            if axis is None or obj.get('mount_axis') != axis:
                continue
            cross = 1 if axis == 'h' else 0
            along = 1 - cross
            lo = obj['y'] if along else obj['x']
            if (obj.get('mount_line') == round(a[cross] * 100)
                    and min(a[along], b[along]) <= lo and max(a[along], b[along]) >= lo + 1):
                cells.add((obj['mount_line'] // 100 if axis == 'v' else obj['x'],
                           obj['mount_line'] // 100 if axis == 'h' else obj['y']))
    return cells


def placed_wall_cells(wall, document, raster):
    # Cut each matching segment before unioning: another segment of the same
    # polyline can still block the aperture square, just like another wall.
    segments = ([{**wall, 'points': [a, b]}
                 for a, b in zip(wall['points'], wall['points'][1:])]
                if wall.get('shape') == 'line' else [wall])
    cells = set()
    for segment in segments:
        cells.update(raster(segment, document['width_squares'], document['height_squares'])
                     - opening_cells(segment, document.get('objects', [])))
    return cells
