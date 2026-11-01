"""AUTO5/AUTO5f1 (round 24 live 42e43e14): the Spirit Companions Binding Seal family through accepted table actions.

Every case runs a real Factory character at the table, casts the printed ability through TabletopService,
reloads the saved fight from disk and checks the printed effect and its replay. AUTO5f1 adds the regressions the
independent review asked for: a failed check must change nothing, the ban is on the SEALED creature attacking its
binder (not the binder attacking its own spirit), every talent combination asks the right question, generic mark
removal takes the seal's clause with it, a suppressed spirit is out of a group command at execution time, the
printed Difficulty Class is the binder's and equality meets it, the Violent Ghost mark is placed by an attack and
belongs to the binder who owns the talent, both posture choices carry the printed Nature rider, and the one-mile
recall keeps its distance limit.

AUTO5r3f1 answers the AUTO5r3 review: the Pact's Help really benefits the NEXT attack roll and survives the blow that
asked for it (the old case pinned the opposite, the blow that asked spending its own benefit), unused Help ends at the
start of the spirit's next turn, the Exorcist's Mercy check is measured against the DC of the layer it breaks with the
two binders' DCs genuinely different and the non-casting binder's seal applied first, the movement choice's square is
asserted as the Binder's committed position, and a binder who is no longer in the fight is named in plain words.
"""
import json
import re

import pytest

from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.r10_fixup_support import cast_sender, commit, fixed_dice
from tests.test_lock2_persistence import act
from combat.ext.spirit_bond_state import STRAIN_MAX
from tests.test_tabletop_hunt6 import HOLD, LEFT, RIGHT, ALLY, on_hold, table_fight

SEAL = 'TAL_SPIRIT_COMPANIONS_BINDING_SEAL'
COVENANT = 'tianxia.talent.spirit_companions.covenant_spirit'
MANIFESTATION = 'tianxia.talent.spirit_companions.battle_manifestation'
PAINFUL = 'tianxia.talent.spirit_companions.painful_binding_seal'
PUNISH = 'tianxia.talent.spirit_companions.punishing_seal'
VIOLENT = 'tianxia.talent.spirit_companions.bind_the_violent_ghost'
MERCY = 'tianxia.talent.spirit_companions.exorcist_s_mercy'
CRUEL = 'tianxia.talent.spirit_companions.break_the_cruel_seal'
POSTURE = 'tianxia.talent.spirit_companions.guardian_spirit_posture'
NAME = 'tianxia.talent.spirit_companions.name_binding'
RECALL = 'tianxia.talent.spirit_companions.spirit_recall'
PACT = 'tianxia.talent.spirit_companions.pact_brother_battle_rhythm'
SHARED = 'tianxia.talent.spirit_companions.shared_senses'
SEALED = 'condition:typed.spirit_sealed'
SUPPRESSED = 'condition:typed.spirit_seal_suppressed'
VIOLENT_MARK = 'condition:typed.mark.violent_ghost'   # the prefix; a mark is stored under its binder's id
STRAIN = 'resource:named.bond_strain'
SPIRIT = f'{LEFT}.summon.bonded_spirit.1'
SEAL_BUTTONS = ('Binding Seal', 'Exorcist', 'Break the Cruel Seal', 'Guardian Spirit Posture',
                'Command Bonded Spirit', 'Spirit Recall', 'Shared Senses')


def sealer(tmp_path, monkeypatch, *, extra=(), cl=17, ask=True, control_modes=None):
    """Left is a Spirit Companions binder; its Bonded Spirit is already on the map and its Ally is Restrained.

    The restraint is the engine-visible half of the printed eligibility ("An unwilling spirit must be ...
    restrained"), put on inside an accepted action so it reaches the saved fight. ``ask=False`` drops the Ask-me
    reaction mode and ``control_modes`` can move the Binder off MANUAL, which is how the same fight becomes one
    whose Binder is run by the AI and decides the printed questions for itself."""
    talents = [SEAL, COVENANT, MANIFESTATION] + list(extra)
    combat, table, mid = table_fight(tmp_path, talents, cl=cl, ask=ask, ally_talents=[],
                                     control_modes=control_modes)

    def restrain(engine):
        engine._apply_condition(engine.state.actors[ALLY], 'condition:typed.restrained', SEAL, LEFT,
                                expires_on='UNTIL_REMOVED', data={'label': 'Restrained'})

    on_hold(monkeypatch, restrain)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    while (table.state(mid)['menu'] or {}).get('actor_id') != LEFT:
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
    return combat, table, mid, SPIRIT


def load(combat, tmp_path, mid):
    return CombatService(ROOT, tmp_path)._load_session(mid)


def mark_id(name, owner):
    from combat.typed_executor import mark_condition_id
    return mark_condition_id(name, owner)


def advance_to(table, mid, actor_id):
    while (table.state(mid)['menu'] or {}).get('actor_id') != actor_id:
        assert act(table, mid, 'end')['status'] == 'COMMITTED'


def choose(*ids):
    """Answer a sequence of prompts with the named option ids, in the order they are asked."""
    wanted = list(ids)

    def pick(prompt):
        options = [o['id'] for o in prompt['choice']['options']]
        for wanted_id in wanted:
            if wanted_id in options:
                wanted.remove(wanted_id)
                return wanted_id, True
        return (options[0], True) if options else (None, False)

    return pick


def scripted_dice(monkeypatch, dice_for):
    """One dice script per accepted intent.

    ``fixed_dice`` installs one queue and every intent restarts it, so a fight that needs the seal's saving throw to
    fail and the next Cultivation Check to win cannot be scripted with it. ``dice_for(engine, source)`` returns the
    dice for the intent about to resolve, chosen by the action it casts -- read from the engine's own candidate list,
    because an ActionIntent carries only the candidate's id. The returned box is the live script, so a test can
    retarget it between intents instead of installing a second, nesting wrapper."""
    from combat.gate4_engine import Gate4ControllerEngine
    from tests.h1_support import script

    original = Gate4ControllerEngine.execute_intent
    box = {'dice_for': dice_for}

    def execute(engine, *args, **kwargs):
        intent = args[0] if args else kwargs.get('intent')
        candidate_id = str(getattr(intent, 'candidate_id', '') or '')
        source = next((c.source_definition_id for c in engine.legal_candidates()
                       if c.candidate_id == candidate_id), '')
        script(engine, box['dice_for'](engine, source))
        return original(engine, *args, **kwargs)

    monkeypatch.setattr(Gate4ControllerEngine, 'execute_intent', execute)
    return box


def seal_then(win_die):
    """The Binding Seal's saving throw fails (die 1); every later Cultivation Check rolls ``win_die``.

    The seal's own action carries its authority id in its source (the saved SAVE_ROLLED events end with it), so the
    script keys on that id rather than on a lower-cased spelling of the ability's name. ``win_die`` may be a callable,
    so one installed script can be retargeted between intents instead of stacking a second wrapper."""
    def dice_for(engine, source):
        value = win_die() if callable(win_die) else win_die
        return [1] * 12 if SEAL in source else [value] * 40

    return dice_for


def prompt_names(prompts):
    """The ability each prompt says it belongs to, as the table reads it back."""
    return [str(p.get('context', {}).get('name') or p.get('context', {}).get('title') or p.get('title') or '')
            for p in prompts]


def _obey():
    """Every printed question answered the way that costs nothing."""
    return lambda prompt: ('willing' if 'willing' in {o['id'] for o in prompt['choice']['options']}
                           else 'aligns' if 'aligns' in {o['id'] for o in prompt['choice']['options']}
                           else 'exempt' if 'exempt' in {o['id'] for o in prompt['choice']['options']}
                           else 'no', True)


def _refuse():
    """The spirit refuses the order outright, the refusal breaks its Nature or Taboo, Painful's own "unless" does not
    excuse it, and the binder punishes the disobedience."""
    return choose('refuses', 'violates', 'strained', 'punish')


def _charges_since(events, mark, sources):
    """The Bond Strain charge lines recorded after index ``mark``, keyed by the ability that charged.

    Bond Strain stops at 3, so the counter alone cannot show how many printed sentences fired once a third has been
    added. Each charge also writes the sentence that caused it, and that is what this reads."""
    out = {}
    for event in events[mark:]:
        if event.event_type == 'PASSIVE_TRIGGERED' and event.source_definition_id in sources:
            out.setdefault(event.source_definition_id, []).append(str((event.payload or {}).get('log') or ''))
    return out


def _to_ai(combat, mid, actor_id):
    """Hand one actor to the AI the way a table does mid-fight, so its turns stop waiting for a player."""
    combat.set_controller_mode(mid, actor_id=actor_id, controller_mode='LOCAL_AUTO')


def _ai_step_choosing(combat, table, mid, actor_id, choose, answers=()):
    """Run one AI turn in which the AI takes the action ``choose`` picks (hunt31_support's controller swap).

    An AI actor's turn is driven by ``auto_step``, which lets the controller pick its own action. This makes that
    pick the printed order, so what is under test is the AI ANSWERING the printed questions -- not which action its
    policy would have preferred. Test-only; the real controller and the actor's mode are restored afterwards."""
    from combat.gate4_adapters import ManualControllerAdapter

    original = combat.controller

    class Chosen:
        def choose_primary_action(self, context):
            legal = combat._load_session(mid).engine.legal_candidates()
            picked = next(candidate for candidate in legal if choose(candidate))
            context = context.model_copy(update={'legal_candidates': tuple(legal)})
            return ManualControllerAdapter(lambda _: (picked.candidate_id, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(original, name)

    combat.controller = Chosen()
    combat.set_controller_mode(mid, actor_id=actor_id, controller_mode='LOCAL_AUTO')
    try:
        return table.auto_step(mid, table.state(mid)['last_sequence'], list(answers))
    finally:
        combat.controller = original
        combat.set_controller_mode(mid, actor_id=actor_id, controller_mode='MANUAL')


# --------------------------------------------------------------------------- Binding Seal: the button the sphere never had
def test_binding_seal_saves_marks_and_strains_and_survives_reload(tmp_path, monkeypatch):
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[PAINFUL])
    fixed_dice(monkeypatch, [1] * 200)  # the spirit fails its Wisdom saving throw
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    fresh = load(combat, tmp_path, mid)
    binder, sealed = fresh.engine.state.actors[LEFT], fresh.engine.state.actors[spirit]
    saves = [e for e in fresh.engine.events if e.event_type == 'SAVE_ROLLED' and e.source_definition_id.endswith(SEAL)]
    assert len(saves) == 1, [(e.event_type, e.source_definition_id) for e in fresh.engine.events[-20:]]
    assert saves[0].payload['reason'].endswith(':WIS'), saves[0].payload['reason']
    numbers = next(((((a.parameters or {}).get('typed') or {}).get('numbers') or {})
                   for a in fresh.engine.action_catalog.values()
                   if SEAL in a.source_definition_id), {})
    assert saves[0].payload['dc'] == int(numbers['save_dc'])
    assert any(row.condition_id == mark_id('Binding Seal', LEFT) for row in sealed.conditions.values())
    held = next((row for row in sealed.conditions.values() if row.condition_id == SEALED), None)
    assert held is not None and held.source_actor_id == LEFT
    assert held.data['tether_ft'] == 120, held.data           # the Bonded Spirit's own printed command range
    assert binder.resources[STRAIN] == 1, binder.resources     # "A spirit bound this way gains Bond Strain 1 immediately"
    assert fresh.mechanical.replay()['status'] == 'PASS'


def test_binding_seal_success_leaves_the_spirit_free(tmp_path, monkeypatch):
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch)
    fixed_dice(monkeypatch, [20] * 200)  # the spirit makes its saving throw
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    fresh = load(combat, tmp_path, mid)
    sealed = fresh.engine.state.actors[spirit]
    assert not any(row.condition_id == mark_id('Binding Seal', LEFT) for row in sealed.conditions.values())
    assert not any(row.condition_id == SEALED for row in sealed.conditions.values())
    assert fresh.engine.state.actors[LEFT].resources[STRAIN] == 0
    assert fresh.mechanical.replay()['status'] == 'PASS'


def test_binding_seal_offers_only_a_target_the_table_can_see_is_eligible(tmp_path, monkeypatch):
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch)
    engine = combat._load_session(mid).engine
    targets = {engine.state.actors[t].display_name for c in engine.legal_candidates()
               if c.display_name == 'Binding Seal' for t in c.target_ids}
    # "A Binding Seal restrains or compels a spirit": no side is printed, so every creature in reach is a legal target,
    # including the Binder's own Bonded Spirit (the sphere's coercive half commands that one).
    assert targets == {'Ally', 'Right', 'Bonded Spirit'}, targets


# --------------------------------------------------------------------------- finding 2: the ban is on the sealed spirit attacking its binder
def _alone_with_binder(monkeypatch, table, mid, spirit):
    """Everyone but the Binder out of the spirit's reach, so the only creature it could strike is its own binder."""
    def arrange(engine):
        from combat.gate2_runtime_models import Position
        engine.state.actors[ALLY].position = Position(x=11, y=7)
        engine.state.actors[RIGHT].position = Position(x=11, y=0)
        binder = engine.state.actors[LEFT]
        engine.state.actors[spirit].position = Position(x=binder.position.x, y=binder.position.y - 1)

    on_hold(monkeypatch, arrange)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'


def _play_round(table, mid):
    for _ in range(10):
        if table.state(mid)['menu'] is None:
            break
        act(table, mid, 'end')


def _strike_targets(engine, actor, wanted):
    """Whether ``actor`` may aim its own printed attack at ``wanted``, through the engine's own candidate filter.

    The spirit's Companion Strike and the Binder's improvised weapon attack are NATIVE actions with no typed attack
    row, which is the half of "cannot directly attack you" the old code could not see; both are read here with the
    production hook, not with a copy of its condition."""
    from types import SimpleNamespace

    from combat import ext
    from combat.ext import spirit_seals

    strike = next(action for action in engine.action_catalog.values()
                  if action.owner_id == actor.entity_id and action.display_name in ('Companion Strike',
                                                                                    'Improvised weapon attack'))
    assert spirit_seals._strikes(strike), (strike.display_name, strike.resolution_kind)
    candidate = SimpleNamespace(actor_id=actor.entity_id, source_definition_id=strike.source_definition_id,
                                target_ids=(wanted,))
    return not any(result is False
                   for result in ext.run("candidate_allowed", engine, actor, candidate, strike))


def test_a_sealed_spirit_cannot_attack_the_binder_who_sealed_it(tmp_path, monkeypatch):
    """"the spirit cannot directly attack you unless the seal cracks", read from the attacker: a sealed spirit may not
    aim its strike at the creature that sealed it."""
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[PAINFUL])
    fixed_dice(monkeypatch, [1] * 200)
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    engine = combat._load_session(mid).engine
    assert _strike_targets(engine, engine.state.actors[spirit], LEFT) is False


def test_an_unsealed_spirit_may_strike_the_creature_beside_it(tmp_path, monkeypatch):
    """The control for the test above: the same board and the same strike, with no seal, aims at the Binder freely --
    without it, a filter that merely hid friendly targets would pass the test above."""
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch)
    engine = combat._load_session(mid).engine
    assert _strike_targets(engine, engine.state.actors[spirit], LEFT) is True


def test_a_sealed_spirit_may_still_strike_anybody_else(tmp_path, monkeypatch):
    """The ban names one creature: the binder."""
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[PAINFUL])
    fixed_dice(monkeypatch, [1] * 200)
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    engine = combat._load_session(mid).engine
    assert _strike_targets(engine, engine.state.actors[spirit], RIGHT) is True


def test_the_binder_may_still_strike_its_own_sealed_spirit(tmp_path, monkeypatch):
    """The other half of finding 2: the printed ban does not stop the Binder attacking the creature it bound."""
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[PAINFUL])
    fixed_dice(monkeypatch, [1] * 200)
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    engine = combat._load_session(mid).engine
    assert _strike_targets(engine, engine.state.actors[LEFT], spirit) is True


def test_a_commanded_sealed_spirit_lands_nothing_on_its_binder(tmp_path, monkeypatch):
    """The whole order played out at the table: no blow from the spirit reaches its Binder, and the fight still
    replays (the spirit's own turn is resolved by the controller here, so this is the smoke half of finding 2)."""
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[PAINFUL])
    fixed_dice(monkeypatch, [1] * 400)
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    _alone_with_binder(monkeypatch, table, mid, spirit)
    advance_to(table, mid, LEFT)
    before = load(combat, tmp_path, mid).engine.state.actors[LEFT].current_hp
    commit(cast_sender(combat, table, mid, 'Command Bonded Spirit'), selections=_obey())
    _play_round(table, mid)
    fresh = load(combat, tmp_path, mid)
    assert not [e for e in fresh.engine.events if e.event_type == 'DAMAGE_COMMITTED'
                and e.actor_id == spirit and LEFT in (e.target_ids or ())], [
        (e.event_type, e.actor_id, e.target_ids) for e in fresh.engine.events[-25:]]
    assert fresh.engine.state.actors[LEFT].current_hp == before
    assert fresh.mechanical.replay()['status'] == 'PASS'


# --------------------------------------------------------------------------- finding 4: the condition follows its mark
def test_clearing_the_mark_by_any_means_ends_the_seals_clauses(tmp_path, monkeypatch):
    """A Binding Seal that is dispelled, cleansed or expired leaves with its condition: the engine's public mark id is
    the only thing that recognises it, so no creature is left unable to attack or unable to leave the bond."""
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch)
    fixed_dice(monkeypatch, [1] * 200)
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))

    def dispel(engine):
        from combat.ext.rider_support import remove_instance
        subject = engine.state.actors[spirit]
        for key, row in list(subject.conditions.items()):
            if row.condition_id == mark_id('Binding Seal', LEFT):
                remove_instance(engine, subject, key, 'system:test.dispel')

    on_hold(monkeypatch, dispel)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    fresh = load(combat, tmp_path, mid)
    sealed = fresh.engine.state.actors[spirit]
    assert not any(row.condition_id == SEALED for row in sealed.conditions.values()), [
        (row.condition_id, row.source_actor_id) for row in sealed.conditions.values()]
    assert not any(row.condition_id == mark_id('Binding Seal', LEFT) for row in sealed.conditions.values())
    assert fresh.mechanical.replay()['status'] == 'PASS'


def test_mercy_releases_a_seal_saved_before_the_condition_existed(tmp_path, monkeypatch):
    """An older saved fight carries the Binding Seal mark with no companion condition; Exorcist's Mercy must still
    break it, because the mark -- not the condition -- is what the printed rule removes."""
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[MERCY])

    def legacy_seal(engine):
        subject = engine.state.actors[spirit]
        engine._apply_condition(subject, mark_id('Binding Seal', LEFT), SEAL, LEFT,
                                expires_on='UNTIL_REMOVED', data={'label': 'Binding Seal'})

    on_hold(monkeypatch, legacy_seal)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    advance_to(table, mid, LEFT)
    fixed_dice(monkeypatch, [20] * 200)
    commit(cast_sender(combat, table, mid, 'Exorcist', contains='One layer of the Binding Seal on this creature ends', target=spirit))
    fresh = load(combat, tmp_path, mid)
    sealed = fresh.engine.state.actors[spirit]
    assert not any(row.condition_id == mark_id('Binding Seal', LEFT) for row in sealed.conditions.values()), [
        (row.condition_id, row.source_actor_id) for row in sealed.conditions.values()]
    assert not any(row.condition_id == SEALED for row in sealed.conditions.values())


# --------------------------------------------------------------------------- findings 3 and 9: one question per printed clause
def test_commanding_a_sealed_spirit_asks_and_punishes(tmp_path, monkeypatch):
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[PAINFUL, PUNISH])
    fixed_dice(monkeypatch, [1] * 400)
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    before = load(combat, tmp_path, mid)
    mark = len(before.engine.events)
    prompts = commit(cast_sender(combat, table, mid, 'Command Bonded Spirit'), selections=_refuse())
    titles = prompt_names(prompts)
    assert 'Painful Binding Seal' in titles, titles
    assert 'Punishing Seal' in titles, titles
    assert any('against its will' in str(p) for p in prompts), [str(p)[:200] for p in prompts]
    assert any('Bond Strain' in str(o['label']) for p in prompts for o in p['choice']['options']), [
        [o['label'] for o in p['choice']['options']] for p in prompts]
    fresh = load(combat, tmp_path, mid)
    binder = fresh.engine.state.actors[LEFT]
    damage = [e for e in fresh.engine.events if e.event_type == 'DAMAGE_COMMITTED'
              and e.source_definition_id.endswith(PUNISH)]
    assert len(damage) == 1, [(e.event_type, e.source_definition_id) for e in fresh.engine.events[-25:]]
    assert damage[0].target_ids == (spirit,)
    assert damage[0].payload['damage_type'] == 'PSYCHIC', damage[0].payload
    # Three printed sentences charge for one refused, coercive, Nature-breaking order: the seal's own clause,
    # Painful Binding Seal's own clause (its printed "unless" was refused), and Punishing Seal's "Using this talent
    # increases Bond Strain by 1". Bond Strain stops at 3, so the charges are read from the recorded lines.
    charges = _charges_since(fresh.engine.events, mark, {SEAL, PAINFUL, PUNISH})
    assert set(charges) == {SEAL, PAINFUL, PUNISH}, charges
    assert any("breaks that spirit's Nature" in line for line in charges[SEAL]), charges[SEAL]
    assert any('neither aligned with its Nature nor feared' in line for line in charges[PAINFUL]), charges[PAINFUL]
    assert any('punishes' in line for line in charges[PUNISH]), charges[PUNISH]
    assert binder.resources[STRAIN] == STRAIN_MAX, binder.resources
    assert binder.reaction_available is False
    assert fresh.mechanical.replay()['status'] == 'PASS'


def test_punishing_seal_alone_asks_and_names_its_own_talent(tmp_path, monkeypatch):
    """Finding 3: with Punishing Seal and neither of the other two talents there is no "unwilling talent" to name, and
    the old code raised KeyError on that name, so the whole prompt was skipped and the punishment never happened."""
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[PUNISH])
    fixed_dice(monkeypatch, [1] * 400)
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    before = load(combat, tmp_path, mid).engine.state.actors[LEFT].resources[STRAIN]
    prompts = commit(cast_sender(combat, table, mid, 'Command Bonded Spirit'), selections=choose('refuses', 'punish'))
    titles = prompt_names(prompts)
    assert 'Punishing Seal' in titles, titles
    fresh = load(combat, tmp_path, mid)
    assert [e for e in fresh.engine.events if e.event_type == 'DAMAGE_COMMITTED'
            and e.source_definition_id.endswith(PUNISH)], [e.event_type for e in fresh.engine.events[-20:]]
    # Punishing Seal's own sentence plus the Binding Seal's own coercion clause; no Painful, no Name-Binding.
    assert fresh.engine.state.actors[LEFT].resources[STRAIN] == before + 2
    assert fresh.mechanical.replay()['status'] == 'PASS'


def test_name_binding_alone_asks_its_own_question_and_never_the_punishment(tmp_path, monkeypatch):
    """Finding 3 again: Name-Binding alone was labelled "Punishing Seal", which it is not."""
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[NAME])
    fixed_dice(monkeypatch, [1] * 400)
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    before = load(combat, tmp_path, mid).engine.state.actors[LEFT].resources[STRAIN]
    prompts = commit(cast_sender(combat, table, mid, 'Command Bonded Spirit'), selections=choose('unwilling', 'violates'))
    titles = prompt_names(prompts)
    assert 'Punishing Seal' not in titles, titles
    assert 'Binding Seal' in titles, titles
    fresh = load(combat, tmp_path, mid)
    assert fresh.engine.state.actors[LEFT].resources[STRAIN] == before + 2, fresh.engine.state.actors[LEFT].resources
    assert not [e for e in fresh.engine.events if e.source_definition_id.endswith(PUNISH)]


def test_an_obeyed_command_costs_nothing(tmp_path, monkeypatch):
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[PAINFUL, PUNISH])
    fixed_dice(monkeypatch, [1] * 400)
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    before = load(combat, tmp_path, mid).engine.state.actors[LEFT].resources[STRAIN]
    commit(cast_sender(combat, table, mid, 'Command Bonded Spirit'), selections=_obey())
    fresh = load(combat, tmp_path, mid)
    assert fresh.engine.state.actors[LEFT].resources[STRAIN] == before
    assert not [e for e in fresh.engine.events if e.source_definition_id.endswith(PUNISH)]
    assert fresh.mechanical.replay()['status'] == 'PASS'


def test_the_seals_own_coercion_clause_runs_without_any_optional_talent(tmp_path, monkeypatch):
    """Finding 9: "each coercive command that violates the spirit's Nature or Taboo increases Bond Strain by 1" is the
    seal's own printed sentence, so it cannot need one of the three optional talents to be charged."""
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch)
    fixed_dice(monkeypatch, [1] * 400)
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    before = load(combat, tmp_path, mid).engine.state.actors[LEFT].resources[STRAIN]
    prompts = commit(cast_sender(combat, table, mid, 'Command Bonded Spirit'), selections=choose('unwilling', 'violates'))
    assert any('Nature' in str(p) for p in prompts), [str(p)[:200] for p in prompts]
    fresh = load(combat, tmp_path, mid)
    assert fresh.engine.state.actors[LEFT].resources[STRAIN] == before + 1, fresh.engine.state.actors[LEFT].resources


def test_the_printed_nature_exception_costs_nothing(tmp_path, monkeypatch):
    """Painful Binding Seal's printed "unless the command aligns with its Nature or the spirit fears a greater
    consequence": answered, this talent adds no Bond Strain. The seal's own clause is answered too, and it too breaks
    nothing, so nothing at all is charged."""
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[PAINFUL])
    fixed_dice(monkeypatch, [1] * 400)
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    before = load(combat, tmp_path, mid).engine.state.actors[LEFT].resources[STRAIN]
    commit(cast_sender(combat, table, mid, 'Command Bonded Spirit'), selections=choose('unwilling', 'aligns', 'exempt'))
    fresh = load(combat, tmp_path, mid)
    assert fresh.engine.state.actors[LEFT].resources[STRAIN] == before, fresh.engine.state.actors[LEFT].resources


def test_name_binding_charges_bond_strain_for_unwilling_service(tmp_path, monkeypatch):
    """Name-Binding's printed counter: "Every time the standing command forces unwilling service, increase Bond
    Strain by 1". It is asked through the same printed question as Painful Binding Seal."""
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[NAME])
    fixed_dice(monkeypatch, [1] * 400)
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    before = load(combat, tmp_path, mid).engine.state.actors[LEFT].resources[STRAIN]
    prompts = commit(cast_sender(combat, table, mid, 'Command Bonded Spirit'), selections=choose('unwilling', 'violates'))
    assert any('against its will' in str(p) for p in prompts), [str(p)[:200] for p in prompts]
    fresh = load(combat, tmp_path, mid)
    binder = fresh.engine.state.actors[LEFT]
    assert binder.resources[STRAIN] == before + 2, binder.resources   # the seal took hold, then the refusal
    # An obeyed standing command costs nothing.
    before = binder.resources[STRAIN]
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    advance_to(table, mid, LEFT)
    commit(cast_sender(combat, table, mid, 'Command Bonded Spirit'), selections=_obey())
    assert load(combat, tmp_path, mid).engine.state.actors[LEFT].resources[STRAIN] == before


def test_both_name_binding_and_painful_binding_seal_charge_together(tmp_path, monkeypatch):
    """Three printed sentences are true at once for one unwilling, coercive, Nature-breaking order, so a character who
    owns all three pays all three: Name-Binding's "forces unwilling service", the seal's own "violates the spirit's
    Nature or Taboo", and Painful Binding Seal's own clause (its printed "unless" was refused)."""
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[NAME, PAINFUL])
    fixed_dice(monkeypatch, [1] * 400)
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    before = load(combat, tmp_path, mid)
    mark = len(before.engine.events)
    commit(cast_sender(combat, table, mid, 'Command Bonded Spirit'),
           selections=choose('unwilling', 'violates', 'strained'))
    fresh = load(combat, tmp_path, mid)
    charges = _charges_since(fresh.engine.events, mark, {NAME, SEAL, PAINFUL})
    assert set(charges) == {NAME, SEAL, PAINFUL}, charges
    assert any('unwilling service' in line for line in charges[NAME]), charges[NAME]
    assert any('Nature' in line for line in charges[SEAL]), charges[SEAL]
    assert any('against its desire' in line for line in charges[PAINFUL]), charges[PAINFUL]
    assert fresh.engine.state.actors[LEFT].resources[STRAIN] == STRAIN_MAX, fresh.engine.state.actors[LEFT].resources


# --------------------------------------------------------------------------- finding 1: a failed check changes nothing
def test_exorcists_mercy_rolls_the_printed_cultivation_check(tmp_path, monkeypatch):
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[MERCY])
    fixed_dice(monkeypatch, [20] * 200)  # the Cultivation Check beats the printed DC
    commit(cast_sender(combat, table, mid, 'Exorcist', contains='One layer of the Binding Seal on this creature ends', target=spirit))
    fresh = load(combat, tmp_path, mid)
    checks = [e for e in fresh.engine.events if e.event_type == 'CHECK_ROLLED' and MERCY in e.source_definition_id]
    assert len(checks) == 1
    assert checks[0].payload['check'] == 'Cultivation Check'
    assert checks[0].payload['target']['expression'].startswith('DC ')
    assert checks[0].payload['success'] is True
    assert fresh.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('contains,condition', [
    ('One layer of the Binding Seal on this creature ends', None),
    ('The spirit cannot be commanded for 1 minute', SUPPRESSED),
])
def test_a_failed_cultivation_check_changes_nothing(tmp_path, monkeypatch, contains, condition):
    """Finding 1: the outcome is nested under the check's success, so a failed check must not break a seal, suppress
    it, or hand out any other printed benefit."""
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[MERCY, PAINFUL])
    fixed_dice(monkeypatch, [1] * 200)   # the Wisdom save fails (the seal takes hold) and the check below fails
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    advance_to(table, mid, LEFT)
    commit(cast_sender(combat, table, mid, 'Exorcist', contains=contains, target=spirit))
    fresh = load(combat, tmp_path, mid)
    checks = [e for e in fresh.engine.events if e.event_type == 'CHECK_ROLLED' and MERCY in e.source_definition_id]
    assert len(checks) == 1 and checks[0].payload['success'] is False, checks[0].payload
    # The state read back AFTER the cast: a failed check that still removed the mark or added a suppression would be
    # invisible in a snapshot taken before the cast.
    sealed = fresh.engine.state.actors[spirit]
    assert any(row.condition_id == mark_id('Binding Seal', LEFT) for row in sealed.conditions.values()), [
        (row.condition_id, row.source_actor_id) for row in sealed.conditions.values()]
    if condition:
        assert not any(row.condition_id == condition for row in sealed.conditions.values()), [
            row.condition_id for row in sealed.conditions.values()]
    assert fresh.mechanical.replay()['status'] == 'PASS'


def test_break_the_cruel_seal_checks_then_suppresses_the_seal(tmp_path, monkeypatch):
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[CRUEL, PAINFUL])
    fixed_dice(monkeypatch, [20] * 300)  # the printed Cultivation Check is won
    commit(cast_sender(combat, table, mid, 'Break the Cruel Seal', contains='Suppress the seal', target=spirit))
    fresh = load(combat, tmp_path, mid)
    sealed = fresh.engine.state.actors[spirit]
    checks = [e for e in fresh.engine.events if e.event_type == 'CHECK_ROLLED' and CRUEL in e.source_definition_id]
    assert len(checks) == 1, [(e.event_type, e.source_definition_id) for e in fresh.engine.events[-20:]]
    assert checks[0].payload['check'] == 'Cultivation Check'
    assert checks[0].payload['success'] is True, checks[0].payload
    assert any(row.condition_id == SUPPRESSED for row in sealed.conditions.values())
    assert fresh.mechanical.replay()['status'] == 'PASS'


def test_a_failed_cruel_seal_check_does_not_suppress(tmp_path, monkeypatch):
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[CRUEL, PAINFUL])
    fixed_dice(monkeypatch, [1] * 300)
    commit(cast_sender(combat, table, mid, 'Break the Cruel Seal', contains='Suppress the seal', target=spirit))
    fresh = load(combat, tmp_path, mid)
    checks = [e for e in fresh.engine.events if e.event_type == 'CHECK_ROLLED' and CRUEL in e.source_definition_id]
    assert checks and checks[0].payload['success'] is False, checks[0].payload
    assert not any(row.condition_id == SUPPRESSED for row in fresh.engine.state.actors[spirit].conditions.values())


# --------------------------------------------------------------------------- finding 7: the printed Difficulty Class
def test_the_printed_check_is_measured_against_the_binders_dc(tmp_path, monkeypatch):
    """"against the binder's Cultivation Save DC" -- not the spirit's own, and not a flat number."""
    from combat.ext.end_effect import cultivation_dc

    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[CRUEL, PAINFUL])
    scripted_dice(monkeypatch, seal_then(20))   # the seal takes hold, then the printed check is won
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    advance_to(table, mid, LEFT)
    engine = combat._load_session(mid).engine
    binder_dc, spirit_dc = cultivation_dc(engine, engine.state.actors[LEFT]), cultivation_dc(engine, engine.state.actors[spirit])
    assert binder_dc != spirit_dc, (binder_dc, spirit_dc)   # otherwise this test cannot tell the two apart
    commit(cast_sender(combat, table, mid, 'Break the Cruel Seal', contains='Suppress the seal', target=spirit))
    fresh = load(combat, tmp_path, mid)
    checks = [e for e in fresh.engine.events if e.event_type == 'CHECK_ROLLED' and CRUEL in e.source_definition_id]
    assert checks[0].payload['target']['expression'] == f'DC {binder_dc}', checks[0].payload


def test_meeting_the_printed_difficulty_class_succeeds(tmp_path, monkeypatch):
    """Finding 7: a printed Difficulty Class is met by matching it, where an opposed contest's tie is a failure."""
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[CRUEL, PAINFUL])
    win = [20]
    dice = scripted_dice(monkeypatch, seal_then(lambda: win[0]))   # the seal takes hold, then a check over the DC
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    advance_to(table, mid, LEFT)
    commit(cast_sender(combat, table, mid, 'Break the Cruel Seal', contains='Suppress the seal', target=spirit))
    high = load(combat, tmp_path, mid).engine
    check = next(e for e in high.events if e.event_type == 'CHECK_ROLLED' and CRUEL in e.source_definition_id)
    # The die that lands the Cultivation Check EXACTLY on the printed DC (total = die + modifier).
    dc, modifier = check.payload['target']['total'], check.payload['actor']['modifier']
    exact = dc - modifier
    assert 1 <= exact <= 20, (dc, modifier, exact)
    assert check.payload['success'] is True and check.payload['margin'] > 0, check.payload

    win[0] = exact
    assert dice['dice_for'](None, 'action:x.' + SEAL) == [1] * 12      # the seal still fails its saving throw
    # A separate userdata root: two fights built from the same seed share a match id, so the second one must be read
    # back from its own root or the probe would reload the first.
    root = tmp_path / 'exact'
    combat, table, mid, spirit = sealer(root, monkeypatch, extra=[CRUEL, PAINFUL])
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    advance_to(table, mid, LEFT)
    commit(cast_sender(combat, table, mid, 'Break the Cruel Seal', contains='Suppress the seal', target=spirit))
    fresh = load(combat, root, mid)
    rolled = next(e for e in fresh.engine.events if e.event_type == 'CHECK_ROLLED' and CRUEL in e.source_definition_id)
    assert rolled.payload['actor']['total'] == dc == rolled.payload['target']['total'], rolled.payload
    assert rolled.payload['margin'] == 0 and rolled.payload['success'] is True, rolled.payload
    assert rolled.payload['outcome_override'] is True, rolled.payload
    assert any(row.condition_id == SUPPRESSED for row in fresh.engine.state.actors[spirit].conditions.values())


# --------------------------------------------------------------------------- finding 5: suppression is a command restriction
def test_a_suppressed_spirit_leaves_the_command_menu(tmp_path, monkeypatch):
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[CRUEL, PAINFUL])
    fixed_dice(monkeypatch, [20] * 300)
    commit(cast_sender(combat, table, mid, 'Break the Cruel Seal', contains='Suppress the seal', target=spirit))
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    advance_to(table, mid, LEFT)
    engine = combat._load_session(mid).engine
    names = {c.display_name for c in engine.legal_candidates()}
    assert 'Command Bonded Spirit' not in names, names


def test_one_group_command_does_not_reach_a_suppressed_spirit(tmp_path, monkeypatch):
    """Finding 5: the menu filter alone was not enough -- one order reaches every member the summons module lists, so in
    a group of Corpse Servants a suppressed spirit still acted. The engine's own commandable list must drop exactly
    that one and keep the rest, because that is the list summons.command sends the order with."""
    talents = [SEAL, COVENANT, CRUEL, PAINFUL, 'TAL_DEATH_CORPSE_SERVANT']
    combat, table, mid = table_fight(tmp_path, talents, cl=17, ask=True, ally_talents=[])
    scripted_dice(monkeypatch, seal_then(20))
    servants = [actor.entity_id for actor in combat._load_session(mid).engine.state.actors.values()
                if (actor.summon or {}).get('command_group') == 'death' and actor.active]
    assert len(servants) > 1, servants                      # a real mixed group, not a lone spirit
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=servants[0]))
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    advance_to(table, mid, LEFT)
    commit(cast_sender(combat, table, mid, 'Break the Cruel Seal', contains='Suppress the seal', target=servants[0]))
    from combat import summons

    engine = load(combat, tmp_path, mid).engine
    owner = engine.state.actors[LEFT]
    assert 'Command Death servants' in {c.display_name for c in engine.legal_candidates()}
    reachable = [creature.entity_id for creature in summons.commandable(engine, owner, 'death')]
    assert set(reachable) == set(servants) - {servants[0]}, reachable
    commit(cast_sender(combat, table, mid, 'Command Death servants'))
    fresh = load(combat, tmp_path, mid)
    commanded = [e for e in fresh.engine.events if e.event_type == 'SUMMONS_COMMANDED'][-1]
    assert set(commanded.target_ids) == set(servants) - {servants[0]}, commanded.target_ids
    assert fresh.engine.state.actors[servants[0]].summon['commanded'] is False
    assert fresh.mechanical.replay()['status'] == 'PASS'


def test_a_suppressed_seal_holds_nothing_at_all(tmp_path, monkeypatch):
    """Finding 5 again: a suppressed seal's movement tether is released too, so the spirit may leave the bond."""
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[CRUEL, PAINFUL])
    scripted_dice(monkeypatch, seal_then(20))
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    advance_to(table, mid, LEFT)
    commit(cast_sender(combat, table, mid, 'Break the Cruel Seal', contains='Suppress the seal', target=spirit))
    engine = load(combat, tmp_path, mid).engine
    from combat.ext import move_limits
    held = next(row for row in engine.state.actors[spirit].conditions.values() if row.condition_id == SEALED)
    assert move_limits.tether(engine, held, engine.state.actors[spirit]) is None
    # The printed Bonded Spirit command range is 120 feet and the yard is smaller, so read the rule from the stored
    # length instead of the map: with the seal suppressed the tether is gone whatever the board's size.
    assert held.data['tether_ft'] == 120


def test_an_unsealed_spirit_keeps_its_tether(tmp_path, monkeypatch):
    """The control for the test above."""
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch)
    fixed_dice(monkeypatch, [1] * 200)
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    engine = load(combat, tmp_path, mid).engine
    from combat.ext import move_limits
    held = next(row for row in engine.state.actors[spirit].conditions.values() if row.condition_id == SEALED)
    tied = move_limits.tether(engine, held, engine.state.actors[spirit])
    assert tied is not None and tied[1] == 120, tied


def test_suppression_ends_at_the_binders_next_turn(tmp_path, monkeypatch):
    """Checklist 8 at the exact boundary: "suppress the Binding Seal until the end of your next turn" names one edge,
    so the suppression is read from that edge and asserted still present immediately before it and absent immediately
    after it -- not by advancing several turns and inspecting whatever is left."""
    from combat.ext import effect_durations

    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[CRUEL, PAINFUL])
    scripted_dice(monkeypatch, seal_then(20))
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    advance_to(table, mid, LEFT)

    def board():
        return load(combat, tmp_path, mid).engine

    def suppressed_now():
        return any(row.condition_id == SUPPRESSED
                   for row in board().state.actors[spirit].conditions.values())

    commit(cast_sender(combat, table, mid, 'Break the Cruel Seal', contains='Suppress the seal', target=spirit))
    held = next(row for row in board().state.actors[spirit].conditions.values() if row.condition_id == SUPPRESSED)
    # The deadline is stated here as "the end of the Binder's NEXT turn", from the Binder's own counter and nothing
    # else, and only then compared with what was stored. Finding 3 (AUTO5r2): reading the expected turn back out of
    # the stored token made an incorrectly later deadline pass, because the walk then simply went further.
    caster_turns = int(board().state.actors[LEFT].turns_started)
    assert held.expires_on in (effect_durations.token('end', LEFT, caster_turns + 1),
                               f'END_OF_SOURCE_TURN_AT:{caster_turns + 1}'), \
        (held.expires_on, caster_turns)
    # "the end of your next turn" is one of the engine's own expiry names: END_OF_SOURCE_TURN_AT:<the caster's turn>,
    # or the actor-keyed END_OF_TURN_AT for a window that names its holder. Either way the caster is LEFT.
    named = effect_durations.parse(held.expires_on)
    source_turn = re.fullmatch(r'END_OF_SOURCE_TURN_AT:(\d+)', str(held.expires_on or ''))
    assert named is not None or source_turn is not None, held.expires_on   # never the fallback token
    boundary_edge = 'end'
    boundary_actor = LEFT
    boundary_turn = int(source_turn.group(1)) if source_turn else named[2]
    if named is not None:
        assert (named[0], named[1]) == ('end', LEFT), held.expires_on
    else:
        assert named is None and boundary_actor == LEFT
    assert suppressed_now()
    # Walk exactly onto that edge, one turn at a time, never past it.
    for _ in range(20):
        live = board().state
        if (live.current_actor_id == boundary_actor
                and int(live.actors[boundary_actor].turns_started) == boundary_turn):
            break
        assert table.state(mid)['menu'] is not None, 'the fight ended before the printed edge came'
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
    else:
        raise AssertionError(f'never reached {held.expires_on}')
    assert suppressed_now(), 'the suppression was gone before the end of that turn'
    assert act(table, mid, 'end')['status'] == 'COMMITTED'   # the Binder's next turn ends exactly here
    assert not suppressed_now(), [(row.condition_id, row.expires_on)
                                  for row in board().state.actors[spirit].conditions.values()]


def test_a_one_minute_suppression_lasts_ten_rounds_and_no_longer(tmp_path, monkeypatch):
    """Checklist 8: "suppress the Hosting Bond for 1 minute" is a COUNTED duration, so it is a round clock the engine
    removes on its own -- ten rounds, and it is gone the moment that round comes, not at the end of the fight."""
    from combat.ext import effect_durations

    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[MERCY, PAINFUL])
    scripted_dice(monkeypatch, seal_then(20))
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    advance_to(table, mid, LEFT)
    commit(cast_sender(combat, table, mid, 'Exorcist',
                       contains='The spirit cannot be commanded for 1 minute', target=spirit))
    engine = load(combat, tmp_path, mid).engine
    held = next(row for row in engine.state.actors[spirit].conditions.values() if row.condition_id == SUPPRESSED)
    start = engine.state.round_number
    # A counted duration is one of the engine's own round tokens, ten rounds out; never UNTIL_REMOVED.
    assert held.expires_on == effect_durations.round_token(engine, 10) != 'UNTIL_REMOVED', held.expires_on

    def play_to(round_number):
        while load(combat, tmp_path, mid).engine.state.round_number < round_number:
            if table.state(mid)['menu'] is None:
                break
            assert act(table, mid, 'end')['status'] == 'COMMITTED'

    play_to(start + 9)
    nine = load(combat, tmp_path, mid).engine
    assert start + 9 <= nine.state.round_number < start + 10, (nine.state.round_number, start)
    assert any(row.condition_id == SUPPRESSED for row in nine.state.actors[spirit].conditions.values()), [
        (row.condition_id, row.expires_on) for row in nine.state.actors[spirit].conditions.values()]
    play_to(start + 12)
    fresh = load(combat, tmp_path, mid)
    assert fresh.engine.state.round_number >= start + 10, (fresh.engine.state.round_number, start)
    assert not any(row.condition_id == SUPPRESSED for row in fresh.engine.state.actors[spirit].conditions.values()), [
        (row.condition_id, row.expires_on) for row in fresh.engine.state.actors[spirit].conditions.values()]
    assert fresh.mechanical.replay()['status'] == 'PASS'


# --------------------------------------------------------------------------- finding 8: Bind the Violent Ghost
def test_bind_the_violent_ghost_marks_a_spirit_that_attacked_you(tmp_path, monkeypatch):
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[VIOLENT, PAINFUL])
    fixed_dice(monkeypatch, [1] * 200)

    def strike(engine):
        # The spirit attacks the Binder BEFORE any seal: the printed precondition is about the scene, not the seal.
        engine._append_event('ATTACK_ROLLED', 'test:spirit_attack', actor_id=spirit, target_ids=(LEFT,),
                             payload={'natural_result': 1})

    on_hold(monkeypatch, strike)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    fresh = load(combat, tmp_path, mid)
    marked = fresh.engine.state.actors[spirit]
    assert any(row.condition_id == mark_id('Violent Ghost', LEFT)
               for row in marked.conditions.values()), [
        (row.condition_id, row.source_actor_id) for row in marked.conditions.values()]


def test_bind_the_violent_ghost_marks_a_missed_attack_on_an_allied_spirit(tmp_path, monkeypatch):
    """Finding 8: a spirit that attacked an ally -- a miss counts, and an allied character counts exactly as much as
    one of the Binder's own summoned creatures, because the printed precondition is about a side."""
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[VIOLENT, PAINFUL])
    fixed_dice(monkeypatch, [1] * 200)

    def strike(engine):
        engine._append_event('ATTACK_ROLLED', 'test:spirit_attack', actor_id=spirit, target_ids=(ALLY,),
                             payload={'natural_result': 1})   # the Binder's own ally

    on_hold(monkeypatch, strike)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    fresh = load(combat, tmp_path, mid)
    marked = fresh.engine.state.actors[spirit]
    assert any(row.condition_id == mark_id('Violent Ghost', LEFT) for row in marked.conditions.values()), [
        (row.condition_id, row.source_actor_id) for row in marked.conditions.values()]


def test_bind_the_violent_ghost_makes_the_seal_save_disadvantage(tmp_path, monkeypatch):
    """"the spirit has Disadvantage on its saving throw": the mark the first test plants is what the printed
    disadvantage reads, so the Wisdom saving throw is really rolled at Disadvantage."""
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[VIOLENT])
    # 1s all round: the spirit fails only if its first die (a 1, discarded at Disadvantage) is followed by the 1 the
    # second die uses. Unmarked, the same sequence fails on the first die and never rolls a second.
    fixed_dice(monkeypatch, [1] * 200)

    def attack(engine):
        engine._append_event('ATTACK_ROLLED', 'test:spirit_attack', actor_id=spirit, target_ids=(LEFT,),
                             payload={'natural_result': 1})

    on_hold(monkeypatch, attack)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    fresh = load(combat, tmp_path, mid)
    save = next(e for e in fresh.engine.events
                if e.event_type == 'SAVE_ROLLED' and e.source_definition_id.endswith(SEAL))
    assert save.payload['mode'] == 'DISADVANTAGE', save.payload
    assert len(save.payload['discarded']) == 1, save.payload


def test_an_unmarked_spirit_saves_in_the_normal_order(tmp_path, monkeypatch):
    """The control for the test above: without Bind the Violent Ghost's mark the same dice are a plain save."""
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch)
    fixed_dice(monkeypatch, [1] * 200)
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    fresh = load(combat, tmp_path, mid)
    save = next(e for e in fresh.engine.events
                if e.event_type == 'SAVE_ROLLED' and e.source_definition_id.endswith(SEAL))
    assert save.payload['mode'] == 'NORMAL' and not save.payload['discarded'], save.payload


def test_the_violent_ghost_disadvantage_belongs_to_the_binder_who_owns_it(tmp_path, monkeypatch):
    """Finding 8: the mark is stored under the binder who owns the talent, and the seal's save row reads the mark BY
    that binder. A second binder, without the talent, sealing the same spirit gets a plain save."""
    talents = [SEAL, COVENANT, MANIFESTATION, VIOLENT]
    combat, table, mid = table_fight(tmp_path, talents, cl=17, ask=True,
                                     ally_talents=[SEAL, COVENANT, MANIFESTATION])
    fixed_dice(monkeypatch, [1] * 400)

    def attack(engine):
        engine._append_event('ATTACK_ROLLED', 'test:spirit_attack', actor_id=SPIRIT, target_ids=(LEFT,),
                             payload={'natural_result': 1})

    on_hold(monkeypatch, attack)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    # Left owns Bind the Violent Ghost and binds its own spirit: the printed Disadvantage applies. The spirit is the
    # creature that makes the Wisdom saving throw, so it is the spirit whose roll carries the mode.
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=SPIRIT))
    fresh = load(combat, tmp_path, mid)
    modes = [(e.actor_id, e.payload['mode']) for e in fresh.engine.events
             if e.event_type == 'SAVE_ROLLED' and e.source_definition_id.endswith(SEAL)]
    assert modes == [(SPIRIT, 'DISADVANTAGE')], modes
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    # The Ally walks into the seal's printed 5-foot reach and binds the same spirit, owning no such talent.
    advance_to(table, mid, ALLY)
    board = combat._load_session(mid).engine
    spirit_cell = board.state.actors[SPIRIT].position
    step = next((spirit_cell.x + dx, spirit_cell.y + dy) for dx in range(-1, 2) for dy in range(-1, 2)
                if (dx or dy) and board.grid.in_bounds((spirit_cell.x + dx, spirit_cell.y + dy))
                and not any(other.active and (other.position.x, other.position.y) == (spirit_cell.x + dx, spirit_cell.y + dy)
                            for other in board.state.actors.values()))
    commit(cast_sender(combat, table, mid, f'Move to {step[0]},{step[1]}', at=step))
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=SPIRIT))
    fresh = load(combat, tmp_path, mid)
    modes = [(e.actor_id, e.payload['mode']) for e in fresh.engine.events
             if e.event_type == 'SAVE_ROLLED' and e.source_definition_id.endswith(SEAL)]
    assert modes == [(SPIRIT, 'DISADVANTAGE'), (SPIRIT, 'NORMAL')], modes
    assert fresh.mechanical.replay()['status'] == 'PASS'


def test_a_spirit_that_never_attacked_anyone_saves_normally_for_the_talent_owner(tmp_path, monkeypatch):
    """The other control: owning the talent alone must not put every seal at Disadvantage."""
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[VIOLENT])
    fixed_dice(monkeypatch, [1] * 200)
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    fresh = load(combat, tmp_path, mid)
    save = next(e for e in fresh.engine.events
                if e.event_type == 'SAVE_ROLLED' and e.source_definition_id.endswith(SEAL))
    assert save.payload['mode'] == 'NORMAL', save.payload


# --------------------------------------------------------------------------- finding 10: Guardian Spirit Posture
@pytest.mark.parametrize('contains', ['Disadvantage', 'AC'])
def test_both_postures_offer_the_printed_temporary_hit_points(tmp_path, monkeypatch, contains):
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[POSTURE])
    _beside(monkeypatch, table, mid, spirit)
    advance_to(table, mid, LEFT)
    before = combat._load_session(mid).engine.state.actors[ALLY].temporary_hp
    prompts = commit(cast_sender(combat, table, mid, 'Guardian Spirit Posture', contains=contains, target=ALLY),
                     selections=choose('yes'))
    assert any('Nature' in str(p) for p in prompts), [str(p)[:200] for p in prompts]
    fresh = load(combat, tmp_path, mid)
    protected = fresh.engine.state.actors[ALLY]
    assert protected.temporary_hp == before + 4, (before, protected.temporary_hp)   # PB 4 at CL 17
    assert fresh.mechanical.replay()['status'] == 'PASS'


def test_a_posture_without_the_nature_rider_grants_no_extra_temporary_hit_points(tmp_path, monkeypatch):
    """The printed sentence is conditional on the spirit's Nature; answering "no" grants nothing."""
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[POSTURE])
    _beside(monkeypatch, table, mid, spirit)
    advance_to(table, mid, LEFT)
    before = combat._load_session(mid).engine.state.actors[ALLY].temporary_hp
    commit(cast_sender(combat, table, mid, 'Guardian Spirit Posture', contains='Disadvantage', target=ALLY),
           selections=choose('no'))
    fresh = load(combat, tmp_path, mid)
    assert fresh.engine.state.actors[ALLY].temporary_hp == before


def _beside(monkeypatch, table, mid, spirit):
    def beside(engine):
        from combat.gate2_runtime_models import Position
        ally = engine.state.actors[ALLY]
        free = next(Position(x=ally.position.x + dx, y=ally.position.y) for dx in (-1, 1, -2, 2)
                    if engine.grid.in_bounds((ally.position.x + dx, ally.position.y))
                    and not any(other.active and other.position == Position(x=ally.position.x + dx, y=ally.position.y)
                                for other in engine.state.actors.values()))
        engine.state.actors[spirit].position = free

    on_hold(monkeypatch, beside)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'


# --------------------------------------------------------------------------- finding 11: Spirit Recall keeps its printed limits
def test_the_one_mile_recall_stops_at_one_mile(tmp_path, monkeypatch):
    """Finding 11: a spirit the engine measures at exactly a mile is eligible; the next step out is not."""
    from combat.gate2_runtime_models import Position
    from combat.ext import spirit_bonds

    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[RECALL], cl=17)
    for name, cells, expected in (('inside', spirit_bonds.ONE_MILE_FT // 5, True),
                                  ('outside', spirit_bonds.ONE_MILE_FT // 5 + 1, False)):
        engine = load(combat, tmp_path, mid).engine
        owner = engine.state.actors[LEFT]
        engine.state.actors[spirit].position = Position(x=int(owner.position.x) + cells, y=int(owner.position.y))
        distance = engine._distance_actor_to_actor(owner, engine.state.actors[spirit])
        assert (distance <= spirit_bonds.ONE_MILE_FT) is expected, (name, cells, distance)
        reachable = [s.entity_id for s in spirit_bonds._recallable(engine, owner, {'cl': 17})]
        assert (spirit in reachable) is expected, (name, distance, reachable)


def test_a_distant_spirit_is_not_hidden_and_an_unanswered_question_leaves_it(tmp_path, monkeypatch):
    """Finding 11's other half: beyond the printed range the table cannot see the spirit's surroundings, so the owner
    decides whether it is in a fight, and an unanswered question leaves it where it is. The eligible set is built in
    one pass, so a spirit the printed range does not reach is never hidden by one it does."""
    from combat.gate2_runtime_models import Position
    from combat.ext import spirit_bonds

    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[RECALL], cl=17)
    engine = load(combat, tmp_path, mid).engine
    owner = engine.state.actors[LEFT]
    engine.state.actors[spirit].position = Position(x=int(owner.position.x) + 1000, y=int(owner.position.y))
    assert engine._distance_actor_to_actor(owner, engine.state.actors[spirit]) > 120
    assert [s.entity_id for s in spirit_bonds._recallable(engine, owner, {'cl': 17})] == [spirit]
    # The one-mile question has no answerer in a read-only probe, and a spirit nobody answered about stays put.
    assert spirit_bonds._recalled(engine, owner, {'cl': 17}) == []
    # Inside the printed range the Cultivation Check is not asked at all: the spirit is simply recalled.
    engine.state.actors[spirit].position = Position(x=int(owner.position.x) + 3, y=int(owner.position.y))
    assert [s.entity_id for s in spirit_bonds._recalled(engine, owner, {'cl': 17})] == [spirit]


def test_a_hostile_within_command_range_means_the_spirit_is_in_combat(tmp_path, monkeypatch):
    """Finding 11: "if it is not in combat" reads the hostile summons too, not only primary combatants."""
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[RECALL], cl=17)
    from combat.gate2_runtime_models import Position
    from combat.ext import spirit_bonds
    engine = load(combat, tmp_path, mid).engine
    owner = engine.state.actors[LEFT]
    engine.state.actors[spirit].position = Position(x=owner.position.x + 200, y=owner.position.y)
    assert spirit_bonds._in_combat(engine, engine.state.actors[spirit]) is False
    engine.state.actors[RIGHT].position = Position(x=owner.position.x + 201, y=owner.position.y)
    assert spirit_bonds._in_combat(engine, engine.state.actors[spirit]) is True
    assert spirit not in [s.entity_id for s in spirit_bonds._recallable(engine, owner, {'cl': 17})]


def test_ai_spirit_recall_with_allies_and_enemies_nearby_moves_only_its_bond(tmp_path, monkeypatch):
    """A beneficial automatic pick remains on the owner's side even with both sides in range."""
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[RECALL], cl=17)
    before = load(combat, tmp_path, mid).engine
    owner = before.state.actors[LEFT]
    ally = before.state.actors[ALLY]
    enemy = before.state.actors[RIGHT]
    spirit_start = before.state.actors[spirit].position
    from combat.gate2_runtime_models import Position
    # Commit ordinary movement through the table, then cold-reload before Recall. This
    # makes a no-op Recall fail: the owner, rather than the fixture, creates the gap.
    menu = table.state(mid)['menu']
    move = next((row for row in menu['moves']
                 if before.grid.distance_ft(Position(**row['destination']), spirit_start) > 5
                 and before.grid.distance_ft(Position(**row['destination']), spirit_start) <= 120), None)
    assert move is not None, 'the table must offer a committed move that leaves the spirit in Recall range'
    moved = table.act(mid, move['candidate_id'], menu['decision_id'], menu['state_version'],
                      table.state(mid)['last_sequence'], [])
    assert moved['status'] == 'COMMITTED', moved
    before = load(combat, tmp_path, mid).engine
    owner = before.state.actors[LEFT]
    assert before._distance_actor_to_actor(owner, before.state.actors[spirit]) > 5
    # The stock yard puts the owner, a separate ally, an enemy, and the bonded spirit
    # within the printed 120-foot Foundation range. The enemy is deliberately a legal
    # perceived creature but never a recipient of a beneficial recall.
    assert before._distance_actor_to_actor(owner, ally) <= 120
    assert before._distance_actor_to_actor(owner, enemy) <= 120
    assert before._distance_actor_to_actor(owner, before.state.actors[spirit]) <= 120
    ally_position = (ally.position.x, ally.position.y)
    enemy_position = (enemy.position.x, enemy.position.y)

    result = _ai_step_choosing(combat, table, mid, LEFT,
                               lambda candidate: candidate.display_name == 'Spirit Recall')
    assert result['status'] == 'COMMITTED', result

    fresh = load(combat, tmp_path, mid)
    engine = fresh.engine
    owner, ally, enemy, recalled = (engine.state.actors[key] for key in (LEFT, ALLY, RIGHT, spirit))
    assert engine._distance_actor_to_actor(owner, recalled) <= 5
    recall_events = [e for e in engine.events if e.event_type == 'PASSIVE_TRIGGERED'
                     and e.source_definition_id.endswith(RECALL)
                     and spirit in e.target_ids
                     and 'folds through the bond' in str((e.payload or {}).get('log') or '')]
    assert recall_events, 'a successful Recall must record its source-bound movement event'
    assert (ally.position.x, ally.position.y) == ally_position
    assert (enemy.position.x, enemy.position.y) == enemy_position
    assert fresh.mechanical.replay()['status'] == 'PASS'


def test_spirit_recall_keeps_the_manual_destination_reminder():
    """Unsupported vessel, shrine, and hosted-body destinations remain visible in authority."""
    from combat.typed_numbers import authority_mechanics

    record = authority_mechanics().get(RECALL) or {}
    riders = record.get('riders') or []
    assert record.get('coverage') == 'CORE_WITH_RIDERS', record
    assert any(all(word in rider.lower() for word in ('vessel', 'shrine', 'hosted body', 'requires the gm'))
               for rider in riders), riders


# --------------------------------------------------------------------------- finding 12: the Pact's choices come from its own record
def test_the_pact_choices_are_read_from_the_talents_own_record(tmp_path, monkeypatch):
    from combat.ext import spirit_bonds
    from combat.typed_numbers import authority_mechanics

    choices = spirit_bonds._pact_choices()
    record = (authority_mechanics().get(PACT) or {}).get('effects') or []
    assert [key for key, _, _ in choices] == [row['choice'] for row in record], choices
    labels = {key: label for key, label, _ in choices}
    assert 'Bond Strain' in labels['strain'] and '{creature}' in labels['advantage']


# --------------------------------------------------------------------------- inertness
def test_a_character_outside_the_sphere_is_unaffected(tmp_path):
    combat, table, mid = table_fight(tmp_path, ['TAL_SWORD_DUAL_PRACTICE'], cl=17, ask=True, ally_talents=[])
    engine = combat._load_session(mid).engine
    names = {c.display_name for c in engine.legal_candidates()}
    assert not any('Seal' in name for name in names), names
    assert STRAIN not in engine.state.actors[LEFT].resources
    fresh = load(combat, tmp_path, mid)
    assert not any(row.condition_id in (SEALED, SUPPRESSED, VIOLENT_MARK)
                   for actor in fresh.engine.state.actors.values() for row in actor.conditions.values())
    assert fresh.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('cl', [1, 9, 17])
def test_every_spirit_companions_button_compiles_and_leaves_no_unrun_rider(tmp_path, cl):
    talents = [SEAL, COVENANT, MANIFESTATION, PAINFUL, PUNISH, VIOLENT, MERCY, CRUEL, POSTURE, NAME, RECALL,
               PACT, SHARED]
    combat, table, mid = table_fight(tmp_path, talents, cl=cl, ask=True, ally_talents=[])

    def call_spirit(engine):
        from combat import summons

        summons.summon(engine, engine.state.actors[LEFT], 'bonded_spirit', MANIFESTATION)

    # Battle Manifestation's spirit arrives with the fight in some CL bands, so call it in before the buttons are read:
    # "share senses with a bonded spirit" has no target to share with until one is on the map.
    undo = pytest.MonkeyPatch()
    on_hold(undo, call_spirit)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    engine = combat._load_session(mid).engine
    offered = [c.display_name for c in engine.legal_candidates()]
    missing = [name for name in SEAL_BUTTONS if not any(name in row for row in offered)]
    assert not missing, (missing, sorted(set(offered)))
    assert not [e for e in engine.events if e.event_type == 'GM_RIDER'
                and 'could not run' in str((e.payload or {}).get('rider') or '')], [
        (e.payload or {}).get('rider') for e in engine.events if e.event_type == 'GM_RIDER']
    assert CombatService(ROOT, tmp_path)._load_session(mid).mechanical.replay()['status'] == 'PASS'
    undo.undo()


def test_shared_senses_needs_a_spirit_to_share_with(tmp_path):
    """"you may share senses with a bonded spirit within 1 mile": a cultivator who has learned the bond but has no
    Bonded Spirit on the map gets no button."""
    shared = 'tianxia.talent.spirit_companions.shared_senses'
    combat, table, mid = table_fight(tmp_path, [SEAL, shared, MANIFESTATION], cl=17, ask=True, ally_talents=[])
    engine = combat._load_session(mid).engine
    assert not any(c.summon for c in engine.state.actors.values() if (c.summon or {}).get('owner') == LEFT)
    assert 'Shared Senses' not in {c.display_name for c in engine.legal_candidates()}
    # A cultivator who has not learned the sphere's bond keeps the ability exactly as it was.
    other, other_table, other_mid = table_fight(tmp_path / 'nobond', [SEAL, shared], cl=17, ask=True, ally_talents=[])
    assert 'Shared Senses' in {c.display_name for c in other._load_session(other_mid).engine.legal_candidates()}
    assert CombatService(ROOT, tmp_path)._load_session(mid).mechanical.replay()['status'] == 'PASS'

# =========================================================================== AUTO5r1f1: the review's findings, as regressions
def _free_cell_beside(combat, mid, spirit_id):
    """An in-bounds, unoccupied square next to ``spirit_id``, so a second binder can walk there and cast."""
    board = combat._load_session(mid).engine
    cell = board.state.actors[spirit_id].position
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (1, -1), (-1, 1)):
        spot = (cell.x + dx, cell.y + dy)
        if not board.grid.in_bounds(spot):
            continue
        if any(other.active and (other.position.x, other.position.y) == spot
               for other in board.state.actors.values()):
            continue
        return spot
    raise AssertionError(f'no free square beside {spirit_id}')


def _two_binders(tmp_path, monkeypatch, *, left_extra=(), ally_extra=()):
    """Left and the Ally are two independent binders of the sphere, both with a Bonded Spirit on the map.

    They are separate characters on the same side, so each one's Binding Seal is its own layer on whatever creature it
    seals: the case in which one binder's cleanup must not reach into the other's seal."""
    combat, table, mid = table_fight(tmp_path, [SEAL, COVENANT, MANIFESTATION, *left_extra], cl=17, ask=True,
                                     ally_talents=[SEAL, COVENANT, MANIFESTATION, *ally_extra])
    return combat, table, mid, SPIRIT


def _ally_seals_too(combat, table, mid, spirit):
    """Walk the Ally beside the sealed spirit and cast its own Binding Seal on it: a second layer."""
    spot = _free_cell_beside(combat, mid, spirit)
    advance_to(table, mid, ALLY)
    commit(cast_sender(combat, table, mid, f'Move to {spot[0]},{spot[1]}', at=spot))
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))


def _two_binders_with_distinct_dcs(tmp_path, *, caster_dc=16, ally_dc=19):
    """The same two-binder fight, but the two Cultivators' Cultivation Save DCs really differ.

    ``table_fight`` writes every fighter from one sheet, so both binders answered a Cultivation Check with the same
    number and no regression could say whose DC had been read (AUTO5r3 finding 2: the old case gave both binders DC
    16, so its own assertion could not have failed for the wrong binder). Here each sheet states its own
    ``technique_save_dc``, which is the field the compiled techniques' save DC comes from, so one rolled check can meet
    the caster's DC and miss the Ally's."""
    import zipfile

    from combat.gate5_service import CombatService
    from combat.tabletop import ButtonStore
    from combat.tabletop_service import TabletopService
    from tests.h1_support import sheet

    projects = (('11111111', 'Left', [SEAL, COVENANT, MANIFESTATION, MERCY], caster_dc),
                ('22222222', 'Ally', [SEAL, COVENANT, MANIFESTATION], ally_dc),
                ('33333333', 'Right', [], caster_dc))
    for project, name, owned, dc in projects:
        document = sheet(owned, cl=17, dc=dc)
        document['identity']['display_name'] = name
        folder = tmp_path / 'portable_characters' / project
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document))
    ButtonStore(tmp_path / 'tabletop_buttons').save_reactions('11111111', {'mode': 'ask'}, {'opportunity_attack'})
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({'display_name': 'Hunt6 yard', 'width_squares': 12, 'height_squares': 8,
                                'walls': [], 'starts': {'team1': [[3, 4], [3, 5]], 'team2': [[4, 4]]}})
    ids = [project for project, *_ in projects]
    mid = combat.create_factory_match(project_ids=ids[:2], opponent_actor_ids=[RIGHT],
                                      control_modes={actor: 'MANUAL' for actor in (LEFT, ALLY, RIGHT)},
                                      arena_id='battlefield:map.hunt6-yard',
                                      match_seed='HUNT6-TABLE')['match_id']
    table = TabletopService(combat, tmp_path)
    while table.state(mid)['menu']['actor_id'] != LEFT:
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
    return combat, table, mid, SPIRIT


def _seal_conditions(spirit):
    return [row for row in spirit.conditions.values() if row.condition_id == SEALED]


# --------------------------------------------------------------------------- finding 1: an enemy that strikes the binder earns the mark
def test_a_hostile_strike_on_the_binder_earns_the_mark_and_the_disadvantage(tmp_path, monkeypatch):
    """Finding 1 (AUTO5r1): "a spirit that has attacked you or your allies" is about the binder's side, so the ordinary
    case -- an enemy striking the binder -- is the one that must mark.

    The old code required the victim to share the ATTACKER's team, so a hostile blow never marked and friendly fire
    always did: exactly backwards. This is a real attack cast at the table, not an injected event, and the seal that
    follows it is really rolled at Disadvantage."""
    combat, table, mid = table_fight(tmp_path, [SEAL, COVENANT, MANIFESTATION, VIOLENT], cl=17, ask=True,
                                     ally_talents=[])
    fixed_dice(monkeypatch, [1] * 400)
    board = combat._load_session(mid).engine
    left, right = board.state.actors[LEFT], board.state.actors[RIGHT]
    assert right.team_id != left.team_id, 'the two sides must really be opposed'
    # The enemy strikes the Binder with its own printed attack, from the other side of the board.
    advance_to(table, mid, RIGHT)
    commit(cast_sender(combat, table, mid, 'Unarmed Strike', target=LEFT))
    fresh = load(combat, tmp_path, mid)
    struck = fresh.engine.state.actors[RIGHT]
    assert any(e.event_type == 'ATTACK_ROLLED' and e.actor_id == RIGHT and LEFT in (e.target_ids or ())
               for e in fresh.engine.events), 'the blow must really have been rolled at the table'
    assert any(row.condition_id == mark_id('Violent Ghost', LEFT) for row in struck.conditions.values()), [
        (row.condition_id, row.source_actor_id) for row in struck.conditions.values()]
    # And the mark is not decoration: the seal's saving throw really is resolved at Disadvantage.
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    advance_to(table, mid, LEFT)
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=RIGHT))
    fresh = load(combat, tmp_path, mid)
    save = next(e for e in fresh.engine.events if e.event_type == 'SAVE_ROLLED'
                and e.source_definition_id.endswith(SEAL))
    assert save.payload['mode'] == 'DISADVANTAGE' and save.payload['discarded'], save.payload
    assert fresh.mechanical.replay()['status'] == 'PASS'


def test_a_hostile_strike_on_the_binders_ally_earns_the_mark_too(tmp_path, monkeypatch):
    """Finding 1's other half: "you or your allies" is the whole side, not the binder's own body. An enemy striking
    the Binder's Ally marks the attacker for the Binder exactly as a strike on the Binder itself does."""
    combat, table, mid = table_fight(tmp_path, [SEAL, COVENANT, MANIFESTATION, VIOLENT], cl=17, ask=True,
                                     ally_talents=[])
    fixed_dice(monkeypatch, [1] * 400)
    board = combat._load_session(mid).engine
    assert board.state.actors[ALLY].team_id == board.state.actors[LEFT].team_id
    advance_to(table, mid, RIGHT)
    commit(cast_sender(combat, table, mid, 'Unarmed Strike', target=ALLY))
    fresh = load(combat, tmp_path, mid)
    struck = fresh.engine.state.actors[RIGHT]
    assert any(e.event_type == 'ATTACK_ROLLED' and e.actor_id == RIGHT and ALLY in (e.target_ids or ())
               for e in fresh.engine.events), 'a real blow at the table'
    assert any(row.condition_id == mark_id('Violent Ghost', LEFT) for row in struck.conditions.values()), [
        (row.condition_id, row.source_actor_id) for row in struck.conditions.values()]


def test_an_attack_by_a_third_party_on_a_side_with_no_binder_marks_nothing(tmp_path, monkeypatch):
    """The control for the tests above, and finding 3 (AUTO5r2): the old version of this test asserted that no such
    attack had happened, so it passed without ever striking anything.

    The printed words are "you or your allies", so the mark belongs to the VICTIM's side, not the attacker's. Here two
    real attacks are cast: the enemy strikes the Binder, who owns the talent, and is marked; then the Binder's Ally --
    a third party, neither the Binder nor the Binder's spirit -- strikes the enemy, whose side carries no Binder with
    this talent, and is marked by nobody. Without a real attack on each side the test could not tell the two apart."""
    combat, table, mid = table_fight(tmp_path, [SEAL, COVENANT, MANIFESTATION, VIOLENT], cl=17, ask=True,
                                     ally_talents=[])
    fixed_dice(monkeypatch, [1] * 400)
    advance_to(table, mid, RIGHT)
    commit(cast_sender(combat, table, mid, 'Unarmed Strike', target=LEFT))
    struck = load(combat, tmp_path, mid).engine
    assert any(e.event_type == 'ATTACK_ROLLED' and e.actor_id == RIGHT and LEFT in (e.target_ids or ())
               for e in struck.events), 'the enemy really struck the Binder'
    assert any(row.condition_id == mark_id('Violent Ghost', LEFT)
               for row in struck.state.actors[RIGHT].conditions.values()), \
        [(row.condition_id, row.source_actor_id) for row in struck.state.actors[RIGHT].conditions.values()]

    advance_to(table, mid, ALLY)
    commit(cast_sender(combat, table, mid, 'Unarmed Strike', target=RIGHT))
    fresh = load(combat, tmp_path, mid)
    engine = fresh.engine
    assert any(e.event_type == 'ATTACK_ROLLED' and e.actor_id == ALLY and RIGHT in (e.target_ids or ())
               for e in engine.events), 'the Ally really struck too'
    assert not any(row.condition_id.startswith('condition:typed.mark.violent_ghost')
                   for row in engine.state.actors[ALLY].conditions.values()), [
        (row.condition_id, row.source_actor_id) for row in engine.state.actors[ALLY].conditions.values()]
    assert fresh.mechanical.replay()['status'] == 'PASS'


# --------------------------------------------------------------------------- finding 2: the base seal has no exception of its own
def test_a_binder_without_painful_is_charged_for_a_taboo_broken_through_fear(tmp_path, monkeypatch):
    """Finding 2 (AUTO5r1): "each coercive command that violates the spirit's Nature or Taboo increases Bond Strain by 1"
    is the seal's own sentence and carries no exception. Only Painful Binding Seal's sentence excuses an order ("unless
    the command aligns with its Nature or the spirit fears a greater consequence").

    So a binder WITHOUT Painful who threatens a worse fate to get compliance still pays: the only answer the base
    seal offers is whether the order broke a Nature or a Taboo, and the label must not offer an out it does not have."""
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch)          # no Painful Binding Seal on this character
    fixed_dice(monkeypatch, [1] * 400)
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    before = load(combat, tmp_path, mid).engine.state.actors[LEFT].resources[STRAIN]
    prompts = commit(cast_sender(combat, table, mid, 'Command Bonded Spirit'), selections=choose('unwilling', 'violates'))
    labels = [o['label'] for p in prompts for o in p['choice']['options']]
    assert not any('fears a greater consequence' in label for label in labels), labels
    assert not any('Painful' in str(p) for p in prompts), 'this character owns no Painful Binding Seal'
    fresh = load(combat, tmp_path, mid)
    assert fresh.engine.state.actors[LEFT].resources[STRAIN] == before + 1, fresh.engine.state.actors[LEFT].resources


def test_the_base_seal_says_or_where_the_printing_says_or(tmp_path, monkeypatch):
    """The printed word is "Nature OR Taboo", so breaking either one is breaking the rule, and the option a player
    reads must not narrow that to both."""
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch)
    fixed_dice(monkeypatch, [1] * 400)
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    prompts = commit(cast_sender(combat, table, mid, 'Command Bonded Spirit'), selections=choose('unwilling', 'aligns'))
    labels = [o['label'] for p in prompts for o in p['choice']['options']]
    assert not any('Nature and Taboo' in label for label in labels), labels
    assert any('Nature or its Taboo' in label for label in labels), labels
    assert load(combat, tmp_path, mid).engine.state.actors[LEFT].resources[STRAIN] == 0, '"breaks neither" costs nothing'


def test_the_two_clauses_are_answered_separately(tmp_path, monkeypatch):
    """A character owning Painful Binding Seal answers the seal's own clause and that talent's own "unless" as two
    questions, because only the second one can excuse the order."""
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[PAINFUL])
    fixed_dice(monkeypatch, [1] * 400)
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    before = load(combat, tmp_path, mid).engine.state.actors[LEFT].resources[STRAIN]
    prompts = commit(cast_sender(combat, table, mid, 'Command Bonded Spirit'),
                     selections=choose('unwilling', 'violates', 'exempt'))
    titles = prompt_names(prompts)
    # Two Binding Seal questions (what the spirit did, then whether the order broke a Nature or a Taboo) and one
    # Painful Binding Seal question (its own printed "unless").
    assert titles.count('Binding Seal') == 2 and titles.count('Painful Binding Seal') == 1, titles
    fresh = load(combat, tmp_path, mid)
    # Only the seal's own clause was charged; Painful's printed "unless" was met, so it adds nothing.
    assert fresh.engine.state.actors[LEFT].resources[STRAIN] == before + 1, fresh.engine.state.actors[LEFT].resources


# --------------------------------------------------------------------------- finding 3: refusing is not serving unwillingly
def test_a_refusal_is_charged_nothing_for_service_and_may_be_punished(tmp_path, monkeypatch):
    """Finding 3 (AUTO5r1): Name-Binding charges "every time the standing command forces unwilling service". A spirit
    that refuses outright served nothing, so nothing may be charged for service -- but the refusal IS the disobedience
    Punishing Seal punishes, and it must be truthfully reachable.

    The old code had no refusal at all: both answers said the spirit served, so reaching the punishment meant claiming
    service that never happened and paying Name-Binding for it."""
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[NAME, PUNISH])
    fixed_dice(monkeypatch, [1] * 400)
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    before = load(combat, tmp_path, mid).engine.state.actors[LEFT].resources[STRAIN]
    prompts = commit(cast_sender(combat, table, mid, 'Command Bonded Spirit'),
                     selections=choose('refuses', 'aligns', 'punish'))
    titles = prompt_names(prompts)
    assert 'Punishing Seal' in titles, titles
    fresh = load(combat, tmp_path, mid)
    binder = fresh.engine.state.actors[LEFT]
    # Only Punishing Seal's own "Using this talent increases Bond Strain by 1": no service, no coercive clause, and
    # the seal's own clause was answered as breaking nothing.
    assert binder.resources[STRAIN] == before + 1, binder.resources
    damage = [e for e in fresh.engine.events if e.event_type == 'DAMAGE_COMMITTED'
              and e.source_definition_id.endswith(PUNISH)]
    assert len(damage) == 1 and damage[0].target_ids == (spirit,), damage
    assert binder.reaction_available is False


def test_a_refusal_the_seal_cannot_lawfully_enforce_costs_nothing(tmp_path, monkeypatch):
    """Finding 3's other half: Punishing Seal only reaches a command "that the seal can lawfully enforce". Answering
    that it cannot must spend no Reaction, deal no damage and charge no Bond Strain -- the printed limit, not a
    punishment the binder declined by reflex."""
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[NAME, PUNISH])
    fixed_dice(monkeypatch, [1] * 400)
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    before = load(combat, tmp_path, mid).engine.state.actors[LEFT].resources[STRAIN]
    prompts = commit(cast_sender(combat, table, mid, 'Command Bonded Spirit'),
                     selections=choose('refuses', 'aligns', 'not_enforceable'))
    labels = [o['label'] for p in prompts for o in p['choice']['options']]
    assert any('lawfully enforce' in label for label in labels), labels
    fresh = load(combat, tmp_path, mid)
    assert fresh.engine.state.actors[LEFT].resources[STRAIN] == before, fresh.engine.state.actors[LEFT].resources
    assert fresh.engine.state.actors[LEFT].reaction_available is True
    assert not [e for e in fresh.engine.events if e.source_definition_id.endswith(PUNISH)]


def test_an_unwilling_compliance_is_never_punished_for_disobedience(tmp_path, monkeypatch):
    """Finding 3: a spirit that served, however unwillingly, did not disobey. The punishment question must not appear at
    all, so no player can punish compliance."""
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[NAME, PUNISH])
    fixed_dice(monkeypatch, [1] * 400)
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    prompts = commit(cast_sender(combat, table, mid, 'Command Bonded Spirit'), selections=choose('unwilling', 'aligns'))
    titles = prompt_names(prompts)
    assert 'Punishing Seal' not in titles, titles
    fresh = load(combat, tmp_path, mid)
    assert not [e for e in fresh.engine.events if e.source_definition_id.endswith(PUNISH)]
    assert fresh.engine.state.actors[LEFT].reaction_available is True


def test_all_three_answers_to_the_service_question_are_truthful(tmp_path, monkeypatch):
    """Finding 3, as a menu: a player must be able to say the spirit served willingly, served unwillingly, or refused,
    and every label says plainly what that costs and whether there is anything to punish."""
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[NAME, PAINFUL, PUNISH])
    fixed_dice(monkeypatch, [1] * 400)
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    prompts = commit(cast_sender(combat, table, mid, 'Command Bonded Spirit'), selections=_obey())
    options = {o['id']: o['label'] for o in prompts[0]['choice']['options']}
    assert set(options) == {'willing', 'unwilling', 'refuses'}, options
    assert 'nothing to punish' in options['willing'] and 'nothing to punish' in options['unwilling'], options
    assert 'punishes' in options['refuses'] and 'never happened' in options['refuses'], options
    # Nothing at all is charged for a spirit that served willingly: only the seal taking hold.
    assert load(combat, tmp_path, mid).engine.state.actors[LEFT].resources[STRAIN] == 1


# --------------------------------------------------------------------------- finding 4: one binder never touches another's seal
def test_two_binders_each_hold_their_own_seal_on_one_spirit(tmp_path, monkeypatch):
    """The setup for the finding-4 regressions: two binders, two layers, two conditions on one creature."""
    combat, table, mid, spirit = _two_binders(tmp_path, monkeypatch)
    fixed_dice(monkeypatch, [1] * 400)
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    _ally_seals_too(combat, table, mid, spirit)
    sealed = load(combat, tmp_path, mid).engine.state.actors[spirit]
    assert len(_seal_conditions(sealed)) == 2, [row.instance_id for row in _seal_conditions(sealed)]
    assert {row.source_actor_id for row in _seal_conditions(sealed)} == {LEFT, ALLY}, [
        (row.condition_id, row.source_actor_id) for row in sealed.conditions.values()]


def test_dispelling_one_binders_seal_leaves_the_other_binders_clauses_intact(tmp_path, monkeypatch):
    """Finding 4 (AUTO5r1): a mark cleared by any means takes only ITS OWN binder's condition with it.

    ``CombatEngine._remove_condition`` clears every instance of a condition id, so one binder's dispel used to dissolve
    the second binder's whole seal while its mark still stood: the spirit kept the mark and lost the clauses that mark
    enforces (it could suddenly attack its binder, and walk out of the bond)."""
    combat, table, mid, spirit = _two_binders(tmp_path, monkeypatch)
    fixed_dice(monkeypatch, [1] * 400)
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    _ally_seals_too(combat, table, mid, spirit)

    def dispel_left(engine):
        from combat.ext.rider_support import remove_instance

        subject = engine.state.actors[spirit]
        for key, row in list(subject.conditions.items()):
            if row.condition_id == mark_id('Binding Seal', LEFT):
                remove_instance(engine, subject, key, 'system:test.dispel')

    on_hold(monkeypatch, dispel_left)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    sealed = load(combat, tmp_path, mid).engine.state.actors[spirit]
    assert [row.source_actor_id for row in _seal_conditions(sealed)] == [ALLY], [
        (row.condition_id, row.source_actor_id) for row in sealed.conditions.values()]
    assert not any(row.condition_id == mark_id('Binding Seal', LEFT) for row in sealed.conditions.values())
    assert any(row.condition_id == mark_id('Binding Seal', ALLY) for row in sealed.conditions.values())
    # The surviving clauses are real, not merely stored: the spirit still may not attack the binder that holds it.
    engine = load(combat, tmp_path, mid).engine
    assert _strike_targets(engine, engine.state.actors[spirit], ALLY) is False
    assert _strike_targets(engine, engine.state.actors[spirit], LEFT) is True
    assert load(combat, tmp_path, mid).mechanical.replay()['status'] == 'PASS'


def test_re_binding_does_not_wipe_the_other_binders_seal(tmp_path, monkeypatch):
    """Finding 4 again, on the refresh path: the same binder sealing again replaces only its own layer."""
    combat, table, mid, spirit = _two_binders(tmp_path, monkeypatch)
    fixed_dice(monkeypatch, [1] * 400)
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    _ally_seals_too(combat, table, mid, spirit)
    advance_to(table, mid, LEFT)
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    sealed = load(combat, tmp_path, mid).engine.state.actors[spirit]
    held = _seal_conditions(sealed)
    assert sorted(row.source_actor_id for row in held) == sorted([ALLY, LEFT]), [
        (row.condition_id, row.source_actor_id) for row in sealed.conditions.values()]
    assert len(held) == 2, [row.instance_id for row in held]
    engine = load(combat, tmp_path, mid).engine
    assert _strike_targets(engine, engine.state.actors[spirit], ALLY) is False
    assert _strike_targets(engine, engine.state.actors[spirit], LEFT) is False


def test_exorcists_mercy_removes_one_layer_and_leaves_the_other_binders_seal(tmp_path, monkeypatch):
    """Finding 4's Mercy half: "remove one layer of a Binding Seal if the spirit wants to leave" removes ONE binder's
    seal. The old code removed every binder's mark and condition, so a spirit held by two cultivators was freed from
    both by one exorcism -- twice the printed outcome."""
    combat, table, mid, spirit = _two_binders(tmp_path, monkeypatch, left_extra=[MERCY])
    scripted_dice(monkeypatch, seal_then(20))   # every seal takes hold; every Cultivation Check is won
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    _ally_seals_too(combat, table, mid, spirit)
    assert len(_seal_conditions(load(combat, tmp_path, mid).engine.state.actors[spirit])) == 2, 'two layers to begin with'
    advance_to(table, mid, LEFT)
    commit(cast_sender(combat, table, mid, 'Exorcist', contains='One layer of the Binding Seal on this creature ends', target=spirit))
    sealed = load(combat, tmp_path, mid).engine.state.actors[spirit]
    assert not any(row.condition_id == mark_id('Binding Seal', LEFT) for row in sealed.conditions.values())
    assert any(row.condition_id == mark_id('Binding Seal', ALLY) for row in sealed.conditions.values()), [
        (row.condition_id, row.source_actor_id) for row in sealed.conditions.values()]
    assert [row.source_actor_id for row in _seal_conditions(sealed)] == [ALLY], [
        (row.condition_id, row.source_actor_id) for row in sealed.conditions.values()]
    engine = load(combat, tmp_path, mid).engine
    assert _strike_targets(engine, engine.state.actors[spirit], ALLY) is False, 'the remaining seal still binds'
    assert load(combat, tmp_path, mid).mechanical.replay()['status'] == 'PASS'


def test_exorcists_mercy_says_which_binder_it_released_and_how_many_remain(tmp_path, monkeypatch):
    """Finding 4, as a player sees it: the line names the binder whose seal went and says another still holds, so a
    one-layer release never reads as "the Binding Seal is broken"."""
    combat, table, mid, spirit = _two_binders(tmp_path, monkeypatch, left_extra=[MERCY])
    scripted_dice(monkeypatch, seal_then(20))
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    _ally_seals_too(combat, table, mid, spirit)
    advance_to(table, mid, LEFT)
    commit(cast_sender(combat, table, mid, 'Exorcist', contains='One layer of the Binding Seal on this creature ends', target=spirit))
    fresh = load(combat, tmp_path, mid)
    notes = [str(e.payload.get('log') or '') for e in fresh.engine.events if e.event_type == 'PASSIVE_TRIGGERED']
    mercy = [line for line in notes if 'Exorcist' in line and 'Binding Seal' in line]
    assert mercy, notes[-12:]
    assert 'one layer' in mercy[-1] and '1 other binder' in mercy[-1], mercy[-1]
    # Finding 4 (AUTO5r2): whatever a binder is called here, it is called by name. No entity id ever reaches a player.
    assert 'actor:' not in mercy[-1] and RIGHT not in mercy[-1], mercy[-1]
# --------------------------------------------------------------------------- finding 1: Help really delivers the Advantage it costs a Reaction for
def _pact_asked_after_a_real_blow(tmp_path, monkeypatch, folder, *, reach_ft=None, spirit_blow_asks=False, dice=None):
    """Pact-Brother Battle Rhythm really asked of a Binder at the table, positioned for the Help branch.

    This is the printed order: the Binder commands its Bonded Spirit, the spirit strikes a creature, and then the
    Binder strikes that same creature on its own next turn -- "when you damage a creature that your spirit damaged
    since the start of your last turn". A commanded spirit takes a real turn (an uncommanded one passes by itself),
    so this is an honest table path rather than a direct call into the plug-in. The spirit is put next to the creature
    so a strike is in reach and Help (which needs a partner within 5 feet) is on offer.

    ``reach_ft`` patches the movement row of the record, which is how the movement choice's reach is shown to come
    out of the data rather than a constant typed beside it. ``dice`` supplies ``scripted_dice``'s per-intent chooser
    where a case needs to steer one intent's dice. ``spirit_blow_asks`` plays the printed trigger the other way round
    -- the Binder strikes first, so it is the spirit's blow that asks, on the spirit's own turn, and Help's window
    (5.5e: "before the start of the spirit's next turn") therefore reaches the Binder's NEXT turn. The fixture still
    returns with the Binder's turn open, on the round after the Pact asked."""
    from combat.typed_numbers import authority_mechanics

    if reach_ft is not None:
        original = authority_mechanics()

        def wider(*_args, **_kwargs):
            pact = dict(original[PACT])
            pact['effects'] = [dict(row, distance_ft=reach_ft) if row.get('choice') == 'move' else dict(row)
                               for row in pact['effects']]
            return {**original, PACT: pact}

        monkeypatch.setattr('combat.typed_numbers.authority_mechanics', wider)

    combat, table, mid, spirit = sealer(tmp_path / folder, monkeypatch, extra=[PACT])
    if dice is None:
        fixed_dice(monkeypatch, [15] * 400)      # blows that land: the Pact reads a real damage event
    else:
        scripted_dice(monkeypatch, dice)
    if spirit_blow_asks:
        commit(cast_sender(combat, table, mid, 'Unarmed Strike', target=RIGHT), selections=choose('advantage'))
    commit(cast_sender(combat, table, mid, 'Command Bonded Spirit'), selections=_obey())
    advance_to(table, mid, SPIRIT)
    spot = _free_cell_beside(combat, mid, RIGHT)
    commit(cast_sender(combat, table, mid, f'Move to {spot[0]},{spot[1]}', at=spot))
    commit(cast_sender(combat, table, mid, 'Companion Strike', target=RIGHT),
           selections=choose('help') if spirit_blow_asks else None)
    advance_to(table, mid, LEFT)
    return combat, table, mid, tmp_path / folder


def _help_modifier(binder):
    return [m for m in binder.modifiers.values()
            if m.target_field == 'attack_mode_vs' and m.value == f'ADVANTAGE:{RIGHT}']


def _help_applied(events):
    """The Modifier events the Pact wrote for Help, in order: (event, payload) pairs."""
    return [(e.event_type, e.payload) for e in events
            if e.source_definition_id == PACT and e.event_type in ('MODIFIER_APPLIED', 'MODIFIER_REMOVED')]


def _binder_rolls(engine, binder=LEFT):
    """Every attack roll the Binder made against the foe, in order: (sequence, payload) pairs."""
    return [(e.sequence, e.payload) for e in engine.events
            if e.event_type == 'ATTACK_ROLLED' and e.actor_id == binder and RIGHT in (e.target_ids or ())]


def _advance_to_spirit_turn(combat, root, table, mid, number):
    """End turns until the Bonded Spirit has begun the turn with that number.

    An uncommanded Bonded Spirit's turn passes by itself (documented behaviour), so the table never opens a menu for
    it and "wait until the table offers the spirit its turn" would never stop; the spirit's own turn counter is what
    says the boundary has come."""
    while load(combat, root, mid).engine.state.actors[SPIRIT].turns_started < number:
        assert act(table, mid, 'end')['status'] == 'COMMITTED'


def test_the_spirits_help_really_grants_advantage_and_ends_at_the_printed_edge(tmp_path, monkeypatch):
    """Finding 1 (AUTO5r2): Help spent the spirit's Reaction and the Pact's round use and then the delivery raised
    TypeError before the Advantage was ever written -- ``_pact_expiry`` requires its ``expires_on`` answer and this
    branch never passed one, while the hook dispatcher skips a callback that raises. The player paid twice for nothing.

    So the printed outcome is asserted through the table and after a reload: the Advantage is really written, it is
    aimed at the creature the choice named, its window is the start of the spirit's own next turn (5.5e Help) under a
    name the engine removes by itself, and both costs are really paid."""
    from combat.ext import effect_durations

    combat, table, mid, root = _pact_asked_after_a_real_blow(tmp_path, monkeypatch, 'help')
    before = load(combat, root, mid).engine
    spirit = before.state.actors[SPIRIT]
    assert spirit.reaction_available is True, 'the spirit must start with the Reaction Help costs'
    expected_edge = effect_durations.token('start', SPIRIT, int(spirit.turns_started) + 1)

    prompts = commit(cast_sender(combat, table, mid, 'Unarmed Strike', target=RIGHT), selections=choose('help'))
    assert any('Help' in str(o.get('label') or '') for p in prompts for o in p['choice']['options']), \
        [str(o.get('label')) for p in prompts for o in p['choice']['options']]

    fresh = load(combat, root, mid)
    applied = [payload for kind, payload in _help_applied(fresh.engine.events) if kind == 'MODIFIER_APPLIED']
    assert len(applied) == 1, _help_applied(fresh.engine.events)
    assert applied[0]['target_field'] == 'attack_mode_vs', applied[0]
    assert applied[0]['value'] == f'ADVANTAGE:{RIGHT}', applied[0]
    assert applied[0]['expires_on'] == expected_edge, (applied[0]['expires_on'], expected_edge)
    assert effect_durations.parse(applied[0]['expires_on']) == ('start', SPIRIT, int(spirit.turns_started) + 1), \
        'the Help window must be an expiry name the engine removes by itself'
    assert fresh.engine.state.actors[SPIRIT].reaction_available is False, 'Help costs the spirit its Reaction'
    assert fresh.engine.state.actors[LEFT].turn_flags.get('spirit_pact_round_used') == \
        str(fresh.engine.state.round_number), 'the Pact is once per round'
    assert fresh.mechanical.replay()['status'] == 'PASS'


def test_the_help_advantage_survives_the_blow_that_asked_for_it_and_ends_at_the_printed_edge(tmp_path, monkeypatch):
    """Finding 1 (AUTO5r3): Help cost the spirit its Reaction, the Binder's round use and a real "your NEXT attack
    roll against that creature", and the delivery spent all three on nothing. The modifier is the Vex shape, which the
    engine hands to the first attack roll made against that creature AFTER it is written -- and the roll that asked for
    Help had already been made, so the very blow that asked had it applied and then CONSUMED, exactly as the report
    recorded. The old test pinned that removal in place, so it passed while the printed promise went unmet.

    This is the Binder's own blow asking, at the table, committed and reloaded: the roll that asked keeps its ordinary
    mode, the Help is still on the Binder when the action is saved, and what finally takes it away is the engine's own
    expiry at the start of the spirit's next turn (5.5e Help) -- under the printed window, recorded as an expiry and not
    as a spend. Nothing here can pass while the asking blow eats its own benefit."""
    from combat.ext import effect_durations
    from combat.gate2_engine import SYSTEM_EXPIRATION

    combat, table, mid, root = _pact_asked_after_a_real_blow(tmp_path, monkeypatch, 'helpsurvives')
    edge = effect_durations.token('start', SPIRIT, 2)   # the spirit has taken one turn; its next begins round 2
    commit(cast_sender(combat, table, mid, 'Unarmed Strike', target=RIGHT), selections=choose('help'))

    fresh = load(combat, root, mid)
    asking = _binder_rolls(fresh.engine)[-1][1]
    assert asking['mode'] == 'NORMAL', 'the blow that asked for Help keeps its own ordinary roll'
    granted = _help_modifier(fresh.engine.state.actors[LEFT])
    assert len(granted) == 1, 'the Help asked for must survive the attack that asked for it'
    assert granted[0].expires_on == edge, (granted[0].expires_on, edge)
    assert _binder_rolls(fresh.engine)[-1][1]['mode'] == 'NORMAL', 'and must not be spent by the roll already made'
    assert fresh.engine.state.actors[SPIRIT].reaction_available is False, 'Help costs the spirit its Reaction'

    _advance_to_spirit_turn(combat, root, table, mid, 2)
    fresh = load(combat, root, mid)
    assert _help_modifier(fresh.engine.state.actors[LEFT]) == [], \
        "unused Help must not outlive the start of the spirit's next turn"
    ended = [e for e in fresh.engine.events if e.event_type == 'MODIFIER_REMOVED'
             and (e.payload or {}).get('modifier_id') == granted[0].modifier_id]
    assert [(e.source_definition_id, (e.payload or {}).get('checkpoint'), (e.payload or {}).get('reason'))
            for e in ended] == [(SYSTEM_EXPIRATION, 'START_OF_TURN', None)], \
        [(e.source_definition_id, e.payload) for e in ended]
    # nothing was rolled against that creature after the Help was written, so no roll could have spent it
    written = min(e.sequence for e in fresh.engine.events
                  if e.event_type == 'MODIFIER_APPLIED' and e.source_definition_id == PACT)
    assert [sequence for sequence, payload in _binder_rolls(fresh.engine) if sequence > written] == []
    assert fresh.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('use_next', [True, False])
def test_late_attached_damage_help_survives_reload_and_next_roll(tmp_path, monkeypatch, use_next):
    """SOLFAUTO5r4: primary damage is reduced to zero; a late attached hit packet asks for Help.

    The asking strike is a real table action. After commit/reload, a synthetic additional strike inside an accepted
    Hold action probes the next roll on this same turn (without adding an unrelated extra-action talent). Both
    actions use the normal executor, transaction, event recording and replay. The other case leaves Help unused.
    """
    from combat import typed_executor as te
    from combat.ext import effect_durations, spirit_bonds

    combat, table, mid, root = _pact_asked_after_a_real_blow(tmp_path, monkeypatch, 'latehelp')
    original = te._block_attack_in_chain
    original_dice = te._damage_dice

    def zero_primary(ctx, dice, effect=None, kinds=None):
        dice = original_dice(ctx, dice, effect, kinds)
        if ctx.actor.entity_id == LEFT and effect is None and isinstance(dice, te.DiceSpec):
            return dice.model_copy(update={'modifier': -100})
        return dice

    def attached(ctx, effect):
        if ctx.actor.entity_id == LEFT:
            effect = {**effect, 'count': 1, 'count_by_cl': [], 'on_hit': [*(effect.get('on_hit') or []),
                {'type': 'damage', 'flat': 3, 'damage_types': ['force'], 'applies_to': 'target',
                 'damage_bonus_packet': True}]}
        return original(ctx, effect)

    monkeypatch.setattr(te, '_damage_dice', zero_primary)
    monkeypatch.setattr(te, '_block_attack_in_chain', attached)
    edge = effect_durations.token('start', SPIRIT, 2)
    before_sequence = load(combat, root, mid).engine.events[-1].sequence
    commit(cast_sender(combat, table, mid, 'Unarmed Strike', target=RIGHT), selections=choose('help'))
    fresh = load(combat, root, mid)
    damage = [e.payload for e in fresh.engine.events if e.sequence > before_sequence
              and e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == LEFT and RIGHT in e.target_ids]
    assert len(damage) == 2 and damage[0]['hp_damage'] == 0 and damage[1]['hp_damage'] > 0, damage
    assert _binder_rolls(fresh.engine)[-1][1]['mode'] == 'NORMAL'
    granted = _help_modifier(fresh.engine.state.actors[LEFT])
    assert len(granted) == 1, 'late Help must be installed before this action commits'
    assert granted[0].expires_on == edge
    assert spirit_bonds.PACT_HELP not in fresh.engine.state.actors[LEFT].turn_flags
    assert fresh.engine.state.actors[SPIRIT].reaction_available is False
    assert fresh.engine.state.actors[LEFT].turn_flags[spirit_bonds.PACT_USED] == str(fresh.engine.state.round_number)
    assert fresh.mechanical.replay()['status'] == 'PASS'

    if use_next:
        def extra_strike(engine):
            from tests.h1_support import script

            script(engine, [1, 20] + [15] * 400)
            actor, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
            action = next(a for a in engine.action_catalog.values()
                          if a.owner_id == LEFT and a.display_name == 'Unarmed Strike')
            typed = action.parameters['typed']
            ctx = te.Context(engine, actor, action, None, typed, [target], target)
            te.run_effects(ctx, typed['effects'])

        on_hold(monkeypatch, extra_strike)
        assert act(table, mid, HOLD)['status'] == 'COMMITTED'
        fresh = load(combat, root, mid)
        roll = _binder_rolls(fresh.engine)[-1][1]
        assert roll['mode'] == 'ADVANTAGE' and roll['dice'] == [1, 20] and roll['discarded'] == [1], roll
        assert roll['provisional_hit'] is True
        removed = [e.payload for e in fresh.engine.events if e.event_type == 'MODIFIER_REMOVED'
                   and e.payload.get('modifier_id') == granted[0].modifier_id]
        assert [p.get('reason') for p in removed] == ['CONSUMED'], removed
    else:
        _advance_to_spirit_turn(combat, root, table, mid, 2)
        fresh = load(combat, root, mid)
        removed = [e.payload for e in fresh.engine.events if e.event_type == 'MODIFIER_REMOVED'
                   and e.payload.get('modifier_id') == granted[0].modifier_id]
        assert [p.get('checkpoint') for p in removed] == ['START_OF_TURN'], removed
    assert _help_modifier(fresh.engine.state.actors[LEFT]) == []
    assert fresh.mechanical.replay()['status'] == 'PASS'


def test_the_help_advantage_benefits_the_next_attack_roll(tmp_path, monkeypatch):
    """Finding 1's other half (AUTO5r3), played in the printed order that leaves the benefit a turn to land in: the
    Binder strikes the creature, the spirit strikes it next, so the Pact asks on the spirit's own turn and Help's
    window -- "before the start of the spirit's next turn" -- covers the Binder's next turn.

    The dice decide the case: on that turn the Binder rolls 1 and 20, and 1 + 6 is under the foe's Armour Class while
    20 + 6 is over it, so the second blow can only land if the roll really was made with Advantage. The Help is then
    spent by that roll, and the pact asks again on it, so the whole printed outcome is read back from the saved fight."""
    def dice_for(engine, source):
        # The Binder's own turn from the round after the Pact asked: 1 and 20, a blow only Advantage can land.
        if engine.state.current_actor_id == LEFT and int(engine.state.round_number) >= 2:
            return [1, 20] + [15] * 400
        return [15] * 400

    combat, table, mid, root = _pact_asked_after_a_real_blow(tmp_path, monkeypatch, 'helpnext', spirit_blow_asks=True,
                                                            dice=dice_for)
    fresh = load(combat, root, mid)
    help_id = [m.modifier_id for m in _help_modifier(fresh.engine.state.actors[LEFT])]
    assert len(help_id) == 1, "the Help asked for on the spirit's turn must still be there on the Binder's next turn"
    assert fresh.engine.state.actors[SPIRIT].reaction_available is False, 'Help costs the spirit its Reaction'

    foe_hp = fresh.engine.state.actors[RIGHT].current_hp
    prompts = commit(cast_sender(combat, table, mid, 'Unarmed Strike', target=RIGHT), selections=choose('advantage'))
    assert prompts, "the Pact asks again on the Binder's own blow this round"

    fresh = load(combat, root, mid)
    rolls = _binder_rolls(fresh.engine)
    benefiting = rolls[-1][1]
    assert benefiting['mode'] == 'ADVANTAGE', benefiting
    assert benefiting['dice'] == [1, 20] and benefiting['discarded'] == [1], benefiting
    assert benefiting['provisional_hit'] is True, 'the second blow lands only because of the Help'
    assert fresh.engine.state.actors[RIGHT].current_hp < foe_hp, 'and it really took damage off the foe'
    # the Help is spent by the roll that used it, and only that
    removals = [payload for kind, payload in _help_applied(fresh.engine.events)
                if kind == 'MODIFIER_REMOVED' and payload.get('modifier_id') == help_id[0]]
    assert [payload.get('reason') for payload in removals] == ['CONSUMED'], removals
    assert _help_modifier(fresh.engine.state.actors[LEFT]) == [], 'the spent Help is gone from the saved fight'
    assert fresh.mechanical.replay()['status'] == 'PASS'


# --------------------------------------------------------------------------- finding 5: the Pact's numbers come out of its own record
def test_pact_delivery_reads_its_numbers_from_the_row():
    """Finding 5 (AUTO5r1): ``_pact_feet`` and ``_pact_strain`` are a view on the row the player chose, so the record
    is the single source of truth -- editing ``distance_ft`` or ``flat`` changes what the table does, and no number is
    left typed a second time beside the plug-in. ``_pact_expiry`` is checked here too, because a row that states
    nothing it can read must fall back on the answer the caller supplies rather than raise: the Help branch passes
    the start of the spirit's next turn, and forgetting to (finding 1) silently cost the player the whole outcome."""
    from combat.ext import spirit_bonds
    from combat.typed_numbers import authority_mechanics

    rows = {key: data for key, _, data in spirit_bonds._pact_choices()}
    record = {row['choice']: row for row in (authority_mechanics().get(PACT) or {}).get('effects') or []}
    assert set(rows) == set(record), (sorted(rows), sorted(record))
    for key, data in rows.items():
        assert spirit_bonds._pact_feet(data) == int(record[key]['distance_ft']), key
        assert spirit_bonds._pact_strain(data) == int(record[key]['flat']), key
    # A changed mechanical parameter is what runs, rather than a constant that happens to match today.
    assert spirit_bonds._pact_feet({**rows['move'], 'distance_ft': 15}) == 15
    assert spirit_bonds._pact_strain({**rows['strain'], 'flat': -2}) == -2
    # The shipped values are still the printed ones.
    assert spirit_bonds._pact_feet(rows['move']) == 10
    assert spirit_bonds._pact_strain(rows['strain']) == -1

    class _Spirit:
        entity_id = SPIRIT
        turns_started = 4

    spirit = _Spirit()
    from combat.ext import effect_durations
    # The Help row's own duration is read, and it names the start of the spirit's next turn.
    assert spirit_bonds._pact_expiry(rows['help'], 'start', expires_on='FALLBACK', spirit=spirit) == \
        effect_durations.token('start', SPIRIT, 5)
    # A row that states nothing this helper can read answers with what the caller supplied -- it never raises, because
    # a TypeError here is swallowed by the hook dispatcher and the player simply loses the printed benefit.
    assert spirit_bonds._pact_expiry({}, 'start', expires_on='FALLBACK', spirit=spirit) == 'FALLBACK'
    assert spirit_bonds._pact_expiry(rows['help'], 'start', expires_on='FALLBACK') == 'FALLBACK'


def test_a_changed_pact_record_reaches_the_squares_the_table_is_offered(tmp_path, monkeypatch):
    """Finding 3 (AUTO5r2) replaces a test that called ``free_cells`` itself and so could not tell a record-driven
    reach from a hardcoded 10 feet: it never asked for the movement choice. Here the choice is really taken through
    the table, the squares are read off the prompt the table was given (so the offered set is the one a player would
    have seen) AND the chosen square is read back off the saved fight as the Binder's committed position.

    A record patched to 15 feet offers squares a 10-foot reach never does, the furthest square offered is the one the
    Binder ends up standing on after a reload, and the fight replays."""
    def offered_squares(folder, reach_ft):
        combat, table, mid, root = _pact_asked_after_a_real_blow(tmp_path, monkeypatch, folder, reach_ft=reach_ft)
        prompts = []

        def feet_of(label):
            found = re.search(r'\((\d+) ft\)', str(label or ''))
            return int(found.group(1)) if found else None

        def take(prompt):
            prompts.append(prompt)
            ids = [o['id'] for o in prompt['choice']['options']]
            feet = {o['id']: feet_of(o.get('label')) for o in prompt['choice']['options']}
            feet = {i: f for i, f in feet.items() if f is not None}
            if 'advantage' in ids:                     # the four printed choices: take the movement one
                return 'move', True
            if set(ids) <= {LEFT, SPIRIT}:             # whose move: the Binder's
                return LEFT, True
            return max(feet, key=lambda i: (feet[i], i)), True   # the furthest square offered

        commit(cast_sender(combat, table, mid, 'Unarmed Strike', target=RIGHT), selections=take)
        steps = [p for p in prompts if any(re.search(r'\((\d+) ft\)', str(o.get('label') or ''))
                                         for o in p['choice']['options'])]
        assert len(steps) == 1, [(str(p.get('title')), [str(o.get('label')) for o in p['choice']['options']])
                                 for p in prompts]
        offered = [(o['id'], int(re.search(r'\((\d+) ft\)', str(o.get('label') or '')).group(1)))
                   for o in steps[0]['choice']['options']
                   if re.search(r'\((\d+) ft\)', str(o.get('label') or ''))]
        furthest = max(feet for _, feet in offered)
        chosen = max((cell for cell, feet in offered if feet == furthest), key=str)   # the answer's own tie-break
        fresh = load(combat, root, mid)
        moved = fresh.engine.state.actors[LEFT].position
        assert f'cell:{moved.x},{moved.y}' == chosen, (chosen, moved)   # the square chosen is where the Binder stands
        assert fresh.mechanical.replay()['status'] == 'PASS'
        return offered

    narrow = offered_squares('ten', None)
    wide = offered_squares('fifteen', 15)
    assert max(feet for _, feet in wide) > 10, 'the movement choice reached past a hardcoded 10 feet'
    assert max(feet for _, feet in narrow) <= 10, 'the shipped record is still the printed 10 feet'
    assert {cell for cell, _ in wide} > {cell for cell, _ in narrow}, \
        'a 15-foot record offered nothing a 10-foot record could not reach'



# --------------------------------------------------------------------------- finding 6: an AI binder really decides, and a player really is asked
def _commands_the_bonded_spirit(candidate):
    return 'Command Bonded Spirit' in candidate.display_name and candidate.actor_id == LEFT


def test_an_ai_controlled_binder_answers_the_printed_questions_itself(tmp_path, monkeypatch):
    """Finding 6 (AUTO5r1): reactor membership was all the old test proved -- it executed no command at all. Here the
    Binder is handed to the AI and then really casts the printed order: the action commits in one call with nobody
    pausing to answer, and the saved fight holds the result of the AI's own decisions."""
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[PAINFUL])
    scripted_dice(monkeypatch, seal_then(1))
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    advance_to(table, mid, LEFT)
    result = _ai_step_choosing(combat, table, mid, LEFT, _commands_the_bonded_spirit)
    assert result['status'] == 'COMMITTED', result   # no REACTION_REQUIRED: the AI binder answered for itself
    fresh = load(combat, tmp_path, mid)
    assert any(e.event_type == 'SUMMONS_COMMANDED' and spirit in (e.target_ids or ()) for e in fresh.engine.events)
    assert fresh.mechanical.replay()['status'] == 'PASS'


def test_the_same_order_pauses_for_a_player_controlled_binder_and_not_for_an_ai_one(tmp_path, monkeypatch):
    """Finding 6 as a contrast: the same fight, the same order, two control modes. A Binder a player controls is asked
    all four printed questions; the same Binder under the AI decides for itself and its action commits in one call.
    This is the behaviour, not the reactor set."""
    asked, asked_table, asked_mid, asked_spirit = sealer(tmp_path / 'ask', monkeypatch, extra=[PAINFUL, PUNISH])
    fixed_dice(monkeypatch, [1] * 400)
    commit(cast_sender(asked, asked_table, asked_mid, 'Binding Seal', target=asked_spirit))
    prompts = commit(cast_sender(asked, asked_table, asked_mid, 'Command Bonded Spirit'),
                     selections=choose('refuses', 'violates', 'strained', 'punish'))
    assert prompt_names(prompts) == ['Binding Seal', 'Binding Seal', 'Painful Binding Seal', 'Punishing Seal'], \
        prompt_names(prompts)
    assert load(asked, tmp_path / 'ask', asked_mid).engine.state.actors[asked_spirit].conditions, 'the seal stands'

    auto, auto_table, auto_mid, auto_spirit = sealer(tmp_path / 'auto', monkeypatch, extra=[PAINFUL, PUNISH])
    fixed_dice(monkeypatch, [1] * 400)
    commit(cast_sender(auto, auto_table, auto_mid, 'Binding Seal', target=auto_spirit))
    assert act(auto_table, auto_mid, 'end')['status'] == 'COMMITTED'
    advance_to(auto_table, auto_mid, LEFT)
    assert _ai_step_choosing(auto, auto_table, auto_mid, LEFT, _commands_the_bonded_spirit)['status'] == 'COMMITTED', \
        'an AI Binder is never asked, so its turn must not wait for a player'
    assert load(auto, tmp_path / 'auto', auto_mid).mechanical.replay()['status'] == 'PASS'


def test_a_player_controlled_binder_owns_the_choice_seam_the_off_turn_ask_rides_on(tmp_path, monkeypatch):
    """Checklist 9, the seam that would carry an off-turn ask: ``choice_owner`` is what puts a manual Binder's printed
    decisions in front of a player while another creature acts, and an AI holder stays automatic. Asserted on the
    compiled rows and on the reactor set the service actually reads -- reactor membership alone cannot show that a
    question would ever be put."""
    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[PAINFUL, PUNISH])
    engine = combat._load_session(mid).engine
    rows = [row for owned in (engine.typed_passive_rows or {}).values() for row in owned
            if row.get('block') == 'spirit_seal']
    assert rows and all(row.get('choice_owner') is True for row in rows), [
        (row.get('feature_id'), row.get('kind'), row.get('choice_owner')) for row in rows]
    # A Binder a player controls in this fight is one of the actors the table pauses for, which is what puts its
    # printed questions in front of a player even while another creature acts.
    assert LEFT in engine.typed_ask_reactors, sorted(engine.typed_ask_reactors)


# --------------------------------------------------------------------------- finding 2: the check and the release must name the same layer
def test_mercy_is_checked_against_the_very_layer_it_breaks(tmp_path, monkeypatch):
    """Finding 2 (AUTO5r2), made failable (AUTO5r3): ``seal_binder_dc`` answered with the FIRST binder in condition
    order while the release removed the caster's own layer, so a spirit held by two cultivators could be released by a
    check against a number that was not on the layer that went -- and refused, the same way.

    Two things made the earlier version of this case unable to fail for that bug, and both are fixed here. The Ally,
    who does NOT cast, seals FIRST and the Binder who casts seals second, so "first binder in condition order" and "the
    caster's own layer" name different binders (the old order had the caster first, where both readings agree). And the
    two Cultivators' Difficulty Classes really differ now -- ``table_fight`` gave both sheets the same one, so the old
    case asserted a number that was equal either way. The check is rolled to a total that meets the caster's DC and
    misses the Ally's, so the old reading would have refused the release outright, not merely read a different number."""
    from combat.ext import spirit_seals
    from combat.ext.end_effect import cultivation_dc

    combat, table, mid, spirit = _two_binders_with_distinct_dcs(tmp_path, caster_dc=16, ally_dc=19)
    engine = load(combat, tmp_path, mid).engine
    caster_dc = cultivation_dc(engine, engine.state.actors[LEFT])
    ally_dc = cultivation_dc(engine, engine.state.actors[ALLY])
    assert (caster_dc, ally_dc) == (16, 19), (caster_dc, ally_dc)
    # The Exorcist's Mercy check is a Cultivation Check -- the caster's d20 plus their Proficiency Bonus and key
    # ability modifier -- against the DC on the layer. A die of (DC - that bonus) meets the caster's own DC and is
    # under the Ally's, so one rolled check decides which binder's DC was read.
    variant = 'One layer of the Binding Seal on this creature ends'
    mercy = next(action for action in engine.action_catalog.values() if action.owner_id == LEFT
                 and 'Exorcist' in str(action.display_name) and variant in str(action.display_name))
    numbers = ((mercy.parameters or {}).get('typed') or {}).get('numbers') or {}
    bonus = (int(numbers.get('pb') or engine.state.actors[LEFT].proficiency_bonus)
             + int(numbers.get('key_mod') or 0))
    die = caster_dc - bonus

    scripted_dice(monkeypatch, lambda engine, source: [die] * 12 if MERCY in source else [1] * 12)
    _ally_seals_too(combat, table, mid, spirit)               # the binder who does NOT cast seals first
    advance_to(table, mid, LEFT)
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    engine = load(combat, tmp_path, mid).engine
    binders = [row.source_actor_id for row in _seal_conditions(engine.state.actors[spirit])]
    assert sorted(binders) == sorted([ALLY, LEFT]), binders
    # The release picks the caster's own layer -- the SECOND seal applied, which the old "first binder in condition
    # order" reading would not have picked -- and the Difficulty Class is read off that same layer.
    subject = engine.state.actors[spirit]
    layers = spirit_seals._seal_layers(subject)
    assert layers == [ALLY, LEFT], layers
    assert spirit_seals._one_layer(layers, LEFT) == LEFT, layers

    assert act(table, mid, 'end')['status'] == 'COMMITTED'   # the Binder's Action this turn went on its own seal
    advance_to(table, mid, LEFT)
    commit(cast_sender(combat, table, mid, 'Exorcist', contains=variant, target=spirit))
    fresh = load(combat, tmp_path, mid)
    checked = next(e for e in fresh.engine.events if e.event_type == 'CHECK_ROLLED' and MERCY in e.source_definition_id)
    assert checked.payload['target']['total'] == caster_dc, (checked.payload['target']['total'], caster_dc)
    assert caster_dc <= checked.payload['actor']['total'] < ally_dc, checked.payload['actor']
    assert checked.payload['success'] is True, 'the caster met the DC that is on the layer it breaks'
    sealed = fresh.engine.state.actors[spirit]
    assert not any(row.condition_id == mark_id('Binding Seal', LEFT) for row in sealed.conditions.values()), \
        "the caster's own layer is the one Mercy breaks"
    assert any(row.condition_id == mark_id('Binding Seal', ALLY) for row in sealed.conditions.values())
    assert [row.source_actor_id for row in _seal_conditions(sealed)] == [ALLY], \
        [(row.condition_id, row.source_actor_id) for row in sealed.conditions.values()]
    assert fresh.mechanical.replay()['status'] == 'PASS'


def test_mercy_names_an_unknown_binder_when_that_binder_is_gone(tmp_path, monkeypatch):
    """Checklist 7 (AUTO5r3): the release line says "<binder>'s seal is gone", and a binder who is no longer in the
    fight has no name to say. The two table cases above always have live binders, so the fallback never ran; here the
    binder really is gone from the fight's actors when the release runs, and the line must still be plain English --
    "an unknown binder", never an internal id.

    The release itself is the compiled Exorcist's Mercy row run through a Context on the saved fight's own engine (the
    house pattern for driving one effect), so the layer really is taken off the creature by the same code the table
    runs; only the caster's own Action is not replayed, because a fight cannot remove a fighter from its roster."""
    from combat import typed_executor as te
    from combat.ext import spirit_seals

    combat, table, mid, spirit = _two_binders_with_distinct_dcs(tmp_path)
    scripted_dice(monkeypatch, lambda engine, source: [1] * 12)
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    _ally_seals_too(combat, table, mid, spirit)

    engine = load(combat, tmp_path, mid).engine
    action = next(a for a in engine.action_catalog.values()
                  if a.owner_id == LEFT and 'One layer of the Binding Seal' in str(a.display_name))
    typed = (action.parameters or {})['typed']
    row = typed['effects'][0]['on_success'][0]
    subject = engine.state.actors[spirit]
    ctx = te.Context(engine, engine.state.actors[LEFT], action, None, typed, [subject], subject)
    assert len(spirit_seals._seal_layers(subject)) == 2
    del engine.state.actors[LEFT]          # the caster is no longer in the fight; his layer is still on the spirit

    spirit_seals.seal_release(ctx, row)
    notes = [str(e.payload.get('log') or '') for e in engine.events if e.event_type == 'PASSIVE_TRIGGERED']
    released = [line for line in notes if 'Binding Seal' in line and 'is gone' in line]
    assert released, notes[-8:]
    assert "an unknown binder's seal is gone" in released[-1], released[-1]
    assert 'actor:' not in released[-1], released[-1]
    assert spirit_seals._seal_layers(engine.state.actors[spirit]) == [ALLY], 'one layer really is released'


def test_an_unrelated_earlier_condition_does_not_decide_which_seal_mercys_ages(tmp_path, monkeypatch):
    """Finding 2's other half (AUTO5r2): ``_one_layer`` aged each binder by the earliest of ALL its conditions, so an
    unrelated condition a binder happened to place first could change which layer a third-party exorcist breaks.

    The Ally rests the spirit before anyone seals it -- earlier than either seal -- then the Binder seals and the Ally
    seals. The oldest SEAL is still the Binder's, so a caster who is neither of them must break the Binder's layer."""
    from combat.ext import spirit_seals

    def rest_first(engine):
        engine._apply_condition(engine.state.actors[SPIRIT], 'condition:typed.restrained', SEAL, ALLY,
                                expires_on='UNTIL_REMOVED', data={'label': 'Restrained'})

    combat, table, mid, spirit = _two_binders(tmp_path, monkeypatch)
    on_hold(monkeypatch, rest_first)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    fixed_dice(monkeypatch, [1] * 400)
    commit(cast_sender(combat, table, mid, 'Binding Seal', target=spirit))
    _ally_seals_too(combat, table, mid, spirit)

    engine = load(combat, tmp_path, mid).engine
    subject = engine.state.actors[spirit]
    ally_restraint = next(row for row in subject.conditions.values()
                          if row.source_actor_id == ALLY and row.condition_id == 'condition:typed.restrained')
    marks = {binder: subject.conditions[instance].applied_sequence
             for binder, instance, _ in spirit_seals.seal_marks(subject)}
    assert set(marks) == {LEFT, ALLY}, marks
    assert ally_restraint.applied_sequence < marks[LEFT] < marks[ALLY], (ally_restraint.applied_sequence, marks)
    # The old age scan looked at every condition a binder had placed, so it would have read the Ally as the older
    # binder here and broken the Ally's seal instead of the Binder's.
    layers = spirit_seals._seal_layers(subject)
    assert layers == [LEFT, ALLY], layers
    # RIGHT is a caster who sealed nothing: the oldest seal, not the oldest condition, is what answers.
    assert spirit_seals._one_layer(layers, RIGHT) == LEFT
    assert load(combat, tmp_path, mid).mechanical.replay()['status'] == 'PASS'


# --------------------------------------------------------------------------- finding 4: no internal id reaches the log
