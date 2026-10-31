"""Review F1/F2: legal Sound steps and Release recipients survive table replay.

Only choice preferences are intercepted; native manual/automatic transport,
payment, movement, commits and cold mechanical replay still execute.
"""
import pytest

from combat import ext, senses
from combat.ext import red_thread_release as R, sound_echoes as E
from combat.ext.fate_riders import RED_THREAD
from combat.ext.hit_dice import PREFIX
from combat.gate2_runtime_models import Position
from combat.targeting import line_of_effect
from tests import worker2_support as S
from tests.cw2_service_support import add_action, seal
from tests.mgr_t16_support import automatic


STEP = 'choice:needle.echo_step'
RECIPIENT = 'choice:needle.red_thread_ally'
FAR = 'actor:factory.worker2-ally3'
BLOCKED = 'actor:factory.worker2-ally4'


def use(c, t, mid, name, *, target=None, **kwargs):
    return S.settle(t, mid, S.candidate(c, mid, name, target=target).candidate_id, **kwargs)


@pytest.mark.parametrize('ai', [False, True], ids=['manual', 'automatic'])
def test_field_cast_offers_step_once_per_turn_after_reload(tmp_path, monkeypatch, ai):
    def transform(bundles):
        # A second real Sound talent can resolve during this same turn, so the
        # regression exercises the Field limit independently of action economy.
        for action in bundles[0]['action_catalog']:
            if (action['parameters'].get('typed') or {}).get('source') == E.MUFFLE:
                action['economy'] = 'NONE'
                action['parameters']['free_primary'] = True
        seal(bundles[0])

    c, t, mid = S.fixture(tmp_path, [E.FIELD, E.MUFFLE], dc=-100,
        bundle_transform=transform,
        battlefield_transform=lambda doc: doc.update(terrain_regions=[]))
    before = S.reload(tmp_path, mid).state.actors[S.OWNER].position
    destination = Position(x=3, y=5)
    seen = []
    native = E.ask

    def choose(engine, intent, checkpoint, chooser, choice_id, options, **kwargs):
        if choice_id == STEP:
            seen.append(tuple(options))
            assert 'step:3,5' in options
            kwargs['preferred'] = ['step:3,5']
        return native(engine, intent, checkpoint, chooser, choice_id, options, **kwargs)

    monkeypatch.setattr(E, 'ask', choose)
    prompts = (automatic(c, t, mid, S.OWNER, 'Ten-Thousand Echoes Field') if ai else
               use(c, t, mid, 'Ten-Thousand Echoes Field', picks={STEP: 'step:3,5'}))
    assert seen, 'Casting the Field must offer its own Sound-triggered step'
    assert any(p['context']['reaction_source_id'] == STEP for p in prompts) is (not ai)
    after = S.reload(tmp_path, mid)
    actor = after.state.actors[S.OWNER]
    assert actor.position == destination and actor.position != before
    assert actor.movement_remaining_ft == 30
    stamp = actor.turn_flags['sound_echo_step']
    assert E.fields(after, actor, allied=True)

    # Reconstruct both services, then try another qualifying Sound use in the
    # very same turn. The persisted guard prevents a second offer or movement.
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT
    c = CombatService(ROOT, tmp_path)
    t = TabletopService(c, tmp_path)
    seen.clear()
    prompts = (automatic(c, t, mid, S.OWNER, 'Muffle Footfall') if ai else
               use(c, t, mid, 'Muffle Footfall'))
    assert not seen
    assert not any(p['context']['reaction_source_id'] == STEP for p in prompts)
    after = S.reload(tmp_path, mid).state.actors[S.OWNER]
    assert after.position == destination and after.turn_flags['sound_echo_step'] == stamp


@pytest.mark.parametrize('ai', [False, True], ids=['manual', 'automatic'])
@pytest.mark.parametrize('recipient', ['self', 'invisible'])
def test_release_keeps_legal_recipients_and_physical_limits_after_reload(tmp_path, monkeypatch, ai, recipient):
    def conceal(ctx, row):
        ctx.engine._apply_condition(ctx.actor, 'condition:typed.invisible', ctx.source,
            ctx.actor.entity_id, expires_on='UNTIL_REMOVED')

    monkeypatch.setitem(ext._EFFECTS, 'test_t16_release_invisible', conceal)

    def transform(bundles):
        bundles[1]['actor_template']['resources'].append(
            {'resource_id': PREFIX + '8', 'initial': 2, 'maximum': 2})
        seal(bundles[1])
        add_action(bundles[0], 'Conceal Release recipient',
                   [{'type': 'test_t16_release_invisible'}], target='SELF')

    def arena(doc):
        doc['terrain_regions'] = [{'region_id': 'test:release-wall', 'terrain_type': 'BLOCKED',
            'movement_cost': 0, 'cells': [{'x': x, 'y': 8} for x in range(doc['width_squares'])],
            'description': 'Solid stone wall'}]

    c, t, mid = S.fixture(tmp_path, [RED_THREAD], bundle_transform=transform,
        extra_allies=2, battlefield_transform=arena, positions={
            S.OWNER: {'x': 3, 'y': 6}, S.ALLY: {'x': 4, 'y': 6}, S.FOE: {'x': 10, 'y': 3},
            FAR: {'x': 12, 'y': 6}, BLOCKED: {'x': 4, 'y': 10}})
    use(c, t, mid, 'Red Thread Auspice', target=S.ALLY)
    if recipient == 'invisible':
        use(c, t, mid, 'Conceal Release recipient')
    S.turn(t, mid, S.ALLY)
    before = S.reload(tmp_path, mid)
    bearer = before.state.actors[S.ALLY]
    assert R.held(bearer)
    assert before._distance_actor_to_actor(bearer, before.state.actors[FAR]) > 30
    assert before._distance_actor_to_actor(bearer, before.state.actors[BLOCKED]) <= 30
    assert not line_of_effect(before, bearer, target=before.state.actors[BLOCKED])
    assert line_of_effect(before, bearer, target=before.state.actors[S.OWNER])
    if recipient == 'invisible':
        assert not senses.perceives(before, bearer, before.state.actors[S.OWNER])
    target = S.ALLY if recipient == 'self' else S.OWNER
    seen = []
    native = R.ask

    def choose(engine, intent, checkpoint, chooser, choice_id, options, **kwargs):
        if choice_id == RECIPIENT:
            seen.append(tuple(options))
            assert set(options) == {S.OWNER, S.ALLY}
            kwargs['preferred'] = [target]
        return native(engine, intent, checkpoint, chooser, choice_id, options, **kwargs)

    monkeypatch.setattr(R, 'ask', choose)
    # The ally saw/touched the caster before concealment; this fixture does not
    # give an automatic seat information about an undiscovered creature.
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT
    c = CombatService(ROOT, tmp_path)
    t = TabletopService(c, tmp_path)
    prompts = (automatic(c, t, mid, S.ALLY, 'Red Thread Auspice: Release') if ai else
               use(c, t, mid, 'Red Thread Auspice: Release',
                   picks={RECIPIENT: target, 'choice:needle.red_thread_die': PREFIX + '8'}))
    assert seen
    after = S.reload(tmp_path, mid)
    assert after.state.actors[S.ALLY].resources[PREFIX + '8'] == 1
    assert after.state.actors[target].temporary_hp > 0
    assert all(a.temporary_hp == 0 for key, a in after.state.actors.items() if key != target)
    assert R.held(after.state.actors[S.ALLY]) is None
    assert any(p['context']['reaction_source_id'] == RECIPIENT for p in prompts) is (not ai)
    assert any(p['context']['reaction_source_id'] == 'choice:needle.red_thread_die'
               for p in prompts) is (not ai)
