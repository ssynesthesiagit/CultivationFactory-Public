"""GHOSTMARK1BF9R regression: a creature seen on an earlier fog read keeps its remembered answer.

A browser that loads the page asks for nothing on its first read. The server must still record what the viewer
perceives on that read, so a later request about a creature that has since left sight is answered.
The sight geometry is replaced by a switch in the test, so the test pins only the memory rule.
"""
from tests.test_ghostmark1bf7 import _match


def test_creature_seen_on_an_unasked_read_is_still_answered_after_it_leaves_sight(tmp_path, monkeypatch):
    service, mid, ids = _match(tmp_path)
    viewer = (ids[0],)
    seen_now = {ids[1]}  # the other fighter is in sight of the viewer until this set is cleared
    real_perception = service._fog_perception

    def perception_with_switch(match_id, engine, viewer_ids=None):
        out = real_perception(match_id, engine, viewer_ids)
        rows = {aid: {**row, 'creatures': [c for c in row.get('creatures', []) if c != ids[1]]}
                for aid, row in out.items()}
        if seen_now:
            rows.setdefault(ids[0], {'creatures': []})['creatures'] = [*rows.get(ids[0], {}).get('creatures', []), ids[1]]
        return rows

    monkeypatch.setattr(service, '_fog_perception', perception_with_switch)
    # First read asks about no creature (what a freshly loaded page does) but sees the other fighter.
    first = service.state(mid, fog=True, fog_view='own', fog_actor_ids=viewer)
    assert ids[1] in first['fog_perception'][ids[0]]['creatures']
    # The other fighter now leaves the viewer's sight; the browser asks about it by id.
    seen_now.clear()
    later = service.state(mid, fog=True, fog_view='own', fog_actor_ids=viewer,
                          remembered_ids=(ids[1], 'not-in-this-fight'))
    assert ids[1] not in later['fog_perception'][ids[0]]['creatures']
    assert later['remembered_in_match'] == [ids[1]]
