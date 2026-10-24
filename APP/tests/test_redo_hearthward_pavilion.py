"""Hearthward Pavilion is a live reviewed feature over the owned Kindled Hearth (F8R finding 1)."""
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload

BASE = 'tianxia.subpath.qi.hearthfire_cultivator.feature.'
HEARTH = BASE + 'kindled_hearth'
PAVILION = BASE + 'hearthward_pavilion'
WELCOME = BASE + 'flame_that_welcomes_all'
POSITIONS = {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 6, 'y': 6}, FOE: {'x': 15, 'y': 8}}


def test_pavilion_is_offered_over_an_active_hearth_and_guards_its_recipients(tmp_path):
    from combat.tabletop import normalize_map, to_battlefield
    from combat.spatial_areas import zone_contains
    from combat.ext.qi_hearthward_pavilion import guarded
    battlefield = to_battlefield(normalize_map({'display_name': 'Open pavilion',
        'width_squares': 20, 'height_squares': 14, 'walls': [], 'objects': []}))
    combat, table, mid = fixture(tmp_path, [], cl=10, owner_pb=4,
        owner_features=[HEARTH, PAVILION], battlefield=battlefield, positions=POSITIONS)
    settle(table, mid, candidate(combat, mid, 'Kindled Hearth', at=(5, 6)).candidate_id,
           choices={'choice:needle.kindled_hearth_recipients': [OWNER, ALLY]})
    settle(table, mid, candidate(combat, mid, 'Hearthward Pavilion').candidate_id,
           choices={'choice:needle.pavilion_recipients': [OWNER, ALLY]})
    engine = reload(tmp_path, mid)
    zones = [z for z in engine.state.zones.values() if z.active
             and (z.trigger_profile.get('profile') or {}).get('hearthward_pavilion')]
    assert len(zones) == 1, 'the Pavilion must create exactly one live 20-foot field'
    zone = zones[0]
    assert zone.trigger_profile['profile']['recipients'] == [OWNER, ALLY]
    assert zone_contains(engine, engine.state.actors[ALLY], zone)
    assert guarded(engine, engine.state.actors[ALLY]), 'a chosen ally inside gains the Pavilion protection'
    assert not guarded(engine, engine.state.actors[FOE]), 'a foe receives no Pavilion protection'


def test_pavilion_needs_an_active_hearth(tmp_path):
    from combat.tabletop import normalize_map, to_battlefield
    battlefield = to_battlefield(normalize_map({'display_name': 'No hearth',
        'width_squares': 20, 'height_squares': 14, 'walls': [], 'objects': []}))
    combat, table, mid = fixture(tmp_path, [], cl=10, owner_pb=4,
        owner_features=[HEARTH, PAVILION], battlefield=battlefield, positions=POSITIONS)
    engine = combat._load_session(mid).engine
    names = {engine.action_catalog[c.source_definition_id].display_name
             for c in engine.legal_candidates() if c.source_definition_id in engine.action_catalog}
    assert 'Hearthward Pavilion' not in names, 'no Kindled Hearth means no Pavilion candidate'


def test_flame_record_routes_every_printed_clause_to_live_hooks():
    """Finding 3: the Flame clauses removed from riders_lane11.json stay covered by the plug-in."""
    import json, pathlib
    import combat.ext.qi_welcoming_flame as flame
    root = pathlib.Path(__file__).resolve().parents[1] / 'authority/typed_mechanics/reviewed_final.d/riders_lane11.json'
    row = json.loads(root.read_text())['mechanics'][WELCOME]
    assert row['effects'] == [{'type': 'qi_welcoming_flame', 'applies_to': 'self'}]
    for hook in ('armor', 'resistance', 'saves', 'ordinary_immunity', 'weather_immunity', 'reduction', 'start', 'no_guest_dies_alone', 'entry'):
        assert callable(getattr(flame, hook)), hook
