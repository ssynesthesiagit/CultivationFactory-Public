"""General typed ``displace_object`` effect (object_displacement.py): arguments are
the normal effect context plus name, size, within_ft and distance_ft. It returns
None, chooses one unattended object near the hit recipient and a
straight collision/line-of-effect-safe destination, including zero movement.
No matching typed row means no behavior. Existing Needle choices and
OBJECT_UPDATED supply transactional ownership and persistent replay.
All choosers keep every legal direction, including unseen endpoints and staying
put. Automatic choices select only perceived objects and prefer moving them to
perceived endpoints; destination sight ranks choices without restricting legality.
General typed attack opt-in: object_target="unattended" or "any" adds an owned
object target sibling; object_on_hit_effects lists the typed on-hit effect types
also delivered after a real object hit, and object_before_effects runs its named
effects before the object attack roll. ext/objects.py publishes the sibling from
compile_basic_actions, so a technique a plug-in publishes itself in
compile_actions gets the same sibling; the sibling copies the typed parameters and
names the object recipient. The opt-in rides the compiled attack effect, never a
private Context flag. "any" accepts an attended object only where its own printed
text already allows objects; unattended needs-tag gating is unchanged.
ext/objects.py preserves native damage, activation, target sight/line of effect and
needs-tag gating. Absent opt-ins preserve prior actions and object-hit delivery.
Object damage marks: object_mark leaves an expiring mark on the object the current
instance damaged, carrying its eligible damage_types and expires_on;
object_damage_bonus queues typed count/sides bonus dice for an object instance and
objects.bonus_dice(object, sides) pops them inside the instance's own damage roll.
objects.deal consumes a mark after it applies an eligible type and turn_start
expires stale marks, so a mark is worth exactly one later eligible instance.
Destruction uses these for Fracturing Break and Breaching Proof; a mark, its dice
and its expiry all live in the object's saved component and replay with it.
Each delivered effect receives recipient_object_id as the object's string ID
in its transient effect row; consumers read this public binding rather than
another plug-in's private Context cache. No new persisted state is introduced."""
