"""Role definitions loaded from YAML files.

Each *.yaml in the roles directory maps to a frozen RoleSpec.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ConfigDict

from aftershock.kernel.protocol import Frozen


class RoleSpec(Frozen):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    display_name: str = ""
    description: str = ""
    allowed_decisions: tuple[str, ...] = ()
    system_prompt: str = ""
    model: str = ""
    temperature: float = 0.3
    use_tools: bool = False


def load_roles(path: Path) -> dict[str, RoleSpec]:
    """Load every *.yaml in *path* as a RoleSpec.

    Keys are ``spec.name``. Raises ValueError on duplicate names.
    """
    roles: dict[str, RoleSpec] = {}
    for yaml_file in sorted(path.glob("*.yaml")):
        data: Any = yaml.safe_load(yaml_file.read_text())
        if not isinstance(data, dict):
            raise ValueError(f"role file {yaml_file} must contain a YAML mapping")
        spec = RoleSpec.model_validate(data)
        if spec.name in roles:
            raise ValueError(f"duplicate role name: {spec.name!r}")
        roles[spec.name] = spec
    return roles
