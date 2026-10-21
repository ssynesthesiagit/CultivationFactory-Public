"""F10 regression: hostile terrain recipients keep legacy team semantics without an override.

A hostile zone owned by an enemy-team creature affected neutral-team creatures
before the persisted-relation change. The NEUTRAL default of relation() must not
silently drop them; only an explicit saved override may change the outcome.
"""
from types import SimpleNamespace as NS

from combat import zones
from combat.relation_models import Relations


def actor(entity_id, team_id):
    return NS(entity_id=entity_id, team_id=team_id)


def engine(*actors, relations=None):
    return NS(state=NS(actors={a.entity_id: a for a in actors}, relations=relations))


def hostile_zone(owner_id):
    return NS(owner_id=owner_id, trigger_profile={})


def test_neutral_creature_in_enemy_owned_hostile_terrain_is_affected_without_override():
    owner = actor('owner', 'team:a')
    neutral = actor('bystander', 'team:neutral')
    eng = engine(owner, neutral)
    assert zones.hostile_terrain_recipient(eng, hostile_zone('owner'), neutral) is True


def test_same_team_creature_is_not_affected_without_override():
    owner = actor('owner', 'team:a')
    ally = actor('ally', 'team:a')
    eng = engine(owner, ally)
    assert zones.hostile_terrain_recipient(eng, hostile_zone('owner'), ally) is False


def test_explicit_actor_enemy_override_makes_same_team_creature_affected():
    owner = actor('owner', 'team:a')
    turned = actor('turned', 'team:a')
    rel = Relations(actors={'owner': {'turned': 'ENEMY'}})
    eng = engine(owner, turned, relations=rel)
    assert zones.hostile_terrain_recipient(eng, hostile_zone('owner'), turned) is True


def test_explicit_actor_ally_override_removes_other_team_creature():
    owner = actor('owner', 'team:a')
    friend = actor('friend', 'team:b')
    rel = Relations(actors={'friend': {'owner': 'ALLY'}})
    eng = engine(owner, friend, relations=rel)
    assert zones.hostile_terrain_recipient(eng, hostile_zone('owner'), friend) is False


def test_explicit_team_override_is_honoured_for_neutral_creature():
    owner = actor('owner', 'team:a')
    neutral = actor('bystander', 'team:neutral')
    rel = Relations(teams={'team:a': {'team:neutral': 'ALLY'}})
    eng = engine(owner, neutral, relations=rel)
    assert zones.hostile_terrain_recipient(eng, hostile_zone('owner'), neutral) is False


def test_missing_owner_is_not_hostile():
    neutral = actor('bystander', 'team:neutral')
    eng = engine(neutral)
    assert zones.hostile_terrain_recipient(eng, hostile_zone('gone'), neutral) is False
