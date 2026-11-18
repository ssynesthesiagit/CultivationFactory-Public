"""Synthetic portable adapter fixtures for LOCK4 and HUNT23 table regressions."""
from types import SimpleNamespace

import pytest

from combat.canonical import canonical_sha256
from combat.character_runtime_adapter import (
    CharacterCombatRuntimeAdapter, CharacterCombatRuntimeEngine,
    RuntimeResourceInitialization, SOURCE_ACTOR_ID, dummy_actor_template,
)
from combat.gate2_runtime_models import ActionDefinition, Position
from tests.h1_support import ROOT


@pytest.fixture
def adapter():
    # Exercise the real adapter's bundle builder without importing an owner package.
    obj = CharacterCombatRuntimeAdapter.__new__(CharacterCombatRuntimeAdapter)
    stats = SimpleNamespace(creature_type=' Humanoid ', armor_class=10, hit_points_maximum=100,
        speed_ft=30, initiative_bonus=0, ability_scores={'STR': 10, 'DEX': 10},
        size='Medium', proficiency_bonus=2, saving_throws={}, skills={})
    obj.sheet = SimpleNamespace(combatant_stats=stats, display_name='Synthetic fighter',
        character_id='synthetic', sheet_commitment_sha256='0' * 64)
    obj.lock = SimpleNamespace(mechanics=[], lock_sha256='0' * 64)
    obj.registry = SimpleNamespace(registry_sha256='0' * 64)
    return obj


@pytest.fixture
def bundle(adapter):
    built = adapter.build_bundle(RuntimeResourceInitialization(qi_current=0, martial_focus_current=0,
        provenance_kind='TEST_FIXTURE', provenance_id='synthetic'))
    raw = built.model_dump(mode='json', by_alias=True)
    action = ActionDefinition(source_definition_id='action:core.unarmed_strike', display_name='Unarmed Strike',
        owner_id=SOURCE_ACTOR_ID, economy='ACTION', resolution_kind='C3AR_UNARMED_STRIKE',
        target_kind='HOSTILE_ENTITY', reach_ft=5, attack_bonus=2, damage_type='BLUDGEONING',
        parameters={'fixed_damage': 2})
    raw['action_catalog'] = [action.model_dump(mode='json')]
    raw['actor_template']['action_ids'] = ['action:core.unarmed_strike']
    raw.pop('bundle_sha256')
    raw['bundle_sha256'] = canonical_sha256(raw)
    return type(built).model_validate(raw)


@pytest.fixture
def runtime_package(tmp_path):
    path = tmp_path / 'synthetic.zip'
    path.write_bytes(b'synthetic portable package')
    return path


def runtime_engine(bundle):
    target = dummy_actor_template('dummy:target', armor_class=0, maximum_hp=1000)
    return CharacterCombatRuntimeEngine(ROOT, bundle, match_seed='synthetic',
        additional_actors=(target,),
        positions={SOURCE_ACTOR_ID: Position(x=2, y=2), 'dummy:target': Position(x=3, y=2)})
