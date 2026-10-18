"""Config model and TOML I/O tests (spec §5.3, appendix B.1, §16.3).

Test-first (appendix C): these drive ``gregraph/core/config.py``. Config schema
2 requires a type abbreviation (typed IDs); schema 1 is refused by
``read_config`` with a migration hint.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from gregraph.core.config import (
    Config,
    ConfigSchemaError,
    dumps_toml,
    read_config,
    write_config,
)

#: Appendix B.1 shipped types: name -> (abbreviation, kind, template), B.1 order.
B1_TYPES: dict[str, tuple[str, str, str]] = {
    "context": ("CTX", "goal", "context"),
    "goal": ("GOAL", "goal", "goal"),
    "epic": ("EPIC", "goal", "epic"),
    "feature": ("FEAT", "requirement", "feature"),
    "user-story": ("STORY", "requirement", "user-story"),
    "functional-requirement": ("FUNC", "requirement", "requirement-ears"),
    "non-functional-requirement": ("NFR", "requirement", "requirement-ears"),
    "constraint": ("CON", "requirement", "constraint"),
    "design": ("DSGN", "design", "design"),
    "decision": ("DEC", "design", "decision"),
    "test-case": ("TEST", "verification", "test-case"),
    "stakeholder": ("STKH", "information", "stakeholder"),
    "assumption": ("ASM", "information", "assumption"),
}

B1_TOML = """\
[gregraph]
config_schema = 2
tool_version = "0.2.0"

[ids]
prefix = "RE"

[git]
baseline_branch = "main"

[versioning]
on_outdated_links = "block"   # block | warn
on_cr_modified = "warn"       # block | warn

[graph]
open_conflicts = "warn"       # warn | block (block applies only on the baseline branch)

[assets]
max_size_kb = 5120

[types.context]
abbreviation = "CTX"
kind = "goal"
template = "context"

[types.goal]
abbreviation = "GOAL"
kind = "goal"
template = "goal"

[types.epic]
abbreviation = "EPIC"
kind = "goal"
template = "epic"

[types.feature]
abbreviation = "FEAT"
kind = "requirement"
template = "feature"

[types.user-story]
abbreviation = "STORY"
kind = "requirement"
template = "user-story"

[types.functional-requirement]
abbreviation = "FUNC"
kind = "requirement"
template = "requirement-ears"

[types.non-functional-requirement]
abbreviation = "NFR"
kind = "requirement"
template = "requirement-ears"

[types.constraint]
abbreviation = "CON"
kind = "requirement"
template = "constraint"

[types.design]
abbreviation = "DSGN"
kind = "design"
template = "design"

[types.decision]
abbreviation = "DEC"
kind = "design"
template = "decision"

[types.test-case]
abbreviation = "TEST"
kind = "verification"
template = "test-case"

[types.stakeholder]
abbreviation = "STKH"
kind = "information"
template = "stakeholder"

[types.assumption]
abbreviation = "ASM"
kind = "information"
template = "assumption"

[cr]
enabled = true
template = "change-request"
deciders = []
"""


def type_spec(
    kind: str = "goal",
    template: str = "goal",
    abbreviation: str = "TST",
    **extra: object,
) -> dict[str, object]:
    """A minimal valid ``[types.<name>]`` mapping for tests."""
    return {
        "abbreviation": abbreviation,
        "kind": kind,
        "template": template,
        **extra,
    }


def test_defaults_match_appendix_b1() -> None:
    config = Config()
    assert config.gregraph.config_schema == 2
    assert config.gregraph.tool_version == "0.2.0"
    assert config.ids.prefix == "RE"
    assert config.git.baseline_branch == "main"
    assert config.versioning.on_outdated_links == "block"
    assert config.versioning.on_cr_modified == "warn"
    assert config.graph.open_conflicts == "warn"
    assert config.assets.max_size_kb == 5120
    assert config.cr.enabled is True
    assert config.cr.template == "change-request"
    assert config.cr.deciders == []
    with pytest.raises(ValidationError):
        Config.model_validate({"versioning": {"on_outdated_links": "sometimes"}})
    with pytest.raises(ValidationError):
        Config.model_validate({"versioning": {"on_cr_modified": "no"}})
    with pytest.raises(ValidationError):
        Config.model_validate({"graph": {"open_conflicts": "block!"}})


def test_default_types_match_appendix_b1() -> None:
    types = Config().types
    assert list(types) == list(B1_TYPES)
    for name, (abbreviation, kind, template) in B1_TYPES.items():
        assert types[name].abbreviation == abbreviation
        assert types[name].kind == kind
        assert types[name].template == template


def test_folder_defaults_to_type_name() -> None:
    config = Config.model_validate(
        {"types": {"user-story": type_spec("requirement", "user-story", "STORY")}}
    )
    assert config.types["user-story"].folder == "user-story"


def test_folder_override() -> None:
    config = Config.model_validate(
        {
            "types": {
                "user-story": type_spec(
                    "requirement", "user-story", "STORY", folder="user-stories"
                )
            }
        }
    )
    assert config.types["user-story"].folder == "user-stories"


@pytest.mark.parametrize(
    "name",
    ["a", "goal", "user-story", "a1-b2", "x--y", "user-story-"],
)
def test_type_name_shapes_accepted(name: str) -> None:
    config = Config.model_validate({"types": {name: type_spec()}})
    assert name in config.types


@pytest.mark.parametrize(
    "name",
    [
        "User-Story",
        "1goal",
        "user_story",
        "user story",
        "",
        "-goal",
        "goal!",
        "user.story",
    ],
)
def test_type_name_shapes_rejected(name: str) -> None:
    with pytest.raises(ValidationError):
        Config.model_validate({"types": {name: type_spec()}})


@pytest.mark.parametrize("prefix", ["RE", "R", "A", "ABC12345"])
def test_prefix_shapes_accepted(prefix: str) -> None:
    assert Config.model_validate({"ids": {"prefix": prefix}}).ids.prefix == prefix


@pytest.mark.parametrize(
    "prefix", ["re", "9X", "RE-XY", "ABC123456", "", "A_B", "AB C"]
)
def test_prefix_shapes_rejected(prefix: str) -> None:
    with pytest.raises(ValidationError):
        Config.model_validate({"ids": {"prefix": prefix}})


@pytest.mark.parametrize("abbreviation", ["ASM", "FEAT", "STORY"])
def test_abbreviation_shapes_accepted(abbreviation: str) -> None:
    config = Config.model_validate(
        {"types": {"t": type_spec(abbreviation=abbreviation)}}
    )
    assert config.types["t"].abbreviation == abbreviation


@pytest.mark.parametrize(
    "abbreviation", ["", "FE", "FEATURES", "feat", "Feat", "F3AT", "FE-T"]
)
def test_abbreviation_shapes_rejected(abbreviation: str) -> None:
    with pytest.raises(ValidationError):
        Config.model_validate({"types": {"t": type_spec(abbreviation=abbreviation)}})


def test_abbreviation_is_required() -> None:
    with pytest.raises(ValidationError):
        Config.model_validate({"types": {"t": {"kind": "goal", "template": "goal"}}})


def test_abbreviations_must_be_unique() -> None:
    with pytest.raises(ValidationError):
        Config.model_validate(
            {
                "types": {
                    "a": type_spec(abbreviation="SAME"),
                    "b": type_spec(abbreviation="SAME"),
                }
            }
        )


def test_chg_is_reserved() -> None:
    with pytest.raises(ValidationError):
        Config.model_validate({"types": {"t": type_spec(abbreviation="CHG")}})


@pytest.mark.parametrize(
    "kind", ["goal", "requirement", "design", "verification", "information"]
)
def test_kinds_accepted(kind: str) -> None:
    config = Config.model_validate({"types": {"t": type_spec(kind=kind)}})
    assert config.types["t"].kind == kind


@pytest.mark.parametrize("kind", ["Goal", "goals", "requirement ", ""])
def test_kinds_rejected(kind: str) -> None:
    with pytest.raises(ValidationError):
        Config.model_validate({"types": {"t": type_spec(kind=kind)}})


def test_policy_literals_rejected() -> None:
    with pytest.raises(ValidationError):
        Config.model_validate({"versioning": {"on_outdated_links": "sometimes"}})
    with pytest.raises(ValidationError):
        Config.model_validate({"versioning": {"on_cr_modified": "no"}})
    with pytest.raises(ValidationError):
        Config.model_validate({"graph": {"open_conflicts": "block!"}})


def test_config_schema_must_be_2() -> None:
    with pytest.raises(ValidationError):
        Config.model_validate({"gregraph": {"config_schema": 1}})
    with pytest.raises(ValidationError):
        Config.model_validate({"gregraph": {"config_schema": 3}})


def test_extra_keys_rejected() -> None:
    with pytest.raises(ValidationError):
        Config.model_validate({"bogus": 1})
    with pytest.raises(ValidationError):
        Config.model_validate({"ids": {"prefix": "RE", "bogus": 1}})
    with pytest.raises(ValidationError):
        Config.model_validate({"types": {"t": type_spec(bogus=1)}})


def test_read_appendix_b1_toml(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(B1_TOML, encoding="utf-8")
    config = read_config(path)
    assert config == Config()


def test_read_legacy_schema_1_refuses_with_migration_hint(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        '[gregraph]\nconfig_schema = 1\ntool_version = "0.1.1"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigSchemaError, match="migrate_type_ids"):
        read_config(path)


def test_read_empty_file_yields_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("# gregraph configuration\n", encoding="utf-8")
    assert read_config(path) == Config()


def test_read_unsupported_schema_refuses(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[gregraph]\nconfig_schema = 3\n", encoding="utf-8")
    with pytest.raises(ConfigSchemaError, match="unsupported"):
        read_config(path)


def test_write_read_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    config = Config.model_validate(
        {
            "ids": {"prefix": "XX"},
            "types": {
                "story": type_spec(
                    "requirement", "user-story", "STORY", folder="stories"
                )
            },
            "cr": {"deciders": ["a@example.org", "b@example.org"]},
        }
    )
    write_config(path, config)
    assert read_config(path) == config


def test_write_creates_parent_directories(tmp_path: Path) -> None:
    path = tmp_path / ".gregraph" / "config.toml"
    write_config(path, Config())
    assert path.is_file()
    assert read_config(path) == Config()


def test_write_is_byte_stable(tmp_path: Path) -> None:
    config = Config()
    first = dumps_toml(config).encode("utf-8")
    second = dumps_toml(config).encode("utf-8")
    assert first == second
    path = tmp_path / "config.toml"
    write_config(path, config)
    write_config(path, config)
    assert path.read_bytes() == first


def test_rewrite_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    config = Config.model_validate({"types": {"t": type_spec()}})
    write_config(path, config)
    once = path.read_bytes()
    write_config(path, read_config(path))
    assert path.read_bytes() == once


def test_dumps_toml_shape() -> None:
    text = dumps_toml(Config())
    assert text.endswith("\n")
    assert "config_schema = 2\n" in text
    assert "[gregraph]\n" in text
    assert 'tool_version = "0.2.0"\n' in text
    assert 'prefix = "RE"\n' in text
    assert 'baseline_branch = "main"\n' in text
    assert 'on_outdated_links = "block"\n' in text
    assert 'on_cr_modified = "warn"\n' in text
    assert 'open_conflicts = "warn"\n' in text
    assert "max_size_kb = 5120\n" in text
    assert "[types.user-story]\n" in text
    assert 'abbreviation = "STORY"\n' in text
    assert 'kind = "requirement"\n' in text
    assert 'template = "requirement-ears"\n' in text
    assert "[cr]\n" in text
    assert "enabled = true\n" in text
    assert "deciders = []\n" in text


def test_dumps_toml_omits_default_folder(tmp_path: Path) -> None:
    text = dumps_toml(Config())
    assert "folder" not in text
    config = Config.model_validate(
        {
            "types": {
                "story": type_spec(
                    "requirement", "user-story", "STORY", folder="stories"
                )
            }
        }
    )
    assert 'folder = "stories"' in dumps_toml(config)


def test_dumps_toml_reparses_to_model_dump(tmp_path: Path) -> None:
    config = Config.model_validate(
        {
            "cr": {"deciders": ["a@example.org"]},
            "types": {
                "t": type_spec("goal", "t", "TST", folder="things"),
                "u": type_spec("design", "d", "DSG", folder="more-things"),
            },
        }
    )
    reparsed = tomllib.loads(dumps_toml(config))
    assert reparsed == config.model_dump(mode="json")


def test_string_escaping_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    title = 'quoted " and \\ backslash\nand newline'
    config = Config.model_validate({"git": {"baseline_branch": title}})
    write_config(path, config)
    assert read_config(path) == config
    assert "\\n" in dumps_toml(config)
