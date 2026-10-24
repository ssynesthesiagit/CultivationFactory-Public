"""Automatic Palace recipients do not require sight; no model transport is used."""
import json

from combat.factory_compiler import compile_character
from combat.gate4_adapters import ManualControllerAdapter
from combat.ext.taiyin_palace import FOUNDATION, STATE
from combat.stealth import sees
from combat.targeting import line_of_effect
from tests.h1_support import sheet
from tests.cw2_service_support import add_action
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload


def test_blinded_automatic_owner_protects_known_adjacent_unseen_ally(tmp_path):
    doc = sheet([])
    doc['foundation'] = {'foundation_id': FOUNDATION, 'stage': 'Perfected'}

    def setup(bundles):
        add_action(bundles[0], 'Blindfold', [
            {'type': 'condition', 'condition': 'blinded', 'applies_to': 'self',
             'duration': 'one_minute'}], target='SELF')

    combat, table, mid = fixture(
        tmp_path, [], owner_bundle=compile_character(doc, actor_id=OWNER),
        bundle_transform=setup, seed='PALACE-UNSEEN',
        battlefield={'stable_id': 'battlefield:palace-unseen', 'display_name': 'Open field',
                     'width_squares': 20, 'height_squares': 14, 'square_size_ft': 5,
                     'starting_positions': {}, 'terrain_regions': []})
    # The ally begins adjacent and known; blinding the owner does not impose
    # a new sight prerequisite on the Palace's chosen-allies rule.
    settle(table, mid, candidate(combat, mid, 'Blindfold', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    owner, ally = engine.state.actors[OWNER], engine.state.actors[ALLY]
    assert not sees(engine, owner, ally)
    assert line_of_effect(engine, owner, target=ally)
    cid = candidate(combat, mid, 'Perfected — True Moon Yin Palace', target=OWNER).candidate_id
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    native = combat.controller
    # Choose only the primary action in the fake: recipient choice remains the
    # native automatic policy, with its full legal option set.
    combat.controller = ManualControllerAdapter(
        lambda context: (cid, ()),
        reaction_chooser=lambda context: native.choose_reaction(context).decision)
    assert settle(table, mid, cid, auto=True) == []
    engine = reload(tmp_path, mid)
    field = next(c for c in engine.state.actors[OWNER].conditions.values()
                 if c.condition_id == STATE)
    assert set(json.loads(field.data['chosen'])) == {OWNER, ALLY}
    from combat.ext.taiyin_palace import protects
    assert protects(engine, engine.state.actors[ALLY], engine.state.actors[FOE], {'cold'})
