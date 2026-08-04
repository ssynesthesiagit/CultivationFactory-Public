# Factory Combat Module — Gate 1

This package is the lightweight, in-process content and projection layer for the Factory hybrid-combat feature.

Implemented in Gate 1:

- exact-version pack loading from externally identified ZIP artifacts;
- five typed pack families;
- permanent stable-ID resolution;
- deterministic canonical registry snapshots;
- four CL5 character source mappings;
- deterministic Combat Runtime Projection compilation;
- mechanic-fidelity classification;
- projection-bound Tactical Doctrine artifacts;
- one square-grid battlefield and one encounter;
- concise typed diagnostics and exported JSON schemas.

Not implemented in Gate 1:

- combat state or turn resolution;
- legal-action generation;
- rolls, damage, healing, conditions, resource mutation, or reactions;
- event logging, save/replay/recovery;
- local tactical scoring;
- AI bridge or combat UI.

Compile the retained vertical slice with:

```text
python -m combat.cli --gate1-root combat_gate1 --output <external-output-directory>
```

The compiler writes deterministic JSON artifacts. It does not modify the Factory database or `UserData`.
