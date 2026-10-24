"""Greatbow eligibility guards; these do not certify the five whole records.

The printed "greatbow-family weapon" is undefined in the sources, so no catalog
weapon is classified by name. Only an explicit reviewed weapon_family field counts.
The acquisition/delivery/platform/Anchor implementations are not supplied by
this guard. Real catalog weapons still expose and commit their ordinary attacks.
"""
import pytest

from combat import ext
from combat.factory_compiler import _fits, compile_character
from combat.ext.greatbow import source_family
from tests.h1_support import sheet
from tests.worker2_support import OWNER, FOE, fixture, candidate, settle, reload

PREFIX = 'tianxia.subpath.qi.star_piercing_greatbow_cultivator.feature.'
BRACE = PREFIX + 'brace_the_heavens'


def test_only_explicit_reviewed_family_field_is_classified():
    assert source_family({'name': 'Greatbow', 'weapon_family': 'greatbow'}) == 'greatbow'
    assert source_family({'name': 'Greatbow', 'weapon_family': 'bow'}) is None


@pytest.mark.parametrize('name', [
    'Greatbow', 'War bow', 'Heavy longbow', 'Siege bow designed for one cultivator',
    'Great composite bow', 'Dragon-horn bow', 'Cultivated heavy bow',
    'Da Gong (Greatbow)', 'Shortbow', 'Hand crossbow', 'Longbow',
    'Not a greatbow', 'Greatbow replica',
])
def test_names_never_classify_a_greatbow(name):
    assert source_family({'name': name, 'properties': 'Heavy, Two-Handed'}) is None


@pytest.mark.parametrize('item_id', [
    'tianxia.mortal.weapon.duan_gong', 'tianxia.mortal.weapon.gong_jian',
    'tianxia.mortal.weapon.nu_gong', 'tianxia.mortal.weapon.shou_nu',
    'tianxia.mortal.weapon.bi_zhang_nu', 'tianxia.mortal.weapon.dan_gong',
])
def test_catalog_bows_are_not_greatbows_even_when_renamed(item_id):
    # Renaming an inventory copy must never change the printed weapon's class.
    weapon = {'item_id': item_id, 'name': 'Greatbow', 'melee': False,
              'ranged': True, 'thrown': False}
    assert not _fits(weapon, {'kind': 'ranged', 'family': 'greatbow'})
    assert _fits(weapon, {'kind': 'ranged', 'family': 'bow'})


def kit(item_id):
    return {'starting_kit': {'items': [{'item_id': item_id, 'quantity': 1},
        {'item_id': 'tianxia.mortal.gear.arrows_20', 'quantity': 1}]}}


def test_ordinary_bow_cannot_compile_the_generic_brace_attack():
    doc = sheet([BRACE], cl=3, kit=kit('tianxia.mortal.weapon.gong_jian'))
    bundle = compile_character(doc, actor_id=OWNER)
    assert any('Gong Jian' in a['display_name'] and a['display_name'].endswith('attack')
               for a in bundle['action_catalog'])
    assert not any((a['parameters'].get('typed') or {}).get('source') == BRACE
                   for a in bundle['action_catalog'])


def test_wrong_weapon_preserves_ordinary_attack_commit_and_replay(tmp_path):
    combat, table, mid = fixture(tmp_path, [], cl=3, owner_features=[BRACE],
        owner_kit=kit('tianxia.mortal.weapon.gong_jian'))
    before = reload(tmp_path, mid)
    assert not any('Brace the Heavens' in c.display_name for c in before.legal_candidates())
    shot = candidate(combat, mid, 'Gong Jian (Bow and Arrow) attack', target=FOE)
    settle(table, mid, shot.candidate_id)
    after = reload(tmp_path, mid)  # cold load also asserts full mechanical replay
    assert not after.state.actors[OWNER].action_available
    assert after.state.actors[OWNER].resources['resource:core.qi'] == before.state.actors[OWNER].resources['resource:core.qi']
    assert any(e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER for e in after.events)


def test_family_seam_is_inert_for_unhandled_families():
    weapon = {'item_id': 'unknown', 'name': 'Long spear', 'melee': True,
              'ranged': False, 'thrown': False}
    assert _fits(weapon, {'kind': 'melee', 'family': 'spear'})
    assert not _fits(weapon, {'kind': 'ranged', 'family': 'spear'})


def test_another_express_source_can_classify_an_item(monkeypatch):
    ext.effects()
    previous = list(ext.subscribers('weapon_source_family'))
    def accepts(item, family):
        if family == 'greatbow' and item.get('item_id') == 'tianxia.mortal.weapon.gong_jian':
            return True
    monkeypatch.setitem(ext._HOOKS, 'weapon_source_family', [*previous, accepts])
    assert _fits({'item_id': 'tianxia.mortal.weapon.gong_jian', 'name': 'Bow',
                  'ranged': True, 'melee': False, 'thrown': False}, {'family': 'greatbow'})


def test_family_seam_rejects_malformed_provider(monkeypatch):
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, 'weapon_source_family', [lambda *_: 1])
    with pytest.raises(ValueError, match='weapon_source_family'):
        _fits({'item_id': 'unknown', 'name': 'Bow', 'ranged': True,
               'melee': False, 'thrown': False}, {'family': 'bow'})
