"""Exclusive active-work session used by SeatRunner's built-in and model turns.

Not a presentation cache. Only the owning task accesses the engine, and only
inside the table command reservation. Other writers invalidate the binding;
reacquisition always uses the ordinary verified persistence load. No engines
are retained at human/prompt, pause, terminal or error boundaries.
"""
from .gate3_reducer import canonical_state_sha256
from . import table_state_cache as inputs


class ExecutionSession:
    def __init__(self, table, match_id):
        self.table, self.match_id = table, match_id
        self.session = None
        self.binding = None
        self.state_hash = None
        self.acquisition_ms = 0.0
        self.acquisitions = 0

    def _inputs(self):
        combat = self.table.combat
        # Include controller tail, settings, map/source binding, seats, Pause
        # and pending input. Presentation-only logs must not force a reload.
        return (combat._fingerprint(self.match_id),
                inputs.folder_files(combat._match_dir(self.match_id),
                    skip=("Journal.ndjson", "Manifest.json", "Agent_Decisions.jsonl",
                          "Dao_IChing_Audit.jsonl")),
                inputs.shared_inputs(), inputs.switches())

    def current(self):
        """Call under both table locks, before choosing OR accepting a command."""
        binding = self._inputs()
        if (self.session is None or binding != self.binding
                or canonical_state_sha256(self.session.engine.state) != self.state_hash):
            import time
            start = time.perf_counter()
            self.session = self.table.combat._load_session(self.match_id)
            self.acquisition_ms += (time.perf_counter() - start) * 1000
            self.acquisitions += 1
            self.binding = self._inputs()
            self.state_hash = canonical_state_sha256(self.session.engine.state)
        metadata = self.table.combat._read_metadata(self.match_id, self.session)
        self.table.combat.refresh_execution_controls(self.session, metadata)
        return self.session

    def committed(self):
        """Seal this task's just-durable command, never an outside writer's.

        Table commands hold their reservation from current() through here.
        Prove journal tail and full state with the existing post-commit check;
        next-command inputs also fence controller/seat/settings/source edits.
        """
        session = self.table.combat.presentation_session(self.session)
        if session is None or self._inputs()[2:] != self.binding[2:]:
            self.session = None
            self.binding = None
            return
        metadata = self.table.combat._read_metadata(self.match_id, session)
        self.table.combat.refresh_execution_controls(session, metadata)
        self.binding = self._inputs()
        self.state_hash = canonical_state_sha256(session.engine.state)

    def release(self):
        self.session = None
        self.binding = None
        self.state_hash = None
