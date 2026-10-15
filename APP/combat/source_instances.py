"""Transient exact typed source context for condition and component producers.

Shared by typed_executor, clinical_sources and future provenance readers. This
carries an already-authorized Context; it grants no access and settles no cost.
Nested deliveries restore their parent even on choices/errors. Readers must
match engine, source and source actor; unrelated callbacks cannot borrow it.
No saved state or events are added by the scope itself.
"""
from contextlib import contextmanager
from contextvars import ContextVar
_CONTEXT=ContextVar('typed_source_instance_context',default=None)

@contextmanager
def scope(ctx):
    token=_CONTEXT.set(ctx)
    try:yield
    finally:_CONTEXT.reset(token)

def current(engine,source,owner):
    ctx=_CONTEXT.get()
    return ctx if ctx is not None and ctx.engine is engine and ctx.source==source and getattr(ctx.actor,'entity_id',None)==owner else None
