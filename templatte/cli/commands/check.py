"""``templatte check`` (hidden alias ``roast``): missing values, drift and git leaks.

JSON shape (exit 0, 3 or 5; ``"status": "warning"`` when nonzero)::

    {"status", "command", "exit_code", "strict",
     "summary": {"errors", "warnings"},
     "findings": [{"kind", "severity", "path", "message", "missing_keys", "diff"}]}
"""

from typing import Annotated

import typer
from rich.markup import escape

from templatte.cli import console as theme
from templatte.cli.output import AppContext, guarded, result_payload
from templatte.core.services.checker import ERROR
from templatte.core.services.checker import check as check_service


@guarded
def check(
    ctx: typer.Context,
    strict: Annotated[
        bool, typer.Option("--strict", help="Treat non-drift warnings as errors.")
    ] = False,
    check_git: Annotated[
        bool,
        typer.Option(
            "--check-git/--no-check-git", help="Verify concrete files are untracked and ignored."
        ),
    ] = True,
) -> int:
    """Taste-test the workspace: coverage, drift and git leaks."""
    app: AppContext = ctx.obj
    out = app.out
    result = check_service(
        app.workspace, app.config_file, app.profile, strict=strict, check_git=check_git
    )
    errors = sum(1 for f in result.findings if f.severity == ERROR)
    warnings = len(result.findings) - errors
    if out.json_mode:
        out.emit(
            result_payload(
                "check",
                result.exit_code,
                strict=strict,
                summary={"errors": errors, "warnings": warnings},
                findings=result.findings,
            )
        )
        return result.exit_code

    out.banner("check")
    if not result.findings:
        out.success("All clear: every cup matches its recipe.")
        return result.exit_code
    out.show(
        theme.paths_table(
            "Findings",
            ["Path", "Kind", "Severity", "Message"],
            [(escape(f.path), f.kind, f.severity, escape(f.message)) for f in result.findings],
        )
    )
    for f in result.findings:
        if f.diff:
            out.info(f"[crema]{escape(f.path)}[/]")
            out.show(theme.diff_syntax(f.diff))
    return result.exit_code
