"""Factory-constructed arts: Forged Techniques, Manuals and Recorded Arts, Immortal Arts.

Each constructor is pure and seeded.  It reads only sealed authority and the
character's already-authenticated state, emits a typed record the project lock
can authenticate by re-derivation, and leaves every number to the sealed table
so a Stage 2 compile can recompute and refuse drift.
"""
