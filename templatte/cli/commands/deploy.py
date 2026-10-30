"""``templatte deploy``: render ``.latte`` templates into concrete files.

JSON shape (exit 0)::

    {"status", "command", "exit_code", "dry_run",
     "target_files": [{"template", "destination", "action"}],
     "missing_keys": [], "backups": [...], "diffs": {dest: unified_diff}}   # diffs only with --diff

``action`` is ``create | overwrite | unchanged | skip``; under ``--dry-run`` the mutating
ones become ``would_create | would_overwrite | would_skip`` (``unchanged`` stays).
Missing values abort with the standard error document (exit 3) and nothing is written.
"""

from pathlib import Path
from typing import Annotated

import typer
from rich.markup import escape

from templatte.cli import console as theme
from templatte.cli.output import AppContext, guarded, result_payload
from templatte.core.exceptions import UsageError
from templatte.core.services.deployer import DeployResult
from templatte.core.services.deployer import deploy as deploy_service


def _targets(result: DeployResult) -> list[dict[str, str]]:
    pre = "would_" if result.dry_run else ""
    rows = (
        [(p, pre + "create") for p in result.created]
        + [(p, pre + "overwrite") for p in result.overwritten]
        + [(p, "unchanged") for p in result.unchanged]
        + [(p, pre + "skip") for p in result.skipped_existing]
    )
    return [
        {"template": dest + ".latte", "destination": dest, "action": action}
        for dest, action in sorted(rows)
    ]


@guarded
def deploy(
    ctx: typer.Context,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Report changes without writing.")
    ] = False,
    diff: Annotated[
        bool, typer.Option("--diff", help="Show unified diffs against existing files.")
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", "-y", help="Overwrite existing concrete files without asking."),
    ] = False,
    backup: Annotated[
        bool, typer.Option("--backup", help="Back up each overwritten file (with --force).")
    ] = False,
    file: Annotated[
        Path | None,
        typer.Option("--file", "-f", help="Deploy only this .latte file."),
    ] = None,
) -> int:
    """Render .latte templates into concrete configuration files."""
    app: AppContext = ctx.obj
    out = app.out

    def run(*, dry: bool, force_: bool, backup_: bool) -> DeployResult:
        return deploy_service(
            app.workspace,
            app.config_file,
            app.profile,
            dry_run=dry,
            diff=diff,
            force=force_,
            backup=backup_,
            file=file,
        )

    if dry_run:
        result = run(dry=True, force_=force, backup_=False)
    elif force:
        result = run(dry=False, force_=True, backup_=backup)
    else:
        plan = run(dry=True, force_=False, backup_=False)  # plan first: write nothing yet
        proceed_force = False
        if plan.skipped_existing:
            n = len(plan.skipped_existing)
            if not app.interactive:
                raise UsageError(
                    f"Deploy would overwrite {n} existing file(s); nothing was written. "
                    "Pass --force to overwrite.",
                    details={"would_overwrite": list(plan.skipped_existing)},
                )
            if not out.confirm(f"Deploy will overwrite {n} existing files. Proceed?"):
                raise typer.Abort()
            proceed_force = True
        result = run(dry=False, force_=proceed_force, backup_=backup and proceed_force)

    targets = _targets(result)
    if out.json_mode:
        payload = result_payload(
            "deploy",
            result.exit_code,
            dry_run=result.dry_run,
            target_files=targets,
            missing_keys=[],
            backups=result.backups,
        )
        if diff:
            payload["diffs"] = result.diffs
        out.emit(payload)
        return result.exit_code

    out.banner("deploy" + (" (dry run)" if result.dry_run else ""))
    if targets:
        out.show(
            theme.paths_table(
                "Serve summary",
                ["Destination", "Action"],
                [(escape(t["destination"]), t["action"]) for t in targets],
            )
        )
    else:
        out.info("[steam]No templates found.[/]")
    for path, text in result.diffs.items():
        out.info(f"[crema]{escape(path)}[/]")
        out.show(theme.diff_syntax(text))
    for b in result.backups:
        out.info(f"  [steam]backup:[/] [path]{escape(b)}[/]")
    return result.exit_code
