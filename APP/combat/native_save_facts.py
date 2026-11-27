"""Public final-save fact publisher for native custom effect producers.

Qiweaving's Draw Current supplies the actual hostile-drain save. Consumers
include Returning Field and other save_final readers. The native producer owns
the result and consequence categories; this helper never guesses a category
from a source name or changes a result, resource, die or saved event.
"""
from dataclasses import replace
from . import ext


def publish_native_save(ctx, subject, ability, roll, dc, failed, *, categories):
    """Publish this exact completed roll/result through the documented final seam."""
    if any(not isinstance(tag, str) or not tag for tag in categories):
        raise ValueError('native save categories must be nonempty strings')
    ext.run_strict('save_final', replace(ctx, save_result=roll, save_dc=int(dc)),
                   subject, ability, set(categories), failed)
