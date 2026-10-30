"""``templatte grind``: delete concrete files that have a ``.latte`` template.

JSON shape (exit 0)::

    {"status", "command", "exit_code", "dry_run", "to_delete": [...], "deleted": [...],
     "backups": [...], "skipped_tracked": [...]}

Without ``--force`` and not interactive nothing is deleted and the command exits 2.
"""

from typing import Annotated

import typer
from rich.markup import escape

from templatte.cli import console as theme
from templatte.cli.output import AppContext, guarded, result_payload
from templatte.core.exceptions import UsageError
from templatte.core.services.cleaner import GrindResult
from templatte.core.services.cleaner import grind as grind_service


@guarded
def grind(
    ctx: typer.Context,
    force: Annotated[
        bool, typer.Option("--force", "-y", help="Delete without confirmation.")
    ] = False,
    force_tracked: Annotated[
        bool,
        typer.Option(
            "--force-tracked", help="Also delete Git-tracked files with uncommitted changes."
        ),
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="List files without deleting.")
    ] = False,
    backup: Annotated[
        bool, typer.Option("--backup", help="Copy each file to a .bak sibling before deleting.")
    ] = False,
) -> int:
    """Discard concrete config files that have templates (before you commit)."""
    app: AppContext = ctx.obj
    out = app.out

    def run(*, force_: bool) -> GrindResult:
        return grind_service(
            app.workspace,
            app.config_file,
            force=force_,
            force_tracked=force_tracked,
            dry_run=dry_run,
            backup=backup,
        )

    result = run(force_=force)
    if result.requires_confirmation:
        n = len(result.to_delete)
        if not app.interactive:
            raise UsageError(
                f"Grind would delete {n} file(s); nothing was deleted. Pass --force to proceed.",
                details={"to_delete": list(result.to_delete)},
            )
        if not out.confirm(f"Grind will delete {n} concrete configuration files. Proceed?"):
            raise typer.Abort()
        result = run(force_=True)

    if out.json_mode:
        out.emit(
            result_payload(
                "grind",
                result.exit_code,
                dry_run=result.dry_run,
                to_delete=result.to_delete,
                deleted=result.deleted,
                backups=result.backups,
                skipped_tracked=result.skipped_tracked,
            )
        )
        return result.exit_code

    out.banner("grind" + (" (dry run)" if result.dry_run else ""))
    if result.dry_run:
        for p in result.to_delete:
            out.info(f"  [warn]would delete[/] [path]{escape(p)}[/]")
    for p in result.deleted:
        out.info(f"  [ok]deleted[/] [path]{escape(p)}[/]")
    for p in result.backups:
        out.info(f"  [steam]backup:[/] [path]{escape(p)}[/]")
    for p in result.skipped_tracked:
        out.warn(f"'{p}' is tracked by Git with uncommitted changes; skipped (use --force-tracked)")
    out.show(
        theme.summary_table(
            "Grind summary",
            [
                ("Deleted", len(result.deleted)),
                ("Would delete", len(result.to_delete) if result.dry_run else 0),
                ("Backed up", len(result.backups)),
                ("Skipped (tracked)", len(result.skipped_tracked)),
            ],
        )
    )
    return result.exit_code
