"""Default-inert table procedures, shared by knowledge and study providers.

TabletopService/API produce commands; ext providers own rules, options and sheet
overlays. The existing ButtonStore persists receipts with character advancement.
Providers receive copies. Preview/cancel never writes. A revision and request ID
make committed elapsed time and choices idempotent across a cold reload.
"""
from copy import deepcopy
import fcntl
import hashlib
import json

from . import ext, table_advance
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
    lock_root = service.combat.userdata_root / 'table_procedure_locks'
    lock_root.mkdir(parents=True, exist_ok=True)
    with (lock_root / (project_id + '.lock')).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        sheet = service.combat._factory_owner_sheet(project_id)
        saved = table_advance.normalized(service.buttons.get(project_id).get('advancement'))
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
        if not preview:
            states[namespace] = after
            service.buttons.save_advancement(project_id, saved)
        return {'status': 'PREVIEW' if preview else 'COMMITTED', 'procedure': after}
