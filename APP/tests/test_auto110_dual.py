"""AUTO110 Dual Wielding: Defensive Whirl really costs Focus and really denies the attack rolls it names.

Table level: every case commits through TabletopService, cold-reloads CombatService and
replays. The assertion that matters is the printed window -- "Until the end of that
creature's next turn" -- so a one-round approximation or a blanket penalty fails here.

Note the cost is asserted from the RESOURCE_SPENT record, not the closing balance: the
owner also owns Paired Rhythm ("hitting with both weapons of the pair regains Martial
Focus"), which honestly refunds the point in the same action.
"""
import pytest

from tests.worker2_support import OWNER, ALLY, FOE, fixture, settle, reload, turn
from tests.cw2_service_support import seal
from tests.test_auto_martial import DAGGER_PAIR_KIT

T = 'TAL_DUAL_WIELDING_'
FOCUS = 'resource:core.martial_focus'
ALL_THREE = [T + 'DEFENSIVE_WHIRL', T + 'DANCING_DISPLAY', T + 'DIZZYING_COMBINATION']


def setup(bundles, *, focus=None):
    """The owner's turn comes first and the struck creature's AC is 0, so the Paired Strike lands.

    The on-hit Pair talents are delivered off a real hit on the Answering Weapon; a seeded miss
    would silently skip the whole feature. ``focus`` sets the owner's starting Martial Focus.
    """
    for bundle, bonus in zip(bundles, [100, -100, 0]):
        bundle['actor_template']['initiative_bonus'] = bonus
        bundle['actor_template']['maximum_hp'] = 300
        if focus is not None:
            for row in bundle['actor_template']['resources']:
                if row['resource_id'] == FOCUS:
                    row['initial'] = focus
        seal(bundle)
    bundles[2]['actor_template']['armor_class'] = 0
    seal(bundles[2])


def weapon(combat, mid, suffix='', base=0):
    """The paired-strike attack candidates, exactly as the compiler produced them."""
    engine = combat._load_session(mid).engine
    basics = [a for a in engine.action_catalog.values() if a.owner_id == OWNER and '.weapon.' in a.source_definition_id
              and a.display_name.endswith(' attack') and '#' not in a.source_definition_id]
    action = basics[base]
    return next(c for c in engine.legal_candidates() if c.source_definition_id == action.source_definition_id + suffix
                and c.target_ids == (FOE,))


def whirls(engine):
    """Defensive Whirl modifiers: value names the owner, expiry names the holder's turn end."""
    return [m for m in engine.state.actors[FOE].modifiers.values()
            if m.target_field == 'attack_mode_vs' and m.value == f'DISADVANTAGE:{OWNER}']


def spent(engine):
    return [v for v in engine.events if v.event_type == 'RESOURCE_SPENT'
            and v.payload.get('resource_id') == FOCUS and v.actor_id == OWNER]


def paired_strike(table, combat, mid, pick):
    """Lead attack, then the Answering Weapon attack that triggers the on-hit Pair choice."""
    settle(table, mid, weapon(combat, mid).candidate_id)
    return settle(table, mid, weapon(combat, mid, '#offhand', base=1).candidate_id,
                  {'choice:needle.dual_pair': pick})


def pair_options(prompts):
    choice = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.dual_pair')
    return choice, [o['id'] for o in choice['choice']['options']]


def test_defensive_whirl_costs_focus_and_denies_rolls_until_the_targets_turn_ends(tmp_path):
    combat, table, mid = fixture(tmp_path, ALL_THREE, owner_kit=DAGGER_PAIR_KIT, foe_kit=DAGGER_PAIR_KIT,
                                 foe_position={'x': 3, 'y': 5}, bundle_transform=setup)
    prompts = paired_strike(table, combat, mid, 'dw_defensive_whirl')

    # The owner really is asked, and really sees all three Pair talents.
    choice, options = pair_options(prompts)
    assert choice['context']['reactor_id'] == OWNER
    assert set(options) == {'dw_dancing_display', 'dw_dizzying_combination', 'dw_defensive_whirl'}

    engine = reload(tmp_path, mid)
    # The printed cost ("Expend Martial Focus") was actually paid.
    assert len(spent(engine)) == 1
    assert spent(engine)[0].source_definition_id == 'TAL_DUAL_WIELDING_DEFENSIVE_WHIRL'
    assert spent(engine)[0].payload['amount'] == 1
    # The printed effect exists, on the struck creature only, for the printed window.
    assert len(whirls(engine)) == 1
    assert whirls(engine)[0].expires_on == 'END_OF_HOLDER_NEXT_TURN'
    # It is a real roll penalty, not bookkeeping: that creature's rolls against the owner are Disadvantage.
    assert engine._attack_mode(engine.state.actors[FOE], engine.state.actors[OWNER]) == 'DISADVANTAGE'
    # ...and it is scoped to the owner, not a blanket penalty.
    assert engine._attack_mode(engine.state.actors[FOE], engine.state.actors[ALLY]) != 'DISADVANTAGE'

    # "Until the end of that creature's next turn" -- it must not end before that turn ends.
    turn(table, mid, FOE)   # the owner's turn ends; the struck creature's turn begins
    assert whirls(reload(tmp_path, mid)), "ended before the struck creature's own turn ended"
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    assert not whirls(reload(tmp_path, mid)), "survived the end of the struck creature's own turn"


def test_pair_prompt_states_the_talent_owns_its_own_cost(tmp_path):
    """Checklist 13: the prompt may not promise "no cost" while one option really charges 1 Martial Focus.

    Asserted on the rendered text the player is shown (``moment``/``summary``, not the raw transport
    context), after a cold reload, next to the payment it describes.
    """
    combat, table, mid = fixture(tmp_path, ALL_THREE, owner_kit=DAGGER_PAIR_KIT, foe_kit=DAGGER_PAIR_KIT,
                                 foe_position={'x': 3, 'y': 5}, bundle_transform=setup)
    choice, options = pair_options(paired_strike(table, combat, mid, 'dw_defensive_whirl'))
    rendered = f"{choice['moment']}\n{choice['summary']}"

    assert 'no extra action' in rendered.lower(), rendered
    assert 'no extra action or cost' not in rendered.lower(), f"still promises the Whirl price away: {rendered}"
    assert 'martial focus' in rendered.lower(), f"does not name what Defensive Whirl spends: {rendered}"
    # The expensive option's own label still states its price, and the prompt agrees with it.
    whirl = next(o for o in choice['choice']['options'] if o['id'] == 'dw_defensive_whirl')
    assert 'martial focus' in whirl['label'].lower(), whirl
    # ...and what the prompt describes is what the engine really did: the point was paid.
    assert len(spent(reload(tmp_path, mid))) == 1, options


def test_defensive_whirl_is_offered_only_to_a_character_that_owns_it(tmp_path):
    """Checklist 3: the plug-in is inert for a character without the talent."""
    combat, table, mid = fixture(tmp_path, [T + 'DANCING_DISPLAY', T + 'DIZZYING_COMBINATION'],
                                 owner_kit=DAGGER_PAIR_KIT, foe_kit=DAGGER_PAIR_KIT,
                                 foe_position={'x': 3, 'y': 5}, bundle_transform=setup)
    _, options = pair_options(paired_strike(table, combat, mid, 'first'))
    assert set(options) == {'dw_dancing_display', 'dw_dizzying_combination'}
    assert not whirls(reload(tmp_path, mid)), 'the talent applied to a character that does not own it'


@pytest.mark.parametrize('focus', [0, 1])
def test_defensive_whirl_is_not_offered_without_the_focus_to_pay_for_it(tmp_path, focus):
    """A talent whose printed cost cannot be paid must not appear in the menu."""
    combat, table, mid = fixture(tmp_path, ALL_THREE, owner_kit=DAGGER_PAIR_KIT, foe_kit=DAGGER_PAIR_KIT,
                                 foe_position={'x': 3, 'y': 5}, bundle_transform=lambda b: setup(b, focus=focus))
    _, options = pair_options(paired_strike(table, combat, mid, 'first'))
    assert ('dw_defensive_whirl' in options) == bool(focus), options
    if not focus:
        engine = reload(tmp_path, mid)
        assert not whirls(engine)
        assert not spent(engine), 'paid a cost it did not have'
    else:
        assert len(spent(reload(tmp_path, mid))) == 1, 'the default pick still had to pay'