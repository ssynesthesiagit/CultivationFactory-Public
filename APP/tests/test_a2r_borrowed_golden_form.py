"""Borrowed Golden Form: table transactions, cold reload, the unperfected rule.

A character who has not picked a Form possesses Stable by default
(combat/ext/qi_path.py form()), so the tests below either leave the
default standing or pick the printed choices (Circulating, Reservoir)
the sheet offers."""
import pytest
from combat.ext import borrowed_golden_form as borrowed
from combat.ext import qi_path
from tests.worker2_support import fixture, candidate, settle, reload, turn, OWNER, ALLY, FOE

Q = 'tianxia.path.qi_cultivation.feature.'
INSIGHT = 'insight.borrowed-golden-form'
FORM = 'condition:typed.golden_core_form'
QI = 'resource:core.qi'


def use(combat, table, mid, name, **kw):
    row = candidate(combat, mid, name, target=kw.pop('target', None), at=kw.pop('at', None))
    return settle(table, mid, row.candidate_id, **kw)


def by_name(engine, title):
    return [c for c in engine.legal_candidates()
            if engine.action_catalog.get(c.source_definition_id)
            and engine.action_catalog[c.source_definition_id].display_name == title]


def borrowed_condition(actor):
    return next((c for c in actor.conditions.values()
                 if c.condition_id == FORM and (c.data or {}).get('borrowed')), None)


def setup(tmp_path, *, cl=16, insights=(INSIGHT,), features=(Q + 'golden_core_form',),
          extra=(), **layout):
    return fixture(tmp_path, list(features) + list(extra), cl=cl,
                   owner_insights=list(insights), seed=f'BORROW-{cl}', **layout)


def test_borrow_records_an_unpossessed_form_and_pays_4_qi(tmp_path):
    combat, table, mid = setup(tmp_path)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    # an unchosen character possesses Stable by default
    assert qi_path.forms(owner) == ()
    assert qi_path.form(owner) == 'stable'
    assert borrowed_condition(owner) is None
    offered = by_name(engine, 'Borrowed Golden Form')
    assert offered, 'the Bonus Action is offered while a Form remains unpossessed'
    before = owner.resources[QI]
    prompts = use(combat, table, mid, 'Borrowed Golden Form',
        choices={'choice:needle.borrowed_golden_form': 'circulating'})
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.borrowed_golden_form')
    assert 'unperfected benefits' in prompt['moment'] and '4 Qi' in prompt['moment']
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert qi_path.forms(owner) == ('stable', 'circulating')
    held = borrowed_condition(owner)
    assert held is not None and held.data['form'] == 'circulating'
    assert held.data['perfected'] is False
    assert owner.resources[QI] == before - 4
    # once per scene: the Bonus Action is gone after the borrow
    assert not by_name(engine, 'Borrowed Golden Form')


def test_declining_the_borrow_spends_nothing(tmp_path):
    combat, table, mid = setup(tmp_path)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    before = owner.resources[QI]
    use(combat, table, mid, 'Borrowed Golden Form',
        choices={'choice:needle.borrowed_golden_form': None})
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.resources[QI] == before
    assert borrowed_condition(owner) is None
    assert qi_path.forms(owner) == ()
    # the scene did not spend its one borrow: a later turn offers it again
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert by_name(engine, 'Borrowed Golden Form')


def test_a_borrowed_form_stays_unperfected_at_cl17(tmp_path):
    combat, table, mid = setup(tmp_path, cl=17, extra=[Q + 'domain_armament'])
    use(combat, table, mid, 'Borrowed Golden Form',
        choices={'choice:needle.borrowed_golden_form': 'circulating'})
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    # the default Stable Form is Perfected at CL17; the borrowed Circulating is not
    assert qi_path.form_state(engine, owner, 'stable') is True
    assert qi_path.form_state(engine, owner, 'circulating') is False
    # next turn: a resolved Qi spend triggers the borrowed Circulating
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    prompts = use(combat, table, mid, 'Domain Armament: Manifest', at=(2, 6),
                  choices={'choice:needle.golden_benefits': ['temp_hp']})
    asked = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.golden_benefits']
    assert asked and asked[0]['choice']['minimum'] == 1 and asked[0]['choice']['maximum'] == 1
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.temporary_hp == int(owner.proficiency_bonus)


def test_cl20_two_perfected_forms_grant_the_perfected_state(tmp_path):
    combat, table, mid = setup(tmp_path, cl=20,
                               features=(Q + 'golden_core_form', Q + 'second_golden_core_form'),
                               extra=[Q + 'domain_armament'])
    use(combat, table, mid, 'Golden Core Form: Circulating Golden Core')
    use(combat, table, mid, 'Golden Core Form: Golden Core Reservoir')
    prompts = use(combat, table, mid, 'Borrowed Golden Form',
        choices={'choice:needle.borrowed_golden_form': 'stable'})
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.borrowed_golden_form')
    assert 'Perfected benefits' in prompt['moment'] and 'unperfected benefits' not in prompt['moment']
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    # two permanent Perfected Forms: the third may be granted Perfected for the scene
    assert qi_path.form_state(engine, owner, 'circulating') is True
    assert qi_path.form_state(engine, owner, 'reservoir') is True
    assert qi_path.form_state(engine, owner, 'stable') is True
    held = borrowed_condition(owner)
    assert held is not None and held.data['form'] == 'stable' and held.data['perfected'] is True
    # next turn: the Perfected borrowed Circulating chooses two benefits
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    prompts = use(combat, table, mid, 'Domain Armament: Manifest', at=(2, 6),
                  choices={'choice:needle.golden_benefits': ['temp_hp', 'move']})
    asked = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.golden_benefits']
    assert asked and asked[0]['choice']['minimum'] == 2 and asked[0]['choice']['maximum'] == 2
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.temporary_hp == 2 * int(owner.proficiency_bonus)


def test_a_borrowed_reservoir_begins_unused(tmp_path):
    combat, table, mid = setup(tmp_path)
    use(combat, table, mid, 'Borrowed Golden Form',
        choices={'choice:needle.borrowed_golden_form': 'reservoir'})
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert qi_path.form_state(engine, owner, 'reservoir') is False
    # the borrowed Reservoir grants the Reservoir Bonus Action, beginning unused
    # (the borrow spent the turn's Bonus Action, so the reservoir waits a turn)
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert by_name(engine, 'Golden Core Reservoir')
    owner = engine.state.actors[OWNER]
    before = owner.resources[QI]
    use(combat, table, mid, 'Golden Core Reservoir')
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.resources[QI] == before + int(owner.proficiency_bonus)
    # its once-per-scene use is spent while the borrowed Form lasts
    assert not by_name(engine, 'Golden Core Reservoir')


def test_the_borrow_needs_an_unpossessed_form(tmp_path):
    combat, table, mid = setup(tmp_path, cl=20,
                               features=(Q + 'golden_core_form', Q + 'second_golden_core_form'))
    use(combat, table, mid, 'Golden Core Form: Circulating Golden Core')
    use(combat, table, mid, 'Golden Core Form: Golden Core Reservoir')
    use(combat, table, mid, 'Borrowed Golden Form',
        choices={'choice:needle.borrowed_golden_form': 'stable'})
    engine = reload(tmp_path, mid)
    # all three Forms are recorded: no borrow remains and the action is gone
    assert len(qi_path.forms(engine.state.actors[OWNER])) == 3
    assert not by_name(engine, 'Borrowed Golden Form')


def test_the_borrow_is_not_offered_without_the_insight(tmp_path):
    combat, table, mid = setup(tmp_path, insights=())
    engine = reload(tmp_path, mid)
    assert not by_name(engine, 'Borrowed Golden Form')


def test_the_borrowed_form_survives_a_cold_reload(tmp_path):
    combat, table, mid = setup(tmp_path)
    use(combat, table, mid, 'Borrowed Golden Form',
        choices={'choice:needle.borrowed_golden_form': 'circulating'})
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    held = borrowed_condition(owner)
    assert held is not None
    assert held.data['form'] == 'circulating'
    assert held.data['perfected'] is False
    assert held.data['borrowed'] is True
    assert 'Borrowed Circulating Golden Core' in held.data['label']
