"""One warm fight session per match, shared by every table request in this process (SPEEDHOST1, plan S1).

Before, each table command loaded the fight from disk (a full verified replay), and only SeatRunner kept its engine
across its own AI steps (ExecutionSession, deleted). Now the table keeps one session per match for every act and
auto_step, the human's clicks and the seat runner's steps alike. The journal stays the authority:

- ``session()`` is called under the match's table locks. It reuses the warm engine only while every input it was
  loaded from is unchanged (journal fingerprint, match-folder files, shared inputs, switches) and its state hash is
  the one it was sealed with; any other writer, or an unsealed edit, makes it load again the ordinary verified way.
- ``committed()`` seals the engine a command just committed, with the same post-commit proof as the presentation
  path (exact journal tail and post-state hash); if the proof fails the warm session is dropped.
- At most ``CAP`` fights stay warm; a fight unused for ``IDLE_S`` is dropped (lead rulings 2026-11-16 section 3).
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any

from .gate3_reducer import canonical_state_sha256
from . import table_state_cache as inputs

CAP = 4
IDLE_S = 30 * 60
_SKIP = ("Journal.ndjson", "Manifest.json", "Agent_Decisions.jsonl", "Dao_IChing_Audit.jsonl")


class _Warm:
    __slots__ = ("session", "binding", "state_hash", "used")

    def __init__(self):
        self.session: Any = None
        self.binding: Any = None
        self.state_hash: str | None = None
        self.used = time.monotonic()


class FightHost:
    def __init__(self, table):
        self.table = table
        self._fights: OrderedDict[str, _Warm] = OrderedDict()
        self._guard = threading.Lock()
        self.acquisitions = 0
        self.acquisition_ms = 0.0
        self._sweeper = None

    def _inputs(self, match_id):
        combat = self.table.combat
        # Controller tail, settings, map/source binding, seats, Pause and pending input; presentation-only logs
        # must not force a reload.
        return (combat._fingerprint(match_id),
                inputs.folder_files(combat._match_dir(match_id), skip=_SKIP),
                inputs.shared_inputs(), inputs.switches())

    def _warm(self, match_id) -> _Warm:
        now = time.monotonic()
        with self._guard:
            for mid in [m for m, w in self._fights.items() if now - w.used > IDLE_S]:
                del self._fights[mid]
            warm = self._fights.pop(match_id, None) or _Warm()
            self._fights[match_id] = warm
            while len(self._fights) > CAP:
                self._fights.popitem(last=False)
            warm.used = now
            if self._sweeper is None:
                self._sweeper = threading.Thread(target=self._sweep, name="fight-host-idle", daemon=True)
                self._sweeper.start()
        return warm

    def _sweep(self):
        while True:
            time.sleep(60)
            now = time.monotonic()
            with self._guard:
                for mid in [m for m, w in self._fights.items() if now - w.used > IDLE_S]:
                    del self._fights[mid]

    def session(self, match_id):
        """The fight's session for one command or read. Call under the match's table locks."""
        warm = self._warm(match_id)
        binding = self._inputs(match_id)
        if (warm.session is None or binding != warm.binding
                or canonical_state_sha256(warm.session.engine.state) != warm.state_hash):
            start = time.perf_counter()
            warm.session = self.table.combat._load_session(match_id)
            self.acquisition_ms += (time.perf_counter() - start) * 1000
            self.acquisitions += 1
            warm.binding = self._inputs(match_id)
            warm.state_hash = canonical_state_sha256(warm.session.engine.state)
        metadata = self.table.combat._read_metadata(match_id, warm.session)
        self.table.combat.refresh_execution_controls(warm.session, metadata)
        return warm.session

    def committed(self, match_id):
        """Seal the command this request just made durable (never an outside writer's), or drop the session."""
        with self._guard:
            warm = self._fights.get(match_id)
        if warm is None or warm.session is None:
            return
        session = self.table.combat.presentation_session(warm.session)
        if session is None or self._inputs(match_id)[2:] != warm.binding[2:]:
            self.drop(match_id)
            return
        metadata = self.table.combat._read_metadata(match_id, session)
        self.table.combat.refresh_execution_controls(session, metadata)
        warm.binding = self._inputs(match_id)
        warm.state_hash = canonical_state_sha256(session.engine.state)

    def drop(self, match_id):
        with self._guard:
            self._fights.pop(match_id, None)
