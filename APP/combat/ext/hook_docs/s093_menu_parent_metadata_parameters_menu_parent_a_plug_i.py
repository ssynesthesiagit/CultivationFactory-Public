"""Menu parent metadata (parameters.menu_parent): a plug-in sets action.parameters
["menu_parent"] to the source_definition_id of the ability a picker belongs to,
e.g. a Blossom choice under Cultivate Blossom. The value is a string id, never an
object. It is read-only presentation metadata: it changes no legality, cost,
target, choice or execution. Core projects it as the public `parent` field on
menu groups (tabletop_service.py) and on sheet buttons (tabletop.py _auto_buttons).
The sheet Actions list draws such a picker indented under its parent
(option-groups.js groupOptionRows). The table action bar draws no picker: like
Darkness's talents, it is listed under its parent's Options button (tabletop_service
._shapes "choices"). Only one level
is supported: the parent must itself be top-level. Absent or empty metadata leaves
the row top-level, as before. A row stays top-level, so it stays visible, when its
parent is missing from the same list, is the row itself, is itself a child, or forms
a cycle. Set it only on rows the actor owns; a plug-in must not attach it to another
actor's or another ability's rows, and must not nest a picker under another picker."""
