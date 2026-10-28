"""Spirit Companions: Bind the Violent Ghost's printed exception, through accepted table actions.

"When placing a Binding Seal on a spirit that has attacked you or your allies during the current scene, you have
Advantage on the Binding check or the spirit has Disadvantage on its saving throw ... This advantage does not apply if
you provoked the spirit through betrayal, taboo violation, or unjustified aggression."

The scene fact (the spirit attacked) is engine-visible and marks the spirit; the exception is the binder's own story
fact, so it is asked of the binder when the seal's saving throw is about to read that mark, and a "provoked" answer
takes the mark off so no later seal this scene carries the talent's benefit. Each case runs a real character at the
table, casts Binding Seal through TabletopService, reloads the saved fight from disk and reads the printed save.
"""
import pytest

from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.r10_fixup_support import cast_sender, commit, fixed_dice
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import ALLY, HOLD, LEFT, on_hold, table_fight

SEAL = 'TAL_SPIRIT_COMPANIONS_BINDING_SEAL'
COVENANT = 'tianxia.talent.spirit_companions.covenant_spirit'
MANIFESTATION = 'tianxia.talent.spirit_companions.battle_manifestation'
VIOLENT = 'tianxia.talent.spirit_companions.bind_the_violent_ghost'
VIOLENT_NAME = 'Bind the Violent Ghost'  # the menu name the question shows (prompt key "reaction")
SPIRIT = f'{LEFT}.summon.bonded_spirit.1'


def mark_id(name, owner):
    from combat.typed_executor import mark_condition_id
    return mark_condition_id(name, owner)


def binder(tmp_path, monkeypatch, extra=(VIOLENT,)):
    """Left is a Spirit Companions binder; its Bonded Spirit is on the map and has attacked Left this scene."""
    combat, table, mid = table_fight(tmp_path, [SEAL, COVENANT, MANIFESTATION, *extra], cl=17, ask=True,
                                     ally_talents=[])

    def strike(engine):
        # The printed precondition is a fact about the scene: the spirit attacked the binder before any seal exists.
        engine._append_event('ATTACK_ROLLED', 'test:spirit_attack', actor_id=SPIRIT, target_ids=(LEFT,),
                             payload={'natural_result': 1})

    on_hold(monkeypatch, strike)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    while (table.state(mid)['menu'] or {}).get('actor_id') != LEFT:
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
    return combat, table, mid


def load(combat, tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.mechanical.replay()['status'] == 'PASS'
    return session.engine


def seal_save(engine):
    return next(e for e in engine.events
                if e.event_type == 'SAVE_ROLLED' and e.source_definition_id.endswith(SEAL))


def answer(option):
    def reply(prompt):
        if prompt['reaction'] == VIOLENT_NAME:
            return option, True
        return None, False
    return reply


@pytest.mark.parametrize('option,mode,discarded', [
    ('provoked', 'NORMAL', 0),
    ('unprovoked', 'DISADVANTAGE', 1),
])
def test_the_binders_own_answer_decides_the_printed_exception(tmp_path, monkeypatch, option, mode, discarded):
    combat, table, mid = binder(tmp_path, monkeypatch)
    fixed_dice(monkeypatch, [1] * 200)
    marks = [row for row in load(combat, tmp_path, mid).state.actors[SPIRIT].conditions.values()
             if row.condition_id == mark_id('Violent Ghost', LEFT)]
    assert len(marks) == 1, marks   # the engine-visible half: it attacked the binder this scene

    prompts = commit(cast_sender(combat, table, mid, 'Binding Seal', target=SPIRIT), answer(option))
    assert [p for p in prompts if p['reaction'] == VIOLENT_NAME], prompts
    engine = load(combat, tmp_path, mid)
    save = seal_save(engine)
    assert save.payload['mode'] == mode, save.payload
    assert len(save.payload['discarded']) == discarded, save.payload
    still = [row for row in engine.state.actors[SPIRIT].conditions.values()
             if row.condition_id == mark_id('Violent Ghost', LEFT)]
    # The answer is remembered as the mark itself: a "provoked" binder carries no mark, so no later seal asks again.
    assert len(still) == (0 if option == 'provoked' else 1), still
    if option == 'provoked':
        # A later attack recreates the attack marker, but not the scene exception.
        def strike_again(engine):
            engine._append_event('ATTACK_ROLLED', 'test:spirit_attack_again', actor_id=SPIRIT,
                                 target_ids=(LEFT,), payload={'natural_result': 1})
        on_hold(monkeypatch, strike_again)
        assert act(table, mid, HOLD)['status'] == 'COMMITTED'
        engine = load(combat, tmp_path, mid)
        assert not [row for row in engine.state.actors[SPIRIT].conditions.values()
                    if row.condition_id == mark_id('Violent Ghost', LEFT)]
        assert [row for row in engine.state.actors[SPIRIT].conditions.values()
                if row.condition_id == 'condition:typed.spirit_violent_ghost_provoked']
        prompts = commit(cast_sender(combat, table, mid, 'Binding Seal', target=SPIRIT), answer('provoked'))
        assert not [p for p in prompts if p['reaction'] == VIOLENT_NAME]
        assert seal_save(load(combat, tmp_path, mid)).payload['mode'] == 'NORMAL'


def test_declining_the_exception_leaves_the_talent_at_its_printed_benefit(tmp_path, monkeypatch):
    """The exception is the binder's to invoke: declining the question keeps the printed Disadvantage and the mark."""
    combat, table, mid = binder(tmp_path, monkeypatch)
    fixed_dice(monkeypatch, [1] * 200)
    prompts = commit(cast_sender(combat, table, mid, 'Binding Seal', target=SPIRIT), lambda p: (None, False))
    assert [p['reaction'] for p in prompts] == [VIOLENT_NAME]
    engine = load(combat, tmp_path, mid)
    assert seal_save(engine).payload['mode'] == 'DISADVANTAGE'
    assert [row for row in engine.state.actors[SPIRIT].conditions.values()
            if row.condition_id == mark_id('Violent Ghost', LEFT)]


def test_a_binder_without_the_talent_is_never_asked_and_never_marked(tmp_path, monkeypatch):
    combat, table, mid = binder(tmp_path, monkeypatch, extra=())
    fixed_dice(monkeypatch, [1] * 200)
    engine = load(combat, tmp_path, mid)
    assert not [row for row in engine.state.actors[SPIRIT].conditions.values()
                if row.condition_id == mark_id('Violent Ghost', LEFT)]
    assert commit(cast_sender(combat, table, mid, 'Binding Seal', target=SPIRIT)) == []
    assert seal_save(load(combat, tmp_path, mid)).payload['mode'] == 'NORMAL'
