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
    trim: bool = True,
) -> str:
    """Render the shared output contract for an LLM agent system prompt.

    Sections (in order):
    1. Output JSON schema with field names matching parse.py exactly.
    2. One usage line per allowed decision type (from decision_docs).
    3. One line per proposal kind (from proposal_docs).
    4. Hard rules list.

    The word "JSON" is present — required by DashScope json_mode.

    ``trim`` (default True) selects the FIELD-NOTES §21 cost-trimmed rendering:
    a compact single-line JSON skeleton plus deduped Hard Rules. trim=False
    reproduces the pre-§21 verbose rendering byte-for-byte (the untrimmed control
    for the contract on/off ablation — FIELD-NOTES §21). Only Sections 1 and 4
    differ; Sections 2 and 3 are identical in both modes (their content comes from
    the caller-supplied decision_docs / proposal_docs).
    """
    lines: list[str] = []

    if trim:
        # --- Section 1: JSON schema (compact single-line forms keep the same field
        # vocabulary at a fraction of the tokens; FIELD-NOTES §21 cost trim) ---
        lines.append("## Output Format")
        lines.append("")
        lines.append("Reply with ONLY a JSON object (no markdown, no prose). Schema:")
        if proposal_docs:
            # Full schema: decisions + proposals + responses
            lines.append(
                '{"decisions":[{"decision_type":"<type>","params":{<k>:<v>},'
                '"rationale":"<≤25 words>"}], '
                '"proposals":[{"kind":"<kind>","recipient":"<agent_id|null>","body":{<k>:<v>}}], '
                '"responses":[{"proposal_id":"<id>","accept":true|false,"note":"<optional>"}]}'
            )
        else:
            # Decisions-only schema (no proposals, no responses)
            lines.append(
                '{"decisions":[{"decision_type":"<type>","params":{<k>:<v>},'
                '"rationale":"<≤25 words>"}]}'
            )
    else:
        # --- Section 1: JSON schema (pre-§21 verbose multi-line form) ---
        lines.append("## Output Format")
        lines.append("")
        lines.append("Respond with ONLY a JSON object (no markdown, no extra text):")
        lines.append("")
        if proposal_docs:
            # Full schema: decisions + proposals + responses
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
        else:
            # Decisions-only schema (no proposals, no responses)
            lines.append("{")
            lines.append('  "decisions": [')
            lines.append("    {")
            lines.append('      "decision_type": "<type>",')
            lines.append('      "params": {<key>: <value>, ...},')
            lines.append('      "rationale": "<under 25 words>"')
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

    if trim:
        # --- Section 4: Hard rules (deduped — "JSON only" lives in Output Format and the
        # 25-word cap in the schema; FIELD-NOTES §21) ---
        lines.append("## Hard Rules")
        lines.append("")
        if proposal_docs:
            lines.append(
                "- Use exact ids from the observation"
                " (mission ids like \"m3\", resource names, proposal ids) — never invent ids."
            )
            lines.append('- Answer every proposal in YOUR INBOX via "responses".')
            lines.append(
                "- Resources are granted only through resource_request proposals,"
                " not dispatch decisions."
            )
        else:
            lines.append(
                "- Use exact ids from the observation"
                " (mission ids like \"m3\", resource names) — never invent ids."
            )
            lines.append("- Do not emit proposals or responses.")
    else:
        # --- Section 4: Hard rules (pre-§21 verbose form, before the dedup) ---
        lines.append("## Hard Rules")
        lines.append("")
        lines.append("- Output ONLY a JSON object; no markdown fences, no explanation.")
        if proposal_docs:
            lines.append(
                "- Use exact ids exactly as they appear in the observation"
                " (mission ids like \"m3\", resource names, proposal ids) — never invent ids."
            )
        else:
            lines.append(
                "- Use exact ids exactly as they appear in the observation"
                " (mission ids like \"m3\", resource names) — never invent ids."
            )
        if proposal_docs:
            lines.append('- Answer every proposal in YOUR INBOX via "responses".')
            lines.append(
                "- Resources are granted only through resource_request proposals,"
                " not dispatch decisions."
            )
        else:
            lines.append("- Do not emit proposals or responses.")
        lines.append("- Keep each rationale under 25 words.")

    return "\n".join(lines)
