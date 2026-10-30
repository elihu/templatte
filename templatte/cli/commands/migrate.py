"""``templatte migrate``: upgrade a pre-2.0 registry (and its templates) in place.

JSON shape (exit 0)::

    {"status", "command", "exit_code", "dry_run", "nothing_to_migrate", "registry",
     "files": [{"path", "format", "keys", "secrets", "template_rewritten"}],
     "templates_rewritten": [...], "backups": [...]}

Without ``--force`` (and not ``--dry-run``) the CLI confirms interactively, or exits 2.
"""

from typing import Annotated

import typer
from rich.markup import escape

from templatte.cli import console as theme
from templatte.cli.output import AppContext, guarded, result_payload
from templatte.core.exceptions import UsageError
from templatte.core.services.migrator import MigrateResult
from templatte.core.services.migrator import migrate as migrate_service


@guarded
def migrate(
    ctx: typer.Context,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Report the migration without writing.")
    ] = False,
    force: Annotated[
        bool, typer.Option("--force", "-y", help="Migrate in place without confirmation.")
    ] = False,
    backup: Annotated[
        bool, typer.Option("--backup", help="Back up the registry and rewritten templates first.")
    ] = False,
) -> int:
    """Upgrade an older templatte.toml to the current schema."""
    app: AppContext = ctx.obj
    out = app.out

    def run(*, force_: bool) -> MigrateResult:
        return migrate_service(
            app.workspace, app.config_file, dry_run=dry_run, force=force_, backup=backup
        )

    result = run(force_=force)
    if result.requires_confirmation:
        n = len(result.templates_rewritten)
        if not app.interactive:
            raise UsageError(
                f"Migration would rewrite '{result.registry}' and {n} template(s); nothing was "
                "written. Pass --force to proceed (or --dry-run to preview)."
            )
        if not out.confirm(
            f"Migrate '{result.registry}' and rewrite {n} templates in place. Proceed?"
        ):
            raise typer.Abort()
        result = run(force_=True)

    if out.json_mode:
        out.emit(
            result_payload(
                "migrate",
                result.exit_code,
                dry_run=result.dry_run,
                nothing_to_migrate=result.nothing_to_migrate,
                registry=result.registry,
                files=result.files,
                templates_rewritten=result.templates_rewritten,
                backups=result.backups,
            )
        )
        return result.exit_code

    out.banner("migrate" + (" (dry run)" if result.dry_run else ""))
    if result.nothing_to_migrate:
        out.success(f"Nothing to migrate: '{result.registry}' is already current.")
        return result.exit_code
    out.show(
        theme.paths_table(
            "Migration",
            ["File", "Format", "Keys", "Template"],
            [
                (
                    escape(f.path),
                    f.format,
                    str(f.keys),
                    "rewritten" if f.template_rewritten else "unchanged",
                )
                for f in result.files
            ],
        )
    )
    for b in result.backups:
        out.info(f"  [steam]backup:[/] [path]{escape(b)}[/]")
    if result.dry_run:
        out.info("[steam]Dry run: nothing was written.[/]")
    else:
        out.success(f"Migrated '{result.registry}' to schema version 1.")
    return result.exit_code
