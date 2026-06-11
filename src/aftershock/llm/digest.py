"""Observation digest: sanitize agent-authored text and render Observation -> bounded string.

sanitize:  strip control sequences, backticks, role prefixes, collapse whitespace, cap length.
render_observation: deterministic compact text for small-context models.
"""

from __future__ import annotations

import re

from aftershock.kernel.protocol import Observation

# Regex patterns compiled once
_CONTROL_SEQ = re.compile(r"<\|[^|>]*\|>")  # <|...|> tokens
_BACKTICK = re.compile(r"`+")
_ROLE_PREFIX = re.compile(r"^(system|assistant|user)\s*:\s*", re.IGNORECASE)
_WHITESPACE = re.compile(r"\s+")


def sanitize(text: str, cap: int = 200) -> str:
    """Sanitize agent-authored text for safe inclusion in another agent's prompt.

    Steps (in order):
    1. Strip <|...|> control sequences.
    2. Remove backticks.
    3. Collapse all whitespace (newlines, tabs, multiple spaces) to a single space.
    4. Strip leading "system:", "assistant:", "user:" prefixes (case-insensitive).
    5. Strip surrounding whitespace.
    6. Cap to `cap` characters.
    """
    text = _CONTROL_SEQ.sub("", text)
    text = _BACKTICK.sub("", text)
    text = _WHITESPACE.sub(" ", text)
    text = text.strip()
    while True:
        new = _ROLE_PREFIX.sub("", text)
        if new == text:
            break
        text = new.strip()
    if len(text) > cap:
        text = text[:cap]
    return text


def render_observation(obs: Observation, max_missions: int = 12) -> str:
    """Render an Observation to a deterministic, bounded text string.

    Section order (per DESIGN.md):
    1. TICK / PANIC
    2. POOLS
    3. BLOCKED districts
    4. MISSIONS table (priority desc, deadline asc, id); capped at max_missions with (+N more)
    5. YOUR INBOX
    6. RULINGS
    7. RECENTLY REJECTED (last 3 ticks)  (prefixed "do not repeat these")
    8. ALLOWED DECISIONS
    """
    view = obs.view
    lines: list[str] = []

    # --- Section 1: TICK / PANIC ---
    tick = view.get("tick", obs.tick)
    panic = view.get("panic", 0.0)
    lines.append(f"TICK {tick}  PANIC {panic:.2f}")
    lines.append("")

    # --- Section 2: POOLS ---
    pool_avail: dict[str, int] = view.get("pool_availability", {})
    pool_parts = [f"{k}:{v}" for k, v in sorted(pool_avail.items())]
    lines.append("POOLS  " + "  ".join(pool_parts))
    lines.append("")

    # --- Section 3: BLOCKED ---
    blocked: list[str] = view.get("blocked_districts", [])
    if blocked:
        # Cap each district id and the total count to bound line length.
        blocked_parts = [d[:24] for d in blocked[:20]]
        lines.append("BLOCKED  " + " ".join(blocked_parts))
        lines.append("")

    # --- Section 4: MISSIONS table ---
    open_missions: list[dict] = view.get("open_missions", [])

    # Sort: priority desc, deadline_in asc, id asc
    def _mission_sort_key(m: dict) -> tuple[int, int, str]:
        return (-m.get("priority", 0), m.get("deadline_in", 9999), m.get("id", ""))

    sorted_missions = sorted(open_missions, key=_mission_sort_key)
    total_missions = len(sorted_missions)
    capped = sorted_missions[:max_missions]
    overflow = total_missions - len(capped)

    lines.append("MISSIONS")
    if capped:
        # Header
        lines.append(
            f"  {'id':<6} {'kind':<18} {'district':<22} {'sev':>3} {'lives':>5}"
            f" {'dl_in':>5} {'pri':>3} {'staffing'}"
        )
        for m in capped:
            mid = m.get("id", "")[:8]
            # Cap kind/district to column widths to bound digest size regardless of
            # individual field lengths (DESIGN.md:410 'bounded size regardless of world size').
            kind = m.get("kind", "")[:18]
            district = m.get("district", "")[:22]
            sev = m.get("severity", 0)
            lives = m.get("lives_at_risk", 0)
            dl_in = m.get("deadline_in", 0)
            pri = m.get("priority", 0)
            required: dict[str, int] = m.get("required", {})
            assigned: dict[str, int] = m.get("assigned", {})
            # staffing: "assigned/required" per resource kind, space-separated; cap res name
            staffing_parts = [
                f"{res[:16]}:{assigned.get(res, 0)}/{qty}"
                for res, qty in sorted(required.items())
            ]
            staffing = " ".join(staffing_parts)
            lines.append(
                f"  {mid:<6} {kind:<18} {district:<22} {sev:>3} {lives:>5}"
                f" {dl_in:>5} {pri:>3}  {staffing}"
            )
        if overflow > 0:
            lines.append(f"  (+{overflow} more)")
    else:
        lines.append("  (none)")
    lines.append("")

    # --- Section 5: YOUR INBOX ---
    lines.append("YOUR INBOX")
    if obs.inbox:
        for proposal in obs.inbox:
            body_str = _render_dict(proposal.body)
            sanitized_body = sanitize(body_str, cap=200)
            recipient_str = proposal.recipient or "all"
            # Sanitize kernel-controlled fields too (defense-in-depth: a future change
            # making kind a free str or admitting custom recipient labels would otherwise
            # silently open a prompt-injection hole — DESIGN.md:403).
            safe_sender = sanitize(proposal.sender, cap=64)
            safe_kind = sanitize(str(proposal.kind), cap=32)
            safe_recipient = sanitize(recipient_str, cap=64)
            lines.append(
                f"  [{proposal.proposal_id}] from={safe_sender}"
                f" kind={safe_kind} to={safe_recipient}"
            )
            lines.append(f"    body: {sanitized_body}")
    else:
        lines.append("  (empty)")
    lines.append("")

    # --- Section 6: RULINGS ---
    lines.append("RULINGS")
    if obs.rulings:
        for ruling in obs.rulings:
            outcome = "accepted" if ruling.accepted else "declined"
            reason_str = sanitize(ruling.reason, cap=200) if ruling.reason else ""
            if reason_str:
                lines.append(f"  [{ruling.proposal_id}] {outcome}: {reason_str}")
            else:
                lines.append(f"  [{ruling.proposal_id}] {outcome}")
    else:
        lines.append("  (none)")
    lines.append("")

    # --- Section 7: RECENTLY REJECTED ---
    lines.append("RECENTLY REJECTED (last 3 ticks)")
    if obs.rejections:
        lines.append("  do not repeat these")
        for rej in obs.rejections:
            reason_str = sanitize(rej.reason, cap=200)
            lines.append(f"  [{rej.decision_id}] {rej.decision_type}: {reason_str}")
    else:
        lines.append("  (none)")
    lines.append("")

    # --- Section 8: ALLOWED DECISIONS ---
    lines.append("ALLOWED DECISIONS")
    if obs.allowed_decisions:
        lines.append("  " + "  ".join(obs.allowed_decisions))
    else:
        lines.append("  (none)")

    return "\n".join(lines)


def _render_dict(d: dict) -> str:
    """Render a dict to a compact key=value string for display."""
    return " ".join(f"{k}={v}" for k, v in sorted(d.items()))
