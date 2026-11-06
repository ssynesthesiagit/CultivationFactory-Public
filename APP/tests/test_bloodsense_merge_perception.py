"""Ground-level object visibility and private Bloodsense facts coexist after merge."""
from combat import senses
from tests.worker2_support import OWNER, ALLY, fixture, reload


def test_ground_view_keeps_visible_objects_and_private_findings(tmp_path, monkeypatch):
    from combat import menu_rank, embedding_rank
    monkeypatch.setattr(menu_rank, '_CLIENT', embedding_rank.EmbeddingClient(
        transport=lambda url, body, timeout: {'data': []}))

    def arena(doc):
        doc['sensory_sources'] = [{'medium': 'blood', 'kind': 'spill',
            'position': {'x': 5, 'y': 6}, 'exposed': 1, 'occurred_at_seconds': -30}]
        doc['map_objects'] = [{'id': 700, 'kind': 'custom', 'x': 5, 'y': 6,
            'name': 'vial', 'size': 'tiny', 'blocks': False, 'hp': 10}]

    _, table, mid = fixture(tmp_path, ['BLOOD_BASE_BLOODSENSE'], battlefield_transform=arena)
    expected = 'Bloodsense: Blood was spilled to the east within the last hour.'
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.position.z == 0
    visible = {obj.object_id for obj in engine.state.objects.values()
               if not obj.destroyed and not obj.suppressed
               and senses.perceives_object(engine, owner, obj)}
    assert visible
    perception = senses.perception(engine, owner)
    assert visible <= set(perception['objects'])
    assert expected in perception['information_text']
    state = table.state(mid, fog=True, fog_view='own', fog_actor_ids=(OWNER, ALLY))
    assert visible <= set(state['fog_perception'][OWNER]['objects'])
    assert expected in state['fog_perception'][OWNER]['information_text']
    assert not state['fog_perception'][ALLY].get('information_text')
