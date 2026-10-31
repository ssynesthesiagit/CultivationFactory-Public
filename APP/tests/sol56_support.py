"""Natural-dice saved-table reaction probes. No engine patch or state injection.

Compiled character sheets own real printed talents. Participants use the
printed Charge Yourself option before the relevant reaction trigger.
AI primary actions use the
supported controller interface; reactions use production decisions. Scratch
saves are removed after comparing committed state, fresh reload and replay.
"""
import pathlib, json, shutil, zipfile, traceback, os
APP = pathlib.Path(os.environ.get('SOL56_APP', pathlib.Path(__file__).resolve().parents[1]))
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import sheet
IDS = ['actor:factory.h56_owner', 'actor:factory.h56_ally', 'actor:factory.h56_attacker', 'actor:factory.h56_other']
KIT = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.dao'}, {'item_id': 'tianxia.mortal.weapon.gong_jian'}, {'item_id': 'tianxia.mortal.weapon.bi_shou'}]}}
CASES = {'chain': (['TAL_FLOWING_RIVER_FLOWING_RESPONSE', 'TAL_LIGHTNING_GATHER_CHARGE'], ['TAL_LIGHTNING_CHARGED_COUNTERMEASURE', 'TAL_LIGHTNING_GATHER_CHARGE'], ['TAL_LIGHTNING_CHARGED_COUNTERMEASURE', 'TAL_LIGHTNING_GATHER_CHARGE'], 'Dao'), 'chain_opportunity': (['TAL_LIGHTNING_GATHER_CHARGE'], [], ['TAL_LIGHTNING_CHARGED_COUNTERMEASURE', 'TAL_LIGHTNING_GATHER_CHARGE'], 'move'), 'chain_player': (['TAL_LIGHTNING_CHARGED_COUNTERMEASURE', 'TAL_LIGHTNING_GATHER_CHARGE'], [], [], 'Dao'), 'arrow': (['TAL_BARRAGE_INTERCEPTING_SHOT', 'TAL_BARRAGE_ARROW_CATCHING_REVERSAL'], [], [], 'Gong Jian')}
CASES['blood_opportunity'] = (['tianxia.talent.blood.bloodletting_strike'], [], [], 'move')
CASES['chain_player'] = (['TAL_LIGHTNING_CHARGED_COUNTERMEASURE', 'TAL_LIGHTNING_GATHER_CHARGE'], [], ['TAL_LIGHTNING_GATHER_CHARGE'], 'Dao')

def run(tmp_path, kind, auto=False, use=True, seednum=0):
    label = f'F-{kind}-{int(auto)}-{int(use)}-{seednum}'
    scratch = tmp_path / label
    result = {'label': label, 'kind': kind, 'auto': auto, 'use': use, 'steps': [], 'prompts': []}
    svc = None
    mid = None
    try:
        mine, ally, attacker, trigger = CASES[kind]
        # Each fixture starts with its triggering weapon readied; spare inventory
        # is stowed by the hand-occupancy rules.
        kit = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.gong_jian' if trigger == 'Gong Jian' else 'tianxia.mortal.weapon.dao'}]}}
        docs = [sheet(m, cl=12, primary='Qi', kit=kit) for m in [mine, ally, attacker, []]]
        for n, doc in enumerate(docs):
            doc['identity']['display_name'] = ['Owner', 'Ally', 'Attacker', 'Other'][n]
            folder = scratch / 'portable_characters' / IDS[n].split('.')[-1]
            folder.mkdir(parents=True)
            with zipfile.ZipFile(folder / 'current.zip', 'w') as z:
                z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
        bundles = [compile_character(doc, actor_id=aid, reaction_plan={'ask': True}) for aid, doc in zip(IDS, docs)]
        svc = CombatService(APP, scratch)
        table = TabletopService(svc, scratch)
        arena = svc.tabletop_maps.save({'display_name': 'Focused open yard', 'width_squares': 12, 'height_squares': 10, 'walls': [], 'starts': {'team1': [[4, 3], [4, 4]], 'team2': [[3, 3], [10, 7]]}})
        positions = [{'x': 4, 'y': 3}, {'x': 4, 'y': 4}, {'x': 3, 'y': 3}, {'x': 10, 'y': 7}]
        mid = svc._finish_factory_match(bundles, IDS, dict(zip(IDS, ['team:factory'] * 2 + ['team:opponents'] * 2)), dict(zip(IDS, positions)), svc.factory_arenas()['battlefield:map.' + arena['map_id']], IDS[:2], IDS[2:], control_modes={aid: 'LOCAL_AUTO' if kind == 'chain_player' and n != 0 or (auto and n == 2) else 'MANUAL' for n, aid in enumerate(IDS)}, match_seed=os.environ.get('H56_FOCUSED_SEED', label), maximum_rounds=3, display_name=label)['match_id']
        result['seed'] = os.environ.get('H56_FOCUSED_SEED', label)
        if (auto and os.environ.get('H56_FOCUSED_FORCE_TRIGGER') == '1') or kind == 'chain_player':
            from combat.gate4_adapters import ManualControllerAdapter
            production = svc.controller

            class TriggerController:

                def choose_primary_action(self, context):
                    cs = list(context.legal_candidates)
                    target = IDS[0]
                    selected = next((c for c in cs if trigger.lower() in c.display_name.lower() and target in c.target_ids), None)
                    if kind.startswith('chain'):
                        charge = next((c for c in cs if 'gather_charge' in c.source_definition_id.lower() and 'Charge Yourself' in c.display_name), None)
                        if charge is not None:
                            selected = charge
                    if kind == 'chain_player' and charge is None:
                        selected = next((c for c in cs if c.kind == 'END_TURN'))
                    if trigger == 'move' and not (kind.startswith('chain') and charge is not None):
                        moves = [c for c in cs if c.kind == 'MOVE' and c.destination]
                        selected = max(moves, key=lambda c: abs(c.destination.x - 4) + abs(c.destination.y - 3), default=None)
                    if selected is None:
                        selected = next((c for c in cs if c.kind == 'END_TURN'))
                    return ManualControllerAdapter(lambda _: (selected.candidate_id, ())).choose_primary_action(context)

                def __getattr__(self, name):
                    return getattr(production, name)
            svc.controller = TriggerController()
            result['driver'] = 'scripted legal-action controller; production reaction controller'
        charged = set()
        for step in range(20 if kind == 'chain_player' else 90):
            state = table.state(mid)
            if state['presentation'].get('terminal'):
                break
            menu = state['menu']
            engine = svc._load_session(mid).engine
            aid = engine.state.current_actor_id
            before = engine.state.model_dump(mode='json')
            seq = state['last_sequence']
            answers = []
            chosen = None
            source = 'end'
            result.setdefault('mechanics_states', []).append({'step': step, 'after': seq, 'actors': before['actors']})
            if menu.get('manual'):
                actions = menu.get('actions', [])
                charge_key = (aid, engine.state.actors[aid].turns_started)
                if kind.startswith('chain') and charge_key not in charged:
                    chosen = next((o for g in actions if 'gather_charge' in g['source_definition_id'].lower() and 'Charge Yourself' in g.get('label', '') for o in g['options'] if aid in o['target_ids']), None)
                    if chosen:
                        charged.add(charge_key)
                if aid == IDS[0]:
                    if kind == 'chain_player' and (not chosen):
                        if any(c.condition_id.startswith('condition:typed.mark.charged.') for c in engine.state.actors[IDS[2]].conditions.values()):
                            chosen = max(menu.get('moves', []), key=lambda m: abs(m['destination']['x'] - 3) + abs(m['destination']['y'] - 3), default=None)
                if aid == IDS[2] and (not chosen):
                    if trigger == 'move':
                        moves = menu.get('moves', [])
                        if not kind.startswith('chain') or any(c.condition_id.startswith('condition:typed.mark.charged.') for c in engine.state.actors[IDS[0]].conditions.values()):
                            chosen = max(moves, key=lambda m: abs(m['destination']['x'] - 4) + abs(m['destination']['y'] - 3), default=None)
                    else:
                        chosen = next((o for g in actions if trigger.lower() in g.get('label', '').lower() for o in g['options'] if IDS[0] in o['target_ids']), None)
                cid = chosen['candidate_id'] if chosen else menu['end_turn']
                source = chosen or 'end'

                def call():
                    return table.act(mid, cid, menu['decision_id'], menu['state_version'], seq, answers)
            else:

                def call():
                    return table.auto_step(mid, seq, answers)
            for attempt in range(24):
                response = call()
                assert response['status'] in ('COMMITTED', 'REACTION_REQUIRED'), response
                result['steps'].append({'step': step, 'after': seq, 'actor': aid, 'manual': menu.get('manual'), 'source': source, 'answers': list(answers), 'status': response['status']})
                if response['status'] != 'REACTION_REQUIRED':
                    break
                assert svc._load_session(mid).engine.state.model_dump(mode='json') == before, 'prompt changed committed state'
                p = response['reaction']
                result['prompts'].append({'step': step, 'after': seq, 'actor': aid, **p})
                # Bloodletting Decline must still accept the triggering opportunity hit.
                accept = use or (kind == 'blood_opportunity' and p['reaction'] == 'Opportunity Attack')
                answer = {**p['context'], 'selection': 'USE' if accept else 'DECLINE'}
                choice = p.get('choice')
                if kind == 'blood_opportunity' and p['reaction'] == 'Bloodletting Strike' and not use:
                    # Mandatory choice transport: "Not now" is the printed decline option.
                    assert any(o['id'] == 'skip' for o in choice['options'])
                    answer['selection'] = 'USE'
                    answer['option_ids'] = ['skip']
                elif choice and (accept or not choice.get('allow_decline')):
                    answer['selection'] = 'USE'
                    opts = choice['options']
                    answer['option_ids'] = [o['id'] for o in opts if o['id'] != 'skip'][:max(1, int(choice.get('minimum', 1)))]
                assert answer not in answers, 'prompt repeated after answer'
                answers.append(answer)
            else:
                raise AssertionError('24 prompts without commit')
            if kind == 'blood_opportunity' and any(p['reaction'] == 'Opportunity Attack' and p['reactor'] == 'Owner' for p in result['prompts']):
                break  # inspect/reload the committed hit before next-turn bleeding expires
        loaded = CombatService(APP, scratch)._load_session(mid)
        result['reload_equal'] = loaded.engine.state.model_dump(mode='json') == svc._load_session(mid).engine.state.model_dump(mode='json')
        result['verification'] = loaded.verify()
        result['replay'] = loaded.mechanical.replay()
    except Exception:
        result['error'] = traceback.format_exc()
    finally:
        if svc and mid:
            e = svc._load_session(mid).engine
            result['events'] = [v.model_dump(mode='json') for v in e.events]
            result['final'] = e.state.model_dump(mode='json')
            if scratch.exists():
                shutil.rmtree(scratch)
    return result
