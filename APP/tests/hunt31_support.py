"""Hunt 31 synthetic tables: setup is sealed before genesis, never live data.

Wrap only the fixture's compiler to add generic, evented preparation actions;
production engine classes and functions are never patched.
"""
from tests import hunt28_support as h

OWNER, ALLY, FOE = h.OWNER, h.ALLY, h.FOE
act, options, reload, owner_turn = h.act, h.options, h.reload, h.owner_turn


def send(combat, table, mid, cid, auto, answers=(), *, actor=OWNER):
    # The selected adapter lives only for this request, avoiding nested stale
    # adapters when the same AI owns actions on successive rounds.
    if not auto:
        return act(table, mid, cid, answers)
    from combat.gate4_adapters import ManualControllerAdapter
    selected = next(c for c in combat._load_session(mid).engine.legal_candidates() if c.candidate_id == cid)
    original = combat.controller
    class Selected:
        def choose_primary_action(self, context):
            legal = combat._load_session(mid).engine.legal_candidates()
            choice = next(c for c in legal
                          if c.source_definition_id == selected.source_definition_id
                          and c.target_ids == selected.target_ids and c.destination == selected.destination)
            # Force a legal replacement even when the built-in AI's restraint
            # omits already-active buffs. This tests AI execution, not its policy.
            context = context.model_copy(update={'legal_candidates': tuple(legal)})
            return ManualControllerAdapter(lambda _: (choice.candidate_id, ())).choose_primary_action(context)
        def __getattr__(self, name):
            return getattr(original, name)
    combat.controller = Selected()
    combat.set_controller_mode(mid, actor_id=actor, controller_mode='LOCAL_AUTO')
    try:
        return table.auto_step(mid, table.state(mid)['last_sequence'], list(answers))
    finally:
        combat.controller = original
        combat.set_controller_mode(mid, actor_id=actor, controller_mode='MANUAL')


def fixture(monkeypatch, tmp_path, talents, *, dc=30, setup=(), resources=None, ally_talents=(), armed=False,
            legacy_predator=False):
    original = h.compile_character
    def compile(doc, **kw):
        doc['ability_scores_and_statistics']['technique_save_dc'] = dc
        if armed:
            from tests.test_carry import KIT
            doc['equipment'] = [{'starting_kit': KIT}]
        if legacy_predator and kw['actor_id'] == FOE:
            # The Predator-King die rides a hit, so the test needs one that certainly lands. Worn armour replaces the
            # sheet's own armour-class calculation, so this opponent carries its pack and nothing else: its class is then
            # the one below, and the to-hit drops out of the way. What is under test is the printed line's own gate on a
            # hit the fight actually recorded, not whether the attacker can roll high enough.
            doc['equipment'] = [{'starting_kit': {'items': [{'item_id': 'tianxia.mortal.gear.explorer_s_pack',
                                                              'name': "Explorer's Pack", 'quantity': 1}]}}]
            doc['ability_scores_and_statistics']['armor_class']['base_value'] = 1
        bundle = original(doc, **kw)
        actor = kw['actor_id']
        if legacy_predator and actor == OWNER:
            # The bundle a table sealed before the predator line became a question about the creature: its row reads the
            # predator meal as a kind of Satiety of its own. A resumed match loads such a sealed bundle unchanged, so this
            # is the shape the plug-in has to keep reading, and it is not something a rules edit can reach.
            for row in bundle['typed_passives']:
                if row.get('block') == 'lane9_hunger' and row.get('kind') == 'predator_king':
                    row.pop('reads_provenance', None)
                    row['reads'] = ['predator']
        if actor == OWNER:
            for pool, amount in (resources or {}).items():
                pools = bundle['actor_template']['resources']
                found = next((p for p in pools if p['resource_id'] == pool), None)
                if found:
                    found.update(initial=amount, maximum=amount)
                else:
                    pools.append({'resource_id': pool, 'initial': amount, 'maximum': amount})
        if setup:
            aid = 'action:test.h31.prepare.' + actor
            bundle['actor_template']['action_ids'].append(aid)
            bundle['action_catalog'].append({
                'source_definition_id': aid, 'display_name': 'Prepare', 'owner_id': actor,
                'economy': 'NONE', 'resolution_kind': 'TYPED', 'target_kind': 'ALLY_OR_SELF', 'range_ft': 60,
                # Scenario setup is intentionally free, not an automatic rider packet.
                'parameters': {'free_primary': True, 'typed': {'effects': list(setup), 'numbers': {},
                                         'duration': {'kind': 'instant'}}}})
        return bundle
    monkeypatch.setattr(h, 'compile_character', compile)
    return h.fixture(tmp_path, talents, ally_talents=ally_talents)


def pick(table, mid, text, target=None):
    return next(o['candidate_id'] for g in table.state(mid)['menu']['actions'] if text in g['label']
                for o in g['options'] if target is None or o['target_ids'] == [target])


def prepare(table, mid, target):
    assert act(table, mid, pick(table, mid, 'Prepare', target))['status'] == 'COMMITTED'


def finish_choices(sender, result, *, option=None):
    answers = []
    for _ in range(20):
        if result['status'] != 'REACTION_REQUIRED':
            return result
        prompt = result['reaction']
        ids = [o['id'] for o in prompt['choice']['options']]
        chosen = option if option in ids else ids[0]
        answers.append({**prompt['context'], 'selection': 'USE', 'option_ids': [chosen]})
        result = sender(answers)
    raise AssertionError('too many choices')
