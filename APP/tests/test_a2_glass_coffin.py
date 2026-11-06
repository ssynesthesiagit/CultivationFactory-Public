"""The printed Action opening a shell commits through the table and cold replay."""
from combat.ext.glass_coffin import shells
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload
from tests.cw2_service_support import add_action, seal

COFFIN = 'TAL_GLASS_GLASS_COFFIN_WITHOUT_DEATH'


def test_open_coffin_ends_only_its_own_guarded_condition(tmp_path):
    def prepare(bundles):
        add_action(bundles[0], 'Independent Incapacity', [
            {'type': 'condition', 'condition': 'incapacitated',
             'applies_to': 'target', 'duration': {'kind': 'hours', 'amount': 24}},
            {'type': 'condition', 'condition': 'unconscious',
             'applies_to': 'target', 'duration': {'kind': 'hours', 'amount': 24}}])
        seal(bundles[0])

    combat, table, mid = fixture(tmp_path, [COFFIN], bundle_transform=prepare, foe_position={'x': 4, 'y': 5})
    # Printed cursed/poisoned/unconscious targets can be opponents too. The
    # independent incapacity checks exact-instance cleanup, not consent policy.
    settle(table, mid, candidate(combat, mid, 'Independent Incapacity', target=FOE).candidate_id)
    settle(table, mid, candidate(combat, mid, 'Glass Coffin Without Death', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    owner, ally = engine.state.actors[OWNER], engine.state.actors[FOE]
    held = shells(engine, owner, ally)
    assert len(held) == 1
    shell_id = held[0].object_id
    guarded = set(held[0].component['bound']['conditions'])
    assert guarded and guarded <= set(ally.conditions)
    other = {iid for iid, c in ally.conditions.items() if c.condition_id == 'condition:typed.incapacitated'} - guarded
    assert other
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Open Glass Coffin', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    assert not guarded & set(engine.state.actors[FOE].conditions)
    assert other <= set(engine.state.actors[FOE].conditions)
    assert engine.state.objects[shell_id].destroyed
    assert not shells(engine, engine.state.actors[OWNER], engine.state.actors[FOE])
    assert not [c for c in engine.legal_candidates()
                if engine.action_catalog.get(c.source_definition_id)
                and engine.action_catalog[c.source_definition_id].display_name == 'Open Glass Coffin']


def test_open_coffin_requires_touch_range(tmp_path):
    combat, table, mid = fixture(tmp_path, [COFFIN], ally_position={'x': 12, 'y': 12})
    engine = reload(tmp_path, mid)
    assert not [c for c in engine.legal_candidates()
                if engine.action_catalog.get(c.source_definition_id)
                and engine.action_catalog[c.source_definition_id].display_name == 'Open Glass Coffin']
