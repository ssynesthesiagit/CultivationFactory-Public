"""Real own-view facts reach DOM rendering and offline provider dispatch."""
import json
import subprocess
from urllib.parse import parse_qs, urlsplit

import pytest

from tests.test_mgr_t14_bloodsense import source, probes, BLOOD
from tests.worker2_support import OWNER, ALLY, FOE, candidate, settle, reload, prompt_turn, fixture
from tests.test_agent_seats import runner_for
from tests.test_seat_choices import configure
from tests import test_a2_glass_stock as stock


@pytest.fixture(autouse=True)
def offline_ranking(monkeypatch):
    from combat import menu_rank, embedding_rank
    def transport(url, body, timeout):
        inputs = json.loads(body)['input']
        return {'data': [{'index': index, 'embedding': [1.0, 0.0]}
                         for index, _ in enumerate(inputs)]}
    monkeypatch.setattr(menu_rank, '_CLIENT', embedding_rank.EmbeddingClient(transport=transport))


def prepared(tmp_path):
    rows = [source('creature', entity_id=FOE, circulation=1, source_key='PRIVATE_SOURCE'),
            source('spill', position={'x': 5, 'y': 6}, exposed=1, occurred_at_seconds=-30),
            source('corpse', object_id='object:map.700', obvious=1, likely_blood_loss=1),
            source('sample', object_id='object:map.701', obvious=1, source_key='PRIVATE_SOURCE'),
            source('sample', position={'x': 19, 'y': 6}, label='studied vial',
                   source_key='PRIVATE_SOURCE', studied_by=[OWNER])]
    def arena(doc):
        doc['sensory_sources'] = rows
        doc['map_objects'] = [
            {'id': 700, 'kind': 'custom', 'x': 5, 'y': 7, 'name': 'fallen traveller',
             'size': 'tiny', 'blocks': False, 'hp': 10},
            {'id': 701, 'kind': 'custom', 'x': 5, 'y': 6, 'name': 'new vial',
             'size': 'tiny', 'blocks': False, 'hp': 10}]
    combat, table, mid = fixture(tmp_path, [BLOOD], named=True, bundle_transform=probes,
                               battlefield_transform=arena)
    prompt_turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Injure self').candidate_id)
    reload(tmp_path, mid)
    prompt_turn(table, mid, OWNER)
    # Consumers read a freshly reconstructed service, not a warm session cache.
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    return combat, table, mid


EXPECTED = ['Bloodsense: Mara is injured.',
            'Bloodsense: A creature at half its maximum HP or less is to the east.',
            'Bloodsense: Blood was spilled to the east within the last hour.',
            'Bloodsense: fallen traveller likely died from blood loss.',
            'Bloodsense: new vial comes from the same creature as studied vial, which you already studied.']


def test_own_findings_render_as_text_and_clear_for_other_observers(tmp_path):
    _, table, mid = prepared(tmp_path)
    state = table.state(mid, fog=True, fog_view='own', fog_actor_ids=(OWNER, ALLY))
    lines = state['fog_perception'][OWNER].get('information_text', [])
    assert set(EXPECTED) <= set(lines)
    assert not state['fog_perception'][ALLY].get('information_text')
    assert all('information_text' not in row for row in table.state(mid, fog=True)['fog_perception'].values())
    script = r'''
import assert from 'node:assert/strict';
import fs from 'node:fs';
const {renderInformation} = await import('data:text/javascript;base64,' + fs.readFileSync('static/tabletop/information.js').toString('base64'));
const state = JSON.parse(fs.readFileSync(0, 'utf8'));
const doc = {createElement(tag) {return {tag, textContent: ''};}};
const host = {ownerDocument: doc, childNodes: [], replaceChildren() {this.childNodes = [];},
              append(node) {this.childNodes.push(node);}};
const owner = {entity_id: 'actor:factory.worker2-owner', display_name: 'Wren'};
renderInformation(host, state, [owner]);
assert.equal(host.hidden, false);
assert(host.childNodes.some(n => n.textContent === 'Bloodsense: Mara is injured.'));
assert(host.childNodes.some(n => n.textContent.includes('within the last hour')));
assert(host.childNodes.some(n => n.textContent.includes('likely died from blood loss')));
assert(host.childNodes.some(n => n.textContent.includes('already studied')));
assert(!JSON.stringify(host.childNodes).includes('PRIVATE_SOURCE'));
state.observer_information[owner.entity_id].information_text = ['<img src=x onerror=alert(1)>'];
renderInformation(host, state, [owner]);
assert.equal(host.childNodes[1].textContent, '<img src=x onerror=alert(1)>');
assert(!('innerHTML' in host.childNodes[1]));
renderInformation(host, state, [{entity_id: 'actor:factory.worker2-ally', display_name: 'Tobin'}]);
assert.equal(host.hidden, true);
renderInformation(host, state, []);
assert.equal(host.childNodes.length, 0);
// Guard the actual page wiring, not only the isolated renderer.
const app = fs.readFileSync('static/tabletop/tabletop.js', 'utf8');
assert(app.includes('renderInformation($("#ttInformation"), app.state,'));
assert(app.includes('actors().filter(isOwnedActor)'));
assert(fs.readFileSync('static/tabletop/tabletop.html', 'utf8').includes('id="ttInformation"'));
'''
    result = subprocess.run(['node', '--input-type=module', '-e', script],
                            input=json.dumps(state), text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_fallen_nonowner_keeps_ally_geometry_without_private_findings(tmp_path):
    """Ally fallback supplies eyes, never the ally's privately studied facts."""
    from combat.canonical import canonical_sha256
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT

    def bundles(rows):
        probes(rows)
        owner = rows[0]
        action = next(a for a in owner['action_catalog'] if a['display_name'] == 'Become Invisible')
        action['display_name'] = 'Fall in battle'
        action['parameters']['typed']['effects'] = [
            {'type': 'damage', 'applies_to': 'self', 'flat': 2 * owner['actor_template']['maximum_hp'],
             'damage_types': ['force']}]
        owner.pop('bundle_sha256', None)
        owner['bundle_sha256'] = canonical_sha256(owner)

    def arena(doc):
        doc['sensory_sources'] = [
            source('creature', entity_id=FOE, circulation=1),
            source('spill', position={'x': 5, 'y': 6}, exposed=1, occurred_at_seconds=-30),
            source('corpse', position={'x': 5, 'y': 7}, obvious=1,
                   label='fallen traveller', likely_blood_loss=1),
            source('sample', position={'x': 5, 'y': 6}, obvious=1,
                   label='new vial', source_key='ALLY_PRIVATE_SOURCE'),
            source('sample', position={'x': 19, 'y': 6}, label='studied vial',
                   source_key='ALLY_PRIVATE_SOURCE', studied_by=[ALLY])]

    combat, table, mid = fixture(tmp_path, [], ally_talents=[BLOOD], named=True,
                               bundle_transform=bundles, battlefield_transform=arena)
    settle(table, mid, candidate(combat, mid, 'Fall in battle').candidate_id)
    engine = reload(tmp_path, mid)
    assert not engine.state.actors[OWNER].active
    assert engine.state.actors[ALLY].active
    assert not any(a.active and a.owner_id == OWNER for a in engine.state.actors.values())
    table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)

    # Warm the same cache with the ally's authorized private response first.
    entitled = table.state(mid, fog=True, fog_view='own', fog_actor_ids=(ALLY,))
    private = entitled['observer_information'][ALLY]
    assert {'injury', 'recent_spill', 'corpse_cause', 'sample_match'} <= {
        fact['kind'] for fact in private['information']}
    assert private['information_text']
    assert any(fact.get('same_creature') == 1 for fact in private['information'])

    fallback = table.state(mid, fog=True, fog_view='own', fog_actor_ids=(OWNER,))
    assert set(fallback['fog_perception']) == {ALLY}
    for key in ('cells', 'creatures'):
        assert fallback['fog_perception'][ALLY][key] == entitled['fog_perception'][ALLY][key]
        assert fallback['fog_perception'][ALLY][key]
    assert fallback.get('observer_information', {}) == {}
    assert all('information' not in row and 'information_text' not in row
               for row in fallback['fog_perception'].values())
    # Filtering the fallback response must not remove the owner's cached facts.
    assert table.state(mid, fog=True, fog_view='own', fog_actor_ids=(ALLY,))[
        'observer_information'][ALLY] == private


@pytest.mark.parametrize('fog', ['own', 'team', 'selected'])
@pytest.mark.parametrize('bound', [OWNER, ALLY, None])
def test_map_view_request_preserves_only_bound_observer_findings(tmp_path, fog, bound):
    """Actual page request -> cold native table -> actual panel, without a browser.

    The selected-token map may include the sensing enemy, but that does not
    change the player's private information audience.
    """
    _, table, mid = prepared(tmp_path)
    script = r'''
import fs from 'node:fs';
import vm from 'node:vm';
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const source = fs.readFileSync('static/tabletop/tabletop.js', 'utf8');
const start = source.indexOf('async function readTableState(');
if (start < 0) throw Error('Missing real page request function');
const context = vm.createContext({URLSearchParams, app: {fog: input.fog},
  enc: encodeURIComponent, viewerStore: {read: () => input.binding},
  api: async path => path});
vm.runInContext(source.slice(start, source.indexOf('\n}', start) + 2), context);
console.log(await context.readTableState(input.mid, input.fog));
'''
    binding = {'role': 'player', 'actor_ids': [bound] if bound else []}
    result = subprocess.run(['node', '--input-type=module', '-e', script], text=True,
                            input=json.dumps({'mid': mid, 'fog': fog, 'binding': binding}),
                            capture_output=True)
    assert result.returncode == 0, result.stderr
    query = parse_qs(urlsplit(result.stdout.strip()).query)
    assert query.get('fog_actor_ids', []) == binding['actor_ids']
    assert query.get('fog_view') == (['own'] if fog == 'own' else None)
    state = table.state(mid, fog=query['fog'] == ['true'],
                        fog_view=query.get('fog_view', [None])[0],
                        fog_actor_ids=tuple(query.get('fog_actor_ids', [])))
    private = state.get('observer_information', {})
    if bound == OWNER:
        assert set(private) == {OWNER}
        assert set(EXPECTED) <= set(private[OWNER]['information_text'])
        assert set(private[OWNER]) == {'information', 'information_text'}
    else:
        assert private == {}
    # Shared/chosen geometry continues to contain all eyes and no private facts.
    if fog != 'own':
        assert OWNER in state['fog_perception'] and ALLY in state['fog_perception']
        assert all('information' not in row and 'information_text' not in row
                   for row in state['fog_perception'].values())
    assert 'PRIVATE_SOURCE' not in json.dumps(state)
    script = r'''
import assert from 'node:assert/strict';
import fs from 'node:fs';
const {renderInformation} = await import('data:text/javascript;base64,' + fs.readFileSync('static/tabletop/information.js').toString('base64'));
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const host = {ownerDocument: {createElement: tag => ({tag, textContent: ''})},
  childNodes: [], replaceChildren() {this.childNodes = [];}, append(n) {this.childNodes.push(n);}};
// Selected enemy/ally map tokens do not participate in owned-observer rendering.
const owned = input.bound ? [{entity_id: input.bound, display_name: 'Your fighter'}] : [];
renderInformation(host, input.state, owned);
console.log(JSON.stringify(host.childNodes.map(n => n.textContent)));
renderInformation(host, input.state, []);
assert.equal(host.hidden, true);
assert.equal(host.childNodes.length, 0);
'''
    rendered = subprocess.run(['node', '--input-type=module', '-e', script], text=True,
                              input=json.dumps({'state': state, 'bound': bound}), capture_output=True)
    assert rendered.returncode == 0, rendered.stderr
    lines = json.loads(rendered.stdout)
    assert (set(EXPECTED) <= set(lines)) if bound == OWNER else lines == []


@pytest.mark.parametrize('profile,ranked', [('full', False), ('compact', False),
                                         ('tiny', False), ('choices', False), ('choices', True)])
def test_actual_model_prompts_have_only_observers_findings(tmp_path, monkeypatch, profile, ranked):
    monkeypatch.setenv('CF_EMBED_MENU', '1' if ranked else '0')
    combat, table, mid = prepared(tmp_path)
    prompts = []
    def fake(config, prompt, png):
        prompts.append(prompt)
        if profile == 'choices':
            # Ranked choices expose complete situation through reversible pages.
            if aid == OWNER and 'I) Next situation page' in prompt and 'already studied.' not in prompt:
                return 'I', None
            from agent_seats.choices import decision_payload
            options = decision_payload(prompt)['options']
            key = next(k for k, v in options.items() if 'End turn' in str(v) or 'End my turn' in str(v))
            return key, None
        return json.dumps({'plan': ['end']}), None
    runner, _ = runner_for(tmp_path, table, fake, timeout=30)
    configure(runner, profile)
    # End-only is an engine-legal decision; no live ranking or model transport.
    legal = {'end': {'action': 'End turn', 'source': 'turn', 'targets': [],
                     'destination': None, 'options': []}}
    for aid in (OWNER, ALLY):
        prompts.clear()
        state = table.state(mid)
        view, _ = runner.own_view(mid, state, aid, combat._load_session(mid))
        before = json.dumps(legal, sort_keys=True)
        answer = runner._decide(mid, aid, {'provider_id': 'fake'}, view, legal, 'end', '', 'TURN',
                                ['end'], slot_ranked=ranked)
        assert prompts, 'fake provider must receive an actual prompt'
        assert not answer.get('fallback'), runner.decisions(mid)
        assert json.dumps(legal, sort_keys=True) == before
        # Paged text can split sentences; reconstruct just the situation chunks.
        if profile == 'choices' and any('Situation:\n' in p for p in prompts):
            combined = ''.join(p.split('Situation:\n', 1)[1].split('\nA) End turn here', 1)[0]
                               .split('\n', 1)[1] for p in prompts)
        else:
            combined = '\n'.join(prompts)
        if aid == OWNER:
            for line in EXPECTED:
                assert line in combined
        else:
            assert 'Bloodsense:' not in combined
        assert 'PRIVATE_SOURCE' not in combined
        assert 'creature_id' not in combined
        if profile in {'full', 'compact', 'tiny'}:
            # Visible objects legitimately keep protocol IDs for legal targets;
            # player-readable findings must resolve those references to names.
            displayed = json.loads(prompts[0].split('\n', 1)[1])['state'].get('information', [])
            assert all('object:map.' not in line and 'actor:' not in line for line in displayed)
        else:
            assert 'object:map.' not in combined


@pytest.mark.parametrize('seed', stock.STOCK_SEEDS)
def test_stock_replays_against_merged_main(tmp_path, monkeypatch, seed):
    # Keep the stock guard's shared mainline resolver (or the CI release pin).
    monkeypatch.setenv('CF_STOCK_EVIDENCE', str(tmp_path / 'stock-evidence'))
    stock.test_six_stock_captures_equal_main(tmp_path, seed)


def test_observer_information_keeps_unranked_tail_option_reachable(tmp_path, monkeypatch):
    """New mandatory situation paging must preserve every original legal key."""
    monkeypatch.setenv('CF_EMBED_MENU', '0')
    combat, table, mid = prepared(tmp_path)
    from agent_seats.choices import decision_payload
    prompts = []
    def fake(config, prompt, png):
        prompts.append(prompt)
        options = decision_payload(prompt)['options']
        if 'Plan so far:' in prompt:
            return 'A', None
        if 'B' in options and 'Last legal choice' in options['B']:
            return 'B', None
        return ('L' if 'L' in options else 'A'), None
    runner, _ = runner_for(tmp_path, table, fake, timeout=30)
    configure(runner, 'choices')
    view, _ = runner.own_view(mid, table.state(mid), OWNER, combat._load_session(mid))
    assert view.get('information')
    legal = {key: {'action': name, 'source': 'turn', 'targets': [], 'options': [], 'destination': None}
             for key, name in [('first', 'Dodge'), ('last', 'Last legal choice'), ('end', 'End turn')]}
    answer = runner._decide(mid, OWNER, {'provider_id': 'fake'}, view, legal, 'first', '', 'TURN')
    assert answer == {'plan': ['last', 'end'], 'fallback': False}, runner.decisions(mid)
    assert any('L) More choices' in prompt for prompt in prompts)
    assert set(legal) == {'first', 'last', 'end'}
