"""Spear sphere: the printed lines the table now runs itself (worker AUTO56; review fixes AUTO56f2, 2026-10-05).

Owner 2026-09-29, "automate everything".  These are table-level regressions for the printed
mechanics of tianxia.sphere.spear that were riders ("the GM resolves this") before this file:

  * nine Spear abilities printed "N Spear Resource" and ran for nothing, because the parser reads
    a resource name it does not know as free text and, on seven of them, the prose ran on from the
    "Cost:" line so the whole header stayed one string.  Every one of them is charged now.
  * "Damage by Cultivation Level" (Spear-Light Seed, Penetrating Rainbow, Meteor-Net Spear Art,
    Heaven-Piercing Spear Light) and "gain your Spear Intent" were riders, so a high-CL fighter's
    lines dealt the CL 1 band and never marked anything.
  * Heaven-Piercing Spear Light and World-Transfixing Point carried a parser "Resistance" row that
    GRANTED Resistance to Piercing and Force to every creature in the line, and applied the printed
    "choose one creature that failed" riders to all of them instead of one.  AUTO56's first repair
    replaced the grant with an unconditional damage bypass, which ignored every recipient's
    Resistance; the bypass is now scoped to the chosen creature, the caster's own Spear talents and
    the caster's next turn (combat/ext/resistance_bypass.py).
  * One Line Cannot Be Crossed ran all five printed options at once (the text says "Choose two"),
    still dealt no weapon damage, and its closing step spared every enemy's opportunity attack
    instead of the target's.
  * Intercepting Thrust said "remaining movement" and was typed as a Speed modifier of -999.
  * Pinned Heaven's successful-save branch applied the movement lock as well as the one printed
    option, because the new row did not carry the single-success marker its six siblings carry.

Plus the new general seams combat/ext/approach_lock.py (``held_at_distance``),
combat/ext/resistance_bypass.py (``target_resistance_ignored``) and combat/ext/quiet_step.py
(``move_without_provoking``), and a real table fight that commits one of them, reloads it from disk
and watches it expire.

Run with:  cd APP && pytest -p no:cacheprovider --basetemp=/var/tmp/auto56f2-pytest -q tests/test_auto56_spear.py
"""

import copy
import json
from functools import lru_cache
from pathlib import Path

import pytest

from combat import ext
from combat import typed_executor as te
from combat import typed_reactions
from combat.ext import approach_lock, menus, quiet_step, resistance_bypass
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent, Position, ReactionDecision
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate2_runtime_content import AN as AN_ID
from combat.gate2_runtime_content import BAI, CUI, LEE, LING
from tests.test_auto_support import AN, ME
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
AUTH = json.loads((ROOT / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics']
KIT = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.qiang', 'name': 'Qiang (Spear)', 'quantity': 1}]}}
SPEAR = 'tianxia.sphere.spear'
FOREIGN = LING                               # a second sparring creature, so its opportunity attack is real
RIVAL = 'actor:factory.spear_rival'            # another Factory fighter on the foe's team, for a talent that hits several
ALLY = 'actor:factory.spear_ally'                # an ally of mine, for "a creature ... attacks an ally"
FAIL, PASS = 50, -40                              # technique save DC that makes every save fail / succeed
FIXTURES = {AN_ID, BAI, CUI, LEE, LING}          # the sparring creatures the engine ships with


def _sheet(cl=20, dc=50):
    return {**SHEET, 'equipment': [KIT],
            'identity': {**SHEET['identity'], 'cultivation_level': cl},
            'ability_scores_and_statistics': {**SHEET['ability_scores_and_statistics'],
                'technique_save_dc': dc, 'technique_attack_bonus': 40,
                'primary_resource': {'name': 'Stamina', 'maximum': 100}},
            'spheres_and_talents': {'sphere_record_ids': [SPEAR], 'learned_talent_record_ids': []}}


def _learned(sheet, ids):
    """``sheet`` with each id's sphere plus that sphere's base abilities, the way ``_compiled`` assembles them."""
    spheres, talents = [], []
    for one in ids:
        sphere = AUTH[one]['sphere_id']
        if sphere not in spheres:
            spheres.append(sphere)
        talents.append(one)
    bases = [k for k, v in AUTH.items() if v.get('sphere_id') in spheres and v.get('kind') == 'base_ability']
    return {**sheet, 'spheres_and_talents': {**sheet['spheres_and_talents'], 'sphere_record_ids': spheres,
                                            'learned_talent_record_ids': list(dict.fromkeys([*bases, *talents]))}}


@lru_cache(maxsize=None)
def _compiled(talent, cl=20, dc=50, also=()):
    return compile_character(_learned(_sheet(cl, dc), (talent, *also)), actor_id=ME)


def _reaction(bundle, feature):
    """The compiled typed rows of one printed reaction, which has no action of its own."""
    return next(row for row in bundle['typed_reactions'] if row['feature_id'] == feature)


def _reaction_effects(bundle, feature, kind):
    return next(row for row in _reaction(bundle, feature)['effects'] if row.get('type') == kind)


def _engine(bundles, roster):
    engine = Gate4ControllerEngine(ROOT, match_seed='AUTO56', typed_bundles=tuple(bundles), roster_setup=roster)
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


def _fight(talent, cl=20, dc=50, foe_at=(4, 6), *, bystander=None, rival=None, ally=None, sure_hit=True, also=(),
           ally_also=()):
    """A live Gate 4 fight.  The map is

        (3,5) ally            (3,7) rival
        (3,6) me   (4,6) foe  (4,7) bystander

    ``bystander`` is one of the engine's sparring creatures, so its opportunity attack is the
    ordinary native one, and it is never hit by a printed talent here -- the printed rule that spares
    one creature must not spare it.  ``rival`` is a second Factory fighter on the foe's team that a
    printed talent may hit, and ``ally`` one on my own team, for a reaction printed as "a creature
    ... attacks an ally" or a rule printed as "your ... talents".  ``also`` adds a second sphere's
    talent to me and ``ally_also`` one to the ally, for a rule naming only mine.
    """
    mine = _compiled(talent, cl, dc, also)
    bundles = [mine]
    roster = {"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
              "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": foe_at[0], "y": foe_at[1]}}}
    for extra, team, at in ((ally, "team:a", (3, 5)), (rival, "team:b", (3, 7)),
                            (bystander, "team:b", (foe_at[0], foe_at[1] + 1))):
        if not extra:
            continue
        if extra not in FIXTURES:
            sheet = _sheet(cl, dc)
            if extra == ally and ally_also:
                sheet = _learned(sheet, ally_also)
            bundles.append(compile_character(sheet, actor_id=extra))
        roster["primary_actor_ids"] = [*roster["primary_actor_ids"], extra]
        roster["team_by_actor"][extra] = team
        roster["starting_positions"][extra] = {"x": at[0], "y": at[1]}
    engine = _engine(bundles, roster)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    for actor in [me, foe] + [engine.state.actors[one] for one in (bystander, rival, ally) if one]:
        actor.maximum_hp = actor.current_hp = 5000     # a printed line may catch its own user
        if actor is not me:
            actor.armor_class = -50 if sure_hit else 200     # out of reach of the printed attack bonus
    me.resources['resource:core.martial_focus'] = 1
    return (copy.deepcopy(mine), engine, me, foe,
            engine.state.actors.get(bystander) if bystander else None,
            engine.state.actors.get(ally) if ally else None)


def _use(engine, name, *, actor=ME, destination=None):
    """Run one of the actor's printed abilities, aiming an area at the foe (the pattern
    tests/test_review_sw-gravity.py uses for CELL abilities)."""
    candidates = [c for c in engine.legal_candidates()
                  if c.display_name.startswith(name) and c.actor_id == actor
                  and (destination is None or (c.destination is not None
                                                and (c.destination.x, c.destination.y) == destination))]
    assert candidates, (name, [c.display_name for c in engine.legal_candidates()][:30])
    pos = engine.state.actors[AN].position
    candidate = min(candidates, key=lambda c: (0 if c.destination is None else
                    abs(c.destination.x - pos.x) + abs(c.destination.y - pos.y), c.display_name))
    engine.execute_intent(ActionIntent(intent_id=name, decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=actor,
        target_ids=candidate.target_ids, destination=candidate.destination))
    return candidate


def _answers(engine, picks, uses=()):
    """Immediate engine choice provider.  ``picks`` maps a choice id's last part to a function of the
    offered option ids returning the ones to take (None declines); an unlisted needle choice takes the
    first option.  ``uses`` are substrings of the printed reactions this creature answers with USE.
    Everything else -- the sparring creatures' own guards -- is declined, so a test reads only the
    printed Spear line.  Returns the needle prompts the table asked."""
    asked = []

    def provider(request):
        source = str(request['reaction_source_id'])
        options = list(request['legal_option_ids'])
        if source.startswith('choice:needle.'):
            asked.append(request)
            pick = picks.get(source.split('.')[-1])
            chosen = pick(options) if pick else options[:1]
        elif any(one in source for one in uses):
            chosen = options
        else:
            chosen = None
        return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=request['reactor_id'],
                                reaction_source_id=request['reaction_source_id'],
                                selection='DECLINE' if chosen is None else 'USE',
                                option_ids=tuple(chosen or ())), None

    engine.set_reaction_provider(provider)
    return asked


def _walk_away_from(engine, creature):
    """Pick the offered square furthest from ``creature``: an opportunity attack is only opened by a
    step that LEAVES a creature's reach, so a step that stays inside it proves nothing."""
    def pick(options):
        def where(key):
            cell = key.split(':')[-1].split(',')
            return int(cell[0]), int(cell[1])
        return [max(options, key=lambda key: abs(where(key)[0] - creature.position.x)
                    + abs(where(key)[1] - creature.position.y))]
    return pick


def _ready(engine):
    me = engine.state.actors[ME]
    me.action_available, me.bonus_action_available = True, True
    me.resources['resource:core.stamina'] = 100


def _flat_cost(costs):
    """A compiled action's costs are (resource_id, amount) pairs, the first being the printed pool."""
    return [tuple(pair) for pair in costs or [] if isinstance(pair, (list, tuple)) and len(pair) >= 2]


def _row(bundle, name):
    return next(row for row in bundle['action_catalog'] if row['display_name'] == name)


def _typed(bundle, name):
    return (_row(bundle, name).get('parameters') or {}).get('typed') or {}


def _walk(effects):
    for row in effects or []:
        if isinstance(row, dict):
            yield row
            for key in ('on_hit', 'on_miss', 'on_fail', 'on_success', 'effects', 'after'):
                yield from _walk(row.get(key))


def _events(engine, kind):
    return [e for e in engine.events if e.event_type == kind]


def _riders(engine):
    return [str((e.payload or {}).get('rider') or '') for e in engine.events if e.event_type == 'GM_RIDER']


def _resolved_step_logs(engine):
    """Flowers resolves and logs its step; it emits no GM reminder."""
    events = [e for e in engine.events if e.source_definition_id.endswith('TAL_SPEAR_FLOWERS_IN_THE_STORM')]
    assert not any(e.event_type == 'GM_RIDER' for e in events)
    return [str(e.payload.get('log') or '') for e in events if e.event_type == 'PASSIVE_TRIGGERED']


# -------------------------------------------------------------------------------------- printed costs


@pytest.mark.parametrize('talent,display,amount', [
    ('TAL_SPEAR_SPEAR_LIGHT_SEED', 'Spear-Light Seed', 2),
    ('TAL_SPEAR_PENETRATING_RAINBOW', 'Penetrating Rainbow', 4),
    ('TAL_SPEAR_METEOR_NET_SPEAR_ART', 'Meteor-Net Spear Art: 15-foot cone', 6),
    ('TAL_SPEAR_HEAVEN_PIERCING_SPEAR_LIGHT', 'Heaven-Piercing Spear Light', 8),
    ('TAL_SPEAR_WORLD_TRANSFIXING_POINT', 'World-Transfixing Point', 12),
    ('TAL_SPEAR_SPEAR_PRESSURE', 'Spear Pressure', 7),
    ('TAL_SPEAR_DRAGON_COIL_SPEAR_SOUL', 'Dragon-Coil Spear Soul', 6),
    ('TAL_SPEAR_SPEAR_SOVEREIGN_INCARNATION', 'Spear-Sovereign Incarnation', 15),
    ('TAL_SPEAR_TEN_THOUSAND_SPEAR_SHADOWS', 'Ten-Thousand Spear Shadows', 12),
])
def test_printed_spear_resource_is_actually_charged(talent, display, amount):
    """Every one of these printed "Cost: N Spear Resource ..." and the table charged nothing.

    "Spear Resource" is not one of the parser's known pools, so the cost line stayed free text; on
    seven of them the printed body ran on from "Cost:" and the whole header became one string.
    The earlier reviewed Spear entries (martial.json) already read "N Spear Resource" as the
    character's own pool, so these nine now do too: before this the candidate cost was [].
    """
    bundle = _compiled(talent)
    assert ('resource:core.stamina', amount) in _flat_cost(_row(bundle, display)['costs']), \
        (display, _row(bundle, display)['costs'])


def test_the_table_actually_deducts_a_spear_line_cost():
    bundle, engine, me, _foe, _other, _ally = _fight('TAL_SPEAR_SPEAR_LIGHT_SEED')
    _ready(engine)
    before = me.resources['resource:core.stamina']
    _use(engine, 'Spear-Light Seed')
    assert me.resources['resource:core.stamina'] == before - 2


def test_spear_thrust_prints_no_cost_and_says_none():
    """'Cost: None Replace one attack ...' is no cost; the parser kept the whole line as free text."""
    assert AUTH['SPEAR_BASE_SPEAR_THRUST']['cost'] == []
    assert _row(_compiled('SPEAR_BASE_SPEAR_THRUST'), 'Spear Thrust: Push Target')['costs'] == []


def test_one_line_cannot_be_crossed_costs_four_or_a_martial_focus():
    """It is a Reaction: 'Cost: 4 Spear Resource or expend Martial Focus' used to resolve to []."""
    reaction = next(r for r in _compiled('TAL_SPEAR_ONE_LINE_CANNOT_BE_CROSSED')['typed_reactions']
                    if r.get('name') == 'One Line Cannot Be Crossed')
    assert {'resource_id': 'resource:core.stamina', 'amount': 4} in reaction['costs']   # it used to be []


# ------------------------------------------------------------------- Damage by Cultivation Level


@pytest.mark.parametrize('talent,display,cl,dice', [
    ('TAL_SPEAR_SPEAR_LIGHT_SEED', 'Spear-Light Seed', 1, '2d6'),
    ('TAL_SPEAR_SPEAR_LIGHT_SEED', 'Spear-Light Seed', 5, '3d6'),
    ('TAL_SPEAR_SPEAR_LIGHT_SEED', 'Spear-Light Seed', 11, '5d6'),
    ('TAL_SPEAR_SPEAR_LIGHT_SEED', 'Spear-Light Seed', 17, '7d6'),
    ('TAL_SPEAR_PENETRATING_RAINBOW', 'Penetrating Rainbow', 5, '5d8'),
    ('TAL_SPEAR_PENETRATING_RAINBOW', 'Penetrating Rainbow', 11, '7d8'),
    ('TAL_SPEAR_PENETRATING_RAINBOW', 'Penetrating Rainbow', 17, '9d8'),
    ('TAL_SPEAR_METEOR_NET_SPEAR_ART', 'Meteor-Net Spear Art: 15-foot cone', 10, '6d8'),
    ('TAL_SPEAR_METEOR_NET_SPEAR_ART', 'Meteor-Net Spear Art: 15-foot cone', 17, '8d8'),
    ('TAL_SPEAR_HEAVEN_PIERCING_SPEAR_LIGHT', 'Heaven-Piercing Spear Light', 12, '9d8'),
    ('TAL_SPEAR_HEAVEN_PIERCING_SPEAR_LIGHT', 'Heaven-Piercing Spear Light', 17, '11d8'),
])
def test_printed_cl_bands_are_the_dice_that_are_rolled(talent, display, cl, dice):
    """'Damage by Cultivation Level' was a rider, so every CL dealt the CL 1 band."""
    bundle, engine, _me, _foe, _other, _ally = _fight(talent, cl=cl)
    _use(engine, display)
    rolled = [str(e.payload.get('expression') or '').removesuffix('+0')
              for e in _events(engine, 'DAMAGE_ROLLED')]
    assert rolled, (talent, cl, [e.event_type for e in engine.events][-12:])
    assert rolled[0].startswith(dice), (talent, cl, rolled)


# -------------------------------------------------------------------- the Spear Intent mark lands


@pytest.mark.parametrize('talent,display', [
    ('TAL_SPEAR_SPEAR_LIGHT_SEED', 'Spear-Light Seed'),
    ('TAL_SPEAR_PENETRATING_RAINBOW', 'Penetrating Rainbow'),
    ('TAL_SPEAR_METEOR_NET_SPEAR_ART', 'Meteor-Net Spear Art: 15-foot cone'),
    ('TAL_SPEAR_HEAVEN_PIERCING_SPEAR_LIGHT', 'Heaven-Piercing Spear Light'),
])
def test_a_failed_spear_light_line_marks_every_creature_in_it(talent, display):
    """"Failed Save: Take damage and gain your Spear Intent" was a rider; nothing was marked."""
    _bundle, engine, me, foe, _other, _ally = _fight(talent)
    _use(engine, display)
    assert te.bears_mark(foe, me.entity_id, 'Spear Intent'), _riders(engine)


def test_one_spear_pierces_the_army_marks_what_it_damages():
    """"Creatures damaged gain your Spear Intent" was not typed at all."""
    _bundle, engine, me, foe, _other, _ally = _fight('TAL_SPEAR_ONE_SPEAR_PIERCES_THE_ARMY')
    _use(engine, 'One Spear Pierces the Army: Push Away')
    assert te.bears_mark(foe, me.entity_id, 'Spear Intent'), _riders(engine)


def test_spear_light_infusion_names_the_two_lines_it_cannot_run_yet():
    """"Once per turn when the weapon hits: ... apply Spear Intent" rides the same hit as its
    deferred extra_damage row, and combat/typed_executor._registered_effect only looks up a deferred
    row whose type is extra_damage (typed_executor.py:1742), so it cannot be typed until that filter
    is widened. The line is named rather than silently dropped."""
    assert AUTH['TAL_SPEAR_SPEAR_LIGHT_INFUSION']['riders'] == [
        'the weapon counts as magical for overcoming ordinary Resistance', 'apply Spear Intent']


def test_spear_light_infusion_still_adds_its_printed_cl_banded_damage():
    _bundle, engine, _me, foe, _other, _ally = _fight('TAL_SPEAR_SPEAR_LIGHT_INFUSION', cl=17)
    _use(engine, 'Spear-Light Infusion')          # Bonus Action, sets the infusion up
    _ready(engine)
    before = foe.current_hp
    _use(engine, 'Qiang (Spear) attack')          # then the once-per-turn hit it rides (3d6 at CL 17)
    rolled = [str(e.payload.get('expression') or '') for e in _events(engine, 'DAMAGE_ROLLED')]
    assert any(expression.startswith('3d6') for expression in rolled), (rolled, _riders(engine))
    assert foe.current_hp < before


# --------------------------------- the printed Resistance bypass belongs to ONE chosen creature


def _resistant(engine, actor, kinds=('PIERCING', 'FORCE')):
    for kind in kinds:
        engine._add_modifier(actor, 'test:printed', "damage_resistance", "ADD", kind, "ALWAYS", expires_on=None)


def _lands(engine, defender, source_id, source_actor_id, kind='PIERCING', amount=20):
    """What the table's own defence rule makes of this packet (combat/typed_reactions.defend)."""
    return typed_reactions.defend(engine, defender, amount, kind, source_id, source_actor_id)


@pytest.mark.parametrize('talent,display', [
    ('TAL_SPEAR_HEAVEN_PIERCING_SPEAR_LIGHT', 'Heaven-Piercing Spear Light'),
    ('TAL_SPEAR_WORLD_TRANSFIXING_POINT', 'World-Transfixing Point'),
])
def test_the_chosen_creatures_resistance_is_set_aside_and_nobody_elses(talent, display):
    """"Choose one creature that failed. ... ordinary Resistance to Piercing and Force damage does not
    apply" is about ONE creature.  AUTO56's first repair used a top-level ignore_resistance row,
    which is a property of a single damage packet, so it stripped the Resistance of every recipient
    of the line -- including the creatures that saved.  The bypass now lives on the chosen creature.

    Read through the engine's own defence rule: 20 Piercing damage lands whole against the chosen
    creature, while a creature that failed the same line and was NOT chosen -- the caster is standing
    in its own line -- keeps its own Resistance, as does the chosen creature against a damage type
    the printed sentence does not name.
    """
    bundle, engine, me, foe, _other, _ally = _fight(talent)
    _answers(engine, {'rider_failed_save': lambda options: [who for who in options if who == AN]})
    _resistant(engine, foe, ('PIERCING', 'FORCE', 'BLUDGEONING'))
    _resistant(engine, me)
    assert _lands(engine, foe, 'system:test', AN) == 10          # the foe's own Resistance works
    assert _lands(engine, me, 'system:test', AN) == 10
    _use(engine, display)
    records = resistance_bypass.records(engine, foe)
    assert records and 'PIERCING' in records[0]['damage_types'], [c.condition_id for c in foe.conditions.values()]
    assert resistance_bypass.records(engine, me) == [], \
        'the bypass is the one chosen creature, not every creature that failed the line'
    assert _lands(engine, foe, 'system:test', AN, kind='BLUDGEONING') == 10, \
        'a damage type the printed sentence does not name keeps the Resistance'


@pytest.mark.parametrize('talent,display,scope,me_lands,ally_lands,other_sphere_lands', [
    # "does not apply to your Spear talents against it": the caster's own Spear techniques only
    ('TAL_SPEAR_HEAVEN_PIERCING_SPEAR_LIGHT', 'Heaven-Piercing Spear Light', 'chooser', 20, 10, 10),
    # "does not apply": no source is named, so anyone's Piercing or Force damage is ignored
    ('TAL_SPEAR_WORLD_TRANSFIXING_POINT', 'World-Transfixing Point', 'anyone', 20, 20, 20),
])
def test_the_printed_sentence_decides_whose_damage_ignores_that_resistance(talent, display, scope, me_lands,
                                                                           ally_lands, other_sphere_lands):
    """Whose damage may ignore the bypass is printed, so it is data.

    Heaven-Piercing Spear Light says "does not apply to *your* Spear talents against it", so only the
    creature that chose it benefits from its own Spear damage.  World-Transfixing Point's bullet says
    plain "does not apply" and names no source at all, so an ALLY's own Spear line ignores that
    creature's Resistance too -- before AUTO56r1f1 the bypass demanded the chooser and silently spared
    nothing from anyone else.  A damage type the sentence does not name still resists either way.
    """
    _bundle, engine, me, foe, _other, ally = _fight(talent, also=('TAL_METAL_HEAVEN_PIERCING_NAIL',), ally=ALLY,
                                                    ally_also=('TAL_SPEAR_PENETRATING_RAINBOW',))
    assert ally is not None
    _answers(engine, {'rider_failed_save': lambda options: [who for who in options if who == AN]})
    _resistant(engine, foe, ('PIERCING', 'BLUDGEONING'))
    _use(engine, display)
    assert resistance_bypass.scope_of(resistance_bypass.records(engine, foe)[0]) == scope, \
        resistance_bypass.records(engine, foe)
    me_id, ally_id = me.entity_id, ally.entity_id
    mine = _piercing_ability(engine, me_id, SPEAR)
    theirs = _piercing_ability(engine, ally_id, SPEAR)
    other_sphere = _piercing_ability(engine, me_id, 'tianxia.sphere.metal')
    assert mine and theirs and other_sphere, sorted({str((a.parameters.get('typed') or {}).get('sphere'))
                                                     for a in engine.action_catalog.values()
                                                     if a.owner_id in {me_id, ally_id}})
    assert _lands(engine, foe, mine, me_id) == me_lands, \
        "the chosen creature's Resistance against the printed scope"
    assert _lands(engine, foe, theirs, ally_id) == ally_lands, \
        'another creature\'s own Spear line, which the printed sentence either names or does not'
    assert _lands(engine, foe, other_sphere, me_id) == other_sphere_lands, \
        'the same creature, another sphere'
    assert _lands(engine, foe, theirs, ally_id, kind='BLUDGEONING') == 10, \
        'a damage type the printed sentence does not name keeps the Resistance'


def _piercing_ability(engine, actor_id, sphere):
    """That creature's own ability of ``sphere`` whose printed damage is Piercing or Force."""
    for action in engine.action_catalog.values():
        if action.owner_id != actor_id:
            continue
        typed = action.parameters.get('typed') or {}
        if typed.get('sphere') != sphere:
            continue
        kinds = {str(kind).upper() for row in _walk(typed.get('effects')) if row.get('type') == 'damage'
                 for kind in (row.get('damage_types') or [])}
        if kinds & {'PIERCING', 'FORCE'}:
            return action.source_definition_id
    return None


def test_the_line_abilities_no_longer_strip_any_resistance_they_own():
    """The parser's accidental Resistance grant stays gone: no line grants Resistance to the very
    damage it is about to deal, and no line bypasses Resistance for a whole packet."""
    for talent, display in (('TAL_SPEAR_HEAVEN_PIERCING_SPEAR_LIGHT', 'Heaven-Piercing Spear Light'),
                            ('TAL_SPEAR_WORLD_TRANSFIXING_POINT', 'World-Transfixing Point')):
        types = [row.get('type') for row in _walk(_typed(_compiled(talent), display)['effects'])]
        assert 'resistance' not in types, (talent, types)
        assert 'ignore_resistance' not in types, (talent, types)
        assert 'target_resistance_ignored' in types, (talent, types)


@pytest.mark.parametrize('talent,display', [
    ('TAL_SPEAR_HEAVEN_PIERCING_SPEAR_LIGHT', 'Heaven-Piercing Spear Light'),
    ('TAL_SPEAR_WORLD_TRANSFIXING_POINT', 'World-Transfixing Point'),
])
def test_the_choose_one_creature_that_failed_riders_land_on_one_creature_only(talent, display):
    """"Choose one creature that failed" ran against everyone in the line; rider_after_failed_save
    applies them to the one creature chosen among those that failed."""
    top = _typed(_compiled(talent), display)['effects']
    choice = next(row for row in top if row.get('type') == 'rider_after_failed_save')
    scoped = {row.get('type') for row in choice['after']}
    assert 'reaction_denied' in scoped and 'speed' in scoped, scoped
    assert not any(row.get('type') in {'reaction_denied', 'speed', 'held_at_distance',
                                       'target_resistance_ignored'} for row in top), top


def _run_through_the_table(engine, actor, subject, effects, typed):
    """Resolve rows through combat.typed_executor.run_effects, the same call the table makes when a
    printed ability resolves."""
    action = next((a for a in engine.action_catalog.values() if a.owner_id == actor.entity_id),
                  next(iter(engine.action_catalog.values())))
    te.run_effects(te.Context(engine, actor, action, None, typed, [subject], subject, {}), effects)


def _react_to_a_marked_attack(monkeypatch, engine, reactor, attacker, ally):
    """The printed trigger, for real: a printed talent puts the mark on the attacker inside a
    committed action, and the engine's own reaction machinery (combat/typed_reactions
    ._offer_ally_attacked) answers the moment the mark lands, so every choice carries that action's
    intent and the whole transaction is the table's own."""
    original = Gate4ControllerEngine._append_event
    fired = []

    def run(engine_, event_type, *args, **kwargs):
        result = original(engine_, event_type, *args, **kwargs)
        if not fired and event_type == 'CONDITION_APPLIED' and str((result.payload or {}).get('condition_id')
                                                                    or '').startswith('condition:typed.mark.spear_intent.'):
            fired.append(result)
            typed_reactions._offer_ally_attacked(engine_, ally, attacker, {
                'source_definition_id': 'action:test.ally_attacked', 'action_name': 'Ally Attacked'},
                engine_._active_intent)
        return result

    monkeypatch.setattr(Gate4ControllerEngine, '_append_event', run)
    _use(engine, 'Spear Thrust: Apply Spear Intent')
    assert fired, 'the printed talent never put the Spear Intent mark on the attacker'
    assert te.bears_mark(attacker, reactor.entity_id, 'Spear Intent')


def _lock_row(talent):
    """The printed movement-lock row of a "choose one creature that failed" branch."""
    return [row for row in next(row for row in AUTH[talent]['effects']
                                if row.get('type') == 'rider_after_failed_save')['after']
            if row.get('type') == 'held_at_distance']


@pytest.mark.parametrize('talent,display,beneficiary', [
    # "does not apply to your Spear talents against it": the creature that CHOSE it, not the victim
    ('TAL_SPEAR_HEAVEN_PIERCING_SPEAR_LIGHT', 'Heaven-Piercing Spear Light', 'chooser'),
    # "does not apply", naming no source: any creature's damage, so no chooser is named
    ('TAL_SPEAR_WORLD_TRANSFIXING_POINT', 'World-Transfixing Point', 'anyone'),
])
def test_the_printed_bypass_says_whose_resistance_and_until_when(talent, display, beneficiary):
    """A player reading the pill must learn who may ignore what, and when it ends -- and the pill must
    promise no more than execution does.  Heaven-Piercing's pill names the CHOOSER's own Spear
    techniques as the beneficiary (AUTO56r2f1: it used to say "only that creature's spear techniques
    ignore it", which is the creature whose Resistance was set aside, so a player deciding which attacker
    benefits was told the opposite); World-Transfixing Point's names no source, so it promises any
    creature and names no chooser at all."""
    _bundle, engine, me, foe, _other, _ally = _fight(talent)
    _answers(engine, {'rider_failed_save': lambda options: [who for who in options if who == AN]})
    _use(engine, display)
    record = resistance_bypass.records(engine, foe)[0]
    pill = resistance_bypass.ignored_resistance_text(engine, foe, {'condition_id': resistance_bypass.CONDITION}, record)
    assert f"{foe.display_name}" in pill['text'] and 'Piercing and Force' in pill['text'], pill
    assert "start of " + me.display_name + "'s next turn" in pill['text'], pill
    handling = pill['handling']
    # both roles are named, and neither is confused with the other
    assert f"{foe.display_name}'s Resistance to Piercing and Force damage is set aside" in handling, pill
    if beneficiary == 'chooser':
        assert f"Only the spear techniques of {me.display_name}" in handling, pill
        assert f"never {foe.display_name}'s own" in handling, 'the victim is not the beneficiary'
    else:
        assert "Any creature's Piercing and Force damage" in handling, pill
        assert f"techniques of {me.display_name}" not in handling, 'this sentence named no source'
    assert 'condition' not in pill['text'].lower() and 'modifier' not in pill['text'].lower(), pill


def test_the_bypass_pill_promises_no_more_than_execution_does_for_every_scope_and_sphere_pair():
    """The two printed sentences are ``chooser``+sphere and ``anyone``+no sphere, but the row's two keys are
    independent, so all four pairs are reachable.  Each one must be described by what
    ``ignores_chosen_creature_resistance`` actually does: a sphere-limited ``anyone`` row still requires the
    packet's own sphere, so it promises every creature's techniques *of that sphere* and never every
    creature's damage; a sphere-less ``chooser`` row ignores the bypass for every one of the chooser's
    techniques, not only the technique that placed it (AUTO56r2f1).  With no engine the pill falls back to
    "the creature that chose it", which is the name a loaded record would replace with the real chooser."""
    victim = 'the Warden'
    rows = [dict(by_sphere='tianxia.sphere.spear', attacker_scope='anyone'),
            dict(by_sphere='', attacker_scope='anyone'),
            dict(by_sphere='tianxia.sphere.spear', attacker_scope='chooser'),
            dict(by_sphere='', attacker_scope='chooser')]
    for row in rows:
        record = {**row, "anchor_id": ME, "damage_types": 'PIERCING|FORCE',
                  "until": "until the start of Lian Feng's next turn", "label": "Resistance ignored",
                  "reading": "printed elsewhere"}
        text = resistance_bypass.ignored_resistance_text(
            None, _holder_named(victim), {'condition_id': resistance_bypass.CONDITION}, record)['handling']
        assert f"Only {victim}'s Resistance to Piercing and Force damage is set aside until the start of " \
               "Lian Feng's next turn" in text, (row, text)
        assert f"Only {victim}'s own" not in text, (row, text)
        anyone, sphere = row['attacker_scope'] == 'anyone', bool(row['by_sphere'])
        if anyone and sphere:
            assert "Every creature's spear techniques" in text, (row, text)
            assert "Any creature's Piercing and Force damage" not in text, (row, text)
        elif anyone:
            assert "Any creature's Piercing and Force damage" in text, (row, text)
        elif sphere:
            assert "Only the spear techniques of the creature that chose it" in text, (row, text)
        else:
            assert "Only the techniques of the creature that chose it" in text, (row, text)
            assert "the technique that placed it" not in text, (row, text)


def _holder_named(name):
    """The stand-in creature a condition pill is written for."""
    class _Holder:
        display_name = name
    return _Holder()


def test_world_transfixing_point_pins_exactly_one_creature_in_the_line():
    """"Choose one creature that failed": Speed 0, no Reactions, the movement lock and the Resistance
    bypass all land on the one creature chosen among those that failed."""
    bundle, engine, me, foe, _other, _ally = _fight('TAL_SPEAR_WORLD_TRANSFIXING_POINT')
    effects = _typed(bundle, 'World-Transfixing Point')['effects']
    choice = next(row for row in effects if row.get('type') == 'rider_after_failed_save')
    assert [row.get('type') for row in choice['after']] == ['speed', 'reaction_denied', 'target_resistance_ignored',
                                                           'held_at_distance'], choice
    _run_through_the_table(engine, me, foe, choice['after'], {'numbers': {}, 'duration': {'kind': 'instant'}})
    assert engine._effective_speed(foe) == 0, [str(m.value) for m in foe.modifiers.values()]
    assert any(str(c.condition_id).endswith('reaction_denied') for c in foe.conditions.values()), \
        [c.condition_id for c in foe.conditions.values()]
    assert approach_lock.records(engine, foe), [c.condition_id for c in foe.conditions.values()]
    assert resistance_bypass.records(engine, foe), [c.condition_id for c in foe.conditions.values()]


# --------------------------------------------------------- the printed movement lock, at the table


def test_the_lock_stops_the_step_that_would_cross_the_line_and_leaves_the_budget_alone():
    """"cannot willingly move closer to (or farther from) you": the creature that holds the lock is
    stopped before the step is paid, through the engine's own movement resolution, so position, the
    path and the movement allowance are all unchanged -- and the refusal is recorded on the move the
    table made.  (The lock is placed by the creature who used the ability, so the fighter here is the
    one who failed and the sparring creature is the anchor.)"""
    _bundle, engine, me, foe, _other, _ally = _fight('TAL_SPEAR_WORLD_TRANSFIXING_POINT')
    _run_through_the_table(engine, foe, me, _lock_row('TAL_SPEAR_WORLD_TRANSFIXING_POINT'),
                           {'numbers': {}, 'duration': {'kind': 'instant'}})
    assert approach_lock.records(engine, me)
    _ready(engine)
    engine._system_start_turn()
    me.movement_remaining_ft = engine._effective_speed(me)
    budget, start = me.movement_remaining_ft, me.position
    crossing = [c for c in engine.legal_candidates()
                if c.actor_id == ME and c.destination is not None
                and engine.grid.distance_ft(c.destination, foe.position)
                != engine.grid.distance_ft(start, foe.position)]
    assert crossing, 'no offered step crosses the line'
    candidate = crossing[0]
    engine.execute_intent(ActionIntent(intent_id='blocked', decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=ME, target_ids=candidate.target_ids, destination=candidate.destination))
    receipt = _events(engine, 'MOVEMENT_COMMITTED')[-1]
    assert me.position == start and me.movement_remaining_ft == budget, (me.position, start, me.movement_remaining_ft, budget)
    assert receipt.payload.get('interruptions'), receipt.payload
    said = str(receipt.payload['interruptions'][0].get('label') or receipt.payload['interruptions'][0])
    assert 'willingly' in said and foe.display_name in said, said
    # a step that keeps its distance is still offered and still free
    # every offered square on the way keeps the same distance from the anchor, so the whole path is legal
    sideways = [c for c in engine.legal_candidates()
                if c.actor_id == ME and c.destination is not None and c.destination.z == start.z
                and c.canonical_path
                        and all(engine.grid.distance_ft(cell, foe.position)
                                == engine.grid.distance_ft(start, foe.position) for cell in c.canonical_path)]
    assert sideways, 'no offered step keeps its distance'
    allowed = sideways[0]
    engine.execute_intent(ActionIntent(intent_id='allowed', decision_id=allowed.decision_id,
                                       candidate_id=allowed.candidate_id, state_version=allowed.state_version,
                                       actor_id=ME, target_ids=allowed.target_ids, destination=allowed.destination))
    assert me.position == allowed.destination, me.position


def test_a_step_that_keeps_its_distance_is_allowed_and_an_unmarked_creature_is_untouched():
    _bundle, engine, me, foe, _other, _ally = _fight('TAL_SPEAR_WORLD_TRANSFIXING_POINT')
    _run_through_the_table(engine, me, foe, _lock_row('TAL_SPEAR_WORLD_TRANSFIXING_POINT'),
                           {'numbers': {}, 'duration': {'kind': 'instant'}})
    here = (foe.position.x, foe.position.y)
    assert approach_lock.stop_at_the_line(engine, foe, here, (here[0], here[1] + 1), None) is None
    assert approach_lock.stop_at_the_line(engine, me, here, (here[0] - 1, here[1]), None) is None


def test_the_lock_says_when_it_ends_in_the_pill():
    """"until the lock ends" told a player nothing about whose turn; the pill now names the turn."""
    _bundle, engine, me, foe, _other, _ally = _fight('TAL_SPEAR_WORLD_TRANSFIXING_POINT')
    _run_through_the_table(engine, me, foe, _lock_row('TAL_SPEAR_WORLD_TRANSFIXING_POINT'),
                           {'numbers': {}, 'duration': {'kind': 'instant'}})
    record = approach_lock.records(engine, foe)[0]
    assert record['until'] == f"until the start of {me.display_name}'s next turn", record
    pill = approach_lock.held_at_distance_text(engine, foe, {'condition_id': approach_lock.CONDITION}, record)
    assert record['until'] in pill['text'], pill
    assert 'willingly' in pill['text'] and me.display_name in pill['text'], pill


def test_the_seam_is_inert_for_a_creature_with_no_record():
    _bundle, engine, me, foe, _other, _ally = _fight('TAL_SPEAR_WORLD_TRANSFIXING_POINT')
    assert approach_lock.records(engine, me) == [] and approach_lock.records(engine, foe) == []
    assert resistance_bypass.records(engine, foe) == []
    here = (foe.position.x, foe.position.y)
    assert approach_lock.stop_at_the_line(engine, foe, here, (foe.position.x - 1, foe.position.y), None) is None
    _resistant(engine, foe)
    assert _lands(engine, foe, 'system:test', AN) == 10


def test_pinning_strike_prevent_approach_lands_the_lock_on_the_creature_it_hit():
    """The printed option's own rows, resolved through the table: the lock lands on the creature the
    spear hit, and nothing is said to the GM any more."""
    _bundle, engine, me, foe, _other, _ally = _fight('TAL_SPEAR_PINNING_STRIKE')
    option = next(row for row in AUTH['TAL_SPEAR_PINNING_STRIKE']['modifier']['options']
                  if row['label'] == 'Prevent Approach')
    _run_through_the_table(engine, me, foe, option['effects'],
                           {'numbers': {'save_dc': 50}, 'duration': {'kind': 'instant'}})
    records = approach_lock.records(engine, foe)
    assert records and records[0]['mode'] == 'closer', [c.condition_id for c in foe.conditions.values()]
    assert records[0]['until'] == f"until the start of {me.display_name}'s next turn", records[0]
    assert not any('GM enforces manually' in text for text in _riders(engine)), _riders(engine)


def test_meteor_net_pins_the_creatures_that_failed_inside_the_cone():
    """"A creature that fails also cannot willingly move closer to you" uses the same effect."""
    bundle, engine, me, foe, _other, _ally = _fight('TAL_SPEAR_METEOR_NET_SPEAR_ART')
    on_fail = next(row for row in _walk(_typed(bundle, 'Meteor-Net Spear Art: 15-foot cone')['effects'])
                   if row.get('type') == 'save')['on_fail']
    assert [row.get('type') for row in on_fail][-1] == 'held_at_distance', on_fail
    _run_through_the_table(engine, me, foe, [on_fail[-1]], {'numbers': {}, 'duration': {'kind': 'instant'}})
    records = approach_lock.records(engine, foe)
    assert records and records[0]['mode'] == 'closer', [c.condition_id for c in foe.conditions.values()]


# ------------------------------- One Line Cannot Be Crossed: weapon damage, two options, one spared


def test_one_line_cannot_be_crossed_reacts_deals_its_weapon_damage_and_asks_for_two_of_five(monkeypatch):
    """The whole printed reaction, inside a committed action: "One creature bearing your Spear Intent
    ... attacks an ally adjacent to you" fires, the spear weapon's own damage lands, and the user is
    asked for exactly two of the five printed options, which are then the only ones that run.

    The typed attack had no damage row at all, and a cultivation_melee attack with none sets its own
    dice to None (combat/typed_executor.py:1271-1274), so the player paid the printed cost and hit for
    nothing.
    """
    bundle, engine, me, foe, _bystander, ally = _fight('TAL_SPEAR_ONE_LINE_CANNOT_BE_CROSSED', ally=ALLY)
    on_hit = _reaction_effects(bundle, 'TAL_SPEAR_ONE_LINE_CANNOT_BE_CROSSED', 'attack')['on_hit']
    assert [row['type'] for row in on_hit] == ['damage', 'rider_menu'], on_hit
    assert on_hit[0] == {'type': 'damage', 'weapon_damage': True, 'evidence': 'Make one approved Spear weapon attack'}
    menu = on_hit[1]
    assert menu['count'] == 2 and len(menu['options']) == 5
    asked = _answers(engine, {'spear_line_cannot_be_crossed': lambda options: ['pin', 'no_reactions']})
    before = foe.current_hp
    where = foe.position
    _react_to_a_marked_attack(monkeypatch, engine, me, foe, ally)
    damage = [e for e in _events(engine, 'DAMAGE_COMMITTED')
              if e.source_definition_id.endswith('ONE_LINE_CANNOT_BE_CROSSED')]
    assert damage and damage[0].payload['hp_damage'] > 0, _riders(engine)
    assert foe.current_hp < before
    rolled = str(_events(engine, 'DAMAGE_ROLLED')[0].payload.get('expression') or '')
    assert rolled.startswith('1d'), rolled
    # exactly the two chosen options ran, and the other three did not
    assert foe.movement_remaining_ft == 0, 'reduce remaining movement to 0'
    assert any(str(c.condition_id).endswith('reaction_denied') for c in foe.conditions.values())
    assert not any(str(c.condition_id).endswith('prone') for c in foe.conditions.values())
    assert foe.position == where, 'the push was not one of the two chosen, so nothing may move it'
    assert me.position == Position(x=3, y=6), 'the step was not chosen'
    assert [request['reaction_source_id'] for request in asked] == ['choice:needle.spear_line_cannot_be_crossed'], asked


def test_the_printed_push_is_the_only_chosen_option_that_moves_the_target(monkeypatch):
    """"push 10 feet" moves it, "reduce its remaining movement to 0" does not, and the only way to
    say that is to compare against the position saved before the action: comparing a creature with
    itself (AUTO56f2's assertion) is true whatever the engine does."""
    outcomes = {}
    for first in ('push', 'pin'):
        _bundle, engine, me, foe, _bystander, ally = _fight('TAL_SPEAR_ONE_LINE_CANNOT_BE_CROSSED', ally=ALLY)
        _answers(engine, {'spear_line_cannot_be_crossed': lambda options, pick=first: [pick, 'no_reactions']})
        where = foe.position
        _react_to_a_marked_attack(monkeypatch, engine, me, foe, ally)
        outcomes[first] = (engine, where, foe.position, foe.movement_remaining_ft)
    engine, where, after, remaining = outcomes['push']
    assert after != where, (after, where)
    assert engine.grid.distance_ft(after, where) == 10, (after, where)
    engine, where, after, remaining = outcomes['pin']
    assert after == where, (after, where)
    assert remaining == 0, 'the printed option that was chosen did run'


def _hit_list_probe(monkeypatch):
    """See exactly what this module's hit recorder left in the activation's scratch dict after each attack."""
    seen = []
    real = quiet_step.remember_a_hit

    def probe(ctx, target, hit, critical):
        real(ctx, target, hit, critical)
        # copy: the recorder appends to one growing list, so a reference would show later hits too
        seen.append((hit, list(ctx.damage_cache.get(quiet_step.HIT_KEY) or ())))

    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "attack_result", [probe])
    return seen


def test_the_settled_hit_records_the_creature_the_attack_actually_reached(monkeypatch):
    """"one creature hit by this talent" means the creature that was really struck.  Native resolution
    can send the attack somewhere else (Guardian Interpose takes the blow instead), and the
    ``attack_result`` hook is handed the ORIGINALLY DECLARED target, so recording ``target.entity_id``
    offered a creature that was never touched and left the creature actually struck out of the
    exemption.  Two creatures are declared here and the blow aimed at one of them is redirected onto the
    bystander, which ``rider_targets`` could never have chosen: the exemption must offer the bystander,
    which was actually struck, and must not offer the declared target, which was not."""
    _bundle, engine, me, foe, other, _ally = _fight('TAL_SPEAR_FLOWERS_IN_THE_STORM', bystander=FOREIGN,
                                                    rival=RIVAL)
    assert other is not None
    seen = _hit_list_probe(monkeypatch)
    monkeypatch.setitem(ext._HOOKS, "retarget_attack", [
        lambda engine_, attacker, defender, intent_, context: {"source_id": "test:interpose",
                                                               "target_id": other.entity_id}
        if defender.entity_id == foe.entity_id else None])
    asked = _answers(engine, {'rider_targets': lambda options: options[:2],
                              'quiet_step_creature': lambda options: [who for who in options
                                                                     if who == other.entity_id],
                              'move_without_provoking': _walk_away_from(engine, foe)})
    _ready(engine)
    _use(engine, 'Flowers in the Storm')
    rival = engine.state.actors[RIVAL]
    hit = {who for event in _events(engine, 'DAMAGE_COMMITTED') if event.actor_id == ME
           for who in event.target_ids}
    # the declared target's blow landed on the bystander instead; the rival's own blow was not redirected
    assert hit == {other.entity_id, rival.entity_id}, hit
    assert foe.entity_id not in hit, 'the declared target was never hit'
    recorded = [row[1] for row in seen if row[0]][-1]      # the last hit's list is the whole activation
    assert sorted(recorded) == sorted([other.entity_id, rival.entity_id]), recorded
    assert foe.entity_id not in recorded, 'the declared target was never hit, so it was never recorded'
    chooser = next(request for request in asked if request['reaction_source_id'].endswith('quiet_step_creature'))
    assert sorted(chooser['legal_option_ids']) == sorted([other.entity_id, rival.entity_id]), chooser
    assert foe.entity_id not in chooser['legal_option_ids'], 'the declared target was never hit'
    # and the printed step named the creature that was actually struck
    assert not any('skips nobody' in text for text in _resolved_step_logs(engine)), _resolved_step_logs(engine)
    assert any(other.display_name in text for text in _resolved_step_logs(engine)), _resolved_step_logs(engine)
    assert not any(foe.display_name in text and 'opportunity attack' in text for text in _resolved_step_logs(engine)), \
        _resolved_step_logs(engine)


def test_the_hit_recorder_is_inert_for_an_ability_with_no_printed_step():
    """An ability that prints no "move N feet without provoking" row must leave this plug-in's scratch
    dict exactly as it was, even for a settled hit: the recorder returns before it reads anything.  Before
    this the recorder booked every typed attack on the table, which coupled unrelated characters to this
    module's bookkeeping (owner checklist 3).  ``test_the_settled_hit_records_the_creature_the_attack_
    actually_reached`` is the other half: the recorder is still collecting for an ability that does print
    the step, so this is a guard and not a disconnection."""
    bundle, engine, me, foe, _other, _ally = _fight('TAL_SPEAR_PINNING_STRIKE')
    context = te.Context(engine, me, None, None, _typed(bundle, 'Pinning Strike: Pinning Strike'), [foe], foe)
    assert quiet_step.has_step(context) is False, 'this talent prints no step'
    quiet_step.remember_a_hit(context, foe, True, False)
    assert context.damage_cache == {}, 'an ability with no printed step wrote into the scratch dict'
    assert quiet_step.hits_this_activation(context) == []


def test_a_step_printed_inside_an_option_is_a_printed_step(monkeypatch):
    """One Line Cannot Be Crossed prints its step as one of the five options its reaction menu offers, so
    the row sits at ``effects[1].on_hit[1].options[4].effects[0]`` -- inside ``options``, a container the
    engine really runs (``rider_menu`` executes ``option["effects"]``).  The guard delegated to
    ``typed_executor._walk_rows``, which descends only into the branch containers, so it reported that
    this talent prints no step at all and its settled hits were never recorded.  Before the fix the first
    assert below fails (``has_step`` is False for exactly this shape)."""
    bundle, engine, me, foe, other, ally = _fight('TAL_SPEAR_ONE_LINE_CANNOT_BE_CROSSED',
                                                 bystander=FOREIGN, ally=ALLY)
    assert other is not None
    attack = _reaction_effects(bundle, 'TAL_SPEAR_ONE_LINE_CANNOT_BE_CROSSED', 'attack')
    step = next(option for option in attack['on_hit'][1]['options'] if option['id'] == 'step')['effects'][0]
    assert step == {'type': 'move_without_provoking', 'applies_to': 'self', 'distance_ft': 10,
                    'exempt_from': 'target',
                    'evidence': 'move 10 feet without provoking opportunity attacks from the target'}, step
    typed = te.Context(engine, me, None, None, {'effects': [attack]}, [foe], foe)
    assert quiet_step.has_step(typed) is True, 'a step printed inside an option was not discovered'
    # the same question asked of the option container on its own, and of a row that is only a branch child
    assert quiet_step.has_step(te.Context(engine, me, None, None, {'effects': [attack['on_hit'][1]]}, [foe], foe))
    assert not quiet_step.has_step(te.Context(engine, me, None, None,
                                              {'effects': [{'type': 'attack',
                                                            'options': [{'label': 'blow', 'effects': [
                                                                {'type': 'damage'}]}]}]}, [foe], foe)), \
        'an option with no step row must stay inert'
    # options nest: a step two containers deep is still the activation's own printed row
    deep = {'effects': [{'type': 'attack', 'options': [{'label': 'outer', 'effects': [
        {'type': 'rider_menu', 'options': [{'label': 'inner', 'effects': [
            {'type': 'move_without_provoking', 'distance_ft': 5, 'exempt_from': 'creatures_hit'}]}]}]}]}]}
    assert quiet_step.has_step(te.Context(engine, me, None, None, deep, [foe], foe))

    # and for real, through the table: a settled hit on a step printed inside an option is recorded, so the
    # printed exemption has a creature to name instead of saying it hit nobody
    seen = _hit_list_probe(monkeypatch)
    _answers(engine, {'spear_line_cannot_be_crossed': lambda options: ['step', 'no_reactions'],
                      'move_without_provoking': _walk_away_from(engine, other)})
    start = me.position
    _react_to_a_marked_attack(monkeypatch, engine, me, foe, ally)
    recorded = [row[1] for row in seen if row[0]]
    assert recorded, 'a confirmed attack recorded no hit for a step printed inside an option'
    hit = {who for event in _events(engine, 'DAMAGE_COMMITTED')
           if str(event.source_definition_id or '').endswith('ONE_LINE_CANNOT_BE_CROSSED')
           for who in event.target_ids}
    assert hit and set(recorded[-1]) <= hit, (recorded[-1], hit)
    assert foe.entity_id in recorded[-1], 'the creature the attack actually struck was not recorded'
    assert not any('skips nobody' in text for text in _riders(engine)), _riders(engine)
    assert me.position != start, 'the printed 10 feet were not walked'
    assert not me.turn_flags.get('oa_free_ft'), 'no turn-long pool for the rest of the turn'


def test_an_option_printed_creatures_hit_offers_the_creatures_it_hit(monkeypatch):
    """The exemption the review named: a ``move_without_provoking`` row printed with
    ``exempt_from: "creatures_hit"`` INSIDE an option offers the creatures this activation hit and grants
    the exemption.  The guard missed option rows, so the recorder held nothing and the step offered no
    creature and spared nobody despite successful attacks.  The exemption candidates are read from the
    recorded hits, so this drives the option-nested row end to end at the effect itself."""
    _bundle, engine, me, foe, _other, _ally = _fight('TAL_SPEAR_FLOWERS_IN_THE_STORM', bystander=FOREIGN,
                                                     rival=RIVAL)
    rival = engine.state.actors[RIVAL]
    action = next(row for row in engine.action_catalog.values()
                  if str(row.display_name).startswith('Flowers in the Storm'))
    nested = {'effects': [{'type': 'attack', 'options': [{'label': 'printed option', 'effects': [
        {'type': 'move_without_provoking', 'applies_to': 'self', 'distance_ft': 5,
         'exempt_from': 'creatures_hit', 'optional': True,
         'evidence': 'move 5 feet without provoking opportunity attacks from one creature hit by this talent'}]}]}]}
    context = te.Context(engine, me, action, None, nested, [foe], foe)
    assert quiet_step.has_step(context) is True, 'the option-nested step row was not discovered'
    quiet_step.remember_a_hit(context, foe, True, False)
    quiet_step.remember_a_hit(context, rival, True, False)
    assert quiet_step.hits_this_activation(context) == [foe.entity_id, rival.entity_id]

    offered = {}

    def fake_ask(_engine, _intent, _checkpoint, _actor, _choice_id, options, **kwargs):
        offered['options'] = list(options)
        offered['kwargs'] = kwargs
        return list(options)[:1]

    from combat.ext import needle as needle_module
    monkeypatch.setattr(needle_module, 'ask', fake_ask)
    spared = quiet_step._choose_exempt(context, engine, None)
    assert sorted(offered['options']) == sorted([foe.entity_id, rival.entity_id]), offered
    assert spared == [foe.entity_id], spared
    assert offered['kwargs']['maximum'] == 1, offered['kwargs']
    # a missed activation still offers nobody, so the step says it hit nobody instead of naming a bystander
    empty = te.Context(engine, me, action, None, nested, [foe], foe)
    quiet_step.remember_a_hit(empty, foe, False, False)
    assert quiet_step._choose_exempt(empty, engine, None) == []


def test_the_printed_step_spares_only_the_creature_the_text_names(monkeypatch):
    """"move 10 feet without provoking opportunity attacks from the target": the reaction's target is
    spared and the bystander that the printed sentence does not name still gets its window.  The old
    row handed out a turn-long pool that skipped every enemy's reaction."""
    bundle, engine, me, foe, other, ally = _fight('TAL_SPEAR_ONE_LINE_CANNOT_BE_CROSSED',
                                                  bystander=FOREIGN, ally=ALLY)
    assert other is not None
    step = next(option for option in
                _reaction_effects(bundle, 'TAL_SPEAR_ONE_LINE_CANNOT_BE_CROSSED', 'attack')['on_hit'][1]['options']
                if option['id'] == 'step')['effects'][0]
    assert step == {'type': 'move_without_provoking', 'applies_to': 'self', 'distance_ft': 10,
                    'exempt_from': 'target', 'evidence': 'move 10 feet without provoking opportunity attacks from the target'}
    # "Choose two": the printed step plus the printed Reactions denial
    _answers(engine, {'spear_line_cannot_be_crossed': lambda options: ['step', 'no_reactions'],
                      'move_without_provoking': _walk_away_from(engine, other)})
    start = me.position
    _react_to_a_marked_attack(monkeypatch, engine, me, foe, ally)
    assert _events(engine, 'MOVEMENT_COMMITTED') and me.position != start, (me.position, start)
    asked = {who for e in _events(engine, 'REACTION_WINDOW_OPENED')
             if e.payload.get('checkpoint') == 'LEAVE_REACH' for who in e.target_ids}
    assert other.entity_id in asked, 'the bystander must keep its legal opportunity attack'
    assert foe.entity_id not in asked, 'the printed target must be spared'
    assert not me.turn_flags.get('oa_free_ft'), 'no turn-long pool for the rest of the turn'


def test_flowers_in_the_storm_spares_one_creature_it_hit_and_no_other():
    """"You may move 5 feet after resolving all attacks without provoking opportunity attacks from one
    creature hit by this talent": the user chooses which of the creatures it hit is spared, and the
    creature it did not hit still gets its window."""
    bundle, engine, me, _foe, other, _ally = _fight('TAL_SPEAR_FLOWERS_IN_THE_STORM',
                                                    bystander=FOREIGN, rival=RIVAL)
    assert other is not None
    asked = _answers(engine, {'rider_targets': lambda options: options[:2],
                              'quiet_step_creature': lambda options: options[:1],
                              'move_without_provoking': _walk_away_from(engine, other)})
    _ready(engine)
    start = me.position
    _use(engine, 'Flowers in the Storm')
    hit = [who for event in _events(engine, 'DAMAGE_COMMITTED') if event.actor_id == ME for who in event.target_ids]
    assert len(hit) == 2, hit
    spared = next(request for request in asked if request['reaction_source_id'].endswith('quiet_step_creature'))
    assert sorted(spared['legal_option_ids']) == sorted(hit), spared
    # the step names the spared creature where the player reads it
    assert any(spared['legal_option_ids'][0] in text or engine.state.actors[
        spared['legal_option_ids'][0]].display_name in text for text in _resolved_step_logs(engine)), _resolved_step_logs(engine)
    assert me.position != start, 'the printed 5 feet were not walked'
    windows = {who for e in _events(engine, 'REACTION_WINDOW_OPENED')
               if e.payload.get('checkpoint') == 'LEAVE_REACH' for who in e.target_ids}
    assert other.entity_id in windows, 'an enemy the sentence does not name must keep its opportunity attack'
    assert not me.turn_flags.get('oa_free_ft'), 'no turn-long pool for the rest of the turn'


def test_flowers_in_the_storm_hands_the_protection_to_nobody_when_every_attack_missed():
    """Every attack missed: there is no creature the sentence names, so the step skips nobody's
    opportunity attack and says so."""
    _bundle, engine, me, _foe, other, _ally = _fight('TAL_SPEAR_FLOWERS_IN_THE_STORM', bystander=FOREIGN,
                                                      rival=RIVAL, sure_hit=False)
    _answers(engine, {'rider_targets': lambda options: options[:2],
                      'move_without_provoking': _walk_away_from(engine, other)})
    _ready(engine)
    _use(engine, 'Flowers in the Storm')
    assert not [e for e in _events(engine, 'DAMAGE_COMMITTED') if e.actor_id == ME]
    assert any('skips nobody' in text for text in _resolved_step_logs(engine)), _resolved_step_logs(engine)
    windows = {who for e in _events(engine, 'REACTION_WINDOW_OPENED')
               if e.payload.get('checkpoint') == 'LEAVE_REACH' for who in e.target_ids}
    assert other.entity_id in windows, 'a step that spared nobody still provokes'
    assert not me.turn_flags.get('oa_free_ft')


@pytest.mark.parametrize('barrier', ['temporary_hp', 'immunity'], ids=['temporary_hp_absorbed', 'reduced_to_nothing'])
def test_flowers_in_the_storm_spares_a_creature_its_hit_that_cost_no_normal_hp(barrier):
    """"one creature hit by this talent" is the settled hit, not a creature that lost normal Hit
    Points.  One of the two creatures it hit costs it nothing: the whole packet went into Temporary HP,
    or the creature's own Immunity removed all of it.  It is still a hit, so the printed line may spare
    it -- AUTO56f2 dropped such a creature from the chooser and said the step had hit nobody."""
    _bundle, engine, me, foe, other, _ally = _fight('TAL_SPEAR_FLOWERS_IN_THE_STORM',
                                                     bystander=FOREIGN, rival=RIVAL)
    assert other is not None
    rival = engine.state.actors[RIVAL]
    # one chosen creature is hit for nothing at all; the other is hit normally
    if barrier == 'temporary_hp':
        spared, unhurt = foe, rival
        foe.temporary_hp = 500
    else:
        spared, unhurt = rival, foe
        engine._add_modifier(spared, 'test:printed', 'damage_immunity', 'ADD', 'PIERCING', 'ALWAYS', expires_on=None)
    asked = _answers(engine, {'rider_targets': lambda options: options[:2],
                              'quiet_step_creature': lambda options: [who for who in options if who == spared.entity_id],
                              'move_without_provoking': _walk_away_from(engine, other)})
    _ready(engine)
    where = me.position
    _use(engine, 'Flowers in the Storm')
    # both attacks landed, and only the other creature lost normal Hit Points
    assert [bool(e.payload.get('provisional_hit')) for e in _events(engine, 'ATTACK_ROLLED')] == [True, True]
    committed = {who: e for e in _events(engine, 'DAMAGE_COMMITTED') if e.actor_id == ME for who in e.target_ids}
    assert sorted(committed) == sorted([foe.entity_id, rival.entity_id]), committed
    assert int(committed[spared.entity_id].payload['hp_damage']) == 0, committed[spared.entity_id].payload
    assert int(committed[unhurt.entity_id].payload['hp_damage']) > 0, committed[unhurt.entity_id].payload
    assert spared.current_hp == 5000 and spared.temporary_hp < 5000, (spared.current_hp, spared.temporary_hp)
    chooser = next(request for request in asked if request['reaction_source_id'].endswith('quiet_step_creature'))
    assert sorted(chooser['legal_option_ids']) == sorted([foe.entity_id, rival.entity_id]), chooser
    assert not any('skips nobody' in text for text in _resolved_step_logs(engine)), _resolved_step_logs(engine)
    assert any(spared.display_name in text for text in _resolved_step_logs(engine)), _resolved_step_logs(engine)
    assert me.position != where, 'the printed 5 feet were not walked'


# ------------------------------------------ the successful-save branch keeps ONE printed option


def test_a_successful_save_of_pinned_heaven_gives_only_the_one_printed_option():
    """"Successful Save: the first of them": the movement lock must not ride along with the Stunned.
    The new row carried no menu_success marker, so any selected option ran on a successful save
    (combat/effect_eligibility.py:62-65 -> combat/ext/menus.picked), which applied Stunned AND the
    movement lock."""
    bundle, engine, me, foe, _other, _ally = _fight('TAL_SPEAR_THE_POINT_THAT_PINNED_HEAVEN_TO_EARTH', dc=PASS)
    for name in ('The Point That Pinned Heaven to Earth: Spear Line',
                 'The Point That Pinned Heaven to Earth: Spear Light'):
        typed = _typed(bundle, name)
        menu = typed['effects'][0]
        on_success = next(row for row in _walk(typed['effects']) if row.get('type') == 'save')['on_success']
        assert [row['option'] for row in on_success] == list(menu['options']), name
        assert all(row.get('menu_success') for row in on_success), \
            (name, [row['option'] for row in on_success if not row.get('menu_success')])
    menu = _typed(bundle, 'The Point That Pinned Heaven to Earth: Spear Line')['effects'][0]
    menu_id, options = menu['id'], list(menu['options'])
    for option in ('Held at Distance', 'Stunned', 'No Reactions'):
        menus.pick(engine, me, menu_id, option, 'system:test')   # count 3: the oldest pick would be replaced
    assert menus.picks(engine, me, menu_id) == ['Held at Distance', 'Stunned', 'No Reactions']
    _use(engine, 'The Point That Pinned Heaven to Earth: Spear Line')
    assert any(str(c.condition_id).endswith('stunned') for c in foe.conditions.values()), \
        [c.condition_id for c in foe.conditions.values()]
    assert approach_lock.records(engine, foe) == [], \
        'a successful save may only apply the first of the chosen options'


def test_the_earliest_printed_option_among_those_chosen_is_what_a_save_gives():
    """"Successful Save: the first of them" -- the first option in printed order among the three
    chosen, which is what the shared menu picks, is the one that lands.  Choosing three later
    options gives the lock, and no Stunned."""
    bundle, engine, me, foe, _other, _ally = _fight('TAL_SPEAR_THE_POINT_THAT_PINNED_HEAVEN_TO_EARTH', dc=PASS)
    menu = _typed(bundle, 'The Point That Pinned Heaven to Earth: Spear Line')['effects'][0]
    for option in ('Held at Distance', 'Spear Intent', 'Pushed 30 Feet'):
        menus.pick(engine, me, menu['id'], option, 'system:test')
    assert menus.picks(engine, me, menu['id']) == ['Held at Distance', 'Spear Intent', 'Pushed 30 Feet']
    _use(engine, 'The Point That Pinned Heaven to Earth: Spear Line')
    assert approach_lock.records(engine, foe), [c.condition_id for c in foe.conditions.values()]
    assert not any(str(c.condition_id).endswith('stunned') for c in foe.conditions.values())
    assert not any(str(c.condition_id).endswith('reaction_denied') for c in foe.conditions.values())


def test_the_failed_save_branch_of_pinned_heaven_still_applies_every_chosen_option():
    """The marker only gates the successful-save branch; a failure keeps all three."""
    _bundle, engine, me, foe, _other, _ally = _fight('TAL_SPEAR_THE_POINT_THAT_PINNED_HEAVEN_TO_EARTH', dc=FAIL)
    menu = AUTH['TAL_SPEAR_THE_POINT_THAT_PINNED_HEAVEN_TO_EARTH']['options'][0]['effects'][0]
    for option in ('Held at Distance', 'Stunned', 'No Reactions'):
        menus.pick(engine, me, menu['id'], option, 'system:test')
    assert menus.picks(engine, me, menu['id']) == ['Held at Distance', 'Stunned', 'No Reactions']
    assert 'Stunned' == menu['options'][0]   # printed first, so it is the successful-save option here
    _use(engine, 'The Point That Pinned Heaven to Earth: Spear Line')
    assert approach_lock.records(engine, foe)
    assert any(str(c.condition_id).endswith('stunned') for c in foe.conditions.values())


# -------------------------------------------------------------- use limits and covered lines


def test_spear_sovereign_incarnation_is_once_per_long_rest_not_once_per_turn():
    """"Use Limit: Once per long rest" was read as 'once per turn', so the table offered the
    transformation again every turn."""
    assert AUTH['TAL_SPEAR_SPEAR_SOVEREIGN_INCARNATION']['use_limit'] == 'once_per_long_rest'
    resources = [resource for resource, _amount in
                 _flat_cost(_row(_compiled('TAL_SPEAR_SPEAR_SOVEREIGN_INCARNATION'),
                                 'Spear-Sovereign Incarnation')['costs'])]
    assert any('uses.' in resource for resource in resources), resources


@pytest.mark.parametrize('talent', [
    'TAL_SPEAR_LONG_SHAFT_DISCIPLINE',      # 'ordinary attack reach does not increase' holds by construction
    'TAL_SPEAR_TEN_THOUSAND_SPEAR_SHADOWS',  # the one sentence describes the area the zone row already makes
    'TAL_SPEAR_ARMY_BREAKING_THRUST',        # cost + use limit + all five options were already typed
    'TAL_SPEAR_PURSUIT_SPEAR',               # the two halves of its own option menu
    'TAL_SPEAR_INTERCEPTING_THRUST',
    'TAL_SPEAR_ONE_LINE_CANNOT_BE_CROSSED',
    'TAL_SPEAR_PINNING_STRIKE',
])
def test_these_talents_leave_nothing_for_the_gm(talent):
    assert AUTH[talent]['coverage'] == 'FULL', (talent, AUTH[talent]['riders'])


def test_flowers_in_the_storm_binds_the_printed_line_to_the_chosen_weapon():
    """The shared selector measures the held weapon before offering its capped roster.

    Actual service selection at ten feet, hit-only consequences and reload are
    checked by test_a2_spear_service; this assertion preserves the reviewed contract.
    """
    record = AUTH['TAL_SPEAR_FLOWERS_IN_THE_STORM']
    assert record['coverage'] == 'FULL' and record['riders'] == []
    assert record['effects'][0]['type'] == 'attach_spear_weapon'
    selector = record['effects'][1]
    assert selector['type'] == 'rider_targets' and selector['range_from_weapon']
    assert selector['count'] == 'pb' and selector['hostile_only']
