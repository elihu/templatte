"""Round-trip fidelity matrix and fixed-point regression suite (Invariant 6).

This module is the executable documentation the MASTER_SPEC requires:

    "Every normalization permitted above must be covered by an explicit test
    in the fidelity matrix (`tests/unit/adapters/test_fidelity_matrix.py`)
    documenting the input, the normalized output, and the reason. A
    round-trip difference not present in that matrix is a bug, not a
    normalization."

Part 1 documents, one named test per case, every known *first-cycle*
`genelatte` -> `deploy` difference (and every case that is byte-for-byte),
using a positive assert when the input survives untouched and a negative
assert plus the exact normalized output when it does not. Nothing is left
implicit: if any of these behaviours changes, a test here fails.

Part 2 proves Invariant 6.c -- the exact fixed point -- for all five format
adapters, using fixtures that deliberately contain the gnarly inputs of
Part 1 so the proof is not trivial.

Assertions below were verified against the real adapters; they describe
current behaviour, not an ideal. Each negative assert names, in its docstring,
the entry of the Invariant 6 guarantee table that permits the difference.
"""

from __future__ import annotations

from typing import Any

import pytest

from templatte.adapters.env_adapter import EnvAdapter
from templatte.adapters.ini_adapter import IniAdapter
from templatte.adapters.json_adapter import JsonAdapter
from templatte.adapters.toml_adapter import TomlAdapter
from templatte.adapters.yaml_adapter import YamlAdapter


def _cycle(adapter: Any, source: str) -> str:
    """Run one full `genelatte` -> `deploy` cycle and return the deployed bytes."""
    values, template = adapter.extract_values(source)
    return adapter.render(template, values)


# ===========================================================================
# Part 1 -- Corpus of known first-cycle normalizations
# ===========================================================================

# --------------------------------------------------------------------------
# TOML: "Scalar lexical representation (radix, thousands separators,
# exponential notation, quote style) and internal array spacing normalization
# is permitted."
# --------------------------------------------------------------------------


def test_toml_single_quoted_string_is_normalized_to_double_quotes() -> None:
    """Literal strings lose their quote style: the registry stores a plain
    ``str`` and ``tomlkit.item()`` re-emits it as a basic (double-quoted)
    string. Permitted: "quote style" normalization.
    """
    adapter = TomlAdapter()
    source = "name = 'hello'\n"

    values, _ = adapter.extract_values(source)
    rendered = _cycle(adapter, source)

    assert values == {"name": "hello"}
    assert rendered != source
    assert rendered == 'name = "hello"\n'


def test_toml_thousands_separator_is_normalized_away() -> None:
    """``1_000_000`` parses to the int ``1000000``; the underscores are lexical
    only and are not stored. Permitted: "thousands separators".
    """
    adapter = TomlAdapter()
    source = "big = 1_000_000\n"

    values, _ = adapter.extract_values(source)
    rendered = _cycle(adapter, source)

    assert values == {"big": 1000000}
    assert rendered != source
    assert rendered == "big = 1000000\n"


def test_toml_hex_notation_is_normalized_to_decimal() -> None:
    """Radix is lexical: ``0xDEADBEEF`` round-trips as its decimal value.
    Permitted: "radix".
    """
    adapter = TomlAdapter()
    source = "mask = 0xDEADBEEF\n"

    values, _ = adapter.extract_values(source)
    rendered = _cycle(adapter, source)

    assert values == {"mask": 3735928559}
    assert rendered != source
    assert rendered == "mask = 3735928559\n"


def test_toml_binary_notation_is_normalized_to_decimal() -> None:
    """Same radix normalization for ``0b`` literals."""
    adapter = TomlAdapter()
    source = "b = 0b1010\n"

    values, _ = adapter.extract_values(source)
    rendered = _cycle(adapter, source)

    assert values == {"b": 10}
    assert rendered != source
    assert rendered == "b = 10\n"


def test_toml_exponential_notation_is_normalized_to_plain_float() -> None:
    """``1e3`` is a float; it is re-emitted in Python's ``repr`` form.
    Permitted: "exponential notation".
    """
    adapter = TomlAdapter()
    source = "f = 1e3\n"

    values, _ = adapter.extract_values(source)
    rendered = _cycle(adapter, source)

    assert values == {"f": 1000.0}
    assert rendered != source
    assert rendered == "f = 1000.0\n"


def test_toml_multiline_array_collapses_to_one_line() -> None:
    """A leaf array is extracted whole as a plain Python list, so its multiline
    layout (and trailing comma) is not preserved. Permitted: "internal array
    spacing normalization".
    """
    adapter = TomlAdapter()
    source = "x = [\n  1,\n  2,\n]\n"

    values, _ = adapter.extract_values(source)
    rendered = _cycle(adapter, source)

    assert values == {"x": [1, 2]}
    assert rendered != source
    assert rendered == "x = [1, 2]\n"


def test_toml_array_internal_spacing_is_normalized() -> None:
    """``[ 8000, 8001 ]`` loses the padding inside the brackets; element
    separators keep the canonical ``, ``. Permitted: "internal array spacing".
    """
    adapter = TomlAdapter()
    source = "ports = [ 8000, 8001 ]\n"

    values, _ = adapter.extract_values(source)
    rendered = _cycle(adapter, source)

    assert values == {"ports": [8000, 8001]}
    assert rendered != source
    assert rendered == "ports = [8000, 8001]\n"


def test_toml_multiline_string_stays_multiline() -> None:
    """Invariant 6.b: "a multiline string remains multiline". The placeholder
    is itself written with triple delimiters (``doc = \"\"\"{{ doc }}\"\"\"``), so
    the layout survives into the template and back out. The delimiters are
    canonicalised to ``\"\"\"`` and the newline that immediately follows the
    opening delimiter -- which TOML strips, so it carries no data -- is not
    re-emitted. Permitted: "quote style".
    """
    adapter = TomlAdapter()
    source = "doc = '''\nhello\n'''\n"

    values, template = adapter.extract_values(source)
    rendered = _cycle(adapter, source)

    assert values == {"doc": "hello\n"}
    assert template == 'doc = """{{ doc }}"""\n'
    assert rendered != source
    assert rendered == 'doc = """hello\n"""\n'
    assert _cycle(adapter, rendered) == rendered


def test_toml_inline_table_survives_round_trip() -> None:
    """Invariant 6.b: an inline table stays inline and byte-identical."""
    adapter = TomlAdapter()
    source = "pt = { x = 1, y = 2 }\n"

    values, _ = adapter.extract_values(source)
    rendered = _cycle(adapter, source)

    assert values == {"pt.x": 1, "pt.y": 2}
    assert rendered == source


def test_toml_offset_datetime_survives_round_trip() -> None:
    """Dates are native TOML types; tomlkit re-emits the exact same literal."""
    adapter = TomlAdapter()
    source = "dob = 1979-05-27T07:32:00-08:00\n"

    rendered = _cycle(adapter, source)

    assert rendered == source


# --------------------------------------------------------------------------
# JSON: "Non-ASCII escaping and numeric notation normalization is permitted."
# --------------------------------------------------------------------------


def test_json_exponential_notation_is_normalized_to_plain_float() -> None:
    """``1e3`` becomes the float ``1000.0``. Permitted: "numeric notation"."""
    adapter = JsonAdapter()
    source = '{"a": 1e3}'

    values, _ = adapter.extract_values(source)
    rendered = _cycle(adapter, source)

    assert values == {"a": 1000.0}
    assert rendered != source
    assert rendered == '{"a": 1000.0}'


def test_json_non_ascii_is_escaped_to_unicode_sequence() -> None:
    """``json.dumps`` defaults to ``ensure_ascii=True``, so ``café`` is
    re-emitted as ``caf\\u00e9``. Permitted: "non-ASCII escaping". The value
    itself is untouched, so 6.a holds.
    """
    adapter = JsonAdapter()
    source = '{"a": "caf\u00e9"}'

    values, _ = adapter.extract_values(source)
    rendered = _cycle(adapter, source)

    assert values == {"a": "caf\u00e9"}
    assert rendered != source
    assert rendered == '{"a": "caf\\u00e9"}'


def test_json_compact_document_with_consistent_separators_survives() -> None:
    """A one-line document whose separator style is uniform is byte-for-byte.

    The mixed-separator counter-case is documented by the next test.
    """
    adapter = JsonAdapter()
    source = '{"a": 1, "b": [1, 2, 3]}'

    rendered = _cycle(adapter, source)

    assert rendered == source


def test_json_mixed_separator_styles_are_unified() -> None:
    """``_detect_formatting`` derives a single item separator for the whole
    document, so a file that separates object members with ``, `` but array
    items with ``,`` is re-emitted with one style throughout. Permitted:
    "separator spacing ... the separator style of a document that mixes styles
    between object and array level is unified".
    """
    adapter = JsonAdapter()
    source = '{"a": 1, "b": [1,2,3]}'

    values, _ = adapter.extract_values(source)
    rendered = _cycle(adapter, source)

    assert values == {"a": 1, "b": [1, 2, 3]}
    assert rendered != source
    assert rendered == '{"a": 1, "b": [1, 2, 3]}'
    assert _cycle(adapter, rendered) == rendered


# --------------------------------------------------------------------------
# YAML: "quote-style and flow-sequence spacing normalization is permitted."
# --------------------------------------------------------------------------


def test_yaml_flow_sequence_internal_spacing_is_normalized() -> None:
    """Invariant 6.b: a leaf flow sequence stays in flow style. The template
    keeps the brackets around the placeholder (``a: ["{{ a }}"]``), so
    ``render`` restores the style; only the internal spacing is canonicalised
    to ``, ``. Permitted: "flow-sequence spacing normalization".
    """
    adapter = YamlAdapter()
    source = "a: [1,2,3]\n"

    values, template = adapter.extract_values(source)
    rendered = _cycle(adapter, source)

    assert values == {"a": [1, 2, 3]}
    assert template == 'a: ["{{ a }}"]\n'
    assert rendered != source
    assert rendered == "a: [1, 2, 3]\n"


def test_yaml_canonically_spaced_flow_sequence_survives_round_trip() -> None:
    """A flow sequence already written with canonical spacing is byte-for-byte."""
    adapter = YamlAdapter()
    source = "a: [1, 2, 3]\n"

    rendered = _cycle(adapter, source)

    assert rendered == source


def test_yaml_block_sequence_stays_in_block_style() -> None:
    """The flow flag is carried per sequence, not forced: a leaf sequence
    written as a block stays a block and is byte-for-byte.
    """
    adapter = YamlAdapter()
    source = "a:\n  - 1\n  - 2\n"

    values, template = adapter.extract_values(source)
    rendered = _cycle(adapter, source)

    assert values == {"a": [1, 2]}
    assert template == 'a: "{{ a }}"\n'
    assert rendered == source


def test_yaml_single_quoted_scalar_is_normalized_to_plain_scalar() -> None:
    """Quote style is NOT propagated through the registry: ``render`` rebuilds
    a harmless string as a ``PlainScalarString``, so ``'hi'`` comes back
    unquoted. Permitted explicitly by the table ("quote-style ...
    normalization is permitted"). Note this drops the quotes entirely rather
    than swapping their style.
    """
    adapter = YamlAdapter()
    source = "a: 'hi'\n"

    values, _ = adapter.extract_values(source)
    rendered = _cycle(adapter, source)

    assert values == {"a": "hi"}
    assert rendered != source
    assert rendered == "a: hi\n"


def test_yaml_inline_comment_column_is_not_preserved() -> None:
    """The comment text survives (6.b) but not its column: ruamel remembers the
    comment's original start column, computed against the placeholder line
    ``a: "{{ a }}"``, and pads to it when the shorter value is written back.
    """
    adapter = YamlAdapter()
    source = "a: 1  # inline\n"

    values, template = adapter.extract_values(source)
    rendered = _cycle(adapter, source)

    assert values == {"a": 1}
    assert template == 'a: "{{ a }}" # inline\n'
    assert rendered != source
    assert rendered == "a: 1         # inline\n"
    assert "# inline" in rendered


def test_yaml_merge_key_survives_round_trip() -> None:
    """Invariant 6.b: ``<<: *anchor`` is never expanded and the document is
    byte-for-byte. Keys inherited through the merge are extracted once, at the
    anchor's own definition.
    """
    adapter = YamlAdapter()
    source = (
        "defaults: &defaults\n"
        "  timeout: 30\n"
        "\n"
        "service:\n"
        "  <<: *defaults\n"
        "  name: api\n"
    )

    values, _ = adapter.extract_values(source)
    rendered = _cycle(adapter, source)

    assert values == {"defaults.timeout": 30, "service.name": "api"}
    assert rendered == source
    assert "<<: *defaults" in rendered


def test_yaml_flow_sequence_followed_by_blank_line_is_byte_for_byte() -> None:
    """Invariant 6.c (and 6.b): keeping the sequence in flow style keeps the
    blank line ruamel attaches to the key anchored where it was written, so the
    very first deploy is already byte-for-byte and the fixed point is exact.

    When the sequence was expanded to a block instead, that token was emitted
    between the key and the first item and then dropped on the next cycle, so
    the first two deploys differed.
    """
    adapter = YamlAdapter()
    source = "a: [1, 2]\n\nb: 1\n"

    rendered1 = _cycle(adapter, source)
    rendered2 = _cycle(adapter, rendered1)

    assert rendered1 == source
    assert rendered2 == rendered1


def test_yaml_comment_after_flow_sequence_is_preserved() -> None:
    """A whole-line comment following a leaf flow sequence keeps its position
    across every cycle (Invariant 6.b), for the same reason as above.
    """
    adapter = YamlAdapter()
    source = "a: [1, 2]\n# tail\nb: 1\n"

    rendered1 = _cycle(adapter, source)
    rendered2 = _cycle(adapter, rendered1)

    assert rendered1 == source
    assert rendered2 == rendered1
    assert "# tail" in rendered2


# --------------------------------------------------------------------------
# INI / .properties: "Byte-for-byte, except horizontal whitespace around
# separators and inline comments."
# --------------------------------------------------------------------------


def test_ini_horizontal_spacing_around_separator_survives_round_trip() -> None:
    """Better than the guarantee: the separator run (``=`` with its surrounding
    whitespace) is captured verbatim by the line regex and written back as-is,
    so even irregular padding is byte-for-byte.
    """
    adapter = IniAdapter()
    source = "[s]\nhost=localhost\nport   =   5432\n"

    values, _ = adapter.extract_values(source)
    rendered = _cycle(adapter, source)

    assert values == {"s.host": "localhost", "s.port": 5432}
    assert rendered == source


def test_ini_inline_comment_spacing_is_normalized_to_one_space() -> None:
    """The exempted case: the whitespace between the value and an inline
    comment is collapsed to a single space, for both ``;`` and ``#`` markers.
    The comment text and its position after the value are preserved.
    """
    adapter = IniAdapter()
    source = "[s]\nport = 5432    ; note\nname = x  # hash\n"

    values, _ = adapter.extract_values(source)
    rendered = _cycle(adapter, source)

    assert values == {"s.port": 5432, "s.name": "x"}
    assert rendered != source
    assert rendered == "[s]\nport = 5432 ; note\nname = x # hash\n"


def test_ini_full_line_comments_and_sections_survive_round_trip() -> None:
    """Lines that are not ``key = value`` (section headers, blank lines,
    whole-line comments) are copied through untouched.
    """
    adapter = IniAdapter()
    source = "; header comment\n# another\n\n[section]\nk = v\n"

    rendered = _cycle(adapter, source)

    assert rendered == source


# --------------------------------------------------------------------------
# .env: "Byte-for-byte."
# --------------------------------------------------------------------------


def test_env_comments_and_double_quoted_values_survive_round_trip() -> None:
    """Byte-for-byte as the table demands: comments, blank lines, bare values
    and double-quoted values with whitespace all come back unchanged.
    """
    adapter = EnvAdapter()
    source = (
        "# Application configuration\n"
        "APP_NAME=templatte\n"
        "PORT=8080\n"
        "\n"
        '# Secrets\nSECRET_KEY="super secret passphrase"\n'
    )

    values, _ = adapter.extract_values(source)
    rendered = _cycle(adapter, source)

    assert values == {
        "APP_NAME": "templatte",
        "PORT": 8080,
        "SECRET_KEY": "super secret passphrase",
    }
    assert rendered == source


def test_env_export_prefixed_line_survives_round_trip_unextracted() -> None:
    """``export VAR=1`` does not match the adapter's ``KEY=value`` regex, so the
    line is passed through verbatim into the template and back out. It is
    byte-for-byte, but the value is deliberately *not* templatised -- recorded
    here so the day ``export`` becomes supported this test flags the change.
    """
    adapter = EnvAdapter()
    source = "export VAR=1\n"

    values, template = adapter.extract_values(source)
    rendered = _cycle(adapter, source)

    assert values == {}
    assert template == source
    assert rendered == source


def test_env_single_quoted_value_is_normalized_to_double_quotes() -> None:
    """The exempted case: quote style is not carried through the registry --
    the value is stored unquoted and re-emitted with the shell-safe
    double-quoting rule because it contains a space. Permitted: "the quote
    style of a value".
    """
    adapter = EnvAdapter()
    source = "A='hi there'\n"

    values, _ = adapter.extract_values(source)
    rendered = _cycle(adapter, source)

    assert values == {"A": "hi there"}
    assert rendered != source
    assert rendered == 'A="hi there"\n'


def test_env_inline_comment_spacing_is_normalized_to_one_space() -> None:
    """As in INI, the whitespace between the value and a trailing ``#`` comment
    is collapsed to a single space by the line reconstruction. The comment text
    and its position after the value are preserved. Permitted: "horizontal
    whitespace before an inline comment".
    """
    adapter = EnvAdapter()
    source = "A=1  # note\n"

    values, _ = adapter.extract_values(source)
    rendered = _cycle(adapter, source)

    assert values == {"A": 1}
    assert rendered != source
    assert rendered == "A=1 # note\n"


# ===========================================================================
# Part 2 -- Invariant 6.c: exact fixed point, all five formats
# ===========================================================================

# Every fixture below deliberately contains at least one case from Part 1, so
# the fixed-point proof exercises the normalizations rather than trivially
# stable input.

FIXTURE_TOML = """# Master TOML File
title = 'TOML Example'
big = 1_000_000
mask = 0xDEADBEEF
ratio = 1e3

[owner]
dob = 1979-05-27T07:32:00-08:00
pt = { x = 1, y = 2 }

[database]
enabled = true
ports = [ 8000, 8001 ]
matrix = [
  1,
  2,
]
cpu = 79.5 # CPU temperature target

[[servers]]
ip = "10.0.0.1" # Frontend server
role = 'frontend'
"""

FIXTURE_YAML = """# Main application configuration
defaults: &defaults
  timeout: 30

server:
  <<: *defaults
  features: [toml, yaml, json]
  host: '0.0.0.0'
  port: 8080  # inline comment

replicas:
  - host: db1.internal
    port: 5432
  - host: db2.internal
    port: 5433
"""

FIXTURE_JSON = '{"name": "caf\u00e9", "ratio": 1e3, "ports": [8000, 8001]}'

FIXTURE_INI = """# Database settings
[database]
host=localhost
port   =   5432    ; default postgres port
enabled = true
ports = 8000,8001,8002

[service]
name = my_service  # inline hash comment
"""

FIXTURE_ENV = """# Application configuration
APP_NAME=templatte
PORT=8080
export LEGACY_VAR=untouched

# Secrets
SECRET_KEY='super secret passphrase'
NOTE=plain  # trailing note
"""

FIXED_POINT_CASES = [
    pytest.param(TomlAdapter, FIXTURE_TOML, id="toml"),
    pytest.param(YamlAdapter, FIXTURE_YAML, id="yaml"),
    pytest.param(JsonAdapter, FIXTURE_JSON, id="json"),
    pytest.param(IniAdapter, FIXTURE_INI, id="ini"),
    pytest.param(EnvAdapter, FIXTURE_ENV, id="env"),
]


class TestInvariant6cFixedPoint:
    """Invariant 6.c: from the first `deploy` onward, every subsequent
    `genelatte` -> `deploy` cycle is byte-for-byte identical.
    """

    @pytest.mark.parametrize(("adapter_cls", "source"), FIXED_POINT_CASES)
    def test_second_cycle_is_byte_for_byte_identical(
        self, adapter_cls: type, source: str
    ) -> None:
        adapter = adapter_cls()

        extracted1, template1 = adapter.extract_values(source)
        rendered1 = adapter.render(template1, extracted1)
        extracted2, template2 = adapter.extract_values(rendered1)
        rendered2 = adapter.render(template2, extracted2)

        # The deployed file stops changing after the first cycle.
        assert rendered2 == rendered1
        # And so does the .latte template, so `git diff` stays empty.
        assert template2 == template1
        # The registry is stable too (6.a survives the normalization).
        assert extracted2 == extracted1

    @pytest.mark.parametrize(("adapter_cls", "source"), FIXED_POINT_CASES)
    def test_third_cycle_still_identical(self, adapter_cls: type, source: str) -> None:
        """`deploy` run N times always produces the same byte stream."""
        adapter = adapter_cls()

        current = _cycle(adapter, source)
        stable = _cycle(adapter, current)

        for _ in range(3):
            stable = _cycle(adapter, stable)
            assert stable == current

    @pytest.mark.parametrize(("adapter_cls", "source"), FIXED_POINT_CASES)
    def test_first_cycle_preserves_registry_values(
        self, adapter_cls: type, source: str
    ) -> None:
        """Invariant 6.a: the normalization of cycle one changes bytes, never
        the data model -- the registry extracted from the deployed file equals
        the one extracted from the original.
        """
        adapter = adapter_cls()

        values1, _ = adapter.extract_values(source)
        rendered1 = _cycle(adapter, source)
        values2, _ = adapter.extract_values(rendered1)

        assert values2 == values1
