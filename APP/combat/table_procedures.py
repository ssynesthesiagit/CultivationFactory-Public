"""Default-inert table procedures, shared by knowledge and study providers.

TabletopService/API produce commands; ext providers own rules, options and sheet
overlays. The existing ButtonStore persists receipts with character advancement.
Providers receive copies. Preview/cancel never writes. A revision and request ID
make committed elapsed time and choices idempotent across a cold reload.
"""
from copy import deepcopy
import hashlib
import json

from . import ext
from .tabletop import TabletopError


def options(service, project_id):
    sheet = service.combat._factory_owner_sheet(project_id)
    states = (service.buttons.get(project_id).get('advancement') or {}).get('procedures') or {}
    return [row for reply in ext.run_strict('table_procedure_options', sheet, deepcopy(states))
            for row in reply]


def command(service, project_id, namespace, action, payload, revision, request_id, *, gm=False, preview=False):
    # Validate the character before using its ID as a lock filename.
    service.buttons.get(project_id)
    if type(revision) is not int or revision < 0 or not isinstance(request_id, str) or not 1 <= len(request_id) <= 120:
        raise TabletopError('TABLE_PROCEDURE_REQUEST', 'Use a current revision and a request identifier.', 400)
    if not isinstance(payload, dict):
        raise TabletopError('TABLE_PROCEDURE_REQUEST', 'Procedure details must be an object.', 400)
    # The ownership sheet, current advancement and namespace update must share
    # the ordinary advancement writer's lock, including reverse interleavings.
    with service.buttons.advancement_transaction(project_id, preview=preview) as saved:
        sheet = service.combat._factory_owner_sheet(project_id)
        states = saved.setdefault('procedures', {})
        before = deepcopy(states.get(namespace) or {'revision': 0, 'requests': {}})
        signature = hashlib.sha256(json.dumps([namespace, action, payload, gm], sort_keys=True).encode()).hexdigest()
        prior = before.get('requests', {}).get(request_id)
        if prior:
            if prior != signature:
                raise TabletopError('TABLE_PROCEDURE_REUSE', 'That request identifier was already used for another decision.', 409)
            return {'status': 'COMMITTED', 'procedure': before}
        if before['revision'] != revision:
            raise TabletopError('TABLE_PROCEDURE_STALE', 'The procedure changed. Read its current choices again.', 409)
        replies = ext.run_strict('table_procedure_command', sheet, namespace, deepcopy(before), action, deepcopy(payload), gm)
        if len(replies) != 1 or not isinstance(replies[0], dict):
            raise TabletopError('TABLE_PROCEDURE_UNKNOWN', 'That table procedure is not available.', 400)
        after = replies[0]
        after['revision'] = revision + 1
        after.setdefault('requests', {})[request_id] = signature
        after.setdefault('events', []).append({
            'revision': revision + 1, 'request_id': request_id, 'action': action,
            'payload': deepcopy(payload), 'gm_confirmed': int(bool(gm)),
            'source_sheet_sha256': hashlib.sha256(json.dumps(sheet, sort_keys=True).encode()).hexdigest(),
        })
        if not preview:
            states[namespace] = after
        return {'status': 'PREVIEW' if preview else 'COMMITTED', 'procedure': after}
