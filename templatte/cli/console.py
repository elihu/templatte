"""Rich console factory, barista theme and reusable renderables.

Everything here is presentational: functions take the ``Console`` they should
write to, which the :class:`~templatte.cli.output.OutputHandler` chooses (stdout
in human mode, stderr when ``--json`` owns stdout).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from rich.console import Console
from rich.status import Status
from rich.syntax import Syntax
from rich.table import Table
from rich.theme import Theme

from templatte import __version__

#: Coffee-named styles (a light barista touch; see MASTER_SPEC §2).
THEME = Theme(
    {
        "espresso": "bold dark_orange3",
        "crema": "tan",
        "latte": "wheat1",
        "steam": "grey70",
        "ok": "green",
        "warn": "yellow",
        "burnt": "bold red",
        "path": "cyan",
    }
)

SPINNER = "dots"


def make_console(
    *, stderr: bool = False, color: bool = True, force_terminal: bool | None = None
) -> Console:
    """Build a Console writing to the (current) stdout or stderr.

    With ``color=False`` no ANSI escape sequence is ever emitted.
    """
    return Console(
        stderr=stderr,
        theme=THEME,
        no_color=not color,
        color_system="auto" if color else None,
        force_terminal=force_terminal,
        highlight=False,
        soft_wrap=True,
    )


def banner(console: Console, title: str) -> None:
    """A one-line header, e.g. ``☕ Templatte 2.0.0 · deploy``."""
    console.print(f"[espresso]☕ Templatte {__version__}[/] [steam]·[/] [crema]{title}[/]")


def status(console: Console, message: str) -> Status:
    """A (not yet started) spinner; call ``start()``/``stop()`` or use as a context manager."""
    return console.status(f"[crema]{message}[/]", spinner=SPINNER)


def summary_table(title: str, rows: Iterable[tuple[str, object]]) -> Table:
    """Two-column key/value summary."""
    table = Table(title=title, title_style="espresso", show_header=False, box=None, pad_edge=False)
    table.add_column(style="crema", no_wrap=True)
    table.add_column(style="latte", overflow="fold")
    for key, value in rows:
        table.add_row(key, str(value))
    return table


def paths_table(title: str, columns: Sequence[str], rows: Iterable[Sequence[str]]) -> Table:
    """A table whose cells are (mostly) paths."""
    table = Table(title=title, title_style="espresso", header_style="crema")
    for i, name in enumerate(columns):
        table.add_column(name, style="path" if i == 0 else "latte", overflow="fold")
    for row in rows:
        table.add_row(*row)
    return table


def diff_syntax(diff: str) -> Syntax:
    """Syntax-highlighted unified diff."""
    return Syntax(diff, "diff", theme="ansi_dark", word_wrap=True)
