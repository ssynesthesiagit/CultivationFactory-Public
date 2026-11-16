"""Ordered line effect piercing_area(ctx, row): row.effects supplies one save with
damage on failure and half_damage on success; object_multiplier defaults to 1.
The existing nearest-first traversal damages barriers before checking creatures
beyond them. Explicit row.all_creatures=True includes friendly creatures in that
same line; absence retains the existing enemy-only target procedure. Hidden
creatures do not influence automatic damage-type selection. Maw's printed line
uses this flag; no other ability acquires it implicitly."""
