"""Drown the Killing Intent (Flowing River, CL 17+) through the table service.

Printed: on a melee miss while Dodging you may force the attacker's Wisdom saving throw; on a
failure it cannot willingly make another attack against you until the start of its next turn
unless you are the only creature it can perceive as a legal target; on a success its next attack
roll against you has Disadvantage. These tests drive real fights and read the committed state:
the question the defender is asked, the condition the failed save leaves, and the roll modifier
the successful save leaves. Wording is never asserted, so the record's prose can change.

The synthetic Cause attack is set so it always misses; the Visitor's Wisdom save total is set to
either extreme, so each outcome is the record's own and not a lucky die.
"""
import pytest

from combat.ext import flowing_river_drown as drown
from tests.auto_worker1_support import ALLY, LEFT, RIGHT, act, fight, reload, settle, turn

P = 'TAL_FLOWING_RIVER_'
TALENT = P + 'DROWN_THE_KILLING_INTENT'
ASK = 'choice:needle.river_drown'
MISS = [{'type': 'attack', 'attack_kind': 'melee', 'no_damage': True}]


def missing_attack(bundle):
    """The talent only listens for a melee miss, so the synthetic attack is reach-only and cannot land."""
    for action in bundle['action_catalog']:
        if action['display_name'] == 'Cause':
            action['range_ft'] = None
            action['parameters']['typed']['range_ft'] = None
            action['parameters']['typed']['numbers']['attack_bonus'] = -100


def wis_save(total):
    """The attacker's own Wisdom save: an extreme total makes the record's branches deterministic."""
    def edit(doc, aid):
        if aid == RIGHT:
            doc['ability_scores_and_statistics']['saving_throws'] = {'WIS': total}
    return edit


def use_drown(prompt):
    """Take the talent when it is offered; leave any other question to its own default."""
    return ['use'] if (prompt.get('context') or {}).get('reaction_source_id') == ASK else []


def miss_while_dodging(tmp_path, *, save, talents=(TALENT,), dodge=True, witness=False):
    """Left Dodges, then the Visitor's melee attack at the Keeper misses; returns the prompts asked."""
    c, t, m = fight(tmp_path, list(talents), cl=17, ally=() if witness else None, bundle_edit=missing_attack,
                    sheet_edit=wis_save(save), cause=MISS)
    if dodge:
        settle(lambda a: act(t, m, 'Dodge', a))
    reload(c, m)
    turn(t, m, RIGHT)
    _, prompts = settle(lambda a: act(t, m, 'Cause', a, target_id=LEFT), use_drown)
    return c, t, m, prompts


def attack_targets(engine):
    """Every creature the current actor is offered a Cause attack on."""
    return {target for candidate in engine.legal_candidates() if candidate.display_name.startswith('Cause')
            for target in candidate.target_ids}


def test_native_melee_miss_commits_drown_save_consequence(tmp_path):
    """The ordinary weapon attack path must trigger Drown and persist its failed-save bar."""
    def sheet_edit(doc, aid):
        if aid == LEFT:
            doc['ability_scores_and_statistics']['armor_class']['base_value'] = 1000
        elif aid == RIGHT:
            doc['ability_scores_and_statistics']['saving_throws'] = {'WIS': -100}

    c, t, m = fight(tmp_path, [TALENT], cl=17, sheet_edit=sheet_edit, cause=())
    settle(lambda a: act(t, m, 'Dodge', a))
    reload(c, m)
    turn(t, m, RIGHT)
    _, prompts = settle(lambda a: act(t, m, 'Fu (Short Axe) attack', a, target_id=LEFT), use_drown)
    assert [(p.get('context') or {}).get('reaction_source_id') for p in prompts] == [ASK]
    engine = reload(c, m)
    assert [bar['blocker_id'] for bar in drown.records(engine, engine.state.actors[RIGHT])] == [LEFT]


def test_failed_save_hides_the_attack_on_the_defender(tmp_path):
    c, t, m, prompts = miss_while_dodging(tmp_path, save=-100, witness=True)
    assert [(p.get('context') or {}).get('reaction_source_id') for p in prompts] == [ASK]
    engine = reload(c, m)
    visitor = engine.state.actors[RIGHT]
    bars = drown.records(engine, visitor)
    assert [bar['blocker_id'] for bar in bars] == [LEFT]
    assert all(bar['instance_id'] for bar in bars)
    assert drown.barred(engine, visitor, engine.state.actors[LEFT])
    assert not drown.barred(engine, visitor, engine.state.actors[ALLY])
    offered = attack_targets(engine)
    assert LEFT not in offered
    assert ALLY in offered


def test_ban_lifts_when_the_defender_is_the_only_legal_target(tmp_path):
    """The printed exception: with nobody else to attack, the ban leaves the attack offered."""
    c, t, m, prompts = miss_while_dodging(tmp_path, save=-100)
    assert [(p.get('context') or {}).get('reaction_source_id') for p in prompts] == [ASK]
    engine = reload(c, m)
    visitor = engine.state.actors[RIGHT]
    assert [bar['blocker_id'] for bar in drown.records(engine, visitor)] == [LEFT]
    assert not drown.barred(engine, visitor, engine.state.actors[LEFT])
    assert LEFT in attack_targets(engine)


def test_perceived_but_forbidden_target_does_not_lift_the_ban(tmp_path):
    """An enemy barred by another rule is not a legal alternative target."""
    c, t, m, prompts = miss_while_dodging(tmp_path, save=-100, witness=True)
    assert [(p.get('context') or {}).get('reaction_source_id') for p in prompts] == [ASK]
    engine = reload(c, m)
    visitor = engine.state.actors[RIGHT]
    engine._apply_condition(visitor, 'condition:test.creature_bar', 'test:bar', ALLY,
                            expires_on='START_OF_SOURCE_NEXT_TURN',
                            data={'bar': {'attack': 'source'}})
    assert not drown.barred(engine, visitor, engine.state.actors[LEFT])
    assert LEFT in attack_targets(engine)


def test_successful_save_gives_disadvantage_on_the_next_attack_against_the_defender(tmp_path):
    c, t, m, prompts = miss_while_dodging(tmp_path, save=100)
    assert [(p.get('context') or {}).get('reaction_source_id') for p in prompts] == [ASK]
    engine = reload(c, m)
    visitor = engine.state.actors[RIGHT]
    assert drown.records(engine, visitor) == []
    modes = [(modifier.value, modifier.applies_to) for modifier in visitor.modifiers.values()
             if modifier.target_field == 'attack_mode_vs']
    assert modes == [(f'DISADVANTAGE:{LEFT}', 'NEXT_ATTACK')]
    assert LEFT in attack_targets(engine)


@pytest.mark.parametrize('talents,dodge', [((), True), ((TALENT,), False)])
def test_only_a_dodging_owner_is_asked(tmp_path, talents, dodge):
    c, t, m, prompts = miss_while_dodging(tmp_path, save=-100, talents=talents, dodge=dodge)
    assert prompts == []
    engine = reload(c, m)
    assert drown.records(engine, engine.state.actors[RIGHT]) == []
    assert LEFT in attack_targets(engine)


def test_plug_in_imports_no_private_core_names():
    """Modularity: a plug-in uses core's public names (typed_executor.default_subjects), never its _private ones."""
    import ast
    from pathlib import Path

    source = Path(drown.__file__).read_text()
    private = [alias.name for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ImportFrom)
               and (node.module or "").endswith("typed_executor") for alias in node.names
               if alias.name.startswith("_")]
    assert private == []
