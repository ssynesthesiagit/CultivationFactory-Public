"""Manifest Messenger uses native object defense and bound support origins."""
import pytest

from combat.gate2_runtime_models import ActionIntent
from combat.ext import spirit_assets
from test_riders_c8 import ME, MK_ALL, held
from test_a2_group_traditions4 import ENEMY, ALLY, setup, act, advance, reload


def test_messenger_contact_gate_manifest_profile_and_destruction_lockout(tmp_path):
    service, session, metadata = setup(tmp_path, MK_ALL)
    advance(service, session, metadata, ME)
    assert not any(c.display_name.startswith('Manifest Messenger:') for c in session.engine.legal_candidates())
    def choose(context):
        if context.reaction_source_id.endswith('miko.messenger_contact'):
            return ('record',)
        spec = context.extension_choice
        return spec.option_ids[:spec.minimum_selections] if spec and not spec.allow_decline else ()
    act(service, session, metadata, 'Record willing messenger contact', choose=choose)
    session = reload(service, session)
    before = session.engine.state.actors[ME].resources['resource:core.resonance']
    def place_near(context):
        if context.reaction_source_id == 'choice:needle.spirit_asset.space':
            return ('cell:5,6,0',) if 'cell:5,6,0' in context.extension_choice.option_ids else context.extension_choice.option_ids[:1]
        return choose(context)
    act(service, session, metadata, 'Manifest Messenger: Walk', choose=place_near)
    session = reload(service, session)
    me = session.engine.state.actors[ME]
    obj = spirit_assets.assets(session.engine, me, 'Kami Messenger')[0]
    assert obj is not None and obj.current_hp == obj.maximum_hp == 24 and obj.ac == 40
    assert obj.component['resist'] == ['PSYCHIC']
    assert me.resources['resource:core.resonance'] == before - 4
    # The live Asset supplies a real alternative origin for support, but no attack origin.
    support = [c for c in session.engine.legal_candidates() if (c.metadata.get('effect_origin') or {}).get('id') == obj.object_id]
    # The Action is spent; on the next turn both support and the default origin are offered.
    act(service, session, metadata, 'End turn')
    advance(service, session, metadata, ME)
    support = [c for c in session.engine.legal_candidates() if (c.metadata.get('effect_origin') or {}).get('id') == obj.object_id]
    assert support
    assert all(session.engine.action_catalog[c.source_definition_id].target_kind == 'ALLY_OR_SELF' for c in support)
    assert not any('Mind Spike' in c.display_name for c in support)
    candidate = next(c for c in support if 'Advantage against Frightened' in c.display_name)
    act(service, session, metadata, candidate.display_name)
    session = reload(service, session)
    assert session.engine.state.actors[ME].turn_flags.get('miko_messenger_delivered')
    assert any(e.event_type == 'EFFECT_ORIGIN_SELECTED' or (e.payload or {}).get('effect_origin')
               for e in session.engine.events)
    assert not any((c.metadata.get('effect_origin') or {}).get('id') == obj.object_id
                   for c in session.engine.legal_candidates())
    # Break the Asset with ordinary committed object packets; each 10 Psychic is halved.
    for _ in range(5):
        advance(service, session, metadata, ENEMY)
        act(service, session, metadata, 'Asset damage probe', obj.object_id)
        act(service, session, metadata, 'End turn')
        session = reload(service, session)
    assert session.engine.state.objects[obj.object_id].destroyed
    assert not spirit_assets.assets(session.engine, session.engine.state.actors[ME], 'Kami Messenger')
    assert spirit_assets.assets(session.engine, session.engine.state.actors[ME], 'Kami Messenger', live=False)
    advance(service, session, metadata, ME)
    assert not any(c.display_name.startswith('Manifest Messenger:') for c in session.engine.legal_candidates())


def test_ai_does_not_invent_a_willing_messenger_agreement(tmp_path):
    from combat.ext.miko import MESSENGER_CONTACT
    service, session, metadata = setup(tmp_path, MK_ALL, control='LOCAL_AUTO')
    advance(service, session, metadata, ME)
    act(service, session, metadata, 'Record willing messenger contact')
    session = reload(service, session)
    assert not held(session.engine.state.actors[ME], MESSENGER_CONTACT)
    assert not any(c.display_name.startswith('Manifest Messenger:') for c in session.engine.legal_candidates())
