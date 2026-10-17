"""Verdant Growth automations added by AUTO132.

Hungry Root Drinks the Spill prints "you may place 1 Growth Mark on that creature or on the Living Claim".  The
claim option used to be a GM call; it is now asked for and stored on the claim, which survives a commit and reload
and ends when the marker's next turn does.

Review AUTO132r1 required (a) the unwilling creature's printed Constitution save to gate BOTH recipients rather
than only the mark on the creature, and (b) the claim's deadline to be a real integer compared at turn end, so the
mark survives the turn it was placed on.  The tests below fail without both.
"""
from copy import deepcopy

import pytest
from combat.canonical import canonical_sha256
from combat.ext import verdant_chassis as verdant
from tests.worker2_support import ALLY, FOE, OWNER, candidate, fixture, reload, settle

SOW = 'TAL_VERDANT_GROWTH_SOW_LIVING_CLAIM'
HUNGRY = 'TAL_VERDANT_GROWTH_HUNGRY_ROOT_DRINKS_THE_SPILL'
SEED = 'TAL_VERDANT_GROWTH_SEED_THORN_STRIKE'
SPILL = "choice:needle.hungry_root"

# "Cultivation Save DC" is the owner's, so a DC of 1 can never be failed and a DC of 40 can never be made.  That
# forces either printed save outcome without touching the roller, for either recipient of the choice.
ALWAYS_REFUSES, NEVER_REFUSES = 1, 40


def spill_setup(bundles, who=(OWNER,)):
    """A fixed setup action so a creature really regains Hit Points through the typed table resolver."""
    for b in bundles:
        if b['actor_id'] not in who:
            continue
        catalog = b['action_catalog']
        # The owner copies Seed-Thorn Strike; an actor with no Verdant rows borrows its own basic action.
        base = next((x for x in catalog if x['display_name'] == 'Seed-Thorn Strike'), None) \
            or next(x for x in catalog if x.get('parameters', {}).get('typed') is not None)
        a = deepcopy(base)
        # A unique id per actor: two bundles may not carry the same typed action id.
        spill_id = f'test:auto132.spill.{b["actor_id"].rsplit(".", 1)[-1]}'
        a.update(source_definition_id=spill_id, display_name='Prepare Spill', economy='NONE')
        a['parameters']['typed'].update(source=spill_id, effects=[
            {"type": "damage", "applies_to": "target", "dice": {"count": 1, "sides": 6}, "flat": 0,
             "formula": "none", "damage_types": ["piercing"], "ability": "none", "condition": "none",
             "distance_ft": 0, "on": "", "duration": "instant", "evidence": "setup: a wound"},
            {"type": "healing", "applies_to": "target", "dice": {"count": 1, "sides": 6}, "flat": 0,
             "formula": "none", "damage_types": [], "ability": "none", "condition": "none",
             "distance_ft": 0, "on": "", "duration": "instant", "evidence": "setup: it drinks the spill"},
        ])
        b['action_catalog'].append(a)
        b['actor_template']['action_ids'].append(spill_id)
    for b in bundles:
        b.pop('bundle_sha256', None)
        b['bundle_sha256'] = canonical_sha256(b)


def owner_claim(engine):
    claims = verdant.claims(engine, engine.state.actors[OWNER])
    assert len(claims) == 1, claims
    return claims[0]


def next_turn_of(table, mid, actor):
    """End the current turn, then advance to ``actor``'s NEXT turn, answering prompts on the way."""
    end_turn(table, mid)
    for _ in range(12):
        state = table.state(mid)
        if state['menu']['actor_id'] == actor:
            return
        settle(table, mid, state['menu']['end_turn'])
    raise AssertionError(f'{actor} never receives a turn')


def end_turn(table, mid):
    settle(table, mid, table.state(mid)['menu']['end_turn'])


def spill_candidate(combat, mid, creature=FOE):
    """The setup action aimed at ``creature``. The action is an attack row, so a later turn may offer it without a
    target id; prefer the aimed one and fall back to the single offered candidate."""
    engine = combat._load_session(mid).engine
    rows = [c for c in engine.legal_candidates()
            if getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', None) == 'Prepare Spill']
    assert rows, 'Prepare Spill is not offered'
    aimed = [c for c in rows if creature in (c.target_ids or ())]
    return aimed[0] if aimed else rows[0]


def spill(tmp_path, table, mid, combat, picks, dc=16):
    """Sow a claim under the foe, then have it drink the spill; returns the prompts the choice raised."""
    settle(table, mid, candidate(combat, mid, 'Sow Living Claim', at=(6, 5)).candidate_id)
    return settle(table, mid, spill_candidate(combat, mid).candidate_id, {SPILL: picks})


def hungry_saves(engine, creature=FOE):
    """The Constitution saves Hungry Root made the creature, taken from the recorded rolls."""
    return [r for r in engine.rolls if r.actor_id == creature and HUNGRY in str(r.reason)]


@pytest.mark.parametrize('pick,on_claim,on_foe', [('claim', 1, 0), ('mark', 0, 1), (None, 0, 0)])
def test_hungry_root_offers_the_printed_claim_choice(tmp_path, pick, on_claim, on_foe):
    """The owner is asked whether the mark goes on the creature or on the Living Claim it is touching."""
    combat, table, mid = fixture(tmp_path, [SOW, HUNGRY, SEED], bundle_transform=spill_setup,
                                foe_position={"x": 6, "y": 5})
    settle(table, mid, candidate(combat, mid, 'Sow Living Claim', at=(6, 5)).candidate_id)
    prompts = settle(table, mid, candidate(combat, mid, 'Prepare Spill', target=FOE).candidate_id,
                     {SPILL: pick})
    if pick is not None:
        assert any(p['context']['reaction_source_id'] == SPILL for p in prompts)
        offered = next(p['choice'] for p in prompts if p['context']['reaction_source_id'] == SPILL)
        assert [o['id'] for o in offered['options']] == ['mark', 'claim']
        assert 'Living Claim' in offered['options'][1]['label']
    engine = reload(tmp_path, mid)
    assert verdant.claim_marks(owner_claim(engine), engine.state.actors[OWNER]) == on_claim
    assert verdant.marks(engine.state.actors[FOE], engine.state.actors[OWNER]) == on_foe


@pytest.mark.parametrize('pick', ['claim', 'mark'])
@pytest.mark.parametrize('refuses,dc', [(True, ALWAYS_REFUSES), (False, NEVER_REFUSES)])
def test_an_unwilling_creature_saves_against_both_mark_recipients(tmp_path, pick, refuses, dc):
    """"If the creature is unwilling, it makes a Constitution saving throw. Successful Save: No mark."

    The printed save governs the whole choice, so an unwilling creature that refuses gets no mark even when the
    owner aims it at its Living Claim -- the bug this test exists for.
    """
    combat, table, mid = fixture(tmp_path, [SOW, HUNGRY, SEED], bundle_transform=spill_setup,
                                 foe_position={"x": 6, "y": 5}, owner_dc=dc)
    spill(tmp_path, table, mid, combat, [pick], dc=dc)
    engine = reload(tmp_path, mid)
    saves = hungry_saves(engine)
    assert saves, [str(r.reason) for r in engine.rolls]  # the refusal save is really rolled
    assert all((s.total >= dc) is refuses for s in saves), [(s.total, dc) for s in saves]
    placed = 0 if refuses else 1
    owner = engine.state.actors[OWNER]
    assert verdant.claim_marks(owner_claim(engine), owner) == (placed if pick == 'claim' else 0)
    assert verdant.marks(engine.state.actors[FOE], owner) == (placed if pick == 'mark' else 0)


def test_claim_mark_deadline_is_an_integer_and_ends_on_the_markers_next_turn(tmp_path):
    """Persisted on the claim, not an ad-hoc value: it survives a reload, keeps an integer deadline and ends at the
    end of the marker's NEXT turn -- not the turn it was placed on."""
    combat, table, mid = fixture(tmp_path, [SOW, HUNGRY, SEED], bundle_transform=spill_setup,
                                 foe_position={"x": 6, "y": 5})
    spill(tmp_path, table, mid, combat, ['claim'])
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    claim = owner_claim(engine)
    assert verdant.claim_marks(claim, owner) == 1
    stored = claim.component["growth_marks"][owner.entity_id]
    # type(), not isinstance(): a boolean is an int, and a boolean deadline read as "already due".
    assert all(type(value) is int for value in stored.values()), stored
    assert stored["deadline"] == stored["marker_turn"] + 1, stored
    assert stored["marker_turn"] == owner.turns_started, stored

    next_turn_of(table, mid, OWNER)  # the turn it was placed on ends, and everyone else's follows
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].turns_started == stored["marker_turn"] + 1
    assert verdant.claim_marks(owner_claim(engine), engine.state.actors[OWNER]) == 1, 'ended a turn early'

    end_turn(table, mid)  # the end of the marker's next turn is the printed deadline
    engine = reload(tmp_path, mid)
    assert verdant.claim_marks(owner_claim(engine), engine.state.actors[OWNER]) == 0


def test_a_second_claim_mark_renews_the_deadline(tmp_path):
    """Placing another mark starts a new deadline, as a mark on a creature does; only spending keeps the old one."""
    combat, table, mid = fixture(tmp_path, [SOW, HUNGRY, SEED], bundle_transform=spill_setup,
                                 foe_position={"x": 6, "y": 5}, owner_dc=NEVER_REFUSES)
    spill(tmp_path, table, mid, combat, ['claim'])
    first = reload(tmp_path, mid)
    marker_turn = first.state.actors[OWNER].turns_started

    next_turn_of(table, mid, OWNER)
    settle(table, mid, spill_candidate(combat, mid).candidate_id, {SPILL: ['claim']})
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    claim = owner_claim(engine)
    stored = claim.component["growth_marks"][owner.entity_id]
    assert verdant.claim_marks(claim, owner) == 2
    assert stored["marker_turn"] > marker_turn, stored
    assert stored["deadline"] == stored["marker_turn"] + 1, stored

    end_turn(table, mid)  # the renewed mark does not end with the turn that renewed it
    engine = reload(tmp_path, mid)
    assert verdant.claim_marks(owner_claim(engine), engine.state.actors[OWNER]) == 2


def test_a_claim_mark_placed_on_another_creatures_turn_ends_on_the_owners_next_turn(tmp_path):
    """Hungry Root can fire while somebody else acts. The mark is still the OWNER's, so it ends with the owner's
    next turn and not with the turn of whoever happened to be acting."""
    combat, table, mid = fixture(tmp_path, [SOW, HUNGRY, SEED], ally_talents=[SEED],
                                 bundle_transform=lambda b: spill_setup(b, (OWNER, ALLY)),
                                 foe_position={"x": 6, "y": 5}, owner_dc=NEVER_REFUSES)
    settle(table, mid, candidate(combat, mid, 'Sow Living Claim', at=(6, 5)).candidate_id)
    next_turn_of(table, mid, ALLY)  # the spill is drunk on the ally's turn, not the owner's
    settle(table, mid, spill_candidate(combat, mid).candidate_id, {SPILL: ['claim']})

    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    stored = owner_claim(engine).component["growth_marks"][owner.entity_id]
    assert verdant.claim_marks(owner_claim(engine), owner) == 1
    assert all(type(value) is int for value in stored.values()), stored
    assert stored["marker_turn"] == owner.turns_started, stored
    assert stored["deadline"] == stored["marker_turn"] + 1, stored

    next_turn_of(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert verdant.claim_marks(owner_claim(engine), engine.state.actors[OWNER]) == 1, 'ended a turn early'

    end_turn(table, mid)
    engine = reload(tmp_path, mid)
    assert verdant.claim_marks(owner_claim(engine), engine.state.actors[OWNER]) == 0


def legacy_hold(monkeypatch):
    """Rewrite the claim's stored Growth Mark to the shape saved before deadlines were integers.

    Anchored on the claim's own OBJECT_UPDATED event, so the rewrite is a journaled part of the same committed
    action that placed the mark: the reload below reads a real saved fight, not a doctored state document.
    """
    from combat.gate2_runtime_models import RuntimeObjectState
    from combat.gate4_engine import Gate4ControllerEngine

    original = Gate4ControllerEngine._update_object

    def rewrite(engine, obj, source_id, actor_id=None):
        result = original(engine, obj, source_id, actor_id)
        held = (obj.component or {}).get("growth_marks")
        if obj.object_kind == verdant.KIND and held and OWNER in held:
            component = {**obj.component,
                         "growth_marks": {OWNER: {"count": 1, "marker_turn": 0, "deadline": False}}}
            original(engine, RuntimeObjectState.model_validate(obj.model_copy(update={"component": component}).model_dump(mode="json")),
                     source_id, actor_id)
        return result

    monkeypatch.setattr(Gate4ControllerEngine, "_update_object", rewrite)


def test_a_boolean_deadline_mark_saved_on_a_claim_still_ends_at_the_owners_first_turn_end(monkeypatch, tmp_path):
    """A fight saved before the deadline was an integer stored a boolean, and 0 is a real turn counter.

    Such a mark used to be read as "no turn number recorded", so each turn asked for it again and the comparison
    could never come true: the mark stayed on the claim for the rest of the fight. It must end on the owner's
    first turn end -- the deadline a mark placed during turn 0 has -- through a real commit and reload.
    """
    combat, table, mid = fixture(tmp_path, [SOW, HUNGRY, SEED], bundle_transform=spill_setup,
                                 foe_position={"x": 6, "y": 5})
    legacy_hold(monkeypatch)
    spill(tmp_path, table, mid, combat, ['claim'])

    engine = reload(tmp_path, mid)  # the legacy shape is what the journal really holds
    owner = engine.state.actors[OWNER]
    stored = owner_claim(engine).component["growth_marks"][owner.entity_id]
    assert stored == {"count": 1, "marker_turn": 0, "deadline": False}, stored
    assert type(stored["deadline"]) is bool, stored
    assert verdant.claim_marks(owner_claim(engine), owner) == 1

    end_turn(table, mid)  # the owner's first turn end is the printed deadline
    engine = reload(tmp_path, mid)
    assert verdant.claim_marks(owner_claim(engine), engine.state.actors[OWNER]) == 0, 'the legacy mark never ended'
