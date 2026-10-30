"""``templatte genelatte``: discover configs, write ``.latte`` templates and the registry.

JSON shape (exit 0, or 3 with ``"status": "warning"`` when files need manual review)::

    {"status", "command", "exit_code", "workspace", "dry_run", "scanned_files",
     "generated_templates": [...], "skipped_existing": [...], "manual_review": [...],
     "values_file", "total_keys_extracted", "gitignore_updated", "warnings": [...]}
"""

from typing import Annotated

import typer
from rich.markup import escape

from templatte.cli import console as theme
from templatte.cli.output import AppContext, guarded, result_payload
from templatte.core.services.generator import generate
from templatte.core.services.scanner import DEFAULT_FORMATS


@guarded
def genelatte(
    ctx: typer.Context,
    formats: Annotated[
        list[str] | None,
        typer.Option(
            "--format",
            "-f",
            help=f"Formats to discover (repeatable). [default: {', '.join(DEFAULT_FORMATS)}]",
            show_default=False,
        ),
    ] = None,
    include: Annotated[
        list[str] | None,
        typer.Option("--include", "-i", help="Extra glob patterns to include (repeatable)."),
    ] = None,
    exclude: Annotated[
        list[str] | None,
        typer.Option("--exclude", "-e", help="Extra glob patterns to exclude (repeatable)."),
    ] = None,
    force_include: Annotated[
        bool, typer.Option("--force-include", help="Let --include match hard-denylisted files.")
    ] = False,
    force: Annotated[
        bool, typer.Option("--force", "-y", help="Overwrite existing .latte files.")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Show what would be created without writing.")
    ] = False,
    no_gitignore_update: Annotated[
        bool, typer.Option("--no-gitignore-update", help="Do not update the workspace .gitignore.")
    ] = False,
) -> int:
    """Grind your configs into .latte templates and a values registry."""
    app: AppContext = ctx.obj
    result = generate(
        app.workspace,
        app.config_file,
        formats=tuple(formats) if formats else DEFAULT_FORMATS,
        include=include or (),
        exclude=exclude or (),
        force_include=force_include,
        force=force,
        dry_run=dry_run,
        update_gitignore=not no_gitignore_update,
    )
    warnings = [
        f"'{p}' already exists; skipped (use --force to overwrite)" for p in result.skipped_existing
    ] + [
        f"'{p}' contains another template engine's delimiters; needs manual review"
        for p in result.manual_review
    ]
    values_file = app.display_path(app.config_file)
    out = app.out
    if out.json_mode:
        out.emit(
            result_payload(
                "genelatte",
                result.exit_code,
                workspace=app.workspace,
                dry_run=result.dry_run,
                scanned_files=result.files_scanned,
                generated_templates=result.templates_created,
                skipped_existing=result.skipped_existing,
                manual_review=result.manual_review,
                values_file=values_file,
                total_keys_extracted=result.keys_extracted,
                gitignore_updated=result.gitignore_updated,
                warnings=warnings,
            )
        )
        return result.exit_code

    out.banner("genelatte" + (" (dry run)" if dry_run else ""))
    for latte in result.templates_created:
        out.info(f"  [ok]+[/] [path]{escape(latte)}[/]")
    out.show(
        theme.summary_table(
            "Brew summary",
            [
                ("Workspace", app.workspace),
                ("Files scanned", result.files_scanned),
                (
                    "Templates " + ("planned" if dry_run else "created"),
                    len(result.templates_created),
                ),
                ("Keys extracted", result.keys_extracted),
                ("Values file", values_file),
            ],
        )
    )
    for w in warnings:
        out.warn(w)
    if dry_run:
        out.info("[steam]Dry run: nothing was written.[/]")
    return result.exit_code
