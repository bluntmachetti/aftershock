"""Output contract appended to every LLM agent system prompt.

decision_contract renders the exact JSON schema, per-decision usage lines,
proposal kind lines, and hard rules. Must contain the word "JSON" (DashScope
json_mode requirement).
"""

from __future__ import annotations


def decision_contract(
    allowed: tuple[str, ...],
    decision_docs: dict[str, str],
    proposal_docs: dict[str, str],
) -> str:
    """Render the shared output contract for an LLM agent system prompt.

    Sections (in order):
    1. Output JSON schema with field names matching parse.py exactly.
    2. One usage line per allowed decision type (from decision_docs).
    3. One line per proposal kind (from proposal_docs).
    4. Hard rules list.

    The word "JSON" is present — required by DashScope json_mode.
    """
    lines: list[str] = []

    # --- Section 1: JSON schema ---
    lines.append("## Output Format")
    lines.append("")
    lines.append("Respond with ONLY a JSON object (no markdown, no extra text):")
    lines.append("")
    lines.append("{")
    lines.append('  "decisions": [')
    lines.append("    {")
    lines.append('      "decision_type": "<type>",')
    lines.append('      "params": {<key>: <value>, ...},')
    lines.append('      "rationale": "<under 25 words>"')
    lines.append("    }")
    lines.append("  ],")
    lines.append('  "proposals": [')
    lines.append("    {")
    lines.append('      "kind": "<kind>",')
    lines.append('      "recipient": "<agent_id or null>",')
    lines.append('      "body": {<key>: <value>, ...}')
    lines.append("    }")
    lines.append("  ],")
    lines.append('  "responses": [')
    lines.append("    {")
    lines.append('      "proposal_id": "<id>",')
    lines.append('      "accept": true|false,')
    lines.append('      "note": "<optional note>"')
    lines.append("    }")
    lines.append("  ]")
    lines.append("}")
    lines.append("")

    # --- Section 2: Allowed decision types ---
    if allowed:
        lines.append("## Allowed Decision Types")
        lines.append("")
        for dtype in allowed:
            if dtype in decision_docs:
                lines.append(f"- {decision_docs[dtype]}")
            else:
                lines.append(f"- {dtype}")
        lines.append("")

    # --- Section 3: Proposal kinds ---
    if proposal_docs:
        lines.append("## Proposal Kinds")
        lines.append("")
        for _kind, doc in sorted(proposal_docs.items()):
            lines.append(f"- {doc}")
        lines.append("")

    # --- Section 4: Hard rules ---
    lines.append("## Hard Rules")
    lines.append("")
    lines.append("- Output ONLY a JSON object; no markdown fences, no explanation.")
    lines.append(
        "- Use exact ids exactly as they appear in the observation"
        " (mission ids like \"m3\", resource names, proposal ids) — never invent ids."
    )
    lines.append('- Answer every proposal in YOUR INBOX via "responses".')
    lines.append(
        "- Resources are granted only through resource_request proposals,"
        " not dispatch decisions."
    )
    lines.append("- Keep each rationale under 25 words.")

    return "\n".join(lines)
