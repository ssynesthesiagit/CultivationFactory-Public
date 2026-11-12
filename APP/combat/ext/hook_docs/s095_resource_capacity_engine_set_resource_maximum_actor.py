"""Resource capacity: engine._set_resource_maximum(actor, resource_id, maximum,
source_id, retain_excess=False) events the new integer capacity. The default
clamps held points. An explicit Source Rule can pass retain_excess=True to keep
existing records above the new capacity; this grants no extra gains. Pool gains
always stop at capacity, including when existing points exceed it. Maw's timed
capacity and other source-qualified temporary pools use this contract; callers
own acquisition, record selection and expiry. No caller means no behavior change."""
