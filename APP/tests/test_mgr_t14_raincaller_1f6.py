"""Sol 1F5R: legal ritual placement and reusable public hook contracts."""
import pytest

from combat.ext import mgr_reserve_raincaller_cultivator_call_rain as rain
from tests.test_mgr_t14_raincaller_native import (
    installed, civil, scene, command, rainstate, site_profile,
)
from tests.test_mgr_t14_raincaller_review_fixes import review_journey
from tests.test_mgr_t14_raincaller_1f5 import pick, with_seat_mode


@pytest.mark.parametrize('automatic', [False, True])
@pytest.mark.parametrize('site_z', [None, 0])
def test_rite_selector_only_offers_recorded_site_and_no_altitude_browsing(
        review_journey, automatic, site_z):
    combat, aid, jid, _ = with_seat_mode(review_journey, automatic)
    civil = combat, aid, jid
    site = site_profile()
    if site_z is not None:
        site['center']['z'] = site_z
    scene(civil, site)
    before = combat.journey_state(jid)
    pick(civil, 'rain_rite:mist:configure', automatic)
    options = combat.journey_menu(jid, aid)['options']
    centers = [o['payload']['value'] for o in options if o['payload']['step'] == 'center']
    assert centers == [{'x': 3, 'y': 6, 'z': 0}]
    assert not any(o['payload']['step'] == 'height' for o in options)
    assert 'recorded ritual site' in next(o['label'] for o in options if o['payload']['step'] == 'center')
    # Invalid/stale UI payloads cannot move the admitted regional site.
    for step, value in [('center', {'x': 4, 'y': 6, 'z': 0}), ('height', 1)]:
        unchanged = combat.journey_state(jid)
        with pytest.raises(ValueError, match='currently offered'):
            command(civil, 'rain_select', {'step': step, 'value': value})
        assert combat.journey_state(jid) == unchanged
    pick(civil, 'rain_select:center:3,6,0', automatic)
    started = pick(civil, 'rain_select:confirm', automatic)
    assert started['actors'][aid]['resources']['resource:core.qi'] == before['actors'][aid]['resources']['resource:core.qi'] - 5
    assert started['actors'][aid]['source_states']['journey:activity']['worked_seconds'] == 0
    result = command(civil, 'activity_work', {'seconds': 600})
    area = rainstate(result, aid)['rains']['rite']
    assert area['center'] == centers[0]
    assert area['expires_at'] - result['seconds'] == 8 * 3600


@pytest.mark.parametrize('site_z,request_z', [(None, 0), (0, None)])
def test_rite_direct_activity_accepts_equivalent_ground_coordinates(civil, site_z, request_z):
    site = site_profile()
    if site_z is not None:
        site['center']['z'] = site_z
    scene(civil, site)
    center = {'x': 3, 'y': 6}
    if request_z is not None:
        center['z'] = request_z
    result = command(civil, 'rain_rite', {'effects': ['mist'], 'center': center})
    assert rainstate(result, civil[1])['rains']['rite']['effects'] == ['mist']


@pytest.mark.parametrize('center', [{'x': 4, 'y': 6}, {'x': 3, 'y': 6, 'z': 1}])
def test_rite_cannot_relocate_recorded_site_through_direct_command(civil, center):
    combat, aid, jid = civil
    scene(civil)
    before = combat.journey_state(jid)
    with pytest.raises(ValueError, match='actual recorded regional site'):
        command(civil, 'rain_rite', {'effects': ['mist'], 'center': center})
    assert combat.journey_state(jid) == before


def test_off_site_rite_is_not_offered_and_direct_start_still_rejects(civil):
    combat, aid, jid = civil
    site = site_profile()
    site['center'] = {'x': 4, 'y': 6}
    scene(civil, site)
    options = combat.journey_menu(jid, aid)['options']
    assert not any(o['id'].startswith('rain_rite:') for o in options)
    assert any(o['kind'] == 'rain_call' for o in options)
    before = combat.journey_state(jid)
    with pytest.raises(ValueError, match='actual recorded ritual site'):
        command(civil, 'activity_start', {'source': rain.RITE, 'parameters': {'effects': ['mist']}})
    assert combat.journey_state(jid) == before


@pytest.mark.parametrize('signature,clauses', [
    ('journey_resource_spent(session, actor_id, resource_id, before, after, source)',
     ['strict notification', 'return values are ignored', 'Errors abort', 'default-inert']),
    ('fact_admission_schema(session, source, subject, kind)',
     ['Exactly one', 'None abstains', 'errors are logged', 'default-inert']),
    ('observer_information_rows(engine, viewer)',
     ['concatenate', 'deep-copied', 'knowledge', 'Errors', 'default-inert']),
    ('observer_source_profile(engine, source, data)',
     ['At most one', 'override', 'Errors', 'default-inert']),
])
def test_remaining_shared_hooks_have_central_composition_and_error_contracts(signature, clauses):
    from combat import ext
    # Ignore line wrapping, but require each hook's own documented semantics.
    # Continuation lines have additional indentation; delimit on the next hook.
    import re
    block = re.split(r'\n  [a-z_]+\(', ext.__doc__.split(signature, 1)[1], maxsplit=1)[0]
    block = ' '.join(block.split())
    assert all(clause in block for clause in clauses)
