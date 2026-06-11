"""Doctrine loading and prompt rendering for the town society.

Rule         — frozen dataclass for a single doctrine rule
load_doctrine — load and validate doctrine.yaml (unique id check)
doctrine_blocks — render numbered TEAM DOCTRINE / YOUR ROLE DOCTRINE sections
                  filtered by arm; empty sections are omitted.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

_DEFAULT_YAML = Path(__file__).parent / "doctrine.yaml"


@dataclass(frozen=True)
class Rule:
    id: str
    text: str
    arms: tuple[str, ...]
    role: str | None  # None = team rule


def load_doctrine(path: Path | None = None) -> list[Rule]:
    """Load doctrine rules from a YAML file and validate unique ids.

    Args:
        path: path to a doctrine YAML file; defaults to the bundled doctrine.yaml.

    Returns:
        Flat list of Rule objects (team rules first, then role rules in YAML order).

    Raises:
        ValueError: if any rule id is duplicated.
        FileNotFoundError: if the path does not exist.
    """
    if path is None:
        path = _DEFAULT_YAML

    with path.open() as fh:
        data = yaml.safe_load(fh)

    rules: list[Rule] = []

    # Team rules
    for entry in data.get("team", []):
        rules.append(
            Rule(
                id=entry["id"],
                text=entry["text"],
                arms=tuple(entry.get("arms", [])),
                role=None,
            )
        )

    # Role rules
    for role_name, entries in data.get("roles", {}).items():
        for entry in entries or []:
            rules.append(
                Rule(
                    id=entry["id"],
                    text=entry["text"],
                    arms=tuple(entry.get("arms", [])),
                    role=role_name,
                )
            )

    # Unique id validation
    seen: set[str] = set()
    for rule in rules:
        if rule.id in seen:
            raise ValueError(f"duplicate doctrine rule id: {rule.id!r}")
        seen.add(rule.id)

    return rules


def doctrine_blocks(rules: list[Rule], role: str, arm: str) -> str:
    """Render the doctrine prompt blocks for a given role and arm.

    Produces up to two sections:
      "TEAM DOCTRINE:\\n  T1. ...\\n  T2. ..."
      "YOUR ROLE DOCTRINE:\\n  C1. ...\\n  C2. ..."

    Only rules whose arms list includes arm are included.
    Sections with no applicable rules are omitted entirely.

    Args:
        rules: full list of Rule objects from load_doctrine().
        role:  the agent's role name (e.g. "commander", "medical").
        arm:   the benchmark arm name (e.g. "society", "swarm", "solo").

    Returns:
        A string with the doctrine blocks, or an empty string when no rules apply.
    """
    team_lines: list[str] = []
    role_lines: list[str] = []

    for rule in rules:
        if arm not in rule.arms:
            continue
        line = f"  {rule.id}. {rule.text}"
        if rule.role is None:
            team_lines.append(line)
        elif rule.role == role:
            role_lines.append(line)
        elif role == "solo":
            # The solo generalist performs every role's duties, so it inherits
            # every role rule applicable to its arm.
            role_lines.append(line)

    sections: list[str] = []
    if team_lines:
        sections.append("TEAM DOCTRINE:\n" + "\n".join(team_lines))
    if role_lines:
        sections.append("YOUR ROLE DOCTRINE:\n" + "\n".join(role_lines))

    return "\n\n".join(sections)
