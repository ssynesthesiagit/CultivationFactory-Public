"""Out-of-combat preparation choices, called by the sheet's procedure API.

Both deterministic and model seats see all finite fields of one current form on
their own character. No encounter, other character, hidden discovery, physical
die, payment or GM confirmation is sent or generated. Suggestions never commit;
the same source-owned procedure command revalidates the owner's final decision.
"""
import json
import math

from combat.tabletop import TabletopError


def decision_seat_choice(seats, provider, label, field):
    """Letter-protocol transports browse a complete choice tree (12 per page).

    Every leaf remains reachable; grouping never removes or randomly samples an
    option. The ordinary text transports receive the complete JSON form below.
    """
    remaining = field['options']
    while len(remaining) > 1:
        width = max(1, math.ceil(len(remaining) / 12))
        groups = [remaining[i:i + width] for i in range(0, len(remaining), width)]
        letters = 'ABCDEFGHIJKL'[:len(groups)]
        prompt = 'Prepare your own character. ' + label + '\n' + '\n'.join(
            letter + ') ' + '; '.join(o['label'] for o in group)
            for letter, group in zip(letters, groups)) + '\nReply with one offered letter.'
        answer, _ = seats.suggest_preparation(provider, prompt)
        if answer not in letters or len(answer) != 1:
            raise ValueError('Choose one offered preparation letter')
        remaining = groups[letters.index(answer)]
    return remaining[0]['value']


def suggest(table, seats, project_id, namespace, form_id, revision, provider_id):
    menu = next((m for m in table.procedures(project_id) if m['id'] == namespace), None)
    if menu is None or menu['revision'] != revision:
        raise TabletopError('TABLE_PROCEDURE_STALE', 'Refresh the character’s table studies before choosing.', 409)
    form = next((f for f in menu['forms'] if f['id'] == form_id), None)
    fields = [f for f in (form or {}).get('fields', []) if f['type'] == 'select' and f.get('seat_choice')]
    if not fields or any(not f.get('options') for f in fields):
        raise TabletopError('TABLE_PROCEDURE_CHOICE', 'This procedure needs actual table facts, not a seat choice.', 400)
    if provider_id == 'builtin':
        # No random truncation: all choices remain available to the owner and
        # model. Prefer the best admitted modifier for ability selection.
        values = {f['name']: max(f['options'], key=lambda o: o.get('modifier', 0))['value'] for f in fields}
    else:
        provider = seats.registry.load().get(provider_id)
        if not provider:
            raise TabletopError('SEAT_PROVIDER_INVALID', 'Choose an installed preparation model.', 422)
        prompt = json.dumps({'instruction': 'Choose one offered value per field for your own character. '
                            'Return only a JSON object mapping field names to values. Do not invent table facts.',
                            'procedure': menu['name'], 'decision': ', '.join(f['label'] for f in fields),
                            'fields': fields}, ensure_ascii=False)
        # Reuse the production runner's deadline and capacity limit. This view
        # contains no battlefield and cannot request an image of hidden state.
        provider = {**provider, 'vision': False}
        try:
            if provider.get('kind') == 'd1':
                values = {f['name']: decision_seat_choice(seats, provider, f['label'], f) for f in fields}
            else:
                reply, _ = seats.suggest_preparation(provider, prompt)
                values = json.loads(reply)
        except Exception:
            raise TabletopError('TABLE_PROCEDURE_MODEL', 'The preparation model could not supply an offered choice.', 422) from None
    if not isinstance(values, dict) or set(values) != {f['name'] for f in fields} or any(
            values[f['name']] not in [o['value'] for o in f['options']] for f in fields):
        raise TabletopError('TABLE_PROCEDURE_CHOICE', 'The preparation seat must choose from the complete offered list.', 422)
    return {'values': values, 'revision': revision}
