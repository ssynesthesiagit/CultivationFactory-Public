"""Square-placed abilities at the table since lazy placement menus (0b7a87b01, 2026-10-13).

The table shows one picker row per square-placed ability instead of one row per square; the square picker then submits
the engine's exact native candidate for the chosen square. Tests that aim at a square submit that same candidate.
"""


def square_candidate(table, mid, label, xy, *, contains=False):
    """The exact candidate id for the table row ``label`` aimed at ground square ``xy``.

    The row is found in the table's own menu (``contains`` matches part of its label), then the square is the
    engine's candidate for that row's source, as the square picker resolves it.
    """
    groups = table.state(mid)["menu"]["actions"]
    source = next(g["source_definition_id"] for g in groups
                  if (label in g["label"] if contains else g["label"] == label))
    engine = table.combat._load_session(mid).engine
    return next(c.candidate_id for c in engine.legal_candidates()
                if c.source_definition_id == source and c.destination is not None
                and (c.destination.x, c.destination.y, c.destination.z) == (*xy, 0))
