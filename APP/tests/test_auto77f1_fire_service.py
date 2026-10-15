"""AUTO77f1 (the AUTO77 pre-merge review) at the service: the Fire sphere's new choices really pause a manual table, a
declined choice really declines, and every new state survives a table commit and a reload.

The table-level rules live in tests/test_auto77_fire.py; these drive the same printed effects through the real
CombatService + TabletopService (MANUAL control modes, so the owner of a choice is really asked) and through
Gate4Persistence (a saved fight written to disk and read back).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from combat.gate2_runtime_models import ActionIntent
from combat.gate4_adapters import ManualControllerAdapter
from tests.r1i_service_support import FOE, OWNER, fixture

ROOT = Path(__file__).resolve().parents[1]
AUTH = json.loads((ROOT / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics']
FIRE = 'tianxia.talent.fire.'
BURN = 'FIRE_TAL_BURNING_WEAPON'
FOCUS = FIRE + 'white_hot_focus'
COUNTERWEAVE = 'TAL_QIWEAVING_COUNTERWEAVE'
FOCUS_BUTTON = 'White-Hot Focus: your next Fire talent gains one: one target'
KIT = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.fu', 'name': 'Fu (Short Axe)', 'quantity': 1}]}}
AXE = 'Fu (Short Axe) attack'


def _run(table, mid, cid, answer):
    """Press one table button and answer every pause it raises with ``answer(choice, ids)``; None declines."""
    answers = []
    for _ in range(24):
        menu = table.state(mid)['menu']
        result = table.act(mid, cid, menu['decision_id'], menu['state_version'], 0, list(answers))
        if result['status'] == 'COMMITTED':
            return result
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        reply = {**prompt['context'], 'selection': 'DECLINE'}
        choice = prompt.get('choice')
        if choice is not None:
            ids = list(choice.get('preferred') or [row['id'] for row in choice['options']])
            chosen = answer(prompt, choice, ids)
            if chosen is not None:
                reply.update(selection='USE', option_ids=tuple(chosen))
        answers.append(reply)
    raise AssertionError('too many prompts')


def _candidate(combat, table, mid, label, near=None):
    """The first table option on the button(s) named by ``label``; ``near`` keeps the ones aimed at that creature (a
    creature target) or nearest that square (an area aimed at a cell)."""
    groups = [group for group in table.state(mid)['menu']['actions'] if group['label'].startswith(label)]
    assert groups, sorted({group['label'] for group in table.state(mid)['menu']['actions']})
    rows = [row for group in groups for row in group['options']]
    if near is None:
        return rows[0]['candidate_id']
    here = combat._load_session(mid).engine.state.actors[near].position if near else None
    if here is None:
        return rows[0]['candidate_id']
    def distance(row):
        cell = row.get('destination')
        if cell is None:
            return 0 if near in (row.get('target_ids') or ()) else 99
        return abs(cell['x'] - here.x) + abs(cell['y'] - here.y)
    return min(rows, key=distance)['candidate_id']


def _condition(actor, name):
    return [row for row in actor.conditions.values() if row.condition_id == f'condition:typed.{name}']


def test_burning_weapon_asks_the_owner_which_strike_burns_and_the_answer_is_honoured(tmp_path):
    """The printed "one weapon, unarmed strike, or natural weapon" is a real table question with real answers: the pause
    carries the bearer's weapons by name, and the option picked is the one that burns.

    Before this the plug-in raised a choice id nothing owned, so combat/choice_checkpoints.py supplied no option
    specification and the engine fell back to legacy reaction handling that never offers these weapons."""
    combat, table, mid, _send, _commit = fixture(tmp_path, [BURN], owner_kit=KIT, owner_dc=30)
    asked = []

    def watch(prompt, choice, ids):
        asked.append((prompt['context']['reaction_source_id'], [row.get('label') for row in choice['options']]))
        return ['unarmed']

    assert _run(table, mid, _candidate(combat, table, mid, 'Burning Weapon', OWNER), watch)['status'] == 'COMMITTED'
    assert [source for source, _labels in asked] == ['choice:fire.imbue_weapon'], asked
    labels = [str(label) for _source, rows in asked for label in rows]
    assert any('Fu (Short Axe)' in label for label in labels), labels
    assert not any('tianxia.mortal' in label for label in labels), labels
    assert any('unarmed strike' in label for label in labels), labels
    (state,) = _condition(combat._load_session(mid).engine.state.actors[OWNER], 'state.burning_weapon')
    assert state.data['numbers']['weapon'] == 'unarmed', state.data
    assert state.expires_on == 'CONCENTRATION_END', state.expires_on


def test_a_declined_burning_weapon_imbues_nothing(tmp_path):
    """"Imbue one weapon ...": saying no leaves the bearer with no flame at all (it used to imbue the unarmed strike)."""
    combat, table, mid, _send, _commit = fixture(tmp_path, [BURN], owner_kit=KIT, owner_dc=30)
    assert _run(table, mid, _candidate(combat, table, mid, 'Burning Weapon', OWNER), lambda prompt, choice, ids: None)['status'] == 'COMMITTED'
    assert not _condition(combat._load_session(mid).engine.state.actors[OWNER], 'state.burning_weapon')


def test_white_hot_focus_asks_nothing_itself_and_leaves_the_choice_for_the_next_fire_talent(tmp_path):
    """"The next Fire talent you use this turn gains one:": pressing White-Hot Focus is not a question, and the question it
    does ask belongs to the next Fire activation, with the creatures that activation affects."""
    combat, table, mid, send, commit = fixture(tmp_path, [BURN, FOCUS], owner_kit=KIT, owner_dc=30)
    asked = []

    def watch(prompt, choice, ids):
        asked.append(prompt['context']['reaction_source_id'])
        return ids[:1]

    _run(table, mid, _candidate(combat, table, mid, 'White-Hot Focus: your next Fire talent'), watch)
    assert asked == [], 'casting White-Hot Focus itself asks nothing'
    (state,) = _condition(combat._load_session(mid).engine.state.actors[OWNER], 'state.white_hot_focus_save_disadvantage')
    assert 'bound' not in state.data and 'chosen' not in state.data, state.data
    # The very next Fire talent is the question's owner (Conflagration: the other Fire base ability, an Action, so the
    # Bonus Action White-Hot Focus already spent does not hide it).
    _run(table, mid, _candidate(combat, table, mid, 'Conflagration', FOE), watch)
    assert asked == ['choice:fire.white_hot_focus_target'], asked


def test_a_manual_fire_fighter_is_enrolled_so_an_automatic_step_would_ask_them(tmp_path):
    """What this proves, and no more: a MANUAL-controlled Fire fighter is enrolled in ``typed_ask_reactors``, the predicate
    that decides who an automatic step pauses for. Enrollment alone is not the behaviour; the automatic step itself is
    exercised in the next test."""
    combat, _table, mid, _send, _commit = fixture(tmp_path, [BURN, FOCUS], owner_kit=KIT, owner_dc=30)
    assert OWNER in combat._load_session(mid).engine.typed_ask_reactors


def test_an_automatic_step_answers_the_focus_question_for_an_ai_fighter_without_asking_the_table(tmp_path):
    """Checklist item 9 at the service, end to end: the same White-Hot Focus question, asked by a *real* automatic step.

    The fighter is handed to LOCAL_AUTO and the step is driven through TabletopService.auto_step, so the question is
    answered by the controller inside CombatService.local_step's probe run (gate5_service._ask_during_ai_step), not by a
    test harness supplying an answer. The step commits without a pause, and the benefit lands on the creature the fighter
    prefers -- the hostile -- which is only visible in the saving throw it rolled."""
    combat, table, mid, _send, _commit = fixture(tmp_path, [BURN, FOCUS], owner_kit=KIT, owner_dc=30)
    _run(table, mid, _candidate(combat, table, mid, FOCUS_BUTTON, OWNER), lambda prompt, choice, ids: ids[:1])
    # The candidate is chosen from the live decision context: switching control rebuilds the menu, so an id read from
    # the table before the switch would be stale by the time the step runs.
    real = combat.controller
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    here = combat._load_session(mid).engine.state.actors[FOE].position

    class Fixed:
        def choose_primary_action(self, context):
            chosen = min((row for row in context.legal_candidates
                          if row.display_name.startswith('Conflagration') and row.destination is not None),
                         key=lambda row: abs(row.destination.x - here.x) + abs(row.destination.y - here.y))
            return ManualControllerAdapter(lambda _context: (chosen.candidate_id, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(real, name)

    combat.controller = Fixed()
    result = table.auto_step(mid, 0, [])
    assert result['status'] == 'COMMITTED', result
    saves = [dict(row.payload) for row in combat._load_session(mid).engine.events
             if row.event_type == 'SAVE_ROLLED' and row.actor_id == FOE]
    assert saves and saves[-1]['mode'] == 'DISADVANTAGE', 'the AI answered its own question: the hostile it prefers'
    assert not _condition(combat._load_session(mid).engine.state.actors[OWNER], 'state.white_hot_focus_save_disadvantage')


def test_a_bound_white_hot_focus_survives_a_table_commit_and_reload(tmp_path):
    """Checklist item 7 for the two fields the bound form adds: ``bound`` (which activation it belongs to) and ``chosen``
    (which creature that activation's owner named). The earlier lane test saved the state straight after casting, which
    carries neither.

    A legacy sealed Fire talent the table reads as countered leaves the state bound -- that attempt is the one it belongs to (AUTO77r1f1)
    -- so this is a state a real fight really holds, written to disk through Gate4Persistence and read back."""
    from combat.gate4_persistence import Gate4Persistence
    from tests.h1_support import sheet
    from combat.factory_compiler import compile_character

    foe_sheet = sheet([COUNTERWEAVE], cl=17, dc=30)
    foe_sheet['ability_scores_and_statistics']['technique_attack_bonus'] = 100   # the counter is won, every time
    owner = compile_character(sheet([FOCUS], cl=17, dc=30, kit=KIT), actor_id=OWNER)
    # Retain the pre-A2FIRE sealed state shape and its already-paid backlash.
    # This fixture proves old bound/chosen data still reloads unchanged; new
    # countered-completion behavior is covered by test_auto2_fire at the service.
    from combat.canonical import canonical_sha256
    for action in owner['action_catalog']:
        typed = action['parameters'].get('typed') or {}
        if str(typed.get('source') or '').split('#', 1)[0] == FOCUS:
            for effect in typed.get('effects') or []:
                if effect.get('type') == 'fire_focus_state':
                    effect['type'] = 'state'
            typed['effects'].append({'type': 'damage', 'applies_to': 'self',
                'formula': 'pb', 'damage_types': ['fire'], 'duration': 'instant'})
    owner.pop('bundle_sha256', None)
    owner['bundle_sha256'] = canonical_sha256(owner)
    foe = compile_character(foe_sheet, actor_id=FOE)
    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed='AUTO77R1F1-BOUND', typed_bundles=(owner, foe),
                                       roster_setup={'primary_actor_ids': [OWNER, FOE],
                                                     'team_by_actor': {OWNER: 'team:a', FOE: 'team:b'},
                                                     'starting_positions': {OWNER: {'x': 3, 'y': 6}, FOE: {'x': 4, 'y': 6}}})
    while session.engine.state.current_actor_id != OWNER:
        _end_turn(session)
    unweaver = session.engine.state.actors[FOE]
    unweaver.resources['resource:core.martial_focus'] = 0   # it cannot counter while White-Hot Focus is cast
    _press(session, FOCUS_BUTTON)
    unweaver.resources['resource:core.martial_focus'] = 1   # and now it spends that countering the next Fire talent
    _press(session, _area_over(session, FOE))          # countered: the state stays bound to that attempt
    before = _fire_rows(session.engine)
    bound = [row for row in before if 'white_hot_focus' in row[1]]
    assert bound, before
    assert all('"bound": "' in row[4] and '"chosen": "' in row[4] for row in bound), bound
    loaded = persistence.load_match(session.match_id).engine
    assert _fire_rows(loaded) == before, (before, _fire_rows(loaded))


def _area_over(session, who):
    """The button for the area aimed at the square that creature stands on."""
    here = session.engine.state.actors[who].position
    rows = [row for row in session.engine.legal_candidates() if row.actor_id == OWNER
            and row.display_name.startswith('Conflagration') and row.destination is not None]
    return min(rows, key=lambda row: abs(row.destination.x - here.x) + abs(row.destination.y - here.y)).display_name


@pytest.mark.parametrize('talent,button', [(BURN, None), (FIRE + 'furnace_heart', 'Furnace Heart'),
                                           (FIRE + 'fire_sovereign_incarnation', 'Fire-Sovereign Incarnation'),
                                           (FOCUS, 'White-Hot Focus: your next Fire talent')])
def test_the_new_fire_states_survive_a_table_commit_and_reload(tmp_path, talent, button):
    """Everything these Fire plug-ins store in fight state is a string or an integer inside a condition's own data, and it
    is still there after the fight is written to disk and read back. The neighbours' commit-and-reload tests in
    tests/test_riders_c13.py cover the Fire areas, not these states."""
    from combat.gate4_persistence import Gate4Persistence
    from tests.h1_support import sheet
    from combat.factory_compiler import compile_character

    owner = compile_character(sheet([BURN, talent], cl=17, dc=30, kit=KIT), actor_id=OWNER)
    foe = compile_character(sheet([], cl=17), actor_id=FOE)
    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed='AUTO77F1-PERSIST', typed_bundles=(owner, foe),
                                       roster_setup={'primary_actor_ids': [OWNER, FOE],
                                                     'team_by_actor': {OWNER: 'team:a', FOE: 'team:b'},
                                                     'starting_positions': {OWNER: {'x': 3, 'y': 6}, FOE: {'x': 4, 'y': 6}}})
    while session.engine.state.current_actor_id != OWNER:
        _end_turn(session)
    if button is None:
        _press(session, 'Burning Weapon')
        _press(session, AXE)          # the once-per-turn stamp is written on this hit
    else:
        _press(session, button)
    before = _fire_rows(session.engine)
    assert before, 'the presses stored no Fire state at all, so this would prove nothing'
    loaded = persistence.load_match(session.match_id).engine
    assert _fire_rows(loaded) == before, (before, _fire_rows(loaded))


def _end_turn(session):
    row = next(candidate_row for candidate_row in session.engine.legal_candidates() if candidate_row.display_name == 'End turn')
    session.submit_intent(ActionIntent(intent_id=f'end-{row.state_version}', decision_id=row.decision_id,
                                       candidate_id=row.candidate_id, state_version=row.state_version,
                                       actor_id=row.actor_id, target_ids=row.target_ids),
                          primary_decision_record=None, reaction_provider=None)


def _press(session, name):
    found = [row for row in session.engine.legal_candidates() if row.actor_id == OWNER
             and row.display_name == name and OWNER in (row.target_ids or ())]
    if not found:
        found = [row for row in session.engine.legal_candidates() if row.actor_id == OWNER and row.display_name.startswith(name)]
    assert found, (name, sorted({row.display_name for row in session.engine.legal_candidates() if row.actor_id == OWNER}))
    row = found[0]
    session.submit_intent(ActionIntent(intent_id=f'i-{name}-{row.state_version}', decision_id=row.decision_id,
                                       candidate_id=row.candidate_id, state_version=row.state_version, actor_id=OWNER,
                                       target_ids=row.target_ids, destination=row.destination),
                          primary_decision_record=None, reaction_provider=session.engine._gate4_reaction_provider)


def _fire_rows(engine):
    """Every condition this lane's Fire plug-ins own, as the state a save has to keep: holder, id, source, expiry, data."""
    rows = []
    for actor in engine.state.actors.values():
        for condition in actor.conditions.values():
            if any(mark in condition.condition_id for mark in ('burning_weapon', 'white_hot_focus', 'furnace_heart',
                                                               'fire_sovereign_incarnation')):
                rows.append((actor.entity_id, condition.condition_id, condition.source_definition_id,
                             condition.expires_on, json.dumps(condition.data, sort_keys=True)))
    return sorted(rows)