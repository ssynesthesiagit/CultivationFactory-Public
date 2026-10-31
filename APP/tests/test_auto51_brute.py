"""AUTO51 Brute through compiled actions, actual table decisions and reloads."""
import pytest
from tests.cw2_service_support import add_action, seal
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, reload, settle, turn


@pytest.mark.parametrize('owned,already_expert,ability', [(True, False, 'STR'), (True, True, 'STR'),
                                                        (False, False, 'STR'), (True, False, 'DEX')])
def test_greater_brute_explicit_athletics_expertise_does_not_stack(tmp_path, owned, already_expert, ability):
    def prepare(bundles):
        for b in bundles:
            add_action(b, 'Athletics contest', [{'type': 'contest_against',
                'actor_check': {'ability': ability, 'skill': 'Athletics'}, 'target_check': {'ability': 'WIS'}}])
        if already_expert:
            bundles[0]['skills'] = {'Athletics': 10}
            seal(bundles[0])
    combat, table, mid = fixture(tmp_path, ['TAL_BRUTE_GREATER_BRUTE'] if owned else [], bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Athletics contest', target=FOE).candidate_id)
    e = reload(tmp_path, mid)
    roll = next(x for x in reversed(e.events) if x.event_type == 'CHECK_ROLLED')
    assert roll.payload['actor']['modifier'] == (10 if owned and ability == 'STR' else 2)
    assert sum(x.event_type == 'D20_REWRITTEN' and x.source_definition_id == 'TAL_BRUTE_GREATER_BRUTE'
               for x in e.events) == int(owned and not already_expert and ability == 'STR')


@pytest.mark.parametrize('ally_ready', [False, True])
def test_focused_might_requires_its_owners_success_not_an_allys(tmp_path, ally_ready):
    def prepare(bundles):
        add_action(bundles[0], 'Prepare ally ready', [{'type': 'condition', 'condition': 'focused_might_ready',
            'applies_to': 'target', 'expires_on': 'UNTIL_REMOVED'}])
        add_action(bundles[0], 'Spend Focus', [{'type': 'spend_resource', 'resource_id': 'resource:core.martial_focus',
                                              'flat': 1, 'applies_to': 'self'}], target='SELF')
        bundles[0]['skills'] = {'Athletics': 100}
        bundles[2]['skills'] = {'Athletics': -100, 'Acrobatics': -100}
        seal(bundles[0]);seal(bundles[2])
    combat, table, mid = fixture(tmp_path, ['TAL_BRUTE_FOCUSED_MIGHT'], bundle_transform=prepare,
                               foe_position={'x': 4, 'y': 5})
    settle(table, mid, candidate(combat, mid, 'Spend Focus').candidate_id)
    if ally_ready:
        settle(table, mid, candidate(combat, mid, 'Prepare ally ready', target=ALLY).candidate_id)
    e = reload(tmp_path, mid)
    assert not any('Focused Might' in c.display_name for c in e.legal_candidates())
    shove = next(c for c in e.legal_candidates() if c.target_ids == (FOE,)
                 and (a := e.action_catalog.get(c.source_definition_id)) and a.display_name == 'Brutal Shove')
    settle(table, mid, shove.candidate_id, {'choice:needle.brutal_shove_result': 'prone'})
    e = reload(tmp_path, mid)
    assert any(c.condition_id == 'condition:typed.focused_might_ready' for c in e.state.actors[OWNER].conditions.values())
    ready = candidate(combat, mid, 'Focused Might: Regain Martial Focus')
    assert ready.target_ids == (OWNER,)
    settle(table, mid, ready.candidate_id)
    e = reload(tmp_path, mid)
    assert e.state.actors[OWNER].resources['resource:core.martial_focus'] == 1
    assert not any(c.condition_id == 'condition:typed.focused_might_ready' for c in e.state.actors[OWNER].conditions.values())
    assert any(c.condition_id == 'condition:typed.focused_might_ready' for c in e.state.actors[ALLY].conditions.values()) == ally_ready


@pytest.mark.parametrize('talent,name,size,width', [
    ('MUSCULAR_SURGE', 'Muscular Surge', 'Huge', 3),
    ('COURT_OF_THE_MOVING_MOUNTAIN', 'Court of the Moving Mountain', 'Huge', 3),
    ('SOVEREIGN_WEIGHT_INCARNATION', 'Sovereign Weight Incarnation', 'Gargantuan', 4)])
def test_brute_states_raise_grapple_limit_without_changing_body_size(tmp_path, talent, name, size, width):
    def prepare(bundles):
        foe = bundles[2]['actor_template']
        foe['saving_throws'].update(STR=-100, DEX=-100)
        add_action(bundles[2], 'Prepare large opponent', [{'type': 'size_change', 'size': size,
            'applies_to': 'self', 'expires_on': 'UNTIL_REMOVED'}], target='SELF')
        seal(bundles[2])
    combat, table, mid = fixture(tmp_path, ['TAL_BRUTE_' + talent], bundle_transform=prepare,
                               foe_position={'x': 0, 'y': 6-width})
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Prepare large opponent').candidate_id)
    turn(table, mid, OWNER)
    e = reload(tmp_path, mid)
    assert e._footprint(e.state.actors[FOE]).width_cells == width
    grapples = lambda engine: [c for c in engine.legal_candidates() if c.target_ids == (FOE,)
                              and 'Grapple' in c.display_name and 'Escape' not in c.display_name]
    # The inherited menu admits this target; the real save resolver rejects
    # the attempt at the ordinary size limit. Prove that negative outcome.
    settle(table, mid, grapples(e)[0].candidate_id)
    e = reload(tmp_path, mid)
    assert not any(c.condition_id == 'condition:typed.grappled' for c in e.state.actors[FOE].conditions.values())
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, name).candidate_id)
    e = reload(tmp_path, mid)
    assert e._footprint(e.state.actors[OWNER]).width_cells == 1
    held = next(c for c in e.state.actors[OWNER].conditions.values() if (c.data or {}).get('brute_grapple_steps'))
    assert held.expires_on.startswith('START_OF_SLOT_AT:')
    assert grapples(e)
    settle(table, mid, grapples(e)[0].candidate_id)
    e = reload(tmp_path, mid)
    assert any(c.condition_id == 'condition:typed.grappled' for c in e.state.actors[FOE].conditions.values())


@pytest.mark.parametrize('exhausted', [False, True])
def test_surge_exhaustion_gate_and_no_premature_strength_advantage(tmp_path, exhausted):
    def prepare(bundles):
        add_action(bundles[0], 'Prepare Exhaustion', [{'type': 'exhaustion', 'amount': 1, 'applies_to': 'self'}], target='SELF')
        add_action(bundles[0], 'Strength contest', [{'type': 'contest_against',
            'actor_check': {'ability': 'STR'}, 'target_check': {'ability': 'WIS'}}])
    combat, table, mid = fixture(tmp_path, ['TAL_BRUTE_MUSCULAR_SURGE'], bundle_transform=prepare)
    if exhausted:
        settle(table, mid, candidate(combat, mid, 'Prepare Exhaustion').candidate_id)
        assert not any(c.display_name == 'Muscular Surge' for c in reload(tmp_path, mid).legal_candidates())
    else:
        settle(table, mid, candidate(combat, mid, 'Muscular Surge').candidate_id)
        settle(table, mid, candidate(combat, mid, 'Strength contest', target=FOE).candidate_id)
        e = reload(tmp_path, mid)
        roll = next(x for x in reversed(e.events) if x.event_type == 'CHECK_ROLLED')
        assert roll.payload['actor']['mode'] == 'NORMAL'
        assert any(c.condition_id == 'condition:typed.state.muscular_surge' for c in e.state.actors[OWNER].conditions.values())


@pytest.mark.parametrize('ordinary_shove', [False, True])
def test_strength_save_proficiency_does_not_inflate_brute_checks_or_damage(tmp_path, ordinary_shove):
    def prepare(bundles):
        bundles[0]['actor_template']['saving_throws']['STR'] = 6
        bundles[2]['skills'] = {'Athletics': -100, 'Acrobatics': -100}
        add_action(bundles[0], 'Athletics contest', [{'type': 'contest_against',
            'actor_check': {'ability': 'STR', 'skill': 'Athletics'}, 'target_check': {'ability': 'WIS'}}])
        seal(bundles[0]);seal(bundles[2])
    combat, table, mid = fixture(tmp_path, ['TAL_BRUTE_GREATER_BRUTE'], bundle_transform=prepare,
                               foe_position={'x': 4, 'y': 5})
    settle(table, mid, candidate(combat, mid, 'Brutal Shove' if ordinary_shove else 'Athletics contest', target=FOE).candidate_id)
    e = reload(tmp_path, mid)
    check = next(x for x in reversed(e.events) if x.event_type == 'CHECK_ROLLED')
    assert e.state.actors[OWNER].strength_score == 14
    assert check.payload['actor']['modifier'] == 10
    if ordinary_shove:
        damage = next(x for x in reversed(e.events) if x.event_type == 'DAMAGE_COMMITTED')
        assert damage.payload['hp_damage'] == 2


def test_overrun_damage_reads_the_strength_score_not_the_strength_saving_throw(tmp_path):
    """Alternative Maneuvers: an Overrun "appl[ies] Brutal Shove damage". This owner has a Strength score of 14 (+2) and a
    Strength SAVING THROW of +6, so the damage it deals says which of the two answered "your Strength modifier": 2 is
    the score, 6 would be the saving throw. AUTO107r2 changed this path to the shared score-based helper, and the
    damage it produces is sealed into the packet, so the reading has to be guarded here rather than assumed."""
    def prepare(bundles):
        bundles[0]['actor_template']['saving_throws']['STR'] = 6
        bundles[2]['skills'] = {'Athletics': -100, 'Acrobatics': -100}
        seal(bundles[0]); seal(bundles[2])
    combat, table, mid = fixture(tmp_path, ['tianxia.talent.brute.alternative_maneuvers'],
                                 bundle_transform=prepare, foe_position={'x': 4, 'y': 5})
    e = reload(tmp_path, mid)
    assert e.state.actors[OWNER].strength_score == 14
    assert e.state.actors[OWNER].saving_throws['STR'] == 6
    settle(table, mid, candidate(combat, mid, 'Overrun', target=FOE).candidate_id)
    e = reload(tmp_path, mid)
    damage = next(x for x in reversed(e.events) if x.event_type == 'DAMAGE_COMMITTED')
    assert damage.payload['hp_damage'] == 2, \
        f"Overrun damage is your Strength modifier: +2 from the score, not +6 from the saving throw ({damage.payload})"


@pytest.mark.parametrize('r1f1_window', [False, True])
def test_unmarked_damage_packet_keeps_the_legacy_saving_throw_reading(tmp_path, r1f1_window):
    """The one saved-fight population the ``brute_shove.DAMAGE_SCORE`` gate cannot serve, pinned deliberately.

    AUTO107r1f1 (47fdd95e..76e55fd2, review commits on the unmerged ``auto/brute`` branch) made this path read the
    Strength score without stamping a marker, so a packet sealed in that window carries the old ``auto51_strength_score``
    flag and nothing newer. The older cohort has the same shape, so removing the marker alone cannot identify which
    revision sealed it. At head it reads the saving throw: the boundary named in ``brute_shove.DAMAGE_SCORE_UNSUPPORTED``, with its cohort
    table and the reason no flag can widen it. It is asserted here so the fallback is a stated decision rather than a
    silent difference, and the owner's real +2 score and +6 Strength saving throw keep the two readings apart.
    """
    from combat.ext import brute_shove

    def prepare(bundles):
        bundles[0]['actor_template']['saving_throws']['STR'] = 6
        bundles[2]['skills'] = {'Athletics': -100, 'Acrobatics': -100}
        rows = [row for action in bundles[0]['action_catalog']
                for row in ((action.get('parameters') or {}).get('typed') or {}).get('effects') or ()]
        stamped = sum(1 for row in rows if row.get(brute_shove.DAMAGE_SCORE))
        assert stamped >= 1, "a current packet has to carry the marker, or this case proves nothing"
        if r1f1_window:
            # Exactly the 47fdd95e..76e55fd2 packet shape: the old flag, no marker of its own.
            for row in rows:
                row.pop(brute_shove.DAMAGE_SCORE, None)
            assert not any(row.get(brute_shove.DAMAGE_SCORE) for row in rows)
        seal(bundles[0]); seal(bundles[2])
    combat, table, mid = fixture(tmp_path, ['tianxia.talent.brute.alternative_maneuvers'],
                                 bundle_transform=prepare, foe_position={'x': 4, 'y': 5})
    reload(tmp_path, mid)
    settle(table, mid, candidate(combat, mid, 'Overrun', target=FOE).candidate_id)
    e = reload(tmp_path, mid)
    damage = next(x for x in reversed(e.events) if x.event_type == 'DAMAGE_COMMITTED')
    assert damage.payload['hp_damage'] == (6 if r1f1_window else 2), \
        f"the r1f1 window's packet has no marker, so it keeps the saving-throw reading ({damage.payload})"


@pytest.mark.parametrize('known_score', [True, False])
def test_new_brute_contest_does_not_give_defender_save_proficiency_on_its_check(tmp_path, known_score):
    def prepare(bundles):
        bundles[2]['actor_template']['saving_throws'].update(STR=6, DEX=6)
        if not known_score:
            bundles[2]['actor_template'].pop('strength_score', None)
            bundles[2]['carrying'].pop('strength_score', None)
        seal(bundles[2])
    combat, table, mid = fixture(tmp_path, ['TAL_BRUTE_GREATER_BRUTE'], bundle_transform=prepare,
                               foe_position={'x': 4, 'y': 5})
    settle(table, mid, candidate(combat, mid, 'Brutal Shove', target=FOE).candidate_id,
           {'choice:needle.brute_contest_skill': 'Athletics'})
    check = next(x for x in reversed(reload(tmp_path, mid).events) if x.event_type == 'CHECK_ROLLED')
    assert check.payload['actor']['modifier'] == 10
    assert check.payload['target']['modifier'] == (2 if known_score else 6)
