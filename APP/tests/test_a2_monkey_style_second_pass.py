"""Monkey Style second pass A2MONKEYST (2026-10-11): supported beast-form benefits, explicit GM reminders,
and Tail-Qi Hook's printed list, resolved through the real table.

Authority -> CombatService -> session execute_intent -> cold reload, against the printed text in
APP/authority/typed_mechanics/rules_text.json ("Monkey Style", the talents). Inert without the talent, so each test
gives the sheet only the printed talents it needs.
"""
import pytest

from combat.ext import monkey
from tests.auto_worker1_support import fight, act, reload, action_sender, settle, cell_send, turn, LEFT, RIGHT

SPHERE = 'tianxia.sphere.monkey_style'
M = 'TAL_MONKEY_STYLE_'
TRANSFORM = 'tianxia.talent.monkey_style.seventy_two_earthly_transformations'
TRICKSTER = M + 'HUNDRED_HANDED_TRICKSTER'
HOOK = M + 'TAIL_QI_HOOK'

# The eight printed form templates. Each is one option of the talent, so each is one table action.
TEMPLATES = ['Tiny Scout', 'Swift Beast', 'Climbing Beast', 'Aquatic Beast',
             'Flying Beast', 'Powerful Beast', 'Armored Beast', 'Burrowing Beast']


def form(c, t, m, label, ai=False):
    """Transform into the printed ``label`` template and commit it through the session."""
    return settle(action_sender(c, t, m, f'Seventy-Two Earthly Transformations: {label}', ai=ai))


def beast(tmp_path, label, **kw):
    c, t, m = fight(tmp_path, [TRANSFORM], spheres=[SPHERE], cl=18, left_resource="Stamina", **kw)
    result, prompts = form(c, t, m, label)
    assert result['status'] == 'COMMITTED', result
    return reload(c, m).state.actors[LEFT], prompts


def conditions(actor, suffix):
    return [c for c in actor.conditions.values() if c.condition_id.endswith(suffix)]


def modifiers(actor, field):
    return [m for m in actor.modifiers.values() if m.target_field == field]


def effective_size(actor):
    return actor.transformed_size_category or actor.size_category


@pytest.mark.parametrize('label', TEMPLATES)
def test_every_printed_template_is_a_real_option(tmp_path, label):
    """All eight printed form templates exist on the table; before this pass three of them were not typed at all."""
    c, t, m = fight(tmp_path, [TRANSFORM], spheres=[SPHERE], cl=18, left_resource="Stamina")
    menu = t.state(m)['menu']
    groups = [g for g in menu['actions'] if 'seventy_two_earthly_transformations' in str(g)]
    labels = [str(g.get('label')) for g in groups]
    assert len(labels) == len(TEMPLATES), labels
    assert any(f'Seventy-Two Earthly Transformations: {label}' == str(g.get('label'))
               for g in menu['actions']), label


@pytest.mark.parametrize('label', TEMPLATES)
def test_transforming_commits_and_survives_a_cold_reload(tmp_path, label):
    """The printed transformation is committed through the session and is still the fighter's own state after a
    cold reload, for every printed template."""
    me, prompts = beast(tmp_path, label)
    assert conditions(me, monkey.BEAST_FORM), f'{label}: the transformation is not on the fighter'
    assert not prompts, prompts
    assert me.resources['resource:core.stamina'] == 90, 'the real transformation pays its printed 10 Stamina'


@pytest.mark.parametrize(('label', 'required'), [
    ('Tiny Scout', ('Tiny size', 'Speed 30 feet', 'Climb Speed 30 feet')),
    ('Swift Beast', ('Speed 60 feet',)),
    ('Climbing Beast', ('Climb Speed 50 feet',)),
    ('Aquatic Beast', ('Swim Speed 60 feet', 'breathe underwater')),
])
def test_form_reminders_print_numeric_unsupported_movement_after_reload(tmp_path, label, required):
    """The committed and reloaded form action shows newcomers each unsupported template benefit in plain text."""
    c, t, m = fight(tmp_path, [TRANSFORM], spheres=[SPHERE], cl=18, left_resource="Stamina")
    result, _ = form(c, t, m, label)
    assert result['status'] == 'COMMITTED', result
    engine = reload(c, m)
    action = next(a for a in engine.action_catalog.values()
                  if TRANSFORM in a.source_definition_id and
                  any(e.get('type') == 'monkey_transform' for e in a.parameters.get('typed', {}).get('effects', [])))
    riders = ' '.join(action.parameters['typed'].get('riders', []))
    for phrase in required:
        assert phrase in riders, (phrase, riders)


def test_armored_beast_applies_ac_and_slows(tmp_path):
    """"Armored Beast: +3 AC, Speed reduced by 10 feet"."""
    me, _ = beast(tmp_path, 'Armored Beast')
    assert [int(m.value) for m in modifiers(me, 'armor_class')] == [3], 'the printed +3 AC is not applied'
    assert [int(m.value) for m in modifiers(me, 'speed_ft')] == [-10], 'the printed walking Speed penalty is retained'


def test_powerful_beast_applies_large_size(tmp_path):
    """"Powerful Beast: Large size"."""
    me, _ = beast(tmp_path, 'Powerful Beast')
    growth = conditions(me, '.size_change')
    assert growth, 'the printed Large size is not applied'
    assert growth[0].data.get('growth_category') == 'Large', growth[0].data


def test_transform_is_inert_without_the_talent(tmp_path):
    """The seam is inert without the printed talent: no beast form may be taken."""
    c, t, m = fight(tmp_path, [], spheres=[SPHERE], cl=18, left_resource="Stamina")
    e = reload(c, m)
    menu = t.state(m)['menu']
    assert not [g for g in menu['actions'] if 'seventy_two_earthly_transformations' in g.get('source_definition_id', '')]
    assert not conditions(e.state.actors[LEFT], monkey.BEAST_FORM)


def test_trickster_activation_does_not_claim_a_free_cost_bypass(tmp_path):
    """The unsupported Borrowed Treasure free-use benefit remains a Game Master reminder."""
    c, t, m = fight(tmp_path, [TRICKSTER], spheres=[SPHERE], cl=18, left_resource="Stamina")
    result, _ = settle(action_sender(c, t, m, 'Hundred-Handed Trickster'))
    assert result['status'] == 'COMMITTED', result
    engine = reload(c, m)
    assert not hasattr(monkey, 'free_borrow_earned')
    assert not hasattr(monkey, '_free_borrow')
    assert not hasattr(monkey, 'FREE_BORROW')

def test_trickster_does_not_create_a_free_use_from_an_unrelated_hit(tmp_path):
    """A hit cannot create a free Borrowed Treasure bypass now that the misleading event hooks are gone."""
    c, t, m = fight(tmp_path, [TRICKSTER], spheres=[SPHERE], cl=18, left_resource="Stamina",
                    prepare=[{'type': 'attack', 'attack_kind': 'melee', 'no_damage': True}])
    result, _ = settle(action_sender(c, t, m, 'Hundred-Handed Trickster'))
    assert result['status'] == 'COMMITTED', result
    result, _ = settle(action_sender(c, t, m, 'Prepare'))
    assert result['status'] == 'COMMITTED', result
    engine = reload(c, m)
    assert not any('borrow' in str(key).lower() for key in engine.state.actors[LEFT].turn_flags)
    assert not hasattr(monkey, 'free_borrow_earned')


def test_tail_qi_hook_asks_its_printed_list(tmp_path):
    """"Choose one:" is a real question carrying all four printed results."""
    c, t, m = fight(tmp_path, [HOOK], spheres=[SPHERE], cl=18, left_resource="Stamina")
    wanted = 'pull yourself 5 feet toward a stable object or climbable surface'

    def by_label(prompt):
        return [o['id'] for o in prompt['choice']['options'] if o['label'] == wanted]

    result, prompts = settle(action_sender(c, t, m, 'Tail-Qi Hook', ai=False), by_label)
    assert result['status'] == 'COMMITTED', result
    # The printed list is asked first, then the printed 5-foot movement asks where to step.
    listed = [p for p in prompts if any('open or close an unlocked door' in o['label']
                                        for o in (p['choice'].get('options') or []))]
    assert len(listed) == 1, prompts
    labels = [o['label'] for o in listed[0]['choice']['options']]
    for printed in ('pull a Tiny unattended object to your hand',
                    'push or drag a Small unattended object 5 feet',
                    'open or close an unlocked door, drawer, curtain, or latch',
                    'pull yourself 5 feet toward a stable object or climbable surface'):
        assert printed in labels, (printed, labels)


def test_tail_qi_hook_is_inert_without_the_talent(tmp_path):
    c, t, m = fight(tmp_path, [], spheres=[SPHERE], cl=18, left_resource="Stamina")
    menu = t.state(m)['menu']
    assert not [g for g in menu['actions'] if g.get('source_definition_id', '').endswith(HOOK)]



@pytest.mark.parametrize('label', ['Tiny Scout', 'Swift Beast', 'Climbing Beast', 'Aquatic Beast', 'Flying Beast', 'Burrowing Beast'])
def test_form_movement_does_not_inflate_walking_budget(tmp_path, label):
    """Alternate form speeds must not add to ordinary walking speed in the live reloaded engine."""
    c, t, m = fight(tmp_path, [TRANSFORM], spheres=[SPHERE], cl=18, left_resource="Stamina")
    result, _ = form(c, t, m, label)
    assert result['status'] == 'COMMITTED', result
    engine = reload(c, m)
    actor = engine.state.actors[LEFT]
    assert engine._effective_speed(actor) == actor.speed_ft == 30
    assert not modifiers(actor, 'speed_ft')


def test_transformed_hostile_passage_asks_named_link_question_and_commits(tmp_path):
    """A player can choose the transformed passage Link; prompt names the talent/creature and explains use/expiry."""
    caper = M + 'CAPERING_FOOTWORK'
    def make_opponent_huge(bundle):
        if bundle['actor_template']['entity_id'] == RIGHT:
            bundle['actor_template']['size_category'] = 'Huge'
    c, t, m = fight(tmp_path, [TRANSFORM, caper], spheres=[SPHERE], cl=18, left_resource="Stamina",
                  bundle_edit=make_opponent_huge)
    result, _ = form(c, t, m, 'Powerful Beast')
    assert result['status'] == 'COMMITTED', result
    settle(lambda answers: act(t, m, 'end', answers))
    turn(t, m, LEFT)
    result, _ = settle(action_sender(c, t, m, 'Capering Footwork'))
    assert result['status'] == 'COMMITTED', result
    engine = reload(c, m)
    assert conditions(engine.state.actors[LEFT], monkey.BEAST_FORM)
    assert conditions(engine.state.actors[LEFT], '.monkey_caper')
    from combat.creature_passage import permission
    assert permission(engine, engine.state.actors[LEFT], engine.state.actors[RIGHT]) == 'difficult'
    _, prompts = settle(cell_send(t, m, 'Move', (5, 6)), choose=lambda prompt: [
        option['id'] for option in prompt['choice']['options']
        if option['label'].startswith('Create a Monkey Link')])
    question = next((p for p in prompts if any(o['label'].startswith('Create a Monkey Link')
                                                for o in p.get('choice', {}).get('options', []))), None)
    assert question is not None, prompts
    rendered = str(question)
    assert 'Seventy-Two Earthly Transformations' in rendered
    assert 'Visitor' in rendered
    assert 'end of your turn' in rendered
    assert 'Monkey Style talents' in rendered
    engine = reload(c, m)
    assert len(monkey.links(engine.state.actors[LEFT])) == 1
    assert engine.state.actors[LEFT].turn_flags.get('monkey_links_made') == 1


@pytest.mark.parametrize('label', ['Tiny Scout', 'Flying Beast', 'Burrowing Beast'])
def test_form_preserves_unimplemented_benefits_as_player_riders_after_reload(tmp_path, label):
    """The committed transformation still carries explicit GM reminders for unsupported size/mode and Link triggers."""
    c, t, m = fight(tmp_path, [TRANSFORM], spheres=[SPHERE], cl=18, left_resource="Stamina")
    result, _ = form(c, t, m, label)
    assert result['status'] == 'COMMITTED', result
    engine = reload(c, m)
    action = next(a for a in engine.action_catalog.values()
                  if a.display_name == f'Seventy-Two Earthly Transformations: {label}' and
                  any(e.get('type') == 'monkey_transform' for e in a.parameters.get('typed', {}).get('effects', [])))
    text = ' '.join(action.parameters['typed'].get('riders', []))
    for reminder in ('Tiny size', 'movement speed', 'elevation changes', 'climbing', 'flying',
                     'swimming', 'burrowing', 'beast agility', *({
                         'Tiny Scout': (),
                         'Flying Beast': ('Fly Speed 50 feet', 'Hover'),
                         'Burrowing Beast': ('Burrow Speed 30 feet', 'not solid stone'),
                     }[label])):
        assert reminder in text, (reminder, text)


@pytest.mark.parametrize('use', [False, True], ids=['decline-oa', 'accept-oa'])
def test_tail_qi_pull_uses_normal_opportunity_attack_rules(tmp_path, use):
    """Leave the adjacent enemy's reach; accepting its OA hurts, declining does not."""
    def unarmored(bundle):
        if bundle['actor_template']['entity_id'] == LEFT:
            # KIT's worn armor overrides sheet base AC; set the synthetic actor's
            # initial AC explicitly so the fixed-seed ordinary OA hits.
            bundle['actor_template']['armor_class'] = 1

    c, t, m = fight(tmp_path, [HOOK], spheres=[SPHERE], cl=18, left_resource="Stamina",
                    bundle_edit=unarmored)
    before = reload(c, m).state.actors[LEFT]
    hp, budget = before.current_hp, before.movement_remaining_ft
    chosen = 'pull yourself 5 feet toward a stable object or climbable surface'

    def pick(prompt):
        source = prompt['context']['reaction_source_id']
        if source == 'reaction:typed.opportunity_attack':
            return ['USE'] if use else []
        wanted = 'cell:2,6' if source.endswith('monkey_step') else chosen
        return [o['id'] for o in prompt.get('choice', {}).get('options', [])
                if o['id'] == wanted or o['label'] == wanted]

    sender = action_sender(c, t, m, 'Tail-Qi Hook')

    def send(answers):
        # The fixture's settle helper uses a nonempty pick to mean USE. An OA
        # has no option selection: send only its actual USE/DECLINE decision.
        answers = [{**a, 'option_ids': []} if a['reaction_source_id'] == 'reaction:typed.opportunity_attack'
                   else a for a in answers]
        return sender(answers)

    result, prompts = settle(send, choose=pick)
    assert result['status'] == 'COMMITTED', result
    oa = [p for p in prompts if p['context']['reaction_source_id'] == 'reaction:typed.opportunity_attack']
    assert len(oa) == 1 and oa[0]['context']['reactor_id'] == RIGHT, prompts
    engine = reload(c, m)
    actor = engine.state.actors[LEFT]
    assert (actor.position.x, actor.position.y) == (2, 6)
    assert actor.movement_remaining_ft == budget, 'the granted step must not spend walking movement'
    attacks = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED'
               and e.actor_id == RIGHT and LEFT in e.target_ids]
    assert len(attacks) == int(use)
    assert (actor.current_hp < hp) is use
    assert engine.state.actors[RIGHT].reaction_available is (not use)


def test_trickster_reminders_keep_weapon_floor_and_qualification(tmp_path):
    """After committing and reloading, newcomers can read the omitted printed benefit and trigger list."""
    c, t, m = fight(tmp_path, [TRICKSTER], spheres=[SPHERE], cl=18, left_resource="Stamina")
    result, _ = settle(action_sender(c, t, m, 'Hundred-Handed Trickster'))
    assert result['status'] == 'COMMITTED', result
    engine = reload(c, m)
    action = next(a for a in engine.action_catalog.values() if TRICKSTER in a.source_definition_id)
    riders = ' '.join(action.parameters['typed'].get('riders', []))
    for phrase in ('at least 1d8', 'hit, feint', 'move through a creature', 'miss you'):
        assert phrase in riders, (phrase, riders)


def passage_question(prompts):
    return [p for p in prompts if p['context']['reaction_source_id'].endswith('monkey_beast_form_link')]


@pytest.mark.parametrize('boundary', ['accept', 'decline', 'held-full', 'creation-exhausted', 'expanded'])
def test_transformed_passage_decision_boundaries_commit_and_reload(tmp_path, boundary):
    """Both form and caper are active: declining must not fall through to the caper's grant."""
    caper = M + 'CAPERING_FOOTWORK'
    owned = [TRANSFORM, caper]
    if boundary == 'expanded':
        owned += [monkey.COURT, monkey.SAGE]
    setup = [{'type': 'monkey_link_gm'}]
    if boundary == 'creation-exhausted':
        setup += [{'type': 'monkey_spend_link'}]
    elif boundary in ('held-full', 'expanded'):
        setup = [{'type': 'monkey_link_reaction'}]  # held Link, without consuming the counted creation limit

    def huge(bundle):
        if bundle['actor_template']['entity_id'] == RIGHT:
            bundle['actor_template']['size_category'] = 'Huge'

    c, t, m = fight(tmp_path, owned, spheres=[SPHERE], cl=20, left_resource='Stamina',
                    prepare=setup, bundle_edit=huge)
    form(c, t, m, 'Swift Beast')
    for label in (['Great Sage Equal to Heaven', 'Court of the Laughing Sage'] if boundary == 'expanded' else []):
        settle(lambda answers: act(t, m, 'end', answers))
        turn(t, m, LEFT)
        settle(action_sender(c, t, m, label))
    settle(lambda answers: act(t, m, 'end', answers))
    turn(t, m, LEFT)
    settle(action_sender(c, t, m, 'Capering Footwork'))
    if boundary in ('held-full', 'creation-exhausted', 'expanded'):
        settle(action_sender(c, t, m, 'Prepare'))
    before = reload(c, m).state.actors[LEFT]
    held, made = len(monkey.links(before)), int(before.turn_flags.get('monkey_links_made', 0))
    result, prompts = settle(cell_send(t, m, 'Move', (5, 6)), choose=lambda prompt: [
        o['id'] for o in prompt.get('choice', {}).get('options', [])
        if o['label'].startswith('Create a Monkey Link') and boundary != 'decline'])
    assert result['status'] == 'COMMITTED'
    asked = passage_question(prompts)
    assert len(asked) == (0 if boundary in ('held-full', 'creation-exhausted') else 1), prompts
    actor = reload(c, m).state.actors[LEFT]
    granted = int(boundary in ('accept', 'expanded'))
    assert len(monkey.links(actor)) == held + granted
    assert actor.turn_flags.get('monkey_links_made', 0) == made + granted
    assert (actor.position.x, actor.position.y) == (5, 6)
    settle(lambda answers: act(t, m, 'end', answers), choose=lambda prompt: [])
    remaining = monkey.links(reload(c, m).state.actors[LEFT])
    assert {iid for iid, _ in remaining} == ({iid for iid, _ in monkey.links(before)}
            if boundary in ('held-full', 'expanded') else set()), 'only the seeded next-turn Link may survive'
    if remaining:
        turn(t, m, LEFT)
        settle(lambda answers: act(t, m, 'end', answers), choose=lambda prompt: [])
        assert not monkey.links(reload(c, m).state.actors[LEFT])


@pytest.mark.parametrize('mode', ['MANUAL', 'LOCAL_AUTO'])
@pytest.mark.parametrize('accept', [False, True])
def test_passage_link_belongs_to_mover_on_another_actors_turn(tmp_path, mode, accept):
    """Court's response crosses a hostile space on Visitor's turn; Ask me stays with Keeper.

    The real Court/Sage/form activations supply permission and a 10-foot response.
    A narrow synthetic arena makes the AI's furthest perceived square cross Bystander.
    """
    def corridor(arena):
        arena['terrain_regions'] = [{'terrain_type': 'BLOCKED', 'movement_cost': 5,
            'cells': [{'x': x, 'y': y} for x in range(16) for y in range(16)
                      if (x, y) not in {(3, 4), (3, 5), (3, 6), (4, 6)}]}]

    def miss(bundle):
        if bundle['actor_template']['entity_id'] == RIGHT:
            for action in bundle['action_catalog']:
                if action['display_name'] == 'Cause':
                    action['parameters']['typed']['numbers']['attack_bonus'] = -100

    c, t, m = fight(tmp_path, [TRANSFORM, monkey.COURT, monkey.SAGE], spheres=[SPHERE],
                    cl=20, left_resource='Stamina', extra_witness=True, arena_edit=corridor,
                    cause=[{'type': 'attack', 'attack_kind': 'melee', 'no_damage': True}], bundle_edit=miss)
    form(c, t, m, 'Swift Beast')
    for label in ('Great Sage Equal to Heaven', 'Court of the Laughing Sage'):
        settle(lambda answers: act(t, m, 'end', answers))
        turn(t, m, LEFT)
        settle(action_sender(c, t, m, label))
    turn(t, m, RIGHT)
    c.set_controller_mode(m, actor_id=LEFT, controller_mode=mode)
    before = reload(c, m).state.model_dump(mode='json')

    def pick(prompt):
        assert prompt['context']['reactor_id'] == LEFT, prompt
        # Until all choices have answers, the entire accepted attack remains uncommitted.
        assert reload(c, m).state.model_dump(mode='json') == before
        if prompt['context']['reaction_source_id'].endswith('monkey_step'):
            return [o['id'] for o in prompt['choice']['options'] if o['id'] == 'cell:3,4']
        if passage_question([prompt]) and accept:
            return [o['id'] for o in prompt['choice']['options']]
        return []

    result, prompts = settle(action_sender(c, t, m, 'Cause'), choose=pick)
    assert result['status'] == 'COMMITTED'
    questions = passage_question(prompts)
    assert len(questions) == int(mode == 'MANUAL'), prompts
    engine = reload(c, m)
    assert engine.state.current_actor_id == RIGHT
    actor = engine.state.actors[LEFT]
    assert (actor.position.x, actor.position.y) == (3, 4)
    granted = mode == 'LOCAL_AUTO' or accept
    held = monkey.links(actor)
    assert len([link for _, link in held if TRANSFORM in link.source_definition_id]) == int(granted)
    # Automatic Great Sage separately chooses its uncounted Uncatchable Link
    # after the miss. It must not masquerade as a second passage grant.
    assert len([link for _, link in held if monkey.SAGE in link.source_definition_id]) == int(mode == 'LOCAL_AUTO')
    assert len(held) == int(granted) + int(mode == 'LOCAL_AUTO')
    assert actor.turn_flags.get('monkey_links_made', 0) == int(granted)
    assert not monkey.links(engine.state.actors[RIGHT])
    turn(t, m, LEFT)
    assert len(monkey.links(reload(c, m).state.actors[LEFT])) == len(held)
    # The automatic owner has no manual End turn menu. Switch through the
    # service before ending its next turn to check the granted Link's expiry.
    c.set_controller_mode(m, actor_id=LEFT, controller_mode='MANUAL')
    settle(lambda answers: act(t, m, 'end', answers), choose=lambda prompt: [])
    assert not monkey.links(reload(c, m).state.actors[LEFT]), 'the off-turn Link ends at the end of its owner next turn'
