"""Unit tests for the output handler and error serialization."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from templatte.cli.output import (
    OutputHandler,
    color_enabled,
    dumps_json,
    result_payload,
    to_jsonable,
)
from templatte.core.exceptions import MissingValuesError, TemplatteError, UsageError


def test_json_mode_stdout_is_exactly_one_document(capsys: pytest.CaptureFixture[str]) -> None:
    h = OutputHandler(json_mode=True)
    h.banner("deploy")
    h.show("a table")
    h.info("hello")
    h.warn("careful [x]")
    h.success("done")
    h.emit(result_payload("deploy", 0, files=[Path("a/b.toml")]))
    out, err = capsys.readouterr()
    assert json.loads(out) == {
        "status": "success",
        "command": "deploy",
        "exit_code": 0,
        "files": ["a/b.toml"],
    }
    assert out.endswith("}\n")
    assert "hello" in err
    assert "careful [x]" in err
    assert "a table" not in out + err


def test_human_mode_streams(capsys: pytest.CaptureFixture[str]) -> None:
    h = OutputHandler(json_mode=False)
    h.info("to stdout")
    h.show("table on stdout")
    h.warn("to stderr")
    h.error(UsageError("bad usage", details={"file": "x"}))
    out, err = capsys.readouterr()
    assert "to stdout" in out
    assert "table on stdout" in out
    assert "to stderr" not in out
    assert "to stderr" in err
    assert "bad usage" in err
    assert "file" in err
    assert "bad usage" not in out


def test_error_json_shape(capsys: pytest.CaptureFixture[str]) -> None:
    OutputHandler(json_mode=True).error(MissingValuesError("config/app.toml", ["a.b", "c"]))
    out, err = capsys.readouterr()
    doc = json.loads(out)
    assert doc["status"] == "error"
    assert doc["exit_code"] == 3
    assert doc["error_type"] == "MissingValuesError"
    assert doc["details"]["missing_keys"] == ["a.b", "c"]
    assert err == ""


def test_error_markup_brackets_survive(capsys: pytest.CaptureFixture[str]) -> None:
    OutputHandler().error(MissingValuesError("f", ["k"]))
    assert "[k]" in capsys.readouterr().err


def test_unexpected_error_json_and_traceback(capsys: pytest.CaptureFixture[str]) -> None:
    try:
        raise RuntimeError("boom")
    except RuntimeError as exc:
        OutputHandler(json_mode=True).unexpected(exc)
        out, err = capsys.readouterr()
        assert json.loads(out) == {
            "status": "error",
            "exit_code": 1,
            "error_type": "RuntimeError",
            "message": "boom",
        }
        assert "Traceback" not in err
        OutputHandler(json_mode=True, verbose=True).unexpected(exc)
        assert "Traceback" in capsys.readouterr().err


def test_to_jsonable_dataclass_path_and_sets() -> None:
    @dataclass(frozen=True)
    class Inner:
        p: Path

    @dataclass(frozen=True)
    class Outer:
        inner: Inner
        items: tuple[str, ...]
        tags: frozenset[str]
        mapping: dict[str, Path]

    obj = Outer(Inner(Path("a/b")), ("x", "y"), frozenset({"b", "a"}), {"k": Path("c")})
    assert to_jsonable(obj) == {
        "inner": {"p": "a/b"},
        "items": ["x", "y"],
        "tags": ["a", "b"],
        "mapping": {"k": "c"},
    }


def test_dumps_json_deterministic_unsorted_unicode() -> None:
    text = dumps_json({"z": 1, "a": "café ☕"})
    assert text.index('"z"') < text.index('"a"')
    assert "café ☕" in text
    assert text.startswith("{\n  ")


def test_result_payload_warning_status() -> None:
    assert result_payload("check", 5)["status"] == "warning"
    assert result_payload("check", 0)["status"] == "success"


def test_color_enabled_rules() -> None:
    assert color_enabled(False, {})
    assert not color_enabled(True, {})
    assert not color_enabled(False, {"NO_COLOR": "1"})
    assert color_enabled(False, {"NO_COLOR": ""})


def test_no_ansi_when_color_disabled(capsys: pytest.CaptureFixture[str]) -> None:
    plain = OutputHandler(color=False, force_terminal=True)
    plain.info("[espresso]hi[/]")
    plain.warn("w")
    plain.error(TemplatteError("e"))
    out, err = capsys.readouterr()
    assert "hi" in out
    assert "\x1b" not in out + err
    OutputHandler(color=True, force_terminal=True).info("[espresso]hi[/]")
    assert "\x1b[" in capsys.readouterr().out
