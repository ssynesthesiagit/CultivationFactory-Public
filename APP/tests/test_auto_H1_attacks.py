"""Lane H1, family 5: attack-roll rerolls (Executioner, Star-Drawn Projectile's Reroll Miss)."""

from combat.ext.body_berserker import ACTIVE
from combat.typed_executor import mark_condition_id
from tests.h1_support import FOE, ME, amount, duel, give, held, rewrites, script, use

EXECUTIONER = "TAL_BERSERKER_EXECUTIONER"
STAR = "tianxia.talent.stars.star_drawn_projectile"
AXE_KIT = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.fu", "name": "Fu (Short Axe)", "quantity": 1}]}}
STAR_CONDITION = "condition:typed.star_drawn_reroll"


def _hp(engine):
    return engine.state.actors[FOE].current_hp


def test_executioner_rerolls_one_missed_weapon_attack_for_martial_focus_while_its_adrenaline_is_active():
    engine = duel(EXECUTIONER, kit=AXE_KIT)
    use(engine, "Adrenaline: Executioner", ME)
    engine.state.actors[FOE].armor_class = 12
    hp = _hp(engine)
    script(engine, [2, 19])          # a miss (2 + the technique attack bonus is not the point: the weapon roll), then the reroll
    engine.state.actors[ME].action_available = True
    use(engine, "Fu (Short Axe) attack", FOE)
    (rewrite,) = rewrites(engine)
    assert rewrite.source_definition_id == EXECUTIONER and rewrite.payload["original"]["natural_result"] == 2
    assert amount(engine, ME, "focus") == 0 and _hp(engine) < hp
    assert not any(e.event_type == "DAMAGE_COMMITTED" for e in engine.events if e.sequence < rewrite.sequence)


def test_executioner_needs_its_adrenaline_and_the_focus_and_a_miss():
    engine = duel(EXECUTIONER, kit=AXE_KIT)
    engine.state.actors[FOE].armor_class = 12
    script(engine, [2, 19])
    use(engine, "Fu (Short Axe) attack", FOE)                   # no Adrenaline
    assert not rewrites(engine)
    engine = duel(EXECUTIONER, kit=AXE_KIT)
    use(engine, "Adrenaline: Executioner", ME)
    give(engine, ME, focus=0)
    engine.state.actors[FOE].armor_class = 12
    engine.state.actors[ME].action_available = True
    script(engine, [2, 19])
    use(engine, "Fu (Short Axe) attack", FOE)                   # no Martial Focus
    assert not rewrites(engine)


def test_executioner_ignores_a_hit():
    engine = duel(EXECUTIONER, kit=AXE_KIT)
    use(engine, "Adrenaline: Executioner", ME)
    engine.state.actors[FOE].armor_class = 5
    engine.state.actors[ME].action_available = True
    script(engine, [19])
    use(engine, "Fu (Short Axe) attack", FOE)
    assert not rewrites(engine) and amount(engine, ME, "focus") == 1


def _star(engine, marked):
    engine.state.actors[FOE].armor_class = 12
    if marked:
        engine._apply_condition(engine.state.actors[FOE], mark_condition_id("Stellar Mark", ME), "test:mark", ME, expires_on="UNTIL_REMOVED")
    use(engine, "Star-Drawn Projectile: Reroll Miss")
    engine.state.actors[ME].action_available = True


def test_star_drawn_projectile_reroll_miss_rerolls_a_miss_against_a_marked_creature_once():
    engine = duel(STAR)
    _star(engine, marked=True)
    assert amount(engine, ME, "qi") == 28 and held(engine.state.actors[ME], STAR_CONDITION)
    hp = _hp(engine)
    script(engine, [1, 18])          # a natural 1 misses; the reroll hits
    use(engine, "Starbolt", FOE)
    (rewrite,) = rewrites(engine)
    assert "star_drawn_projectile" in rewrite.source_definition_id and _hp(engine) < hp
    assert not held(engine.state.actors[ME], STAR_CONDITION)        # used up


def test_star_drawn_projectile_reroll_miss_is_kept_for_the_next_ranged_attack_only_and_needs_the_mark():
    engine = duel(STAR)
    _star(engine, marked=False)
    script(engine, [1, 18])
    use(engine, "Starbolt", FOE)                                   # no Stellar Mark on the target
    assert not rewrites(engine) and not held(engine.state.actors[ME], STAR_CONDITION)
    engine = duel(STAR)
    _star(engine, marked=True)
    script(engine, [18])
    use(engine, "Starbolt", FOE)                                   # a hit uses the constellation path up
    assert not rewrites(engine) and not held(engine.state.actors[ME], STAR_CONDITION)
