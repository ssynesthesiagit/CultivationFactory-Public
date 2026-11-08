"""Table regression for a paid damage response during declaration priority."""
from tests.cw2_service_support import add_action, seal
from tests.worker2_support import OWNER, FOE, candidate, fixture, reload, settle, turn


def test_paid_damage_row_does_not_break_attack_declaration(tmp_path):
    def prepare(bundles):
        bundles[0]['typed_reactions'].extend([
            {'block': 'generic', 'kind': 'attacked', 'feature_id': 'test:early_guard',
             'name': 'Early guard', 'costs': [], 'effects': []},
            {'block': 'generic', 'kind': 'damaged', 'feature_id': 'test:damage_answer',
             'name': 'Damage answer', 'costs': [['resource:core.qi', 1]],
             'effects': [{'type': 'temp_hp', 'flat': 1, 'applies_to': 'self'}]},
        ])
        add_action(bundles[2], 'Attack probe',
                   [{'type': 'attack', 'attack_kind': 'unarmed', 'count': 1}],
                   typed={'attack_bonus': 100})
        for bundle in bundles:
            seal(bundle)
    combat, table, mid = fixture(tmp_path, [], ask=False, bundle_transform=prepare)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Attack probe', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    assert any(event.event_type == 'REACTION_RESOLVED'
               and event.source_definition_id == 'test:early_guard'
               for event in engine.events)
