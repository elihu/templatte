"""Typer application: global options on the callback, commands registered below."""

from pathlib import Path
from typing import Annotated

import typer

from templatte.cli.commands import check, deploy, genelatte, grind, migrate, pour, press
from templatte.cli.output import (
    AppContext,
    OutputHandler,
    color_enabled,
    configure_logging,
)

app = typer.Typer(
    name="templatte",
    help="Templatte: brew your configuration files from .latte templates. ☕",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode=None,
)


@app.callback()
def main(
    ctx: typer.Context,
    workspace: Annotated[
        Path,
        typer.Option(
            "--workspace",
            "-w",
            help="Root directory of the target workspace.",
            exists=True,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
        ),
    ] = Path("."),
    config_file: Annotated[
        Path,
        typer.Option(
            "--config-file",
            "-c",
            help="Values registry path, relative to the workspace (absolute honored).",
        ),
    ] = Path("templatte.toml"),
    profile: Annotated[
        str | None,
        typer.Option(
            "--profile",
            "-p",
            help="Target environment profile (e.g. dev, prod). [default: default]",
            show_default=False,
        ),
    ] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="Machine-readable JSON on stdout.")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Debug logging and tracebacks.")
    ] = False,
    no_color: Annotated[
        bool, typer.Option("--no-color", help="Disable ANSI colors (respects NO_COLOR).")
    ] = False,
) -> None:
    """Global options; they must precede the command."""
    configure_logging(verbose)
    ctx.obj = AppContext(
        workspace=workspace,
        config_file=config_file,
        profile=profile,
        out=OutputHandler(json_mode=json_output, color=color_enabled(no_color), verbose=verbose),
    )


app.command("genelatte")(genelatte.genelatte)
app.command("deploy")(deploy.deploy)
app.command("grind")(grind.grind)
app.command("press")(press.press)
app.command("pour")(pour.pour)
app.command("check")(check.check)
app.command("roast", hidden=True)(check.check)
app.command("migrate")(migrate.migrate)
