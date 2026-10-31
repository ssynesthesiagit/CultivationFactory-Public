"""Shared Glass Heart declaration helpers for the seam regressions and their callers.

Lives in its own module so no test file has to import another test module (public CI
ships only what each file's own imports reach). Builds GM-style scene declarations
against an engine; it fabricates no scene meaning itself.
"""
from combat.ext import glass_heart as glass
from tests.worker2_support import OWNER


def source(engine, name, owner=OWNER):
    return next(a.source_definition_id for a in engine.action_catalog.values()
                if a.owner_id == owner and a.display_name == name)


def document(engine, source_id, purpose, value, bearer=OWNER, record='glass-declaration'):
    from combat.ext.needle import numbers_of
    source_actor = engine.state.actors[engine.action_catalog[source_id].owner_id]
    source_cl = int(numbers_of(engine, source_actor).get('cl') or 0)
    def answer(p, fact):
        return {'category': glass.KEY + p, 'fact': fact, 'condition': source_id,
                'visible_sign': 'The GM records the actual scene and bearer declaration.', 'source_cl': source_cl}
    answers = {glass.KEY + purpose: answer(purpose, value)}
    if purpose in {'scope', 'pressure'}:
        answers[glass.KEY + 'anti_farming'] = answer('anti_farming', 'genuine_unarranged_event')
    actor = engine.state.actors[bearer]
    return {'record_id': record, 'subject_id': bearer, 'subject_name': actor.display_name,
            'subject_kind': 'creature', 'position': actor.position.model_dump(mode='json'),
            'source_reference': 'GM scene input: truthful disclosure during a real hostile encounter',
            'witness_ids': [bearer], 'valid_through_round': engine.state.round_number,
            'answers': answers}


def record(combat, table, mid, doc):
    version = combat._load_session(mid).engine.state.state_version
    return table.record_fact(mid, doc, expected_state_version=version)
