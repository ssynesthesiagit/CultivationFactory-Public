"""Review regressions: sealed setup, service intent commits, verified cold reload."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from combat.canonical import canonical_sha256
from combat.ext import resistance_bypass
from combat.target_knowledge import located
from tests import test_a2_sword_second_pass as S


def setup(*, invisible=False, critical=False, companion=False, foe_ac=None):
    def transform(bundles):
        bundle = bundles[0]
        action = deepcopy(next(a for a in bundle['action_catalog'] if a['display_name'] == 'Sword Beyond Hand'))
        action.update(source_definition_id='test:sword.review.setup', display_name='Review setup', economy='NONE', costs=[])
        typed = action['parameters']['typed']
        typed['attack_modifier_loadout'] = []
        typed['effects'] = [
            {'type': 'damage', 'flat': 230, 'damage_types': ['force'], 'applies_to': 'target'},
            {'type': 'mark', 'mark': 'Sword Intent', 'applies_to': 'target', 'expires_on': 'UNTIL_REMOVED'},
        ]
        for condition, enabled in [('invisible', invisible), ('paralyzed', critical)]:
            if enabled:
                typed['effects'].append({'type': 'condition', 'condition': condition, 'applies_to': 'target', 'expires_on': 'UNTIL_REMOVED'})
        bundle['action_catalog'].append(action)
        bundle['actor_template']['action_ids'].append(action['source_definition_id'])
        if companion:
            # Companions have no separate mode; the controller belongs to their owner.
            bundle['actor_template'].update(owner_id=S.IDS[3], primary_combatant=False)
        bundle.pop('bundle_sha256', None)
        bundle['bundle_sha256'] = canonical_sha256(bundle)
        if foe_ac is not None:
            foe = bundles[1]
            foe['actor_template']['armor_class'] = foe_ac
            foe.pop('bundle_sha256', None)
            foe['bundle_sha256'] = canonical_sha256(foe)
    return transform


def candidate(combat, mid, name, target=None):
    return next(c for c in combat._load_session(mid).engine.legal_candidates()
                if c.display_name.startswith(name) and (target is None or target in c.target_ids)
                and (name != 'Heaven-Cutting Crescent' or c.destination and c.destination.x > 3 and c.destination.y == 4))


def ai_send(combat, mid, chosen, answers=()):
    payload = {'actor_id': chosen.actor_id, 'decision_id': chosen.decision_id,
               'state_version': chosen.state_version, 'candidate_id': chosen.candidate_id,
               'target_ids': list(chosen.target_ids), 'option_ids': [],
               'destination': chosen.destination.model_dump(mode='json') if chosen.destination else None}
    checked = combat.ai_validate(mid, payload)
    return combat.ai_execute(mid, payload, checked['validation_token'], reactions=list(answers))


def record_choices(combat):
    contexts = []
    original = combat.controller
    class RecordingController:
        def choose_reaction(self, context):
            contexts.append(context)
            return original.choose_reaction(context)
        def __getattr__(self, name):
            return getattr(original, name)
    combat.controller = RecordingController()
    return contexts


@pytest.mark.parametrize('mode', ['LOCAL_AUTO', 'API_AUTO'])
@pytest.mark.parametrize('companion', [False, True])
def test_ai_crescent_only_offers_located_failed_recipients(tmp_path, mode, companion):
    combat, table, mid = S.fixture(tmp_path, 'SWORD-review-area', many=True, hp=1000,
                                  bundle_transform=setup(invisible=True, companion=companion))
    S.press(table, mid, 'Review setup')
    engine = S.reload(combat, tmp_path, mid)
    assert not located(engine, engine.state.actors[S.IDS[0]], engine.state.actors[S.IDS[1]])
    if companion:
        actor = engine.state.actors[S.IDS[0]]
        assert not actor.primary_combatant and actor.owner_id == S.IDS[3]
    contexts = record_choices(combat)
    controller = S.IDS[3] if companion else S.IDS[0]
    combat.set_controller_mode(mid, actor_id=controller, controller_mode=mode)
    assert ai_send(combat, mid, candidate(combat, mid, 'Heaven-Cutting Crescent'))['status'] == 'COMMITTED'
    engine = S.reload(combat, tmp_path, mid)
    assert not resistance_bypass.records(engine, engine.state.actors[S.IDS[1]])
    assert resistance_bypass.records(engine, engine.state.actors[S.IDS[2]])
    questions = [c for c in contexts if c.extension_choice and S.IDS[2] in c.extension_choice.option_ids]
    assert questions
    for question in questions:
        assert set(question.extension_choice.option_ids) == {S.IDS[2]}
        assert 'First foe' not in json.dumps(question.choice_trigger)


@pytest.mark.parametrize('mode', ['LOCAL_AUTO', 'API_AUTO'])
@pytest.mark.parametrize('concealed', [False, True])
def test_ai_fatal_receipt_requires_current_perception(tmp_path, mode, concealed):
    combat, table, mid = S.fixture(tmp_path, 'A2-FATAL-100-Qi', hp=400,
                                  bundle_transform=setup(invisible=concealed, critical=True))
    S.press(table, mid, 'Review setup')
    engine = S.reload(combat, tmp_path, mid)
    owner, foe = (engine.state.actors[aid] for aid in S.IDS[:2])
    assert foe.current_hp <= foe.maximum_hp // 2
    assert S.bears_mark(foe, owner.entity_id, 'Sword Intent')
    assert located(engine, owner, foe) == (not concealed)
    resources = dict(owner.resources)
    combat.set_controller_mode(mid, actor_id=S.IDS[0], controller_mode=mode)
    assert ai_send(combat, mid, candidate(combat, mid, 'Sword Beyond Hand', S.IDS[1]))['status'] == 'COMMITTED'
    engine = S.reload(combat, tmp_path, mid)
    used = any(c.condition_id == 'condition:typed.sword_fatal_strike_used' for c in engine.state.actors[S.IDS[0]].conditions.values())
    assert used == (not concealed)
    rolls = [r for r in engine.rolls if 'sword_fatal_strike.damage' in r.reason]
    assert len(rolls) == (0 if concealed else 1)
    if concealed:
        assert engine.state.actors[S.IDS[0]].resources == resources
    else:
        # Paralysis within five feet forces a critical: Fatal must carry that receipt.
        assert rolls[0].expression.startswith('12d10')
        assert resources['resource:core.qi'] - engine.state.actors[S.IDS[0]].resources['resource:core.qi'] == 8


@pytest.mark.parametrize('mode', ['LOCAL_AUTO', 'API_AUTO'])
def test_manual_fatal_owner_is_asked_during_ai_turn(tmp_path, mode):
    combat, table, mid = S.fixture(tmp_path, 'A2-FATAL-100-Qi', hp=400, bundle_transform=setup(foe_ac=1))
    S.press(table, mid, 'Review setup')
    S.reload(combat, tmp_path, mid)
    S.end(table, mid)
    combat.set_controller_mode(mid, actor_id=S.IDS[1], controller_mode=mode)
    chosen = next(c for c in combat._load_session(mid).engine.legal_candidates()
                  if c.destination and (c.destination.x, c.destination.y) == (6, 4) and str(c.kind) == 'MOVE')
    answers = []
    saw_fatal = False
    resources = dict(S.reload(combat, tmp_path, mid).state.actors[S.IDS[0]].resources)
    for _ in range(12):
        result = ai_send(combat, mid, chosen, answers)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'AWAITING_REACTION'
        context = result['reaction_context']
        assert context['reactor_id'] == S.IDS[0]
        if context['reaction_source_id'] == 'choice:needle.sword_fatal_strike':
            saw_fatal = True
        # The manual owner may decline each optional reaction, including Fatal.
        answers.append({k: context[k] for k in ('checkpoint', 'reactor_id', 'reaction_source_id')} | {'selection': 'DECLINE', 'option_ids': []})
        choice = context.get('extension_choice') or {}
        if choice and not choice.get('allow_decline', True):
            answers[-1].update(selection='USE', option_ids=list(choice['option_ids'])[:choice.get('minimum_selections', 1)])
        if not saw_fatal:
            # Accept the weapon Opportunity Attack, decline optional riders.
            if context['reaction_source_id'] in {'reaction:typed.opportunity_attack', 'system:combat.opportunity_attack'}:
                answers[-1]['selection'] = 'USE'
    else:
        pytest.fail('unbounded manual questions')
    assert saw_fatal
    engine = S.reload(combat, tmp_path, mid)
    assert engine.state.actors[S.IDS[0]].resources == resources
    assert not any(c.condition_id == 'condition:typed.sword_fatal_strike_used' for c in engine.state.actors[S.IDS[0]].conditions.values())


def test_retained_export_stays_in_test_temp_and_preserves_existing(tmp_path, monkeypatch):
    combat, table, mid = S.fixture(tmp_path, 'SWORD-review-export', many=True)
    S.press(table, mid, 'Heaven-Cutting Crescent', want='Second foe')
    S.reload(combat, tmp_path, mid)
    original = S.shutil.copytree
    def guarded(source, destination, *args, **kwargs):
        assert Path(destination).is_relative_to(tmp_path), 'test export escaped tmp_path'
        return original(source, destination, *args, **kwargs)
    monkeypatch.setattr(S.shutil, 'copytree', guarded)
    # Guard deletion before calling the old exporter: baseline must preserve old receipts.
    monkeypatch.setattr(S.shutil, 'rmtree', lambda *args, **kwargs: pytest.fail('test exporter deletes retained evidence'))
    folder = S.retain(combat, mid, 'review-export')
    sentinel = folder / 'preserve.txt'
    sentinel.write_text('retained')
    with pytest.raises(FileExistsError):
        S.retain(combat, mid, 'review-export')
    assert sentinel.read_text() == 'retained'


def test_sword_reviewed_definitions_are_unique_after_service_reload(tmp_path):
    combat, table, mid = S.fixture(tmp_path, 'SWORD-review-authority', many=True)
    S.press(table, mid, 'Heaven-Cutting Crescent', want='Second foe')
    engine = S.reload(combat, tmp_path, mid)
    assert resistance_bypass.records(engine, engine.state.actors[S.IDS[2]])
    for feature in (S.FATAL, S.HEAVEN):
        sources = [p.name for p in (S.ROOT / 'authority/typed_mechanics/reviewed_final.d').glob('*.json')
                   if feature in json.loads(p.read_text()).get('mechanics', {})]
        assert len(sources) == 1, (feature, sources)
