"""Reviewed expression facts used by Foundation alignment at native compilation.

The input is owner-reviewed combat/rules/source_expressions/<policy>.json. A
fact binds an exact rules_text source, its full UTF-8 hash and a literal quote.
The policy itself is bound to its granting record in the same way. Missing facts
are unknown; a sphere, name, damage type or player-supplied sheet flag is never
evidence. Receipts contain only strings and survive bundle sealing/replay.

This public helper is shared by expression policies; it registers no hooks and
confers no action, resource, sphere access or numeric benefit by itself.
"""
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
RULES_TEXT = APP / 'authority/typed_mechanics/rules_text.json'
POLICIES = APP / 'combat/rules/source_expressions'


def validate_policy(policy, texts):
    """Validate a reviewed policy against current canonical source bytes."""
    def bound(source, digest, quote):
        text = texts.get(source)
        return (isinstance(text, str) and isinstance(quote, str) and bool(quote)
                and quote in text and sha256(text.encode('utf-8')).hexdigest() == digest)

    if not bound(policy['grant_source'], policy['grant_sha256'], policy['grant_quote']):
        raise ValueError('Expression policy granting source has changed')
    out = {}
    for fact in policy['facts']:
        source = fact['source_id']
        if source in out or not bound(source, fact['text_sha256'], fact['quote']):
            raise ValueError('Expression fact is duplicate or its source has changed')
        if (not isinstance(fact['expression'], str) or not fact['expression']
                or not policy['allowed_spheres']
                or any(not isinstance(s, str) or not s for s in policy['allowed_spheres'])):
            raise ValueError('Expression fact requires an expression and legal sphere scope')
        out[source] = {
            'allowed_spheres': tuple(policy['allowed_spheres']),
            'receipt': {'source_id': source, 'text_sha256': fact['text_sha256'],
                        'quote': fact['quote'], 'expression': fact['expression'],
                        'grant_source': policy['grant_source'],
                        'grant_sha256': policy['grant_sha256']},
        }
    return out


@lru_cache(maxsize=None)
def _policy(name):
    if not name.replace('_', '').isalnum():
        raise ValueError('Invalid expression policy name')
    return validate_policy(json.loads((POLICIES / (name + '.json')).read_text()),
                           json.loads(RULES_TEXT.read_text()))


def reviewed_expression(policy, source_id):
    """Return an authenticated expression fact, or None for unknown sources."""
    return _policy(policy).get(source_id)
