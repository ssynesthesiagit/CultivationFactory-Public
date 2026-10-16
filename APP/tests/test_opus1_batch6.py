"""OPUS1 batch 6: Insights that act when Initiative is rolled (fight-setup queue), with cold reloads."""
from combat.canonical import canonical_sha256
from combat.ext import initiative_insights as ii
from combat.ext.drunken_style import MARK
from combat.typed_executor import mark_condition_id
from tests.h1_support import sheet
from tests.worker2_support import FOE, OWNER, fixture, reload

WARLEADER = ['WARLEADER_BASE_SET_THE_STANDARD', 'WARLEADER_BASE_MOMENTUM_MARKS']
REELING = 'TAL_DRUNKEN_STYLE_REELING_STEP'
STANDARD = 'condition:typed.warleader_standard'


def _without_focus(bundles):
    for row in bundles[0]['actor_template']['resources']:
        if row['resource_id'] == 'resource:core.martial_focus':
            row['initial'] = 0
    bundles[0].pop('bundle_sha256', None)
    bundles[0]['bundle_sha256'] = canonical_sha256(bundles[0])


def _setup_done(engine):
    return any(e.event_type == 'FIGHT_SETUP_COMPLETED' for e in engine.events)


def test_emergency_commander_sets_a_standard_before_turn_one(tmp_path):
    combat, table, mid = fixture(tmp_path, WARLEADER, owner_insights=[ii.EMERGENCY], ally_position={'x': 1, 'y': 9})
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert _setup_done(engine)
    first_turn = next(i for i, e in enumerate(engine.events) if e.event_type == 'TURN_STARTED')
    set_at = next(i for i, e in enumerate(engine.events) if e.event_type == 'CONDITION_APPLIED'
                  and (e.payload or {}).get('condition_id') == STANDARD and OWNER in e.target_ids)
    assert set_at < first_turn  # set when Initiative was rolled, before any turn


def test_emergency_commander_needs_the_insight(tmp_path):
    combat, table, mid = fixture(tmp_path, WARLEADER, ally_position={'x': 1, 'y': 9})
    engine = reload(tmp_path, mid)
    first_turn = next(i for i, e in enumerate(engine.events) if e.event_type == 'TURN_STARTED')
    assert not any(e.event_type == 'CONDITION_APPLIED' and (e.payload or {}).get('condition_id') == STANDARD
                   for e in engine.events[:first_turn])


def test_fools_balance_reels_before_turn_one_and_regains_focus(tmp_path):
    combat, table, mid = fixture(tmp_path, [REELING], owner_insights=[ii.FOOLS_BALANCE], foe_sheet=sheet([], cl=15, score=1),
                                 foe_position={'x': 4, 'y': 6}, ally_position={'x': 1, 'y': 9}, bundle_transform=_without_focus)
    engine = reload(tmp_path, mid)
    first_turn = next(i for i, e in enumerate(engine.events) if e.event_type == 'TURN_STARTED')
    early = engine.events[:first_turn]
    assert any(e.event_type == 'SAVE_ROLLED' and e.actor_id == FOE for e in early)
    assert any(e.event_type == 'CONDITION_APPLIED' and (e.payload or {}).get('condition_id') == mark_condition_id(MARK, OWNER)
               for e in early)
    assert any(e.event_type == 'RESOURCE_GAINED' and e.source_definition_id == ii.FOOLS_BALANCE for e in early)
