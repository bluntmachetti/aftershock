"""Tests for RoleSpec and load_roles."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from aftershock.kernel.roles import RoleSpec, load_roles

# ---------------------------------------------------------------------------
# RoleSpec unit tests
# ---------------------------------------------------------------------------


def test_role_spec_defaults() -> None:
    spec = RoleSpec(name="medic")
    assert spec.display_name == ""
    assert spec.description == ""
    assert spec.allowed_decisions == ()
    assert spec.system_prompt == ""
    assert spec.model == ""
    assert spec.temperature == 0.3


def test_role_spec_is_frozen() -> None:
    spec = RoleSpec(name="medic")
    with pytest.raises(ValidationError):
        spec.name = "other"  # type: ignore[misc]


def test_role_spec_full() -> None:
    spec = RoleSpec(
        name="commander",
        display_name="The Commander",
        description="Coordinates the response",
        allowed_decisions=("set_priority", "broadcast"),
        system_prompt="You are the commander.",
        model="qwen-turbo",
        temperature=0.5,
    )
    assert spec.name == "commander"
    assert spec.allowed_decisions == ("set_priority", "broadcast")
    assert spec.temperature == 0.5


def test_role_spec_extra_field_forbidden() -> None:
    with pytest.raises(ValidationError):
        RoleSpec(name="x", unknown_field="bad")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# load_roles from tmp_path yaml files
# ---------------------------------------------------------------------------


def write_role(tmp_path: Path, filename: str, data: dict) -> None:
    (tmp_path / filename).write_text(yaml.dump(data))


def test_load_single_role(tmp_path: Path) -> None:
    write_role(
        tmp_path,
        "commander.yaml",
        {
            "name": "commander",
            "display_name": "Town Commander",
            "allowed_decisions": ["set_priority"],
        },
    )
    roles = load_roles(tmp_path)
    assert "commander" in roles
    spec = roles["commander"]
    assert spec.display_name == "Town Commander"
    assert spec.allowed_decisions == ("set_priority",)


def test_load_multiple_roles(tmp_path: Path) -> None:
    write_role(tmp_path, "medical.yaml", {"name": "medical", "model": "qwen-mini"})
    write_role(tmp_path, "rescue.yaml", {"name": "rescue", "temperature": 0.7})
    roles = load_roles(tmp_path)
    assert set(roles.keys()) == {"medical", "rescue"}
    assert roles["medical"].model == "qwen-mini"
    assert roles["rescue"].temperature == 0.7


def test_load_roles_defaults_applied(tmp_path: Path) -> None:
    write_role(tmp_path, "comms.yaml", {"name": "comms"})
    roles = load_roles(tmp_path)
    spec = roles["comms"]
    assert spec.display_name == ""
    assert spec.description == ""
    assert spec.allowed_decisions == ()
    assert spec.system_prompt == ""
    assert spec.model == ""
    assert spec.temperature == 0.3


def test_load_roles_empty_directory(tmp_path: Path) -> None:
    roles = load_roles(tmp_path)
    assert roles == {}


def test_load_roles_ignores_non_yaml(tmp_path: Path) -> None:
    write_role(tmp_path, "fire.yaml", {"name": "fire"})
    (tmp_path / "notes.txt").write_text("not a role")
    (tmp_path / "readme.md").write_text("# docs")
    roles = load_roles(tmp_path)
    assert list(roles.keys()) == ["fire"]


def test_load_roles_duplicate_name_raises(tmp_path: Path) -> None:
    write_role(tmp_path, "alpha.yaml", {"name": "commander"})
    write_role(tmp_path, "beta.yaml", {"name": "commander"})
    with pytest.raises(ValueError, match="duplicate role name"):
        load_roles(tmp_path)


def test_load_roles_key_equals_name(tmp_path: Path) -> None:
    write_role(tmp_path, "infra.yaml", {"name": "infrastructure"})
    roles = load_roles(tmp_path)
    assert "infrastructure" in roles
    # The key is the spec.name, not the filename stem
    assert "infra" not in roles


def test_load_roles_allowed_decisions_tuple(tmp_path: Path) -> None:
    write_role(
        tmp_path,
        "infra.yaml",
        {"name": "infrastructure", "allowed_decisions": ["recall", "repair_road"]},
    )
    roles = load_roles(tmp_path)
    spec = roles["infrastructure"]
    assert isinstance(spec.allowed_decisions, tuple)
    assert spec.allowed_decisions == ("recall", "repair_road")


def test_load_roles_full_spec(tmp_path: Path) -> None:
    write_role(
        tmp_path,
        "fire.yaml",
        {
            "name": "fire",
            "display_name": "Fire Brigade",
            "description": "Puts out fires",
            "allowed_decisions": ["recall"],
            "system_prompt": "You manage fire missions.",
            "model": "qwen-plus",
            "temperature": 0.1,
        },
    )
    roles = load_roles(tmp_path)
    spec = roles["fire"]
    assert spec.display_name == "Fire Brigade"
    assert spec.description == "Puts out fires"
    assert spec.system_prompt == "You manage fire missions."
    assert spec.model == "qwen-plus"
    assert spec.temperature == 0.1
