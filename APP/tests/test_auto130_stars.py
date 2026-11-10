"""Star-Drawn Projectile's four printed benefits and Starlight Ward's Aligned bonus (AUTO130).

Owner text (authority/typed_mechanics/rules_text.json):
  * Star-Drawn Projectile (Stars, Bonus Action, 2 CP): \"The rddo fackpn pbokpt mgpcmn, fdwapb twkagm dmrrvm, Sdvdvhmm, Ccvvb Sywdu,
    or fevrkfd dhlg tlaokr you ltdw dowt turn is egecp evgsa a gppbsliurenob bogr. Choose one benefit: ignore Half Cover; increase
    range by 60 feet; if the target bears your Stellar Mark and the attack hits, push it 10 feet; if the attack misses a marked
    target, you may reroll the attack once, but must use the new result.\"
  * Starlight Ward (Stars, Reaction, 1 CP): \"A small constellation flashes between the harm and the target. Reduce the triggering
    damage by: CL 1-10: 1d8 + key ability modifier; CL 11-16: 2d8 + key ability modifier; CL 17-20: 3d8 + key ability modifier.
    Aligned Benefit: Add your Proficiency Bonus to the reduction.\"
"""
import importlib
import json
from pathlib import Path

import pytest

from combat.ext import stars
from tests.auto_worker1_support import LEFT, RIGHT, act, fight, reload

T = 'tianxia.talent.stars.'
DRAWN = T + 'star_drawn_projectile'
WARD = T + 'starlight_ward'
DOMAIN = T + 'stars_domain'
BOLT = 'STARS_BASE_STARBOLT'
def drawn_labels():
    """Expected menu labels from the shipped authority, including redacted exports."""
    record = authority()[DRAWN]
    return [f"{record['name']}: {option['label']}" for option in record['options']]


def drawn_label(state):
    record = authority()[DRAWN]
    option = next(o for o in record['options'] if any(e.get('state') == state for e in o['effects']))
    return f"{record['name']}: {option['label']}"
MELEE = {'type': 'attack', 'attack_kind': 'melee', 'count': 1,
         'on_hit': [{'type': 'damage', 'flat': 1, 'damage_types': ['force']}]}


def resolve(send, picks=None):
    answers, prompts = [], []
    for _ in range(12):
        result = send(answers)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            return result, prompts
        p = result['reaction']
        prompts.append(p)
        ids = [o['id'] for o in (p.get('choice') or {}).get('options', [])]
        chosen = (picks or {}).get(p['context']['reaction_source_id'], ids[:1])
        answers.append({**p['context'], 'selection': 'USE' if chosen or not p.get('choice') else 'DECLINE', 'option_ids': chosen})
    raise AssertionError('too many choices')


def marked():
    return [{'type': 'mark', 'mark': stars.MARK, 'applies_to': subject, 'duration': {'kind': 'until_removed'}}
            for subject in ('self', 'target')]


def bears(actor, owner_id):
    return any(c.condition_id.endswith('stellar_mark.' + owner_id) for c in actor.conditions.values())


def authority():
    path = Path(__file__).resolve().parents[1] / 'authority' / 'Tianxia_Typed_Mechanics_Authority_R1.json'
    return json.loads(path.read_text(encoding='utf-8'))['mechanics']


# ---------------------------------------------------------------------------- Star-Drawn Projectile
def test_star_drawn_offers_all_four_printed_benefits(tmp_path):
    """The printed "Choose one benefit" is four real actions a player picks between, not a GM reminder."""
    combat, table, mid = fight(tmp_path, [DRAWN], cl=17)
    labels = [g['label'] for g in table.state(mid)['menu']['actions']]
    assert len(drawn_labels()) == 4
    for printed in drawn_labels():
        assert printed in labels, (printed, labels)


def test_star_drawn_cover_belongs_to_the_next_line_attack_only(tmp_path):
    combat, table, mid = fight(tmp_path, [DRAWN, BOLT], prepare=[MELEE], cl=17, left_attack_bonus=100,
                               positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 5, 'y': 6}})
    assert act(table, mid, drawn_label('COVER'))['status'] == 'COMMITTED'
    assert any(c.condition_id == stars.DRAWN_COVER for c in reload(combat, mid).state.actors[LEFT].conditions.values())
    # A melee attack is not one of the printed line attacks, so the benefit is still standing.
    resolve(lambda answers: act(table, mid, 'Prepare', answers, target_id=RIGHT))
    assert any(c.condition_id == stars.DRAWN_COVER for c in reload(combat, mid).state.actors[LEFT].conditions.values())
    # Starbolt is one, and it spends it.
    resolve(lambda answers: act(table, mid, BOLT, answers, target_id=RIGHT))
    assert not any(c.condition_id == stars.DRAWN_COVER for c in reload(combat, mid).state.actors[LEFT].conditions.values())


def test_star_drawn_push_moves_a_marked_target_ten_feet_when_the_attack_hits(tmp_path):
    combat, table, mid = fight(tmp_path, [DRAWN, BOLT], prepare=[*marked()], cl=17, left_attack_bonus=100,
                               positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 6, 'y': 6}})
    assert act(table, mid, 'Prepare', target_id=RIGHT)['status'] == 'COMMITTED'
    assert bears(reload(combat, mid).state.actors[RIGHT], LEFT)
    assert act(table, mid, drawn_label('PUSH'))['status'] == 'COMMITTED'
    before = reload(combat, mid).state.actors[RIGHT].position
    resolve(lambda answers: act(table, mid, BOLT, answers, target_id=RIGHT))
    engine = reload(combat, mid)
    after = engine.state.actors[RIGHT].position
    assert (after.x, after.y) != (before.x, before.y), 'a marked target hit by the chosen attack is pushed'
    assert engine.grid.distance_ft(before, after) == 10


def test_star_drawn_push_leaves_an_unmarked_target_alone(tmp_path):
    """The printed push needs "the target bears your Stellar Mark"."""
    combat, table, mid = fight(tmp_path, [DRAWN, BOLT], cl=17, left_attack_bonus=100,
                               positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 6, 'y': 6}})
    assert act(table, mid, drawn_label('PUSH'))['status'] == 'COMMITTED'
    before = reload(combat, mid).state.actors[RIGHT].position
    resolve(lambda answers: act(table, mid, BOLT, answers, target_id=RIGHT))
    after = reload(combat, mid).state.actors[RIGHT].position
    assert (after.x, after.y) == (before.x, before.y)


def test_star_drawn_range_variant_is_offered_only_for_the_chosen_benefit(tmp_path):
    """The extra 60 feet are that one chosen benefit, not a standing reach."""
    combat, table, mid = fight(tmp_path, [DRAWN, BOLT], cl=17, left_attack_bonus=100,
                               positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 8, 'y': 6}})
    assert not _range_offered(table, mid)
    assert act(table, mid, drawn_label('RANGE'))['status'] == 'COMMITTED'
    assert _range_offered(table, mid)
    engine = reload(combat, mid)
    variant = next(a for a in engine.action_catalog.values()
                   if a.source_definition_id.endswith(BOLT + '#drawn_range') and a.owner_id == LEFT)
    bolt = next(a for a in engine.action_catalog.values() if a.source_definition_id.endswith(BOLT))
    assert variant.range_ft == int(bolt.range_ft) + 60
    # Starbolt is a line attack, so it spends the benefit and the variant goes away with it.
    resolve(lambda answers: act(table, mid, BOLT, answers, target_id=RIGHT))
    assert not any(c.condition_id == stars.DRAWN_RANGE for c in reload(combat, mid).state.actors[LEFT].conditions.values())
    assert not _range_offered(table, mid)


def _range_offered(table, mid):
    return any(g['source_definition_id'].endswith(BOLT + '#drawn_range') for g in table.state(mid)['menu']['actions'])


def test_the_star_drawn_lines_the_table_now_runs_are_no_longer_gm_reminders():
    record = authority()[DRAWN]
    assert record['riders'] == [], record['riders']
    assert record['coverage'] == 'FULL'


def test_star_drawn_is_inert_for_a_character_who_does_not_own_it(tmp_path):
    combat, table, mid = fight(tmp_path, [], cl=17)
    engine = reload(combat, mid)
    labels = [g['label'] for g in table.state(mid)['menu']['actions']]
    assert not any(label.startswith(authority()[DRAWN]['name']) for label in labels), labels
    assert not any(c.condition_id in stars.DRAWN_STATES.values() for c in engine.state.actors[LEFT].conditions.values())
    assert not [a for a in engine.action_catalog.values() if (a.parameters or {}).get('stars_drawn_range')]


# ---------------------------------------------------------------------------- Starlight Ward
from tests import character_fight_support as c13
STARS = 'tianxia.sphere.stars'
ME, AN = c13.ME, c13.AN


def _seeded(engine, seed='auto130-ward'):
    """Same dice for both Ward hits, so the only difference in damage taken is the printed Aligned Proficiency Bonus."""
    from combat.gate2_rolls import DeterministicRollAuthority

    engine.roller = DeterministicRollAuthority(seed)


def _ward_hit(engine, tag):
    """A real hit on the Ward's own bearer, so the printed reaction path runs."""
    from combat.gate2_runtime_models import ActionDefinition, EconomyKind

    action = ActionDefinition(source_definition_id=f"action:auto130.{tag}", display_name="Starlight Ward probe",
                              owner_id=AN, economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY",
                              range_ft=500,
                              parameters={'typed': {'effects': [{'type': 'attack', 'attack_kind': 'unarmed', 'on_hit': [
                                  {'type': 'damage', 'applies_to': 'target', 'flat': 60, 'damage_types': ['bludgeoning']}],
                                  'on_miss': []}],
                                  'numbers': {'pb': 4, 'save_dc': 16, 'attack_bonus': 100, 'cl': 17, 'key_mod': 3},
                                  'duration': {'kind': 'instant'}, 'weapon': None, 'riders': []}})
    engine.action_catalog[action.source_definition_id] = action
    engine.state.actors[AN].action_ids = (action.source_definition_id,)
    engine.state.actors[AN].action_available = True
    before = len(engine.events)
    importlib.import_module('test_reaction_effects_r6')._use(engine, AN, action, ME)
    return engine.events[before:]


def _ward_reduction(with_domain):
    """The reduction Starlight Ward actually applied to one identical hit, aligned or not."""
    engine, me, foe = c13._fight(STARS, [WARD, DOMAIN], cl=17)
    c13.eager(engine)
    if with_domain:
        c13._use(engine, authority()[DOMAIN]['name'], target=None)   # the caster's own Stars Domain: its bearer is Aligned
    _seeded(engine)                                          # both hits roll exactly the same dice
    events = _ward_hit(engine, 'aligned' if with_domain else 'plain')
    resolved = [e for e in events if e.event_type == 'REACTION_RESOLVED']
    assert resolved, events
    return int(resolved[-1].payload['reduction']), me


def test_starlight_ward_adds_proficiency_bonus_to_an_aligned_reduction(tmp_path, monkeypatch):
    """Aligned Benefit: Add your Proficiency Bonus to the reduction (inside the caster's own Stars Domain)."""
    # The public export scrambles free-text triggers, which the generic reaction
    # classifier reads. Preserve the same trigger with synthetic wording here.
    from combat import factory_compiler
    data = json.loads(factory_compiler.TYPED_AUTHORITY.read_text())
    data['mechanics'][WARD]['activation']['trigger'] = 'You or an ally within 30 feet takes damage'
    path = tmp_path / 'ward-authority.json'
    path.write_text(json.dumps(data))
    monkeypatch.setattr(factory_compiler, 'TYPED_AUTHORITY', path)
    plain, _ = _ward_reduction(False)
    aligned, me = _ward_reduction(True)
    assert aligned - plain == max(1, int(me.proficiency_bonus or 2)), (plain, aligned, me.proficiency_bonus)


def test_starlight_ward_is_inert_for_a_reaction_that_is_not_its_own():
    engine, me, foe = c13._fight(STARS, [DOMAIN], cl=17)
    assert stars.ward_aligned_bonus(engine, me, me, foe, {'feature_id': 'TAL_SOME_OTHER_WARD'}) is None


def test_the_starlight_ward_line_the_table_now_runs_is_no_longer_a_gm_reminder():
    record = authority()[WARD]
    assert record['riders'] == [], record['riders']
    assert record['coverage'] == 'FULL'
