"""``templatte press``: encrypt the registry into ``<config>.enc`` (AES-256-GCM).

JSON shape (exit 0)::

    {"status", "command", "exit_code", "output", "plain_removed"}
"""

import sys
from pathlib import Path
from typing import Annotated

import typer

from templatte.cli.output import AppContext, guarded, result_payload
from templatte.core.services.crypto import DEFAULT_ENV_VAR
from templatte.core.services.crypto import press as press_service


@guarded
def press(
    ctx: typer.Context,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Encrypted output file. [default: <config-file>.enc]",
            show_default=False,
        ),
    ] = None,
    passphrase: Annotated[
        str | None,
        typer.Option(
            "--passphrase",
            help="Passphrase (discouraged: visible in ps and shell history; prefer "
            "--passphrase-file or stdin).",
        ),
    ] = None,
    passphrase_file: Annotated[
        Path | None, typer.Option("--passphrase-file", help="File containing the passphrase.")
    ] = None,
    passphrase_env: Annotated[
        str, typer.Option("--passphrase-env", help="Environment variable holding the passphrase.")
    ] = DEFAULT_ENV_VAR,
    keep_plain: Annotated[
        bool, typer.Option("--keep-plain", help="Keep the unencrypted registry.")
    ] = False,
    force: Annotated[
        bool, typer.Option("--force", "-y", help="Overwrite an existing output file.")
    ] = False,
) -> int:
    """Seal the values registry with a passphrase."""
    app: AppContext = ctx.obj
    out = app.out
    if passphrase is not None:
        out.warn(
            "--passphrase is visible to other processes (ps) and shell history; "
            "prefer --passphrase-file or stdin."
        )
    spinner = out.status("Deriving key (PBKDF2)...")

    def prompt(text: str) -> str:
        spinner.stop()  # never draw a spinner over a prompt
        try:
            return out.prompt_secret(text)
        finally:
            spinner.start()

    spinner.start()
    try:
        result = press_service(
            app.workspace,
            app.config_file,
            output,
            passphrase=passphrase,
            passphrase_file=passphrase_file,
            env_var=passphrase_env,
            stdin=sys.stdin,
            prompt=prompt if app.interactive else None,
            keep_plain=keep_plain,
            force=force,
        )
    finally:
        spinner.stop()

    if out.json_mode:
        out.emit(
            result_payload(
                "press",
                result.exit_code,
                output=result.output,
                plain_removed=result.plain_removed,
            )
        )
        return result.exit_code
    out.banner("press")
    out.success(f"Sealed registry into {result.output}")
    if result.plain_removed:
        out.info("  [steam]Plaintext registry removed.[/]")
    return result.exit_code
