"""Lazy ranked menu pages for SeatRunner, retaining every issued legal key.

Only prompt presentation uses these pages. Navigation costs no combat action;
execution and fallback continue to use the original, complete legal menu.
"""
MORE_KEY = "__menu_more__"
MORE_LINE = "L) More choices; no action."
DETAIL_KEY = "__menu_details__"
BACK_KEY = "__menu_back__"
SITUATION_KEY = "__menu_situation__"


def slot_candidate_keys(slots, options, builtin):
    """Translate the table's exact ranked candidate lists to executable seat keys.

    Expanded variants remain in the complete menu; prefer the native selection
    when it represents the same candidate, otherwise stable source order.
    """
    by_candidate = {}
    for key, row in options.items():
        by_candidate.setdefault(row["candidate_id"], key)
    by_candidate[options[builtin]["candidate_id"]] = builtin
    values = [[by_candidate[candidate] for candidate in slots.get(slot, [])
               if candidate in by_candidate]
              for slot in slots]
    return [keys[i] for i in range(5) for keys in values if i < len(keys)]


class RankedPages:
    def __init__(self, legal, ranked, builtin, cap):
        self.legal = legal
        self.cap = max(1, cap)
        self.ends = [key for key, row in legal.items() if row.get("action") == "End turn"]
        self.remaining = dict.fromkeys(key for key in [builtin, *ranked, *legal]
                                       if key in legal and key not in self.ends)
        self.first = [key for key in dict.fromkeys([builtin, *ranked])
                      if key in self.remaining][:self.cap]
        self.page_number = 0
        self.detail_offset = 0
        self.rule_offsets = {}
        self.situation_offset = 0
        self.history = []

    def menu(self):
        keys = (self.history[self.page_number] if self.page_number < len(self.history)
                else self.first if not self.page_number else list(self.remaining)[:self.cap])
        return {key: self.legal[key] for key in [*keys, *self.ends]}

    def has_more(self, offered):
        return self.page_number < len(self.history) or any(key not in offered for key in self.remaining)

    def advance(self, offered):
        # Compact/tiny rendering can expose fewer rows than menu(). Record
        # exactly those issued keys, retaining every unissued row for later.
        if self.page_number == len(self.history):
            self.history.append([key for key in self.menu() if key in offered and key not in self.ends])
            for key in offered:
                self.remaining.pop(key, None)
        self.page_number += 1
        self.detail_offset = 0

    def back(self):
        """Revisit a prior page without staging or executing any step."""
        self.page_number = max(0, self.page_number - 1)
        self.detail_offset = 0


    def display_menu(self, chunk_bytes=512):
        """JSON-profile display copies; DETAILS pages never mutate legal rows."""
        from .choices import option_description
        result = {}
        for key, row in self.menu().items():
            shown = dict(row)
            full = option_description(row, self.legal).encode()
            offset = self.rule_offsets.get(key, 0) % max(1, len(full))
            part = full[offset:offset + chunk_bytes].decode(errors="ignore")
            if offset + len(part.encode()) < len(full):
                part += " [display shortened; reply DETAILS " + key + " for next rules page]"
            for field in ("description", "choice_description"):
                if field in shown:
                    shown[field] = part
            result[key] = shown
        return result

    def more_rules(self, key, chunk_bytes=512):
        from .choices import option_description
        full = option_description(self.legal[key], self.legal).encode()
        offset = self.rule_offsets.get(key, 0) % max(1, len(full))
        self.rule_offsets[key] = offset + len(full[offset:offset + chunk_bytes].decode(errors="ignore").encode())


def tactical_situation(view):
    """Only current own-knowledge actors, never sight memory or hidden state."""
    own = next((a for a in view.get("actors", []) if a.get("entity_id") == view.get("fighter")), {})
    def location(actor):
        p = actor.get("position")
        return (f"({p['x']},{p['y']}), {p.get('z', 0) * 5} ft above ground" if p else "unknown position")
    lines = ["You at " + location(own) + "; squares are 5 ft.",
             "Movement remaining: " + str(own.get("movement_remaining_ft", "unknown")) + " ft"
             + "; Action available: " + str(own.get("action_available", "unknown"))
             + "; Bonus action available: " + str(own.get("bonus_action_available", "unknown")) + "."]
    for actor in sorted(view.get("actors", []), key=lambda a: a.get("entity_id", "")):
        if actor.get("entity_id") == view.get("fighter"):
            continue
        label = "Ally" if actor.get("team_id") == own.get("team_id") else "Threat"
        if actor.get("active") is False:
            label = "Defeated"
        lines.append(label + ": " + str(actor.get("display_name") or "creature") + " at " + location(actor) + ".")
    lines.extend(view.get('information') or [])
    return "\n".join(lines)


def text_page(value, offset, size):
    """UTF-8 byte bounded pages, with offsets on whole characters."""
    raw = value.encode()
    offset %= max(1, len(raw))
    part = raw[offset:offset + size].decode(errors="ignore")
    return part, offset + len(part.encode()), offset + len(part.encode()) < len(raw)


def choice_frame(view, pages, budget, selected=(), repair=None):
    """Bounded next-step frame with reversible choices and lossless facts.

    Only display text is shortened; execution always uses the original legal
    rows. One active row per page lets K expose all of that row's rules in
    bounded chunks, including its full label, targets and cost. I cycles through
    all current own-knowledge situation facts; J revisits choices without acting.
    Reset pages after selecting a step to compose any ordered
    plan across pages; End is an explicit decision, never attached to a step.
    """
    from .choices import perceived_names, step_label, option_description, text
    from .protocol import dao_line
    menu = pages.menu()
    end = next(iter(pages.ends), None)
    key = next((k for k in menu if k != end), None)
    answers = {"A": {"plan": [end]}} if end else {}
    lines = ["Choose the next step of your plan; only End ends your turn. Reply one letter."]
    own = next((actor for actor in view.get("actors", []) if actor.get("entity_id") == view.get("fighter")), {})
    lines.append("Fighter: " + text(own.get("display_name", "Fighter"), 40)
                 + " · " + text(dao_line(view, 40), 100))
    lines.append("Situation:")
    lines.append("HP: " + text(own.get("hit_points", "unknown"), 60)
                 + " · Resources: " + text(own.get("resources", {}), 80))
    situation = tactical_situation(view)
    facts, pages.next_situation_offset, more_facts = text_page(situation, pages.situation_offset, min(300, budget // 5))
    lines.append(facts)
    lines.append("A) End turn here" if end else "Choose a follow-up.")
    if more_facts or pages.situation_offset:
        answers["I"] = {"plan": [SITUATION_KEY]}
        lines.append("I) Next situation page (cycles); no action.")
    if repair:
        lines.append("Invalid reply; choose an offered letter.")
    if key:
        answers["B"] = {"plan": [key]}
        answers["K"] = {"plan": [DETAIL_KEY]}
        lines.append("K) Full rules / next rules page for B; no action.")
    offered = set(menu)
    if pages.has_more(offered):
        answers["L"] = {"plan": [MORE_KEY]}
        lines.append(MORE_LINE)
    if pages.page_number:
        answers["J"] = {"plan": [BACK_KEY]}
        lines.append("J) Back to previous choices; no action.")
    def clip(text, size):
        raw = text.encode()
        marker = " [display shortened; K: full rules]"
        if len(raw) <= size:
            return text
        return raw[:max(0, size - len(marker.encode()))].decode(errors="ignore") + marker
    if selected:
        names = perceived_names(view)
        labels = ", then ".join(step_label(pages.legal[k], names) for k in selected)
        lines.append("Plan so far: " + clip(labels, min(100, budget // 6)))
    if key:
        names = perceived_names(view)
        prefix = "\n".join(lines) + "\nB) "
        # Reserve room for a progressing detail chunk even when Back, repair
        # and staged-plan controls all occupy the bounded frame.
        label_room = budget - len(prefix.encode()) - 2 - 80
        label = clip(step_label(menu[key], names), min(160, budget // 4, max(40, label_room)))
        room = budget - len((prefix + label + ": ").encode())
        full = (step_label(menu[key], names) + ": " + option_description(menu[key], pages.legal)).encode()
        offset = pages.detail_offset % max(1, len(full))
        chunk = full[offset:].decode(errors="ignore")
        shown = clip(chunk, max(40, room))
        pages.next_detail_offset = offset + max(1, len(shown.split(" [display shortened;")[0].encode()))
        lines.append("B) " + label + ": " + shown)
    return "\n".join(lines), answers, offered
