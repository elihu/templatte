"""Unit tests for YAML and JSON format adapters."""

import json
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from templatte.adapters.json_adapter import JsonAdapter
from templatte.adapters.yaml_adapter import YamlAdapter
from templatte.core.exceptions import ConfigSyntaxError, MissingValuesError

SAMPLE_YAML = """# Main application configuration
server:
  host: 0.0.0.0 # Listen on all interfaces
  port: 8080

database:
  enabled: true
  replicas:
    - host: db1.internal
      port: 5432
    - host: db2.internal
      port: 5433
"""

SAMPLE_JSON = """{
  "app": {
    "name": "templatte",
    "version": "0.2.0",
    "port": 8080,
    "debug": true,
    "features": [
      "toml",
      "yaml",
      "json"
    ]
  }
}
"""


def test_yaml_adapter_can_handle() -> None:
    adapter = YamlAdapter()
    assert adapter.can_handle(Path("config.yaml")) is True
    assert adapter.can_handle(Path("config.yml")) is True
    assert adapter.can_handle(Path("config.yaml.latte")) is True
    assert adapter.can_handle(Path("config.json")) is False


def test_yaml_adapter_roundtrip() -> None:
    adapter = YamlAdapter()
    values, template = adapter.extract_values(SAMPLE_YAML)

    assert values["server.host"] == "0.0.0.0"
    assert values["server.port"] == 8080
    assert values["database.enabled"] is True
    # A sequence of mappings is indexed element by element (TOML AoT convention)
    assert values["database.replicas[0].host"] == "db1.internal"
    assert values["database.replicas[0].port"] == 5432

    # Template contains quoted placeholders
    assert '"{{ server.host }}"' in template

    rendered = adapter.render(template, values)
    # Check that comment is preserved
    assert "# Listen on all interfaces" in rendered
    # Re-extracting from rendered output yields identical values
    re_values, _ = adapter.extract_values(rendered)
    assert re_values == values


def test_yaml_adapter_errors() -> None:
    adapter = YamlAdapter()
    with pytest.raises(ConfigSyntaxError):
        adapter.extract_values("server:\n  port: [broken\n")

    _, template = adapter.extract_values(SAMPLE_YAML)
    with pytest.raises(MissingValuesError):
        adapter.render(template, {"server.port": 8080})


def test_json_adapter_can_handle() -> None:
    adapter = JsonAdapter()
    assert adapter.can_handle(Path("package.json")) is True
    assert adapter.can_handle(Path("app.json.latte")) is True
    assert adapter.can_handle(Path("app.yaml")) is False


def test_json_adapter_roundtrip() -> None:
    adapter = JsonAdapter()
    values, template = adapter.extract_values(SAMPLE_JSON)

    assert values["app.name"] == "templatte"
    assert values["app.port"] == 8080
    assert values["app.debug"] is True
    # A scalar array is one registry value under its dot-path, not indexed keys
    assert values["app.features"] == ["toml", "yaml", "json"]
    assert not any(k.startswith("app.features[") for k in values)
    assert '"features": "{{ app.features }}"' in template

    rendered = adapter.render(template, values)
    assert json.loads(rendered) == json.loads(SAMPLE_JSON)
    assert rendered == SAMPLE_JSON


def test_json_adapter_compact_byte_fidelity_consistent_separators() -> None:
    """Byte-for-byte fidelity holds for compact JSON when the item/key separator
    style is consistent across the whole document (same separators at both the
    object and array level). This is not a general guarantee; see the xfail
    below for the case where separator style is mixed.
    """
    adapter = JsonAdapter()

    # Compact single-line with spaces, consistent throughout
    compact_with_spaces = '{"a": 1, "b": [1, 2, 3]}'
    vals, tpl = adapter.extract_values(compact_with_spaces)
    rendered = adapter.render(tpl, vals)
    assert rendered == compact_with_spaces

    # Compact single-line without spaces, consistent throughout
    compact_no_spaces = '{"a":1,"b":[1,2,3]}'
    vals2, tpl2 = adapter.extract_values(compact_no_spaces)
    rendered2 = adapter.render(tpl2, vals2)
    assert rendered2 == compact_no_spaces


@pytest.mark.xfail(
    reason=(
        "_detect_formatting() detects a single item separator for the whole "
        "document; it cannot reproduce a document that mixes separator styles "
        "between object level and array level. This is a normalization the "
        "Invariant 6 table permits for JSON, not a bug: the unified output and "
        "its fixed point are asserted by "
        "test_json_mixed_separator_styles_are_unified in the fidelity matrix."
    ),
    strict=True,
)
def test_json_adapter_compact_mixed_separators_not_byte_fidelity() -> None:
    adapter = JsonAdapter()

    mixed = '{"a": 1, "b": [1,2,3]}'
    vals, tpl = adapter.extract_values(mixed)
    rendered = adapter.render(tpl, vals)
    assert rendered == mixed


def test_json_adapter_errors() -> None:
    adapter = JsonAdapter()
    with pytest.raises(ConfigSyntaxError):
        adapter.extract_values('{"invalid": json,}')

    _, template = adapter.extract_values(SAMPLE_JSON)
    with pytest.raises(MissingValuesError):
        adapter.render(template, {"app.name": "templatte"})


# --- Array schema: scalar arrays vs arrays of objects (MASTER_SPEC §5 / §6.3) ---


def test_yaml_scalar_list_is_single_registry_value() -> None:
    adapter = YamlAdapter()
    source = "features:\n  - alpha\n  - beta\n  - gamma\n"

    values, template = adapter.extract_values(source)

    assert values == {"features": ["alpha", "beta", "gamma"]}
    assert template == 'features: "{{ features }}"\n'
    assert adapter.render(template, values) == source


def test_yaml_nested_scalar_list_is_single_registry_value() -> None:
    """A list of lists of scalars is still a leaf array (spec §5 `database.data`)."""
    adapter = YamlAdapter()
    source = "data:\n  - - delta\n    - phi\n  - - 3.14\n"

    values, template = adapter.extract_values(source)

    assert values == {"data": [["delta", "phi"], [3.14]]}
    assert template == 'data: "{{ data }}"\n'
    # Round-trip preserves the values (ruamel re-indents nested sequences)
    re_values, _ = adapter.extract_values(adapter.render(template, values))
    assert re_values == values


def test_yaml_list_of_mappings_is_indexed() -> None:
    adapter = YamlAdapter()
    source = "servers:\n  - ip: 10.0.0.1\n    role: frontend\n  - ip: 10.0.0.2\n    role: backend\n"

    values, template = adapter.extract_values(source)

    assert values == {
        "servers[0].ip": "10.0.0.1",
        "servers[0].role": "frontend",
        "servers[1].ip": "10.0.0.2",
        "servers[1].role": "backend",
    }
    assert '"{{ servers[0].ip }}"' in template
    assert adapter.render(template, values) == source


def test_yaml_scalar_list_inside_list_of_mappings() -> None:
    """The leaf-array rule applies recursively inside indexed elements."""
    adapter = YamlAdapter()
    source = "servers:\n  - ip: 10.0.0.1\n    tags:\n      - a\n      - b\n"

    values, template = adapter.extract_values(source)

    assert values == {"servers[0].ip": "10.0.0.1", "servers[0].tags": ["a", "b"]}
    assert adapter.render(template, values) == source


def test_yaml_mixed_list_is_indexed_per_element() -> None:
    adapter = YamlAdapter()
    source = "mixed:\n  - k: v\n  - plain\n"

    values, template = adapter.extract_values(source)

    assert values == {"mixed[0].k": "v", "mixed[1]": "plain"}
    assert adapter.render(template, values) == source


def test_json_scalar_list_is_single_registry_value() -> None:
    adapter = JsonAdapter()
    source = '{\n  "features": [\n    "alpha",\n    "beta"\n  ]\n}\n'

    values, template = adapter.extract_values(source)

    assert values == {"features": ["alpha", "beta"]}
    assert template == '{\n  "features": "{{ features }}"\n}\n'
    rendered = adapter.render(template, values)
    # The placeholder string is replaced by a real JSON array, not a string
    assert json.loads(rendered)["features"] == ["alpha", "beta"]
    assert rendered == source


def test_json_nested_scalar_list_is_single_registry_value() -> None:
    adapter = JsonAdapter()
    source = '{"data": [["delta", "phi"], [3.14]], "n": 1}'

    values, template = adapter.extract_values(source)

    assert values == {"data": [["delta", "phi"], [3.14]], "n": 1}
    assert template == '{"data": "{{ data }}", "n": "{{ n }}"}'
    assert adapter.render(template, values) == source


def test_json_compact_single_key_array_keeps_values_not_bytes() -> None:
    """Known limitation of the separator heuristic, unchanged in nature by the
    array schema: collapsing an array into one placeholder can leave the template
    with no ``", "`` to detect, so a compact document whose only separators came
    from that array re-serializes without the spaces. Values are unaffected.
    """
    adapter = JsonAdapter()
    source = '{"ports": [8000, 8001]}'

    values, template = adapter.extract_values(source)
    rendered = adapter.render(template, values)

    assert values == {"ports": [8000, 8001]}
    assert json.loads(rendered) == json.loads(source)
    assert rendered == '{"ports": [8000,8001]}'


def test_json_list_of_objects_is_indexed() -> None:
    adapter = JsonAdapter()
    source = (
        "{\n"
        '  "servers": [\n'
        "    {\n"
        '      "ip": "10.0.0.1",\n'
        '      "tags": [\n'
        '        "a"\n'
        "      ]\n"
        "    },\n"
        "    {\n"
        '      "ip": "10.0.0.2",\n'
        '      "tags": []\n'
        "    }\n"
        "  ]\n"
        "}\n"
    )

    values, template = adapter.extract_values(source)

    assert values == {
        "servers[0].ip": "10.0.0.1",
        "servers[0].tags": ["a"],
        "servers[1].ip": "10.0.0.2",
        "servers[1].tags": [],
    }
    assert '"{{ servers[0].ip }}"' in template
    assert adapter.render(template, values) == source


def test_json_mixed_list_is_indexed_per_element() -> None:
    adapter = JsonAdapter()
    source = '{"mixed": [{"k": "v"}, "plain"]}'

    values, template = adapter.extract_values(source)

    assert values == {"mixed[0].k": "v", "mixed[1]": "plain"}
    assert adapter.render(template, values) == source


def test_yaml_merge_keys_are_not_expanded() -> None:
    """Invariant 6.b: ``<<: *anchor`` survives the cycle and is never inlined.

    Keys inherited through the merge are deliberately NOT templatised in the
    consuming mapping: they are extracted once at the anchor's own definition
    (``defaults.*``) and keep resolving through the merge. A key the mapping
    overrides explicitly (``retries``) is still its own key and is extracted.
    """
    adapter = YamlAdapter()
    source = (
        "defaults: &defaults\n"
        "  timeout: 30\n"
        "  retries: 3\n"
        "\n"
        "service:\n"
        "  <<: *defaults\n"
        "  name: api\n"
        "  retries: 5\n"
    )

    values, template = adapter.extract_values(source)

    # Merged-only keys are not duplicated into `service`.
    assert values == {
        "defaults.timeout": 30,
        "defaults.retries": 3,
        "service.name": "api",
        "service.retries": 5,
    }
    assert "<<: *defaults" in template
    assert "service.timeout" not in template

    rendered = adapter.render(template, values)

    assert "<<: *defaults" in rendered
    assert rendered == source

    reparsed = YAML(typ="safe").load(rendered)
    # timeout resolves through the anchor, not as a literal key of `service`.
    assert reparsed["service"]["timeout"] == 30
    assert reparsed["service"]["retries"] == 5
