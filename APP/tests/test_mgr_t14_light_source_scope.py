"""Light location knowledge is scoped to the seen creature's enrolled Body source.

An unrelated or Invisible light emitter must not grant pinpoint location, while an
enrolled, visible Body light source still does. The hook's collaborators are
replaced so each case states only the facts it depends on.
"""
from types import SimpleNamespace

import pytest

from combat.ext import body_modes_scene_resources as scene
from combat import senses, zones, typed_executor

SOURCE = 'tianxia.subpath.body.hundred_venom_body'


def _actor(entity_id, *conditions):
    return SimpleNamespace(entity_id=entity_id,
                           conditions={str(i): SimpleNamespace(condition_id=c, data={}) for i, c in enumerate(conditions)})


@pytest.fixture
def world(monkeypatch):
    state = {'light': [], 'profiles': {}}

    def query(point, *args, **kwargs):
        assert point == 'light_emission'
        return list(state['light'])

    def profiles(bundle):
        return bundle.get('profiles', [])

    monkeypatch.setattr(scene, 'query', query)
    monkeypatch.setattr(scene, 'profiles', profiles)
    monkeypatch.setattr(scene, 'bundle_of', lambda engine, actor: state['profiles'].get(actor.entity_id, {}))
    monkeypatch.setattr(senses, 'physical_sight', lambda engine, viewer, seen: True)
    monkeypatch.setattr(zones, 'hidden_from', lambda engine, viewer, seen: False)
    monkeypatch.setattr(typed_executor, 'condition_rules', lambda actor: [])
    return state


def _light(source=SOURCE, bright=20):
    return {'source': source, 'bright_ft': bright, 'dim_ft': 0}


def test_unrelated_creature_light_does_not_grant_location(world):
    # The seen creature has no Body enrollment; another creature's light reply names no source.
    world['light'] = [_light(source=None)]
    viewer, seen = _actor('viewer'), _actor('lamp')
    assert scene.visible_light_source(None, viewer, seen) is None


def test_light_from_other_source_does_not_grant_location(world):
    world['profiles']['lamp'] = {'profiles': [{'source': SOURCE}]}
    world['light'] = [_light(source='tianxia.subpath.qi.other')]
    assert scene.visible_light_source(None, _actor('viewer'), _actor('lamp')) is None


def test_invisible_enrolled_light_source_is_not_revealed(world):
    world['profiles']['lamp'] = {'profiles': [{'source': SOURCE}]}
    world['light'] = [_light()]
    seen = _actor('lamp', 'condition:typed.invisible')
    assert scene.visible_light_source(None, _actor('viewer'), seen) is None


def test_enrolled_visible_light_source_still_grants_location(world):
    world['profiles']['lamp'] = {'profiles': [{'source': SOURCE}]}
    world['light'] = [_light()]
    assert scene.visible_light_source(None, _actor('viewer'), _actor('lamp')) is True
