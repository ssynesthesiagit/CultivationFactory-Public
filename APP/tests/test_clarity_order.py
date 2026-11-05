"""Sentence alignment restores moved rules while retaining every edited word."""
from collections import Counter

from tools.clarity_order import restore_order, sentences


def test_moved_rule_returns_after_its_trigger_and_keeps_new_wording():
    old = ('Clean Hands\nUse a reaction.\nTrigger: You would place a Debt Imprint.\n'
           'Cost: None\nYou may choose not to place the Debt Imprint.\n'
           'If its source is absent, learn only that the actor was not the debtor.')
    edited = ('Clean Hands\nYou may choose not to place the Debt Imprint.\n'
              'Use a reaction.\nTrigger: You would place a Debt Imprint.\nCost: None\n'
              'If its source is absent, you learn only that the actor was not the debtor.')
    restored, audit = restore_order(old, edited)
    assert audit['rejected']
    assert restored.index('Trigger:') < restored.index('You may choose not to place')
    assert 'you learn only' in restored
    assert Counter(sentences(restored)) == Counter(sentences(edited))


def test_rule_clause_returns_after_the_condition_it_modifies():
    old = 'Test\nWhile your shield is raised, choose one benefit.\nYou may move 5 feet.\nYou may gain +1 AC.'
    edited = 'Test\nYou may move 5 feet.\nWhile your shield is raised, choose one benefit.\nYou may gain +1 AC.'
    restored, audit = restore_order(old, edited)
    assert audit['rejected']
    assert restored.index('While your shield') < restored.index('You may move')


def test_self_contained_summary_before_requirement_is_a_safe_layout_move():
    old = 'Test\nRequirements: CL 5.\nYou may craft Rare recipes.'
    edited = 'Test\nYou may craft Rare recipes.\nRequirements: CL 5 (Cultivation Level).'
    restored, audit = restore_order(old, edited)
    assert audit['inversions'] and not audit['rejected']
    assert restored == edited


def test_header_and_named_option_keep_their_qualifying_sentences():
    old = ('Test\nTrigger: You place a mark.\nUse Limit: Once per week. If it replaces a greater mark, once per month.\n'
           'You place a mark.\nLift: Move 5 feet. This movement does not provoke Opportunity Attacks.')
    edited = ('Test\nYou place a mark.\nTrigger: You place a mark.\n'
              'Use Limit: Once per week. If it replaces a greater mark, once per month.\n'
              'Lift: Move 5 feet. This movement does not provoke Opportunity Attacks.')
    restored, audit = restore_order(old, edited)
    assert audit['rejected']
    assert 'Use Limit: Once per week. If it replaces a greater mark, once per month.' in restored.splitlines()
    assert 'Lift: Move 5 feet. This movement does not provoke Opportunity Attacks.' in restored.splitlines()
