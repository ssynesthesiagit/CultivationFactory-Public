"""Shared per-fight ownership lookups for ability plug-ins.

One implementation of "does this creature own this, in *this* fight", used by combat/ext/gu_sand.py
(gu_brute's sibling for the Sand sphere), combat/ext/gu_brute.py, combat/ext/destruction_blast.py and
combat/ext/lane4_brute.py. Those four plug-ins used to answer the question from a module-level dict keyed by
the character's actor id. A Factory actor id is a stable ``"actor:factory." + project id``, so that dict
answered for the *next* fight too: a talent the character no longer owned, or never owned in this fight,
still read as owned, and the Sand sphere's Opportunity Attack rider even read the flag for a *target*
creature rather than for its actor.

Everything here reads the current fight's own compiled data, the pattern combat/ext/__init__.py documents
("Key everything off the character's own compiled rows (a "block" in combat/rules/feature_blocks.d/*.json,
compiled through the compile_block hook) or its actions, so other characters and fights saved before are
unaffected"). Two consequences: a fight is never affected by what another fight compiled, and a saved fight
reloaded in a fresh process still knows its own ownership. A creature that owns no such row is never
touched, which is what makes every consumer of this module inert for other characters.

A talent that reaches a fight only through one of these has to say so on its own row: a ``block`` entry in
combat/rules/feature_blocks.d/*.json (read with :func:`owns_block`), an action the plug-in compiled for the
owner (read with :func:`granted_action`), or a typed source recorded on one of its actions (read with
:func:`owns_feature`).

Fights saved before a talent had a row of its own
------------------------------------------------
A fight created earlier loads its frozen Typed_Character_Bundles.json copy instead of recompiling the
character, so a talent that only became an ownership row with this change is simply absent from that fight.
:func:`legacy_owns_block` answers those from the *same* saved bundle, which is the only record of the fight's
own ownership: it is written when the fight is created, travels with the match, and is never recomputed from
another fight or from today's character sheet. Only an exact talent id or an owner-bound action proves
ownership. The "not automated yet" list also takes forged Technique names, even for creatures that own the
same sphere, so names cannot prove ownership. Pre-row Hammer/Ruinous saves with names alone remain
loadable but cannot safely recover those refinements without additional frozen identity evidence.
"""
from __future__ import annotations

from typing import Any

# The per-fight stores a Factory character's compiled rows are registered into (combat/gate2_engine.py, from the
# bundle it was built with). Both are absent on an engine with no Factory fighters; every lookup tolerates that.
_STORES = ("typed_passive_rows", "typed_reaction_rows")


def _actor_id(engine: Any, actor: Any) -> str:
    """The fight-scoped id to look rows up by: an Actor, or the id itself for callers that only hold a string
    (a target whose row is being asked about before the actor is resolved)."""
    return str(getattr(actor, "entity_id", actor) or "")


def block_rows(engine: Any, actor: Any, block: str, kind: str | None = None) -> list[dict[str, Any]]:
    """``actor``'s own compiled rows for ``block`` in this fight, optionally narrowed to one ``kind``."""
    actor_id = _actor_id(engine, actor)
    rows = [row for store in _STORES for row in (getattr(engine, store, {}) or {}).get(actor_id, [])]
    return [row for row in rows if row.get("block") == block and (kind is None or str(row.get("kind")) == kind)]


def owns_block(engine: Any, actor: Any, block: str, kind: str | None = None) -> bool:
    """Whether ``actor`` owns the ability marked by ``block``/``kind`` in this fight, from this fight's own
    compiled rows, or -- for a fight saved before those rows existed -- from its own saved bundle."""
    return bool(block_rows(engine, actor, block, kind)) or legacy_owns_block(engine, actor, block, kind)


def row_number(engine: Any, actor: Any, block: str, key: str, kind: str | None = None, default: int = 0) -> int:
    """An integer the owning row carried from the character's own numbers (its Proficiency Bonus, most often),
    or ``default`` when the row is absent. Integers only: the value is read from the fight and the fight is
    saved, so it must stay a canonical number."""
    for row in block_rows(engine, actor, block, kind):
        try:
            return int(row.get(key, default))
        except (TypeError, ValueError):
            return default
    return default


def granted_action(engine: Any, actor: Any, suffix: str) -> Any | None:
    """The action this fight's catalog holds for ``actor`` whose source id ends with ``suffix``.

    A plug-in that compiles an action of its own for the owner is its own proof of ownership, and the action
    travels with the fight: no separate ownership record is needed, and a fight that never compiled it has no
    such action. Use ``suffix`` for the action's own generated tail, e.g. ``".granted.focused_might"``.
    """
    actor_id = _actor_id(engine, actor)
    catalog = getattr(engine, "action_catalog", {}) or {}
    for action_id in (getattr(actor, "action_ids", ()) or ()):
        if str(action_id).endswith(suffix) and (action := catalog.get(action_id)) is not None and action.owner_id == actor_id:
            return action
    return None


def owns_granted_action(engine: Any, actor: Any, suffix: str) -> bool:
    """Whether this fight gave ``actor`` the action whose source id ends with ``suffix``."""
    return granted_action(engine, actor, suffix) is not None


# Fights saved before a talent had an ownership row can retain an exact feature id or an action tail, read from
# the bundle saved with the fight and never from another fight or today's character sheet:
#   action_tail  -- the tail of an action id the fight's own catalog holds for the actor
#                   (".break_the_guard."), which is how a plug-in that compiled a button of its own is
#                   recognised elsewhere in combat/ext/. Owner-bound: the id carries the acting creature's own
#                   short hash and the catalog entry names that creature as its owner, so a different creature
#                   cannot answer for this one however its talent is named.
# Keyed by the (block, kind) the row would have used, so the lookup is the same one owns_block makes:
#   destruction/hammer      -> tianxia.talent.destruction.hammer_through_the_line
#   destruction/ruinous     -> tianxia.talent.destruction.ruinous_interruption
#   destruction/break_guard -> tianxia.talent.destruction.break_the_guard
# Break the Guard accepts only its exact id or own buttons. Its printed effect is read from the Blast Type's
# on-fail rider, so a name collision would hand a non-owner a real combat effect (an extra AC reduction on
# Fracturing and Scouring blasts), and a fight that compiled Break the Guard's own four buttons has the
# owner-bound action ids above to prove it. Hammer/Ruinous require their exact recorded id; their old
# name-only records are ambiguous even when the actor genuinely owns a Destruction Blast Type.
_LEGACY_OWNERSHIP: dict[tuple[str, str | None], tuple[str, str]] = {
    ("destruction", "hammer"): ("tianxia.talent.destruction.hammer_through_the_line", ""),
    ("destruction", "ruinous"): ("tianxia.talent.destruction.ruinous_interruption", ""),
    ("destruction", "break_guard"): ("tianxia.talent.destruction.break_the_guard", ".break_the_guard."),
}

_FEATURE_ID_MARK = "tianxia.talent."


def _bundle_feature_ids(bundle: dict[str, Any]) -> set[str]:
    """The stable feature ids this frozen bundle recorded for its own character.

    Compiled rows carry their ``feature_id`` and every compiled action carries its ``source_definition_id``.
    A Blast Type's id embeds the talent it came from as its tail ("...destruction_blast_type.tianxia.talent.
    destruction.crushing_break"), so that tail is lifted out whole: it is the one place a pre-row save keeps a
    typed talent's *id* rather than its name. Only an exact match proves ownership of the requested talent.
    """
    ids: set[str] = set()
    for row in [*(bundle.get("typed_passives") or []), *(bundle.get("typed_reactions") or [])]:
        if isinstance(row, dict) and row.get("feature_id"):
            ids.add(str(row["feature_id"]))
    for action in bundle.get("action_catalog") or []:
        source = str((action or {}).get("source_definition_id") or "")
        if source:
            ids.add(source)
            start = source.find(_FEATURE_ID_MARK)
            if start >= 0:
                ids.add(source[start:])
    return ids


def _own_bundle(engine: Any, actor: Any) -> dict[str, Any] | None:
    """The frozen bundle this fight was built from for ``actor``.

    ``engine.typed_bundle_documents`` is the bundle set the fight loaded (combat/gate2_engine.py keeps the
    documents as given), read here the same way combat/carry.py and combat/ext/elephant_sovereign.py read it.
    """
    actor_id = _actor_id(engine, actor)
    return next((bundle for bundle in getattr(engine, "typed_bundle_documents", ()) or ()
                 if bundle.get("actor_id") == actor_id), None)


def legacy_owns_block(engine: Any, actor: Any, block: str, kind: str | None = None) -> bool:
    """Whether a fight saved before ``block``/``kind`` rows existed still shows ``actor`` owning that talent,
    read from this fight's own frozen bundle.

    Only the talents in ``_LEGACY_OWNERSHIP`` left such a record, and those are the only ones answered here: a
    talent whose own save says nothing stays unowned, because inferring one would hand a saved fight an ability
    its file does not unambiguously claim. Current non-owners can also reach this fallback: absence of a row
    does not date a bundle. Exact identity evidence is therefore required for current and saved fights alike.

    ``_own_bundle`` looks the bundle up by this actor's own id, so nothing here can ever answer for another
    creature, however similarly the two are named.
    """
    record = _LEGACY_OWNERSHIP.get((block, kind))
    bundle = _own_bundle(engine, actor)
    if record is None or bundle is None:
        return False
    feature_id, action_tail = record
    recorded = _bundle_feature_ids(bundle)
    if feature_id in recorded:
        return True  # the stable id itself is in this actor's own save
    if not action_tail:
        return False
    catalog = getattr(engine, "action_catalog", {}) or {}
    owner_id = _actor_id(engine, actor)
    return any(str(action_id).endswith(action_tail + key) and (action := catalog.get(action_id)) is not None
               and action.owner_id == owner_id
               for action_id in (getattr(actor, "action_ids", ()) or ())
               for key in ("ac", "advantage", "cover", "off"))


def owns_feature(engine: Any, actor: Any, feature_id: str) -> bool:
    """Whether ``actor`` owns ``feature_id`` in this fight, by any of the recorded forms of ownership: one of
    its own passive/augment/action/reaction ids, one of its compiled rows' feature ids, or the typed source of
    one of its actions.

    The compiled-ownership query combat/fight_setup.py uses for a fight's setup tasks, re-exported here so a
    plug-in asks one module for ownership whatever form it was recorded in.
    """
    from ..alternative_payments import owned

    return bool(owned(engine, actor, feature_id))
