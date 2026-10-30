"""``templatte pour``: decrypt ``<config>.enc`` back into the registry.

JSON shape (exit 0)::

    {"status", "command", "exit_code", "output", "backup", "encrypted_removed"}
"""

import sys
from pathlib import Path
from typing import Annotated

import typer

from templatte.cli.output import AppContext, guarded, result_payload
from templatte.core.services.crypto import DEFAULT_ENV_VAR
from templatte.core.services.crypto import pour as pour_service


@guarded
def pour(
    ctx: typer.Context,
    input_: Annotated[
        Path | None,
        typer.Option(
            "--input",
            "-i",
            help="Encrypted input. [default: <config-file>.enc]",
            show_default=False,
        ),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output", "-o", help="Plaintext output. [default: <config-file>]", show_default=False
        ),
    ] = None,
    passphrase: Annotated[
        str | None,
        typer.Option(
            "--passphrase",
            help="Passphrase (discouraged: visible in ps and shell history).",
        ),
    ] = None,
    passphrase_file: Annotated[
        Path | None, typer.Option("--passphrase-file", help="File containing the passphrase.")
    ] = None,
    passphrase_env: Annotated[
        str, typer.Option("--passphrase-env", help="Environment variable holding the passphrase.")
    ] = DEFAULT_ENV_VAR,
    keep_encrypted: Annotated[
        bool,
        typer.Option(
            "--keep-encrypted/--no-keep-encrypted", help="Keep the .enc file after decrypting."
        ),
    ] = True,
    force: Annotated[
        bool, typer.Option("--force", "-y", help="Overwrite an existing output file.")
    ] = False,
    backup: Annotated[
        bool,
        typer.Option("--backup", help="Back up the output file before overwriting (with --force)."),
    ] = False,
) -> int:
    """Unseal the encrypted registry."""
    app: AppContext = ctx.obj
    out = app.out
    if passphrase is not None:
        out.warn(
            "--passphrase is visible to other processes (ps) and shell history; "
            "prefer --passphrase-file or stdin."
        )
    spinner = out.status("Deriving key (PBKDF2)...")

    def prompt(text: str) -> str:
        spinner.stop()
        try:
            return out.prompt_secret(text)
        finally:
            spinner.start()

    spinner.start()
    try:
        result = pour_service(
            app.workspace,
            app.config_file,
            input_,
            output,
            passphrase=passphrase,
            passphrase_file=passphrase_file,
            env_var=passphrase_env,
            stdin=sys.stdin,
            prompt=prompt if app.interactive else None,
            keep_encrypted=keep_encrypted,
            force=force,
            backup=backup,
        )
    finally:
        spinner.stop()

    if out.json_mode:
        out.emit(
            result_payload(
                "pour",
                result.exit_code,
                output=result.output,
                backup=result.backup,
                encrypted_removed=result.encrypted_removed,
            )
        )
        return result.exit_code
    out.banner("pour")
    out.success(f"Restored registry to {result.output}")
    if result.backup:
        out.info(f"  [steam]backup:[/] [path]{result.backup}[/]")
    if result.encrypted_removed:
        out.info("  [steam]Encrypted file removed.[/]")
    return result.exit_code
