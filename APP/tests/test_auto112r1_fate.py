"""AUTO112r1: the Hallow Mandate review regressions.

AUTO112 review findings fixed here:

1. Legacy auras. A Hallow aura saved before this row existed carries no ``fate_hallow_kind`` and no
   ``kind_choice`` marker on its compiled row. It must keep its old behaviour exactly: its own blanket
   save advantage is untouched and Fate supplies nothing.
2. One implementation. The typed core must no longer carry a blanket save-advantage effect (the review
   found two implementations, and removing one at save time depended on hook order). Only the plug-in
   supplies the source-qualified Advantage now.
3. Campaign categories. The printed rule also allows "another supernatural category appropriate to the
   campaign"; the menu must offer the categories this fight's creatures actually carry.

AUTO112r2 review findings fixed here too:

4. Base-compiled auras. An aura compiled by the reviewed base (4c68d9cf) stored its chosen category *and*
   left one aura-wide blanket save advantage on its allies. Upgrading must not keep that blanket granting
   Advantage against every creature (see ``test_base_compiled_hallow_save_drops_its_own_blanket``).
5. The spatial boundary. The ally really leaves the aura and comes back, through table commits and a cold
   reload of each state (see ``test_hallow_save_advantage_only_while_the_ally_is_inside_the_aura``).
6. Honest coverage. While the printed "another supernatural category appropriate to the campaign" cannot be
   named freely, the row keeps a rider saying so and the builder no longer claims FULL.

Each case runs through TabletopService and reloads through a fresh service (mechanical replay PASS).
"""
import pytest

from tests.cw2_service_support import add_action, seal
from tests.worker2_support import ALLY, FOE, OWNER, candidate, fixture, reload, settle, turn

HALLOW = 'TAL_FATE_HALLOW_MANDATE_EDICT'
CHARM = [{'type': 'save', 'ability': 'CHA', 'on_fail': [{'type': 'condition', 'condition': 'charmed', 'applies_to': 'target'}]}]
BLANKET = 'condition:typed.save_against'


def _prepare(bundles, foe_kind, *, cl=15, ally_save=100):
    for bundle, initiative in zip(bundles, [100, -100, 0]):
        bundle['actor_template']['initiative_bonus'] = initiative
        bundle['actor_template']['maximum_hp'] = 300
        seal(bundle)
    bundles[2]['actor_template']['creature_types'] = [foe_kind]
    bundles[2]['actor_template']['saving_throws']['CHA'] = ally_save
    add_action(bundles[2], 'Foe strike', [{'type': 'attack', 'attack_bonus': 100, 'attack_kind': 'cultivation',
                                            'on_hit': [{'type': 'damage', 'damage_type': 'FORCE', 'flat': 4}]}],
               target='HOSTILE_ENTITY')
    add_action(bundles[2], 'Foe charm', CHARM)
    seal(bundles[2])


def _legacy(bundles):
    """Rewind the owner's compiled Hallow row to its pre-AUTO112 shape: the blanket save advantage, no marker."""
    for action in bundles[0]['action_catalog']:
        if ((action.get('parameters') or {}).get('typed') or {}).get('source') != HALLOW:
            continue
        zone = [eff for eff in action['parameters']['typed']['effects'] if eff.get('type') == 'zone'][0]
        action['parameters']['typed']['effects'] = [
            {k: v for k, v in zone.items() if k != 'kind_choice'},
            {'type': 'advantage', 'applies_to': 'ally', 'flat': 0, 'formula': 'none', 'damage_types': [],
             'ability': 'none', 'condition': 'none', 'distance_ft': 0, 'min_cl': 10, 'duration': 'concentration',
             'on': 'saving throws against being Charmed, Frightened, or possessed by creatures of the chosen kind',
             'evidence': 'At CL 10, allies inside the aura have Advantage on saving throws against being Charmed, '
                         'Frightened, or possessed by creatures of the chosen kind', 'origin': 'model_v2'}]
    seal(bundles[0])


def _base_catalog(bundles):
    """The owner's Hallow row as the reviewed base compiled it: the aura plus one aura-wide blanket.

    This is the 4c68d9cf shape the review named: the typed core could not say "of the chosen kind", so the CL 10
    clause was one blanket advantage condition on every ally, and the owner still chose a category. The
    ``kind_choice`` marker is kept so the row asks for that category, which is what a base save stored; the
    saved state this builds (chosen category + unconsumed blanket) is the one an upgrade has to survive.
    """
    for action in bundles[0]['action_catalog']:
        if ((action.get('parameters') or {}).get('typed') or {}).get('source') != HALLOW:
            continue
        zone = [eff for eff in action['parameters']['typed']['effects'] if eff.get('type') == 'zone'][0]
        action['parameters']['typed']['effects'] = [
            zone,
            {'type': 'advantage', 'applies_to': 'ally', 'flat': 0, 'formula': 'none', 'damage_types': [],
             'ability': 'none', 'condition': 'none', 'distance_ft': 0, 'min_cl': 10, 'duration': 'concentration',
             'on': 'saving throws against being Charmed, Frightened, or possessed by creatures of the chosen kind',
             'evidence': 'At CL 10, allies inside the aura have Advantage on saving throws against being Charmed, '
                         'Frightened, or possessed by creatures of the chosen kind', 'origin': 'model_v2'}]
    seal(bundles[0])


def _blanket_held_by(engine):
    """Which abilities' blanket save-advantage the ally currently carries."""
    return {c.source_definition_id for c in engine.state.actors[ALLY].conditions.values()
            if c.condition_id == BLANKET}


def _hallow_blanket_held_by(engine):
    """Whether the ally carries a blanket save advantage that Hallow itself put there."""
    return any(source.endswith(HALLOW) for source in _blanket_held_by(engine))


def _move_ally(table, combat, mid, *, outside):
    """Commit a real table move to a reachable cell clear of (or inside) the aura's 15 feet.

    Finding 5 of the AUTO112r2 review: the earlier spatial case only ever asserted the inside state, so it
    passed with the aura predicate removed. This actually walks the ally across the boundary. Moving into a new
    cell raises the usual reaction prompts, so the move is driven to its commit like any other action.
    """
    engine = combat._load_session(mid).engine
    owner = engine.state.actors[OWNER]
    moves = [c for c in engine.legal_candidates()
             if c.actor_id == ALLY and c.destination is not None and c.display_name.startswith('Move')
             and (engine.grid.distance_ft(c.destination, owner.position) > 15) is outside]
    assert moves, f"no reachable cell {'outside' if outside else 'inside'} the aura"
    # Farthest out / nearest in, so the move is unambiguous rather than a step that stays on the boundary.
    pick = (max if outside else min)(moves, key=lambda c: engine.grid.distance_ft(c.destination, owner.position))
    settle(table, mid, pick.candidate_id)
    return pick


def _zones(engine):
    return [z for z in engine.state.zones.values() if z.active]


def _charm_save(engine):
    return next(e for e in reversed(engine.events) if e.event_type == 'SAVE_ROLLED' and e.actor_id == ALLY)


# ------------------------------------------------------------------------------------ finding 2: one implementation
def test_hallow_typed_row_no_longer_carries_a_blanket_save_advantage():
    """The typed core cannot say "of the chosen kind"; it must not carry a blanket one either.

    A second implementation in reviewed_final.d left the same benefit reachable twice, and which one won
    depended on hook order (AUTO112r1 review finding 2).
    """
    from tests.h1_support import ROOT
    import json
    from pathlib import Path

    path = Path(ROOT) / 'authority' / 'typed_mechanics' / 'reviewed_final.d' / 'review_sw-earth.json'
    row = json.loads(path.read_text())['mechanics'][HALLOW]
    assert [eff.get('type') for eff in row['effects']] == ['zone'], row['effects']
    # The riders are the printed category menu's own wording; none of them is a save-advantage effect, which
    # is what this case pins. (AUTO112r2 finding 3 added the category-menu rider, so they are no longer empty;
    # the honest-coverage case below is what checks them.)
    assert not [text for text in row['riders'] if 'Advantage' in text or 'saving throw' in text], row['riders']


# ------------------------------------------------------------------------------------ finding 1: legacy auras
@pytest.mark.parametrize('foe_kind,expect', [('undead', 'ADVANTAGE'), ('fey', 'ADVANTAGE')])
def test_legacy_hallow_aura_keeps_its_own_blanket_save_advantage(tmp_path, foe_kind, expect):
    """A pre-change saved aura is left alone: the old blanket Advantage survives, whatever the foe's kind.

    AUTO112r1 review finding 1: the old code deleted that blanket for every ally and only replaced it when
    the aura had a chosen kind, so the first save in an upgraded fight lost its protection for good.
    """
    combat, table, mid = fixture(tmp_path, [HALLOW], cl=15,
                                 bundle_transform=lambda bs: (_prepare(bs, foe_kind), _legacy(bs)))
    # The saved row asks no question of its own, so casting it commits without a prompt.
    prompts = settle(table, mid, candidate(combat, mid, 'Hallow Mandate Edict').candidate_id)
    assert not [p for p in prompts if 'hallow_kind' in p['context']['reaction_source_id']], prompts
    engine = reload(tmp_path, mid)
    zone = _zones(engine)[0]
    # Not asked, not rewritten: no chosen category is invented for a saved aura.
    assert 'fate_hallow_kind' not in zone.trigger_profile
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Foe charm', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    assert _charm_save(engine).payload['mode'] == expect
    # The legacy blanket itself is still on the ally: Fate did not delete it (or any other) condition.
    ally = engine.state.actors[ALLY]
    assert any(c.condition_id == BLANKET for c in ally.conditions.values()), \
        sorted({c.condition_id for c in ally.conditions.values()})


def test_legacy_hallow_aura_gains_no_new_attack_disadvantage(tmp_path):
    """The saved aura keeps its old reach too: no chosen kind means no invented Disadvantage."""
    combat, table, mid = fixture(tmp_path, [HALLOW],
                                 bundle_transform=lambda bs: (_prepare(bs, 'undead'), _legacy(bs)))
    settle(table, mid, candidate(combat, mid, 'Hallow Mandate Edict').candidate_id)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Foe strike', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    strike = next(e for e in reversed(engine.events) if e.event_type == 'ATTACK_ROLLED' and e.actor_id == FOE)
    assert strike.payload['mode'] == 'NORMAL'


# ------------------------------------------------------------------------------------ finding 2: leaving the aura
def test_hallow_save_advantage_only_while_the_ally_is_inside_the_aura(tmp_path):
    """The printed clause is spatial, so this walks the ally across the boundary both ways.

    AUTO112r2 review finding 2: the earlier case only asserted the inside state, so it duplicated the existing
    inside test and passed even with the aura predicate removed. Each state here is a committed table
    transaction, cold-reloaded before it is asserted.
    """
    combat, table, mid = fixture(tmp_path, [HALLOW], cl=15,
                                 bundle_transform=lambda bs: _prepare(bs, 'undead'))
    settle(table, mid, candidate(combat, mid, 'Hallow Mandate Edict').candidate_id,
           {'choice:needle.hallow_kind': 'undead'})
    engine = reload(tmp_path, mid)
    assert _inside(engine), 'the ally starts inside the 15-foot aura'
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Foe charm', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    assert _charm_save(engine).payload['mode'] == 'ADVANTAGE'  # inside: the printed clause applies

    # Out of the aura: the same Undead foe's charm is an ordinary roll again.
    turn(table, mid, ALLY)
    _move_ally(table, combat, mid, outside=True)
    engine = reload(tmp_path, mid)
    assert not _inside(engine), 'the ally left the aura'
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Foe charm', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    assert _charm_save(engine).payload['mode'] == 'NORMAL', 'stale protection must not survive leaving the aura'

    # Back inside: the clause applies again, which is what makes the NORMAL above a boundary and not a decay.
    turn(table, mid, ALLY)
    _move_ally(table, combat, mid, outside=False)
    engine = reload(tmp_path, mid)
    assert _inside(engine), 'the ally re-entered the aura'
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Foe charm', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    assert _charm_save(engine).payload['mode'] == 'ADVANTAGE', 're-entering restores the printed clause'


def _inside(engine):
    """Whether the ally is still within the aura's 15 feet of its owner."""
    owner = engine.state.actors[OWNER]
    return engine.grid.distance_ft(engine.state.actors[ALLY].position, owner.position) <= 15


# ------------------------------------------------- finding 2: another ability's save advantage is independent
def _ward(bs):
    """A sealed setup action for the ally: its own Advantage against being Charmed, from another ability."""
    add_action(bs[1], 'Warding Word', [{'type': 'advantage', 'applies_to': 'self', 'flat': 0, 'formula': 'none',
                                         'damage_types': [], 'ability': 'none', 'condition': 'none', 'distance_ft': 0,
                                         'duration': 'one_minute',
                                         'evidence': 'Advantage on saving throws against being Charmed',
                                         'on': 'saving throws against being Charmed'}],
               target='SELF', typed={'duration': {'kind': 'minutes', 'amount': 1},
                                     'numbers': {'pb': 4, 'key_mod': 2, 'save_dc': 16, 'cl': 15}})


def test_hallow_leaves_another_abilities_save_advantage_alone(tmp_path):
    """An ally warded by another ability keeps that advantage; Hallow never removes a foreign condition."""
    combat, table, mid = fixture(tmp_path, [HALLOW], cl=15,
                                 bundle_transform=lambda bs: (_prepare(bs, 'fey'), _ward(bs)))
    settle(table, mid, candidate(combat, mid, 'Hallow Mandate Edict').candidate_id,
           {'choice:needle.hallow_kind': 'undead'})
    reload(tmp_path, mid)
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Warding Word').candidate_id)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Foe charm', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    # The fey is not the judged kind, so Hallow itself gives nothing; the ally's own ward is the advantage.
    assert _charm_save(engine).payload['mode'] == 'ADVANTAGE'
    ally = engine.state.actors[ALLY]
    held = {c.source_definition_id for c in ally.conditions.values() if c.condition_id == BLANKET}
    assert held and HALLOW not in held, held


# ------------------------------------------------------------------------------------ finding 3: campaign categories
def test_hallow_menu_offers_the_creature_categories_present_in_the_fight(tmp_path):
    """"Another supernatural category appropriate to the campaign" is offered when a creature carries one."""
    combat, table, mid = fixture(tmp_path, [HALLOW], cl=15,
                                 bundle_transform=lambda bs: _prepare(bs, 'construct'))
    prompts = settle(table, mid, candidate(combat, mid, 'Hallow Mandate Edict').candidate_id,
                     {'choice:needle.hallow_kind': 'construct'})
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.hallow_kind')
    options = prompt['choice']['options']
    ids = {o['id'] for o in options}
    # The printed eight are still all there, plus the fight's own creature category.
    assert {'undead', 'fey', 'demons', 'ghosts'} <= ids, sorted(ids)
    assert 'construct' in ids, sorted(ids)
    engine = reload(tmp_path, mid)
    assert engine.state.zones[next(iter(engine.state.zones))].trigger_profile['fate_hallow_kind'] == 'construct'


def test_hallow_campaign_category_gates_the_printed_effects(tmp_path):
    """A campaign category works like a printed one: its attacks on an ally inside get Disadvantage."""
    combat, table, mid = fixture(tmp_path, [HALLOW], cl=15,
                                 bundle_transform=lambda bs: _prepare(bs, 'construct'))
    settle(table, mid, candidate(combat, mid, 'Hallow Mandate Edict').candidate_id,
           {'choice:needle.hallow_kind': 'construct'})
    reload(tmp_path, mid)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Foe strike', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    strike = next(e for e in reversed(engine.events) if e.event_type == 'ATTACK_ROLLED' and e.actor_id == FOE)
    assert strike.payload['mode'] == 'DISADVANTAGE'


def test_hallow_menu_adds_no_invented_category(tmp_path):
    """No category is offered that no printed label supports (nothing guessed from names)."""
    combat, table, mid = fixture(tmp_path, [HALLOW], cl=15,
                                 bundle_transform=lambda bs: _prepare(bs, 'undead'))
    prompts = settle(table, mid, candidate(combat, mid, 'Hallow Mandate Edict').candidate_id,
                     {'choice:needle.hallow_kind': 'undead'})
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.hallow_kind')
    assert {o['id'] for o in prompt['choice']['options']} == {
        'aberrations', 'celestials', 'elementals', 'fey', 'fiends', 'undead', 'demons', 'ghosts'}, \
        sorted(o['id'] for o in prompt['choice']['options'])

# ------------------------------------------------- AUTO112r2 finding 1: a base-compiled aura's leftover blanket
@pytest.mark.parametrize('foe_kind,expect', [('undead', 'ADVANTAGE'), ('fey', 'NORMAL')])
def test_base_compiled_hallow_save_drops_its_own_blanket(tmp_path, foe_kind, expect):
    """An aura compiled by the reviewed base stored its chosen category *and* left a blanket Advantage.

    AUTO112r2 review finding 1: the single save path stopped dropping that blanket, so save_against still read
    it independently and a fey rolled with Advantage even though the judged kind was Undead. The blanket is
    Hallow's own condition on Hallow's own source, so the plug-in takes it over: the judged kind decides.
    """
    combat, table, mid = fixture(tmp_path, [HALLOW], cl=15,
                                 bundle_transform=lambda bs: (_prepare(bs, foe_kind), _base_catalog(bs)))
    settle(table, mid, candidate(combat, mid, 'Hallow Mandate Edict').candidate_id,
           {'choice:needle.hallow_kind': 'undead'})
    engine = reload(tmp_path, mid)
    # The base save as it stands: the category is stored and the blanket is still unconsumed.
    assert engine.state.zones[next(iter(engine.state.zones))].trigger_profile['fate_hallow_kind'] == 'undead'
    assert _hallow_blanket_held_by(engine), _blanket_held_by(engine)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Foe charm', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    assert _charm_save(engine).payload['mode'] == expect
    if expect == 'NORMAL':
        # Taken over, not merely outvoted: the retained blanket is gone from the saved ally.
        assert not _blanket_held_by(engine), _blanket_held_by(engine)


@pytest.mark.parametrize('foe_kind', ['undead', 'fey'])
def test_base_compiled_hallow_leaves_before_first_save(tmp_path, foe_kind):
    """A selected base aura must lose its own blanket even outside, regardless of the foe's category.

    SOLFAUTO112r3: move before the first qualifying save so inside-save cleanup cannot hide the leak.
    Every action is a table commit, and each assertion uses a cold reload with mechanical replay PASS.
    """
    combat, table, mid = fixture(tmp_path, [HALLOW], cl=15,
                                 bundle_transform=lambda bs: (_prepare(bs, foe_kind), _base_catalog(bs)))
    settle(table, mid, candidate(combat, mid, 'Hallow Mandate Edict').candidate_id,
           {'choice:needle.hallow_kind': 'undead'})
    engine = reload(tmp_path, mid)
    assert _inside(engine)
    assert _hallow_blanket_held_by(engine)
    assert _zones(engine)[0].trigger_profile['fate_hallow_kind'] == 'undead'

    turn(table, mid, ALLY)
    _move_ally(table, combat, mid, outside=True)
    engine = reload(tmp_path, mid)
    assert not _inside(engine)
    assert _hallow_blanket_held_by(engine), 'no qualifying save has cleaned up the base blanket yet'
    assert not any(e.event_type == 'SAVE_ROLLED' and e.actor_id == ALLY for e in engine.events)

    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Foe charm', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    assert _charm_save(engine).payload['mode'] == 'NORMAL'
    assert not _hallow_blanket_held_by(engine)
    assert not _blanket_held_by(engine)
    removed = [e for e in engine.events if e.event_type == 'CONDITION_REMOVED'
               and ALLY in e.target_ids and e.payload.get('reason') == 'HALLOW_SOURCE_QUALIFIED']
    assert len(removed) == 1
    assert removed[0].source_definition_id == _zones(engine)[0].source_definition_id


def test_base_compiled_hallow_blanket_drop_leaves_another_abilities_advantage(tmp_path):
    """The drop is scoped to the aura's own source, so a foreign ward on the same ally survives it."""
    combat, table, mid = fixture(tmp_path, [HALLOW], cl=15,
                                 bundle_transform=lambda bs: (_prepare(bs, 'fey'), _base_catalog(bs), _ward(bs)))
    settle(table, mid, candidate(combat, mid, 'Hallow Mandate Edict').candidate_id,
           {'choice:needle.hallow_kind': 'undead'})
    reload(tmp_path, mid)
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Warding Word').candidate_id)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Foe charm', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    held = _blanket_held_by(engine)
    assert held and not _hallow_blanket_held_by(engine), held
    # The fey is not the judged kind, so the surviving advantage is the ally's own ward.
    assert _charm_save(engine).payload['mode'] == 'ADVANTAGE'


# ------------------------------------------------- AUTO112r2 finding 3: coverage matches what the row can do
def test_hallow_coverage_is_honest_while_a_campaign_category_is_the_tables_call():
    """The printed list is automated; naming a campaign category no creature here carries is not.

    AUTO112r2 review finding 3: the row claimed FULL while the menu could only offer the categories present in
    the fight. Either it supports the choice or it says so; this row says so, and the builder derives the
    coverage from that rider instead of overstating it.
    """
    from tests.h1_support import ROOT
    import json
    from pathlib import Path

    reviewed = json.loads((Path(ROOT) / 'authority' / 'typed_mechanics' / 'reviewed_final.d'
                           / 'review_sw-earth.json').read_text())['mechanics'][HALLOW]
    record = json.loads((Path(ROOT) / 'authority' / 'Tianxia_Typed_Mechanics_Authority_R1.json').read_text())
    record = record['mechanics'][HALLOW]
    assert reviewed['riders'], 'the unsupported choice must stay disclosed in the row'
    assert record['coverage'] == 'CORE_WITH_RIDERS', record['coverage']
    # Plain wording for a player who knows only basic D&D: no ability ids, no code names.
    for text in record['riders']:
        assert 'TAL_' not in text and 'fate_hallow' not in text, text
