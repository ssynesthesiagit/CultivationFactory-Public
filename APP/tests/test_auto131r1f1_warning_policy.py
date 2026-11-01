"""AUTO131r1f1: an automatic Warning Trigger answer must not protect the owner's enemies.

Automatic Warning Trigger asked "choose any creatures to warn" and passed every visible creature up to a maximum of
all of them. The automatic controller answers by taking every option up to that maximum, so an unanswered warning
made the owner's enemies safe as well as its allies -- the owner's trap stopped working against whoever it was set
for. The owner at the table still chooses freely (warning an enemy is a real, if odd, choice); only the automatic
answer is narrowed, and only to the owner's allies.

Both routes are covered at table level, committed and reloaded from disk: the warning the owner chose when setting
the trap, and the later "Warn creatures about a trap" action. Each then proves the point that matters -- an enemy
that was never warned still springs the trap.
"""
import pytest

from combat.ext import placed
from tests.cw2_service_support import seal
from tests.worker2_support import ALLY, FOE, OWNER, candidate, fixture, reload, settle, turn


def fail_foe_dex(bundles):
    """The trap springs when a creature fails its Dexterity save, so give the foe one it cannot pass."""
    bundles[2]['actor_template']['saving_throws']['DEX'] = -100
    seal(bundles[2])


def automatic_owner(combat, mid, actor=OWNER):
    combat.set_controller_mode(mid, actor_id=actor, controller_mode='LOCAL_AUTO')


def steer(monkeypatch, combat, mid, label):
    """Aim the automatic controller at the one action named ``label``.

    Set Trap is a ``player_only`` action, so the built-in AI never picks it on its own and the automatic answer to
    the warning would otherwise be unreachable here. Only the choice of action is pinned; the real controller still
    scores it, records the decision and answers the question through the real reaction path, which is the automatic
    answer under test.
    """
    session = combat._load_session(mid)
    target = next(c for c in combat._legal_candidates(session)
                  if getattr(c, 'display_name', '') == label)
    real = combat.controller.choose_primary_action

    def aimed(context):
        return real(context.model_copy(update={'legal_candidates': (target,)}))

    monkeypatch.setattr(combat.controller, 'choose_primary_action', aimed)
    return target


def step(monkeypatch, combat, mid, label):
    steer(monkeypatch, combat, mid, label)
    result = combat.local_step(mid, [])
    # the aim was for this one action only; the controller is its own decision-maker again afterwards
    monkeypatch.undo()
    assert result['status'] == 'COMMITTED', result


def past_owner(combat, mid, actor=OWNER):
    """Run the automatic fighter's turn out so the table is driving again."""
    for _ in range(8):
        if combat._load_session(mid).engine.state.current_actor_id != actor:
            return
        assert combat.local_step(mid, [])['status'] == 'COMMITTED'
    raise AssertionError('the automatic fighter never ended its turn')


def warned(engine):
    return placed.data(placed.of(engine, 'trap', owner_id=OWNER)[0]).get('warned')


def armed(tmp_path):
    """A Warning Trigger tripwire the owner has aimed at (4,7), set up through the real table."""
    combat, table, mid = fixture(tmp_path, ['TAL_TRAP_WARNING_TRIGGER'], bundle_transform=fail_foe_dex)
    settle(table, mid, candidate(combat, mid, 'Trap form: Tripwire').candidate_id)
    settle(table, mid, candidate(combat, mid, 'Trap trigger: Warning Trigger').candidate_id)
    return combat, table, mid


def test_automatic_warning_protects_only_allies(monkeypatch, tmp_path):
    """The automatic answer to "warn anyone you can see" warns the owner's side and leaves its enemies exposed."""
    combat, table, mid = armed(tmp_path)
    automatic_owner(combat, mid)
    step(monkeypatch, combat, mid, 'Set Trap at 4,7')

    engine = reload(tmp_path, mid)
    assert set(warned(engine)) == {OWNER, ALLY}   # every ally that could see it, and no foe
    assert FOE not in warned(engine)


def test_automatic_later_warning_protects_only_allies(monkeypatch, tmp_path):
    """The same holds for the owner's later "Warn creatures about a trap" answer: it cannot warn an enemy."""
    combat, table, mid = armed(tmp_path)
    automatic_owner(combat, mid)
    step(monkeypatch, combat, mid, 'Set Trap at 4,7')
    assert FOE not in warned(reload(tmp_path, mid))

    step(monkeypatch, combat, mid, 'Warn creatures about a trap at 4,7')

    assert set(warned(reload(tmp_path, mid))) == {OWNER, ALLY}
    assert FOE not in warned(reload(tmp_path, mid))


@pytest.mark.parametrize('later', [False, True])
def test_unwarned_enemy_still_springs_the_trap(monkeypatch, tmp_path, later):
    """The consequence of the automatic answer: the owner's trap still goes off against the enemy it was set for."""
    combat, table, mid = armed(tmp_path)
    automatic_owner(combat, mid)
    step(monkeypatch, combat, mid, 'Set Trap at 4,7')
    if later:
        step(monkeypatch, combat, mid, 'Warn creatures about a trap at 4,7')
    past_owner(combat, mid)

    turn(table, mid, FOE)
    engine = combat._load_session(mid).engine
    move = next(c for c in engine.legal_candidates()
                if c.kind.value == 'MOVE' and c.destination
                and (c.destination.x, c.destination.y) == (4, 7))
    prompts = settle(table, mid, move.candidate_id)

    # nothing was warned, so nothing was asked of the enemy, and the trap went off
    assert not [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.trap_warned_trigger']
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == 'condition:typed.prone' for c in engine.state.actors[FOE].conditions.values())
    assert FOE not in warned(engine)


def test_the_owner_at_the_table_may_still_warn_an_enemy(tmp_path):
    """Only the automatic answer is narrowed. Warning a foe is a real choice the owner keeps."""
    combat, table, mid = armed(tmp_path)
    prompts = settle(table, mid, candidate(combat, mid, 'Set Trap', at=(4, 7)).candidate_id,
                     {'choice:needle.trap_warn': [FOE]})
    question = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.trap_warn')
    assert FOE in {o['id'] for o in question['choice']['options']}
    assert warned(reload(tmp_path, mid)) == [FOE]