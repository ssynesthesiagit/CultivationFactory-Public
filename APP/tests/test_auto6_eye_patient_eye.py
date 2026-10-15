"""Heaven Keeps No Secret from the Patient Eye at the table (AUTO6, The Hidden Eye scope; AUTO6f1 review fixes).

The printed Inheritance is: "Time: 1 Action. Range: 120 feet. Target: One creature you can perceive or your current
rival. Duration: 1 minute. Uses: Once per week. Open the perfected record of the target's revealed existence. The target
becomes Analyzed by you for the duration even if it would normally be protected from Analyze. ... the target cannot
benefit from being hidden from you; ... once during each of your turns when you damage the target, choose one known
Damage Resistance to suppress until the start of your next turn; once during the duration when you damage the target,
you may treat one known Damage Immunity as Resistance for that instance of damage."
(APP/authority/typed_mechanics/rules_text.json, TAL_THE_HIDDEN_EYE_HEAVEN_KEEPS_NO_SECRET_FROM_THE_PATIENT_EYE).

Every case below is a real table fight on a real ``TabletopService``: a compiled character owns the talent, the real
Action is offered and paid, real damage packets (attacks, saving throws, a Reaction) carry the printed effect, and each
commit is reloaded from disk and verified (fight_audit-style ``verify()`` plus ``mechanical.replay()``). Assertions read
the damage the target ACTUALLY took (``rolled_or_pending_damage`` against ``reduced_to`` in DAMAGE_COMMITTED), never
only a flag or a log line. combat/ext/eye_patient_eye.py implements it.
"""

from combat.ext.mind_hidden_eye import PATIENT_EYE_ANALYZED, analyzed_by
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_carry import KIT

LEFT = 'actor:factory.left'
ALLY = 'actor:factory.ally'
RIGHT = 'actor:factory.right'
TALENT = 'TAL_THE_HIDDEN_EYE_HEAVEN_KEEPS_NO_SECRET_FROM_THE_PATIENT_EYE'
NAME = 'Heaven Keeps No Secret from the Patient Eye'
USES = 'resource:uses.eye_patient_eye'
STRIKE = 'Stone-Skipping Strike'          # 3d6 + 2 Bludgeoning at CL 10 (a real attack packet)
NOTE_TALENT = 'tianxia.talent.music.dissonant_note'
NOTE = 'Dissonant Note'                   # 2d6 Psychic on a failed Wisdom save (no attack roll at all)
IMMUNE_USED = 'eye_patient_eye_immunity_used'
RESIST_USED = 'eye_patient_eye_resist_used'
MELEE = ['TAL_MONKEY_STYLE_STONE_SKIPPING_STRIKE', NOTE_TALENT]
ROUNDS = 10                               # "Duration: 1 minute"


# --------------------------------------------------------------------------- the table
def fight(tmp_path, *, ally=False, owned=(TALENT,), ally_owns=(), right_hp=1000, seed='AUTO6F1', positions=None):
    """Left (the Patient Eye owner) and Right, optionally Left's ally, on a real table."""
    fighters = [('left', MELEE + list(owned), LEFT), ('right', [], RIGHT)]
    if ally:
        fighters.insert(1, ('ally', MELEE + list(ally_owns), ALLY))
    bundles = []
    for short, mids, actor_id in fighters:
        document = sheet(mids, cl=10, kit={'starting_kit': KIT})
        document['identity']['display_name'] = short.title()
        if actor_id == RIGHT:
            document['ability_scores_and_statistics']['hit_points']['maximum'] = right_hp
        folder = tmp_path / 'portable_characters' / short
        folder.mkdir(parents=True)
        import json
        import zipfile
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document))
        from combat.factory_compiler import compile_character
        # Left's Reactions are asked at the table ("ask"), so its Opportunity Attack really reaches the player.
        bundles.append(compile_character(document, actor_id=actor_id,
                                         reaction_plan={'ask': actor_id == LEFT}))
    combat = CombatService(ROOT, tmp_path)
    ids = [actor_id for _, _, actor_id in fighters]
    spots = positions or {LEFT: {'x': 10, 'y': 11}, ALLY: {'x': 10, 'y': 12}, RIGHT: {'x': 15, 'y': 11}}
    spots = {aid: spot for aid, spot in spots.items() if aid in ids}
    teams = {actor_id: ('team:factory' if actor_id != RIGHT else 'team:opponents') for actor_id in ids}
    mid = combat._finish_factory_match(bundles, ids, teams, spots,
                                       combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],
                                       [a for a in ids if a != RIGHT], [RIGHT],
                                       control_modes={a: 'MANUAL' for a in ids}, match_seed=seed,
                                       display_name='AUTO6f1 regression', maximum_rounds=25)['match_id']
    return combat, TabletopService(combat, tmp_path), mid


def reload(combat, mid):
    """The saved fight read back from disk, with the shipped verification and replay both run."""
    loaded = CombatService(ROOT, combat.userdata_root)._load_session(mid)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
    return loaded.engine


def turn(combat, table, mid, actor=LEFT):
    for _ in range(4 * len(table.state(mid)['menu'].get('actors', []) or [1, 2, 3])):
        if table.state(mid)['menu']['actor_id'] == actor:
            return
        end_turn(combat, table, mid)
    raise AssertionError('the turn never reached ' + actor)


def send(combat, table, mid, cid, *, answers=(), pick=None, use=True):
    """One real table action; every prompt it raises is answered (USE, or the first extension option)."""
    prompts = []
    for _ in range(12):
        state = table.state(mid)
        result = table.act(mid, cid, state['menu']['decision_id'], state['menu']['state_version'],
                           state['last_sequence'], list(answers))
        if result['status'] == 'COMMITTED':
            return prompts
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        prompts.append(prompt)
        answer = {**prompt['context'], 'selection': 'USE' if use else 'DECLINE'}
        if use and prompt.get('choice'):
            options = prompt['choice']['options']
            answer['option_ids'] = [next((o['id'] for o in options if pick and pick(o)), options[0]['id'])]
        answers = [*answers, answer]
    raise AssertionError('the choice loop did not commit')


def candidate(combat, mid, name, *, actor=LEFT, target=RIGHT):
    engine = combat._load_session(mid).engine
    found = [c for c in engine.legal_candidates() if c.actor_id == actor and name in c.display_name
             and (target is None or target in c.target_ids)]
    assert found, (name, actor, target)
    return min(found, key=lambda c: len(c.display_name))


def play(combat, table, mid, name, *, actor=LEFT, target=RIGHT, pick=None, use=True):
    cid = candidate(combat, mid, name, actor=actor, target=target).candidate_id
    return send(combat, table, mid, cid, pick=pick, use=use)


def end_turn(combat, table, mid):
    menu = table.state(mid)['menu']
    cid = menu.get('end_turn') or next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates()
                                       if c.kind.value == 'END_TURN')
    return send(combat, table, mid, cid)


def move_to(combat, table, mid, at, *, actor=LEFT):
    menu = table.state(mid)['menu']
    cid = next(o['candidate_id'] for m in menu['moves']
               for o in [m] if (m['destination']['x'], m['destination']['y']) == at)
    return send(combat, table, mid, cid)


def grant(monkeypatch, field, *kinds, when=LEFT):
    """Give Right the printed ``field`` to every named damage type, inside the live engine.

    The damage is rolled and committed inside one real ``execute_intent``, so a defence added to a loaded session
    from outside is gone again by the time the table reloads for the next intent: this rides the engine's own event
    hook (appended, so every other hook still runs) on the intent ``when`` accepts.
    """
    from combat import ext

    def on_event(engine, event_type, kwargs):
        if event_type == 'INTENT_ACCEPTED' and kwargs.get('actor_id') == when:
            for kind in kinds:
                engine._add_modifier(engine.state.actors[RIGHT], 'test:defence', field, 'SET', kind, 'SELF',
                                     expires_on='UNTIL_REMOVED')
        return None

    ext.effects()
    monkeypatch.setitem(ext._HOOKS, 'event', [*(ext._HOOKS.get('event') or []), on_event])


def dice(monkeypatch, values):
    from tests.r10_fixup_support import fixed_dice

    fixed_dice(monkeypatch, values)


def packet(engine, *, actor, target=RIGHT, kind=None, index=-1):
    """One real DAMAGE_COMMITTED packet: the damage offered and the damage that landed."""
    rows = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == actor
            and target in (e.target_ids or ())
            and (kind is None or str((e.payload or {}).get('damage_type') or '').upper() == kind)]
    assert rows, f'no damage packet from {actor} to {target}'
    return rows[index].payload


def offered(engine, who=LEFT):
    return [a for a in engine.action_catalog.values() if a.display_name == NAME and a.owner_id == who]


def records(target, who=LEFT):
    return [c for c in target.conditions.values()
            if c.condition_id == PATIENT_EYE_ANALYZED and str((c.data or {}).get('by') or '') == who]


def open_record(combat, table, mid):
    """Left spends its one printed use on Right, then hands the turn around so it holds a fresh Action."""
    turn(combat, table, mid)
    send(combat, table, mid, candidate(combat, mid, NAME).candidate_id)
    engine = reload(combat, mid)
    assert records(engine.state.actors[RIGHT])
    end_turn(combat, table, mid)
    turn(combat, table, mid)
    return engine


def rounds_pass(combat, table, mid, count):
    """End turns until ``count`` more full rounds have been played (nothing else happens)."""
    engine = reload(combat, mid)
    start = engine.state.round_number
    while engine.state.round_number < start + count:
        end_turn(combat, table, mid)
        engine = reload(combat, mid)
    return engine


def turn_in(combat, table, mid, actor, round_number):
    """Hand turns around until ``actor`` is to act in ``round_number`` or later, and read the fight back."""
    for _ in range(4 * (round_number + 3)):
        state = table.state(mid)
        engine = combat._load_session(mid).engine
        if state['menu']['actor_id'] == actor and engine.state.round_number >= round_number:
            return engine
        end_turn(combat, table, mid)
    raise AssertionError(f'the turn never reached {actor} in round {round_number}')


# --------------------------------------------------------------------------- 1. the record itself
def test_patient_eye_opens_a_one_minute_record_that_survives_a_commit_and_reload(tmp_path):
    combat, table, mid = fight(tmp_path)
    engine = combat._load_session(mid).engine
    turn(combat, table, mid)
    cast_round = engine.state.round_number
    send(combat, table, mid, candidate(combat, mid, NAME).candidate_id)
    engine = reload(combat, mid)
    [held] = records(engine.state.actors[RIGHT])
    assert held.data['until_round'] == cast_round + ROUNDS, 'Duration: 1 minute'
    assert held.expires_on and held.expires_on.startswith('START_OF_SLOT_AT:'), held.expires_on
    assert analyzed_by(engine.state.actors[RIGHT], LEFT), 'the target becomes Analyzed by you'
    assert not analyzed_by(engine.state.actors[RIGHT], ALLY), 'and by nobody else'
    assert engine.state.actors[LEFT].resources[USES] == 0


def test_patient_eye_is_paid_once_and_only_offered_to_a_character_that_owns_it(tmp_path):
    combat, table, mid = fight(tmp_path)
    engine = combat._load_session(mid).engine
    assert offered(engine) and offered(engine)[0].costs == ((USES, 1),) and offered(engine)[0].range_ft == 120
    assert not offered(engine, RIGHT), 'inert for a character without the talent'
    open_record(combat, table, mid)
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].resources[USES] == 0
    assert not [c for c in engine.legal_candidates() if c.display_name == NAME], \
        '"Uses: Once per week": the single printed use is spent'


# --------------------------------------------------------------------------- 2. the suppressed Resistance
def test_an_allies_damage_meets_no_resistance_of_the_suppressed_type(tmp_path, monkeypatch):
    """"choose one known Damage Resistance to suppress until the start of your next turn" suppresses the TARGET's
    Resistance, not just your own attacks: the ally's very next hit lands whole. (Checked as the damage the target
    actually took, before any state is read back.)"""
    combat, table, mid = fight(tmp_path, ally=True)
    grant(monkeypatch, 'damage_resistance', 'BLUDGEONING')
    dice(monkeypatch, [20] * 80)

    turn(combat, table, mid, ALLY)
    play(combat, table, mid, STRIKE, actor=ALLY)
    engine = reload(combat, mid)
    alone = packet(engine, actor=ALLY)
    assert alone['reduced_to'] == alone['rolled_or_pending_damage'] // 2, 'the printed Resistance is live'

    open_record(combat, table, mid)
    play(combat, table, mid, STRIKE)
    end_turn(combat, table, mid)

    turn(combat, table, mid, ALLY)
    play(combat, table, mid, STRIKE, actor=ALLY)
    engine = reload(combat, mid)
    shared = packet(engine, actor=ALLY)
    assert shared['reduced_to'] == shared['rolled_or_pending_damage'], \
        "an ally's damage meets no Resistance of the suppressed type while the window is open"
    assert [m.value for m in engine.state.actors[RIGHT].modifiers.values()
            if m.target_field == 'resistance_suppressed'] == ['BLUDGEONING'], \
        'it is set aside on the target, not remembered on the user'


def test_the_suppressed_resistance_lasts_to_the_start_of_the_owners_next_turn(tmp_path, monkeypatch):
    """"until the start of your next turn": the window closes when the owner takes its next turn, and the printed
    Resistance is live again for everyone after it."""
    combat, table, mid = fight(tmp_path, ally=True)
    grant(monkeypatch, 'damage_resistance', 'BLUDGEONING')
    dice(monkeypatch, [20] * 80)

    open_record(combat, table, mid)
    prompts = play(combat, table, mid, STRIKE)
    engine = reload(combat, mid)
    mine = packet(engine, actor=LEFT)
    assert mine['reduced_to'] == mine['rolled_or_pending_damage'], 'the chosen packet lands whole'
    assert any(NAME in str(prompt) and 'Bludgeoning' in str(prompt) for prompt in prompts), prompts
    assert [m.value for m in engine.state.actors[RIGHT].modifiers.values()
            if m.target_field == 'resistance_suppressed'] == ['BLUDGEONING']
    end_turn(combat, table, mid)

    rounds_pass(combat, table, mid, 1)  # past the start of Left's next turn
    turn(combat, table, mid, ALLY)
    play(combat, table, mid, STRIKE, actor=ALLY)
    engine = reload(combat, mid)
    later = packet(engine, actor=ALLY)
    assert later['reduced_to'] == later['rolled_or_pending_damage'] // 2, \
        "the window ends at the start of the owner's next turn"
    assert not [m for m in engine.state.actors[RIGHT].modifiers.values() if m.target_field == 'resistance_suppressed']


def test_declining_the_printed_choice_leaves_the_resistance_in_place(tmp_path, monkeypatch):
    combat, table, mid = fight(tmp_path)
    turn(combat, table, mid)
    send(combat, table, mid, candidate(combat, mid, NAME).candidate_id)
    end_turn(combat, table, mid)
    grant(monkeypatch, 'damage_resistance', 'BLUDGEONING')
    dice(monkeypatch, [20] * 80)
    turn(combat, table, mid)
    prompts = play(combat, table, mid, STRIKE, use=False)
    engine = reload(combat, mid)
    assert any(NAME in str(prompt) for prompt in prompts), 'the printed line is offered'
    dealt = packet(engine, actor=LEFT)
    assert dealt['reduced_to'] == dealt['rolled_or_pending_damage'] // 2, 'the Resistance still applies'
    assert not engine.state.actors[LEFT].turn_flags.get(RESIST_USED)
    assert not [m for m in engine.state.actors[RIGHT].modifiers.values() if m.target_field == 'resistance_suppressed']


def test_patient_eye_asks_about_no_resistance_the_recorded_target_does_not_have(tmp_path, monkeypatch):
    combat, table, mid = fight(tmp_path)
    open_record(combat, table, mid)
    grant(monkeypatch, 'damage_resistance', 'FIRE')  # a real Resistance, but not to the damage this attack deals
    dice(monkeypatch, [20] * 80)
    prompts = play(combat, table, mid, STRIKE)
    assert not [p for p in prompts if NAME in str(p)], 'the printed word is "one known Damage Resistance"'
    assert not reload(combat, mid).state.actors[LEFT].turn_flags.get(RESIST_USED)


def test_the_suppression_cannot_be_chosen_on_another_creatures_turn(tmp_path, monkeypatch):
    """"once during each of your turns when you damage the target": Left's Opportunity Attack on Right's turn is damage
    the user deals outside its own turn, so it must neither ask nor set a Resistance aside."""
    combat, table, mid = fight(tmp_path, positions={LEFT: {'x': 10, 'y': 11}, RIGHT: {'x': 11, 'y': 11}})
    turn(combat, table, mid)
    send(combat, table, mid, candidate(combat, mid, NAME).candidate_id)
    end_turn(combat, table, mid)
    grant(monkeypatch, 'damage_resistance', 'PIERCING', 'SLASHING', when=RIGHT)  # the versatile jian picks either
    dice(monkeypatch, [20] * 80)
    turn(combat, table, mid, RIGHT)
    prompts = move_to(combat, table, mid, (13, 11), actor=RIGHT)
    engine = reload(combat, mid)
    assert [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == LEFT], \
        'leaving reach must really produce Left\'s Opportunity Attack'
    assert not [p for p in prompts if NAME in str(p)], 'an off-turn packet never asks'
    dealt = packet(engine, actor=LEFT)
    assert dealt['reduced_to'] == dealt['rolled_or_pending_damage'] // 2, 'the Resistance is untouched'
    assert not engine.state.actors[LEFT].turn_flags.get(RESIST_USED)
    assert not [m for m in engine.state.actors[RIGHT].modifiers.values() if m.target_field == 'resistance_suppressed']


# --------------------------------------------------------------------------- 3. damage with no attack roll
def test_a_saving_throw_can_be_answered_with_the_immunity_line(tmp_path, monkeypatch):
    """"once during the duration when you damage the target, you may treat one known Damage Immunity as Resistance for
    that instance of damage" -- on a saving throw, which carries no attack provenance at all, and only once per minute,
    with the spent use surviving a reload."""
    combat, table, mid = fight(tmp_path)
    grant(monkeypatch, 'damage_immunity', 'PSYCHIC')
    dice(monkeypatch, [1] + [20] * 80)  # the Wisdom save fails; the damage dice are as high as they go

    turn(combat, table, mid)
    play(combat, table, mid, NOTE)
    engine = reload(combat, mid)
    whole = packet(engine, actor=LEFT, kind='PSYCHIC')
    assert whole['reduced_to'] == 0, 'the printed Immunity is live before the record is opened'

    end_turn(combat, table, mid)
    turn(combat, table, mid)
    send(combat, table, mid, candidate(combat, mid, NAME).candidate_id)
    end_turn(combat, table, mid)
    turn(combat, table, mid)
    prompts = play(combat, table, mid, NOTE)
    engine = reload(combat, mid)
    counted = packet(engine, actor=LEFT, kind='PSYCHIC')
    assert counted['reduced_to'] == counted['rolled_or_pending_damage'] // 2 > 0, \
        'the Immunity counts as Resistance for that one instance'
    assert any(NAME in str(prompt) and 'Psychic' in str(prompt) for prompt in prompts), prompts
    [held] = records(engine.state.actors[RIGHT])
    assert held.data.get(IMMUNE_USED) == 1, 'the once-per-record use is recorded on the record itself'

    end_turn(combat, table, mid)
    turn(combat, table, mid)
    prompts = play(combat, table, mid, NOTE)
    engine = reload(combat, mid)
    spent = packet(engine, actor=LEFT, kind='PSYCHIC')
    assert spent['reduced_to'] == 0, '"once during the duration": the Immunity stands again'
    assert not [p for p in prompts if NAME in str(p)], 'and the question is not asked a second time'


def test_a_saving_throw_can_be_answered_with_the_resistance_line_once_per_turn(tmp_path, monkeypatch):
    """"once during each of your turns when you damage the target", on a saving throw: the question is asked of a packet
    that has no attack roll at all, and the choice is available again on the owner's next turn."""
    combat, table, mid = fight(tmp_path)
    grant(monkeypatch, 'damage_resistance', 'PSYCHIC')
    dice(monkeypatch, [1] + [20] * 80)

    turn(combat, table, mid)
    play(combat, table, mid, NOTE)
    engine = reload(combat, mid)
    alone = packet(engine, actor=LEFT, kind='PSYCHIC')
    assert alone['reduced_to'] == alone['rolled_or_pending_damage'] // 2, 'the printed Resistance is live'

    end_turn(combat, table, mid)
    turn(combat, table, mid)
    send(combat, table, mid, candidate(combat, mid, NAME).candidate_id)
    end_turn(combat, table, mid)
    turn(combat, table, mid)
    prompts = play(combat, table, mid, NOTE)
    engine = reload(combat, mid)
    chosen = packet(engine, actor=LEFT, kind='PSYCHIC')
    assert chosen['reduced_to'] == chosen['rolled_or_pending_damage'], 'save damage is not excluded'
    assert any(NAME in str(prompt) for prompt in prompts), prompts

    end_turn(combat, table, mid)
    turn(combat, table, mid)
    prompts = play(combat, table, mid, NOTE, use=False)
    engine = reload(combat, mid)
    again = packet(engine, actor=LEFT, kind='PSYCHIC')
    assert again['reduced_to'] == again['rolled_or_pending_damage'] // 2, \
        'the window ended at the start of the owner next turn'
    assert any(NAME in str(prompt) for prompt in prompts), '"once during each of your turns": asked again'


# --------------------------------------------------------------------------- 4. the one minute, and an ordinary Analyze
def test_the_record_and_its_analyzed_benefit_end_with_the_minute(tmp_path):
    combat, table, mid = fight(tmp_path)
    open_record(combat, table, mid)
    engine = rounds_pass(combat, table, mid, ROUNDS)
    assert not records(engine.state.actors[RIGHT]), '"Duration: 1 minute"'
    assert not analyzed_by(engine.state.actors[RIGHT], LEFT), 'and the Analyzed benefit ends with it'
    assert not [m for m in engine.state.actors[RIGHT].modifiers.values() if m.target_field == 'resistance_suppressed']


def test_the_record_outlives_the_targets_turns_before_its_deadline(tmp_path):
    """The minute ends at the caster's own slot ten rounds on, so the target's earlier turns -- including the
    last one before that slot, in the very round the deadline falls in -- must not end it early (AUTO6r1: a
    round-only fallback read the round number on the target's own turn and took the record off with it)."""
    combat, table, mid = fight(tmp_path, seed='SCANtwo1')  # Right, the recorded target, rolls before Left
    order = list(combat._load_session(mid).engine.state.initiative_order)
    assert order.index(RIGHT) < order.index(LEFT), ('the target must move before the caster', order)

    turn(combat, table, mid)
    send(combat, table, mid, candidate(combat, mid, NAME).candidate_id)
    engine = reload(combat, mid)
    [held] = records(engine.state.actors[RIGHT])
    until, deadline = held.data['until_round'], tuple(int(p) for p in held.expires_on.split(':')[1:])
    assert deadline == (until, order.index(LEFT)), (held.expires_on, order)

    engine = turn_in(combat, table, mid, RIGHT, until)  # the target's turn, inside the deadline round
    assert engine.state.current_slot_index < deadline[1], 'still before the caster\'s own slot'
    assert records(engine.state.actors[RIGHT]), 'the minute has not run out yet'
    assert analyzed_by(engine.state.actors[RIGHT], LEFT), 'so the Analyzed benefit is still live'

    engine = turn_in(combat, table, mid, LEFT, until)  # the caster's own slot, ten rounds on
    assert not records(engine.state.actors[RIGHT]), '"Duration: 1 minute" ends at the caster\'s slot'
    assert not analyzed_by(engine.state.actors[RIGHT], LEFT)


def test_two_owners_records_end_on_their_own_deadlines(tmp_path):
    """Two characters each open a minute on the same creature, staggered. Ally's ends first and must take
    nothing but its own record with it: Left's minute belongs to Left, and one owner's expiry never removes
    another user's still-live record (AUTO6r1)."""
    combat, table, mid = fight(tmp_path, ally=True, ally_owns=(TALENT,), seed='SCANthree3')  # Right, Ally, Left
    order = list(combat._load_session(mid).engine.state.initiative_order)
    assert order == [RIGHT, ALLY, LEFT], order

    turn(combat, table, mid, ALLY)
    send(combat, table, mid, candidate(combat, mid, NAME, actor=ALLY).candidate_id)
    engine = reload(combat, mid)
    ally_until = records(engine.state.actors[RIGHT], who=ALLY)[0].data['until_round']
    assert ally_until == 1 + ROUNDS, ally_until

    turn_in(combat, table, mid, LEFT, 3)  # Left opens its own minute two rounds later
    send(combat, table, mid, candidate(combat, mid, NAME).candidate_id)
    engine = reload(combat, mid)
    left_until = records(engine.state.actors[RIGHT], who=LEFT)[0].data['until_round']
    assert left_until == 3 + ROUNDS, left_until
    assert len([c for c in engine.state.actors[RIGHT].conditions.values()
                if c.condition_id == PATIENT_EYE_ANALYZED]) == 2, 'two owners, two records on one creature'

    engine = turn_in(combat, table, mid, ALLY, ally_until)  # Ally's minute is up; Left's is not
    assert not records(engine.state.actors[RIGHT], who=ALLY), "the earlier owner's minute ended"
    assert not analyzed_by(engine.state.actors[RIGHT], ALLY)
    assert records(engine.state.actors[RIGHT], who=LEFT), "the second owner's minute is its own"
    assert analyzed_by(engine.state.actors[RIGHT], LEFT), 'and its benefits stay readable'

    engine = turn_in(combat, table, mid, LEFT, left_until)
    assert not records(engine.state.actors[RIGHT], who=LEFT), 'and it ends on its own deadline'


def test_an_ordinary_analyze_outlives_the_records_minute(tmp_path, monkeypatch):
    """"Analyze ... Duration: 24 hours" is the user's own record. Opening the Inheritance's minute on the same creature
    must not shorten it."""
    combat, table, mid = fight(tmp_path)
    dice(monkeypatch, [20] * 80)
    turn(combat, table, mid)
    play(combat, table, mid, 'Analyze')
    engine = reload(combat, mid)
    assert analyzed_by(engine.state.actors[RIGHT], LEFT)
    end_turn(combat, table, mid)
    turn(combat, table, mid)
    send(combat, table, mid, candidate(combat, mid, NAME).candidate_id)
    engine = reload(combat, mid)
    assert len(records(engine.state.actors[RIGHT])) == 1, "the Inheritance's own minute is its own record"
    engine = rounds_pass(combat, table, mid, ROUNDS)
    assert not records(engine.state.actors[RIGHT]), 'the minute is over'
    assert analyzed_by(engine.state.actors[RIGHT], LEFT), 'the Analyze the owner already spent is untouched'


def test_a_target_protected_from_analyze_is_still_analyzed_by_the_inheritance(tmp_path, monkeypatch):
    """"The target becomes Analyzed by you for the duration even if it would normally be protected from Analyze"."""
    combat, table, mid = fight(tmp_path)
    dice(monkeypatch, [20] * 80)
    grant(monkeypatch, 'condition_immunity', 'analyzed_by')
    turn(combat, table, mid)
    play(combat, table, mid, 'Analyze')
    engine = reload(combat, mid)
    assert not analyzed_by(engine.state.actors[RIGHT], LEFT), 'the printed protection is live'
    end_turn(combat, table, mid)
    turn(combat, table, mid)
    send(combat, table, mid, candidate(combat, mid, NAME).candidate_id)
    engine = reload(combat, mid)
    assert records(engine.state.actors[RIGHT]), 'the Inheritance records the target in its own right'
    assert analyzed_by(engine.state.actors[RIGHT], LEFT), '"even if it would normally be protected from Analyze"'
