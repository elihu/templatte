"""Output handling: human (Rich) vs. machine (``--json``) rendering and error mapping.

Stream contract:

* ``--json``: stdout carries **exactly one JSON document** and nothing else.
  Banners, tables and spinners are suppressed; ``info``/``warn``/prompts go to stderr.
* human mode: results and ``info`` go to stdout; warnings, errors, prompts and
  spinners go to stderr.
"""

from __future__ import annotations

import dataclasses
import functools
import json
import logging
import os
import sys
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any, ParamSpec, TypeVar

import typer
from rich.console import Console, RenderableType
from rich.markup import escape
from rich.status import Status
from typer.exceptions import TyperException

from templatte.cli import console as theme
from templatte.core.exceptions import TemplatteError

P = ParamSpec("P")
R = TypeVar("R")

EXIT_GENERAL = 1
EXIT_INTERRUPTED = 130


def stdin_is_tty() -> bool:
    """Whether stdin is a terminal. Module-level so tests can monkeypatch it."""
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def color_enabled(no_color_flag: bool, environ: dict[str, str] | None = None) -> bool:
    """Color is off with ``--no-color`` or a non-empty ``NO_COLOR`` environment variable."""
    env = os.environ if environ is None else environ
    return not (no_color_flag or env.get("NO_COLOR"))


def to_jsonable(obj: Any) -> Any:
    """Deterministically convert dataclasses, paths and containers into JSON types."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, PurePath):
        return obj.as_posix()
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (set, frozenset)):
        return [to_jsonable(v) for v in sorted(obj, key=str)]
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if hasattr(obj, "unwrap"):  # tomlkit items
        return to_jsonable(obj.unwrap())
    return str(obj)


def dumps_json(payload: Any) -> str:
    return json.dumps(to_jsonable(payload), indent=2, sort_keys=False, ensure_ascii=False)


class OutputHandler:
    """Routes output to the right stream for the active mode."""

    def __init__(
        self,
        *,
        json_mode: bool = False,
        color: bool = True,
        verbose: bool = False,
        force_terminal: bool | None = None,
    ) -> None:
        self.json_mode = json_mode
        self.color = color
        self.verbose = verbose
        self.out: Console = theme.make_console(color=color, force_terminal=force_terminal)
        self.err: Console = theme.make_console(
            stderr=True, color=color, force_terminal=force_terminal
        )

    @property
    def human(self) -> Console:
        """Console for informational output (stderr under ``--json``)."""
        return self.err if self.json_mode else self.out

    # -- informational ---------------------------------------------------------------

    def show(self, renderable: RenderableType) -> None:
        """Banners, tables, diffs: human mode only (suppressed under ``--json``)."""
        if not self.json_mode:
            self.out.print(renderable)

    def banner(self, title: str) -> None:
        if not self.json_mode:
            theme.banner(self.out, title)

    def info(self, message: str) -> None:
        """Informational line; ``message`` may contain Rich markup (escape untrusted text)."""
        self.human.print(message)

    def success(self, message: str) -> None:
        self.human.print(f"[ok]✔[/] {escape(message)}")

    def warn(self, message: str) -> None:
        self.err.print(f"[warn]warning:[/] {escape(message)}")

    def status(self, message: str) -> Status:
        """Spinner on stderr (never stdout)."""
        return theme.status(self.err, message)

    # -- results ---------------------------------------------------------------------

    def emit(self, payload: dict[str, Any]) -> None:
        """Write the one JSON document to stdout (JSON mode only)."""
        stream = self.out.file
        stream.write(dumps_json(payload) + "\n")
        stream.flush()

    def error(self, exc: TemplatteError) -> None:
        if self.json_mode:
            self.emit(exc.to_dict())
            return
        self.err.print(f"[burnt]error:[/] {escape(exc.message)}")
        for key, value in exc.details.items():
            self.err.print(f"  [steam]{key}:[/] {escape(str(value))}")

    def unexpected(self, exc: BaseException) -> None:
        if self.json_mode:
            self.emit(
                {
                    "status": "error",
                    "exit_code": EXIT_GENERAL,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
            )
        else:
            self.err.print(f"[burnt]error:[/] {type(exc).__name__}: {escape(str(exc))}")
        if self.verbose:
            self.err.print(
                "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
                markup=False,
            )

    # -- prompts (always stderr) -----------------------------------------------------

    def confirm(self, text: str) -> bool:
        return typer.confirm(text, default=False, err=True)

    def prompt_secret(self, text: str) -> str:
        return typer.prompt(text.rstrip(": "), hide_input=True, err=True)


@dataclass
class AppContext:
    """Typed ``ctx.obj`` holding the global options."""

    workspace: Path
    config_file: Path
    profile: str | None
    out: OutputHandler

    @property
    def interactive(self) -> bool:
        """stdin is a TTY and ``--json`` is off."""
        return (not self.out.json_mode) and stdin_is_tty()

    def display_path(self, path: Path) -> str:
        """Workspace-relative POSIX when inside the workspace, else as given."""
        p = path if path.is_absolute() else self.workspace / path
        try:
            return p.relative_to(self.workspace).as_posix()
        except ValueError:
            return p.as_posix()


def configure_logging(verbose: bool) -> None:
    """DEBUG logging on stderr under ``--verbose``."""
    if verbose:
        logging.basicConfig(level=logging.DEBUG, stream=sys.stderr, force=True)


def result_payload(command: str, exit_code: int, **fields: Any) -> dict[str, Any]:
    """Success JSON skeleton: ``status`` is ``warning`` when the exit code is nonzero."""
    return {
        "status": "success" if exit_code == 0 else "warning",
        "command": command,
        "exit_code": exit_code,
        **fields,
    }


def guarded(fn: Callable[P, int | None]) -> Callable[P, None]:
    """Wrap a command: map exceptions to output + exit codes (the single mapping point).

    The command returns its exit code (``None`` means 0) and must take the
    ``typer.Context`` as a parameter named ``ctx``.
    """

    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> None:
        ctx: typer.Context = args[0] if args else kwargs["ctx"]  # type: ignore[assignment]
        app: AppContext = ctx.obj
        try:
            code = fn(*args, **kwargs)
        except (typer.Exit, typer.Abort, TyperException):
            raise  # click/typer usage errors keep exit 2 etc.
        except KeyboardInterrupt:
            app.out.err.print("[warn]Interrupted[/]")
            raise typer.Exit(EXIT_INTERRUPTED) from None
        except TemplatteError as exc:
            app.out.error(exc)
            raise typer.Exit(exc.exit_code) from None
        except Exception as exc:  # noqa: BLE001 - last-resort mapping to exit 1
            app.out.unexpected(exc)
            raise typer.Exit(EXIT_GENERAL) from None
        if code:
            raise typer.Exit(code)

    return wrapper
