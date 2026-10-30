<!-- Target branch must be `develop`. See CONTRIBUTING.md. -->

## Summary

<!-- What does this change and why? -->

## TASK-ID

<!-- e.g. TASK-602, or "none" for a contribution outside the roadmap. -->

## Verification output

<!-- Paste the output of:
uv run ruff check .
uv run ruff format --check templatte tests
uv run pytest
Do not paste secrets or real configuration values. -->

```
```

## Checklist

- [ ] This PR targets `develop` and its commits follow Conventional Commits (`<type>(<scope>): <subject>`).
- [ ] No `templatte.toml`, `.env`, `.bak` backup or other concrete configuration file is staged (check `git status` and `git diff --cached --stat`).
- [ ] Fixtures and examples contain dummy values only, no real secrets.
- [ ] Tests were added or updated, and the verification commands above pass.
- [ ] This is not a security vulnerability (those go through [SECURITY.md](../SECURITY.md)).
