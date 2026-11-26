"""A map keeps a recorded material the rules table has no default for (Cutting Current's list).

The rules table (combat/rules/objects.json) knows rope, cloth, paper, wood, stone and metal. Cutting
Current's printed clause also names ash, salt, mud, clay and soft stone, so a map may record those
materials. The map keeps the author's own facts (material, AC, HP) instead of dropping them; a
material label remains available even without explicit numbers; durability is resolved separately.
"""
from combat.tabletop import TabletopMapStore


def store(tmp_path):
    root = tmp_path / 'maps'
    root.mkdir(parents=True, exist_ok=True)
    return TabletopMapStore(root)


def test_map_keeps_a_listed_material_and_an_unlisted_one_with_its_own_numbers(tmp_path):
    document = {
        'map_id': 'cutting-material-yard',
        'display_name': 'Cutting material yard',
        'width_squares': 10, 'height_squares': 8,
        'starts': {'team1': [[1, 1]], 'team2': [[8, 6]]},
        'walls': [],
        'objects': [
            {'id': 1, 'kind': 'custom', 'name': 'Rope coil', 'material': 'ROPE', 'x': 2, 'y': 2},
            {'id': 2, 'kind': 'custom', 'name': 'Ash pile', 'material': 'ash', 'x': 3, 'y': 2},
            {'id': 3, 'kind': 'custom', 'name': 'Clay urn', 'material': 'clay', 'x': 4, 'y': 2,
             'ac': 11, 'hp': 9},
        ],
    }
    saved = store(tmp_path).save(document)
    rows = {row.get('name'): row for row in saved['objects']}
    # A listed material is normalised to the rules table's spelling.
    assert rows['Rope coil']['material'] == 'rope'
    # Material classification survives independently of durability overrides.
    assert rows['Ash pile']['material'] == 'ash'
    assert 'ac' not in rows['Ash pile'] and 'hp' not in rows['Ash pile']
    # An unlisted material with explicit AC and HP is kept as recorded.
    assert rows['Clay urn']['material'] == 'clay'
    assert (rows['Clay urn']['ac'], rows['Clay urn']['hp']) == (11, 9)


def test_map_keeps_unlisted_material_with_partial_numbers(tmp_path):
    document = {
        'map_id': 'cutting-material-yard-2',
        'display_name': 'Cutting material yard two',
        'width_squares': 10, 'height_squares': 8,
        'starts': {'team1': [[1, 1]], 'team2': [[8, 6]]},
        'walls': [],
        'objects': [
            {'id': 1, 'kind': 'custom', 'name': 'Salt heap', 'material': 'salt', 'x': 2, 'y': 2, 'ac': 11},
            {'id': 2, 'kind': 'custom', 'name': 'Mud pit', 'material': 'mud', 'x': 3, 'y': 2, 'hp': 9},
            {'id': 3, 'kind': 'custom', 'name': 'Soft stone', 'material': 'soft stone', 'x': 4, 'y': 2,
             'ac': 12, 'hp': 15},
        ],
    }
    saved = store(tmp_path).save(document)
    rows = {row.get('name'): row for row in saved['objects']}
    assert rows['Salt heap']['material'] == 'salt'
    assert rows['Salt heap']['ac'] == 11 and 'hp' not in rows['Salt heap']
    assert rows['Mud pit']['material'] == 'mud'
    assert rows['Mud pit']['hp'] == 9 and 'ac' not in rows['Mud pit']
    assert rows['Soft stone']['material'] == 'soft stone'
    assert (rows['Soft stone']['ac'], rows['Soft stone']['hp']) == (12, 15)
