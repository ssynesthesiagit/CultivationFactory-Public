"""RW172 review fixes: Golden Sea Guard's next-save Advantage, and the Tyrant/Womb condition pill text."""
from types import SimpleNamespace

import pytest

from app.core import FoundryError
from combat.ext import foundation_combat, foundations3
from combat.ext import golden_sea_guard_advantage as guard

OWNER, SOURCE, OTHER = 'owner', 'attacker', 'bystander'
REFINED_KEY = 'foundation.ancient_desolate_sacred_body_v0_2C.refined_golden_blood_root'
REFINED_ROW = {'feature_id': guard.REFINED, 'block': 'sacred_body'}


class Engine:
    def __init__(self, refined=True, packet=None):
        self.typed_passive_rows = {OWNER: [REFINED_ROW] if refined else []}
        self.state = SimpleNamespace(actors={
            OWNER: _actor(OWNER, 'Owner'), SOURCE: _actor(SOURCE, 'Attacker'), OTHER: _actor(OTHER, 'Bystander')})
        self.events = []
        self._pending_damage_context = packet

    def _apply_condition(self, target, condition_id, source_id, source_actor_id, *, expires_on, data=None, unavoidable=False):
        target.conditions[condition_id] = SimpleNamespace(condition_id=condition_id, data=data, source_definition_id=source_id)

    def _append_event(self, event_type, source_definition_id, **kwargs):
        self.events.append((event_type, source_definition_id, kwargs))


def _actor(entity_id, name):
    return SimpleNamespace(entity_id=entity_id, team_id=entity_id, display_name=name, active=True, conditions={})


def _packet(damage_type='POISON', pressure_kind='damage', target=OWNER, source=SOURCE, hostile=True):
    return SimpleNamespace(damage_type=damage_type, pressure_kind=pressure_kind, target_id=target, source_actor_id=source,
                           source_id='src', hostile=hostile)


def _reaction(owner=OWNER, reduction=4, targets=(SOURCE,)):
    return {'source_definition_id': guard.GUARD, 'actor_id': owner, 'target_ids': targets,
            'payload': {'reduction': reduction, 'pending_before': 9, 'pending_after': 9 - reduction}}


def _save(engine, subject_id=OWNER, source_id=SOURCE):
    ctx = SimpleNamespace(engine=engine, actor=engine.state.actors[source_id])
    return guard.next_save_advantage(ctx, engine.state.actors[subject_id], 'CON', ['poisoned'])


def _react(engine, kwargs):
    guard.guard_next_save(engine, 'REACTION_RESOLVED', kwargs)


def test_guard_reduction_against_poison_grants_next_save_advantage_against_that_source():
    engine = Engine(packet=_packet('POISON'))
    _react(engine, _reaction())
    assert guard.FOLLOW in engine.state.actors[OWNER].conditions
    assert _save(engine) == {'bonus': 0, 'modes': ['ADVANTAGE']}
    assert guard.FOLLOW not in engine.state.actors[OWNER].conditions  # consumed by the next eligible save


def test_advantage_is_scoped_to_the_same_source():
    engine = Engine(packet=_packet('POISON'))
    _react(engine, _reaction())
    assert _save(engine, source_id=OTHER) is None
    assert guard.FOLLOW in engine.state.actors[OWNER].conditions


@pytest.mark.parametrize('damage_type,pressure_kind', [('NECROTIC', 'damage'), ('UNTYPED', 'possession'),
                                                       ('UNTYPED', 'demonic'), ('FIRE', 'body_suppression')])
def test_printed_corruptive_and_suppressive_sources_all_qualify(damage_type, pressure_kind):
    engine = Engine(packet=_packet(damage_type, pressure_kind))
    _react(engine, _reaction())
    assert guard.FOLLOW in engine.state.actors[OWNER].conditions


def test_plain_fire_damage_gives_no_follow_up():
    engine = Engine(packet=_packet('FIRE', 'damage'))
    _react(engine, _reaction())
    assert guard.FOLLOW not in engine.state.actors[OWNER].conditions


def test_owner_without_refined_golden_blood_root_is_inert():
    engine = Engine(refined=False, packet=_packet('POISON'))
    _react(engine, _reaction())
    assert guard.FOLLOW not in engine.state.actors[OWNER].conditions


def test_a_zero_reduction_or_a_packet_not_aimed_at_the_owner_is_inert():
    engine = Engine(packet=_packet('POISON'))
    _react(engine, _reaction(reduction=0))
    assert guard.FOLLOW not in engine.state.actors[OWNER].conditions
    engine = Engine(packet=_packet('POISON', target=OTHER))
    _react(engine, _reaction())
    assert guard.FOLLOW not in engine.state.actors[OWNER].conditions


def test_other_reactions_are_inert():
    engine = Engine(packet=_packet('POISON'))
    _react(engine, {**_reaction(), 'source_definition_id': 'foundation.other.reaction'})
    assert guard.FOLLOW not in engine.state.actors[OWNER].conditions


def test_tyrant_declaration_pill_no_longer_tells_the_player_to_resolve_checks_manually():
    text = foundation_combat.STATE_BENEFITS['tyrant_declaration']
    assert 'manually' not in text.lower()
    assert 'Advantage on Strength or Constitution checks' in text


def test_devour_womb_pill_states_the_save_and_check_advantage():
    text = foundation_combat.STATE_BENEFITS['devour_womb']
    assert 'Advantage on saves and ability checks' in text
    assert 'poison' in text and 'possession' in text and 'body suppression' in text


def test_a_second_hit_point_tier_is_an_error_not_a_silent_no_op():
    tier = {'block': 'foundation_hp_tier', 'identity': 'x', 'multiple': 3}
    with pytest.raises(FoundryError) as error:
        foundations3.hp_tier_maximum_hp({'typed_passives': [tier, dict(tier, multiple=2)]}, {})
    assert error.value.code == 'COMBAT_FOUNDATION_HP_TIER_DUPLICATE'


def test_talent_heading_tags_come_from_the_printed_seam(monkeypatch):
    # RW172 F1R Darkness: the compiler read the authority file directly, so a printed-text copy (public export, tests)
    # never reached "### Numbing Darkness - Darkness" and Shape Darkness lost its talent.
    from combat import factory_compiler, status_text
    monkeypatch.setattr(status_text, 'printed_rules', lambda: {'TAL_DARK_NUMBING_DARKNESS': '### Numbing Darkness - Pyre\nBody.'})
    assert factory_compiler._talent_tags('TAL_DARK_NUMBING_DARKNESS') == ['Pyre']


def test_refined_golden_blood_root_has_no_unconditional_advantage():
    # RW172 F1R: the top-level "advantage" duplicated the typed modifier and granted Advantage on any roll; only the
    # modifier (with its "against that same source" scope) and the Guard plug-in may grant the next-save Advantage.
    import json
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / 'authority/typed_mechanics/reviewed_final.d/rw172_golden_blood_root.json'
    mechanic = json.loads(path.read_text(encoding='utf-8'))['mechanics'][REFINED_KEY]
    assert not [e for e in mechanic.get('effects') or [] if e.get('type') in ('advantage', 'disadvantage')]
    assert [e for e in mechanic['modifier']['effects'] if e.get('type') == 'advantage']
