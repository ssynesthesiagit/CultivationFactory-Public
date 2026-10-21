"""Regression: Meridians carrier matching admits only the save's own imposed afflictions (F4R finding 2)."""
from types import SimpleNamespace as NS

from combat.ext.adaptations import _new_affliction_carriers

HOSTILE = 'action:test.hostile_affliction'


def condition(cid, *, source=HOSTILE, actor='foe', seq=10):
    return NS(condition_id=cid, source_definition_id=source, source_actor_id=actor, applied_sequence=seq)


def ctx(typed, start=5):
    return NS(source=HOSTILE, actor=NS(entity_id='foe'), damage_cache={'adapt_save_start': start}, typed=typed)


SAVE_POISON = {'type': 'save', 'ability': 'con', 'on_fail': [{'type': 'condition', 'condition': 'poisoned'}]}


def names(carriers):
    return sorted(c.condition_id for c in carriers)


def test_same_actor_unrelated_affliction_in_window_is_not_this_save():
    # The hostile actor applied blindness via another source inside the save window; this save only imposes poison.
    subject = NS(conditions={'a': condition('condition:typed.poisoned'),
                             'b': condition('condition:typed.blinded', source='action:test.other_reaction')})
    assert names(_new_affliction_carriers(ctx(SAVE_POISON), subject)) == ['condition:typed.poisoned']


def test_native_carrier_of_imposed_affliction_still_counts():
    # Poison Touch style: the condition's source is a separate carrier feature, but the save names poisoned.
    subject = NS(conditions={'a': condition('condition:typed.poisoned', source='feature:carrier')})
    assert names(_new_affliction_carriers(ctx(SAVE_POISON), subject)) == ['condition:typed.poisoned']


def test_condition_applied_before_window_is_not_this_save():
    subject = NS(conditions={'a': condition('condition:typed.poisoned', seq=3)})
    assert _new_affliction_carriers(ctx(SAVE_POISON), subject) == []


def test_affliction_not_named_by_save_is_rejected_even_from_same_actor():
    subject = NS(conditions={'a': condition('condition:typed.stunned')})
    assert _new_affliction_carriers(ctx(SAVE_POISON), subject) == []
