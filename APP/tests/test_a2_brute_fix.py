"""Ordinary ability damage modifiers through service intents and cold replay."""
import pytest
from tests.worker2_support import OWNER, FOE, fixture, candidate, reload, settle
from tests.cw2_service_support import seal


@pytest.mark.parametrize('ability', ['STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA'])
@pytest.mark.parametrize('source', ['positive', 'negative', 'missing', 'unmarked'])
def test_damage_ability_uses_ordinary_modifier_without_save_proficiency(tmp_path, ability, source):
    ordinary = -2 if source == 'negative' else 2

    def prepare(bundles):
        owner = bundles[0]
        owner['actor_template'].update(strength_score=14, dexterity_score=14)
        owner['actor_template']['saving_throws'][ability] = 6
        for action in owner['action_catalog']:
            typed = (action.get('parameters') or {}).get('typed') or {}
            if typed.get('source') != 'TAL_BRUTE_THUNDEROUS_CLAP':
                continue
            typed['numbers']['ability_mods'] = {} if source == 'missing' else {ability: ordinary}
            typed['numbers']['key_mod'] = 9
            def rows(value):
                if isinstance(value, dict):
                    yield value
                    for child in value.values():
                        yield from rows(child)
                elif isinstance(value, list):
                    for child in value:
                        yield from rows(child)

            damage_rows = [row for row in rows(typed['effects']) if row.get('type') == 'damage']
            assert damage_rows
            for row in damage_rows:
                if row.get('type') == 'damage':
                    row['dice']['modifier'] = 0
                    if source == 'unmarked':
                        row.pop('damage_ability', None)
                    else:
                        row['damage_ability'] = ability
        for bundle in bundles:
            bundle['actor_template']['saving_throws']['CON'] = -100 if bundle is not owner else 6
            seal(bundle)

    combat, table, mid = fixture(tmp_path, ['TAL_BRUTE_THUNDEROUS_CLAP'], cl=5,
        foe_position={'x':4, 'y':5}, bundle_transform=prepare)
    before = reload(tmp_path, mid)
    hp = before.state.actors[FOE].current_hp
    settle(table, mid, candidate(combat, mid, 'Thunderous Clap').candidate_id)
    cold = reload(tmp_path, mid)
    rolls = [r for r in cold.rolls if 'DAMAGE' in r.reason and 'd8' in r.expression]
    assert rolls and len(rolls[-1].dice) == 2
    expected = (0 if source == 'unmarked' else 2 if ability in ('STR', 'DEX')
                else 0 if source == 'missing' else ordinary)
    assert rolls[-1].modifier == expected
    damage = next(e for e in reversed(cold.events)
                  if e.event_type == 'DAMAGE_COMMITTED' and FOE in e.target_ids)
    assert damage.payload['hp_damage'] == rolls[-1].total
    assert cold.state.actors[FOE].current_hp == hp - rolls[-1].total
