"""Unit tests for workspace discovery."""

from __future__ import annotations

from pathlib import Path

from templatte.core.services.scanner import scan_workspace


def make(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")


def paths(result) -> list[str]:  # type: ignore[no-untyped-def]
    return [c.path for c in result.candidates]


def test_default_whitelist(tmp_path: Path) -> None:
    make(
        tmp_path,
        {
            ".env": "A=1\n",
            "prod.env": "A=1\n",
            ".env.local": "A=1\n",
            "config/app.toml": "a = 1\n",
            "config/deep/x.yaml": "a: 1\n",
            "settings.json": '{"a": 1}\n',
            "random.toml": "a = 1\n",
            "src/other.json": "{}\n",
        },
    )
    r = scan_workspace(tmp_path, ["toml", "yaml", "json", "ini", "env"])
    assert paths(r) == [
        ".env",
        ".env.local",
        "config/app.toml",
        "config/deep/x.yaml",
        "prod.env",
        "settings.json",
    ]
    fmt = {c.path: c.format for c in r.candidates}
    assert fmt["config/app.toml"] == "toml" and fmt[".env"] == "env"


def test_include_adds_files(tmp_path: Path) -> None:
    make(tmp_path, {"random.toml": "a = 1\n", "other.toml": "a = 1\n"})
    r = scan_workspace(tmp_path, ["toml"], include=["random.toml"])
    assert paths(r) == ["random.toml"]


def test_exclude(tmp_path: Path) -> None:
    make(tmp_path, {"config/a.toml": "a = 1\n", "config/skip/b.toml": "a = 1\n"})
    r = scan_workspace(tmp_path, ["toml"], exclude=["config/skip/**"])
    assert paths(r) == ["config/a.toml"]


def test_denylist_blocks_include_unless_forced(tmp_path: Path) -> None:
    make(tmp_path, {"pyproject.toml": "a = 1\n", "config/ok.toml": "a = 1\n"})
    r = scan_workspace(tmp_path, ["toml"], include=["*.toml"])
    assert paths(r) == ["config/ok.toml"]
    r = scan_workspace(tmp_path, ["toml"], include=["*.toml"], force_include=True)
    assert paths(r) == ["config/ok.toml", "pyproject.toml"]


def test_force_include_only_lifts_included_files(tmp_path: Path) -> None:
    make(tmp_path, {"config/Cargo.toml": "a = 1\n"})
    # Matched by the default whitelist only, so force_include must not lift the denylist.
    assert paths(scan_workspace(tmp_path, ["toml"], force_include=True)) == []


def test_latte_and_docker_compose_denied(tmp_path: Path) -> None:
    make(tmp_path, {"config/a.toml.latte": "a = 1\n", "docker-compose.yml": "a: 1\n"})
    r = scan_workspace(tmp_path, ["toml", "yaml"], include=["*.latte", "*.yml"], force_include=True)
    assert paths(r) == ["docker-compose.yml"]


def test_standing_excludes_not_overridable(tmp_path: Path) -> None:
    make(
        tmp_path,
        {
            ".git/config.toml": "a = 1\n",
            ".venv/settings.toml": "a = 1\n",
            "node_modules/x/settings.json": "{}\n",
            "dist/settings.json": "{}\n",
            "__pycache__/settings.json": "{}\n",
            "templatte.toml": "version = 1\n",
            "templatte.toml.enc": "{}\n",
            "settings.toml": "a = 1\n",
        },
    )
    r = scan_workspace(
        tmp_path,
        ["toml", "json"],
        include=["**/*.toml", "**/*.json", "templatte.toml*", ".git/**", "dist/**"],
        force_include=True,
    )
    assert paths(r) == ["settings.toml"]


def test_format_filter(tmp_path: Path) -> None:
    make(tmp_path, {"config/a.toml": "a = 1\n", "config/b.json": "{}\n", "config/c.txt": "x\n"})
    assert paths(scan_workspace(tmp_path, ["json"])) == ["config/b.json"]
    assert paths(scan_workspace(tmp_path, [])) == []


def test_foreign_delimiters_manual_review(tmp_path: Path) -> None:
    make(
        tmp_path,
        {
            "config/helm.yaml": "name: {{ .Values.name }}\n",
            "config/gha.yaml": "x: ${{ secrets.X }}\n",
            "config/ok.yaml": "x: 1\n",
        },
    )
    r = scan_workspace(tmp_path, ["yaml"])
    assert paths(r) == ["config/ok.yaml"]
    assert r.manual_review == ("config/gha.yaml", "config/helm.yaml")


def test_custom_delimiters(tmp_path: Path) -> None:
    make(
        tmp_path,
        {
            "config/helm.yaml": "name: {{ .Values.name }}\n",
            "config/erb.yaml": "name: <% x %>\n",
        },
    )
    r = scan_workspace(tmp_path, ["yaml"], open_tag="<%", close_tag="%>")
    assert paths(r) == ["config/helm.yaml"]
    assert r.manual_review == ("config/erb.yaml",)


def test_non_utf8_skipped(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "bad.toml").write_bytes(b"a = '\xff\xfe'\n")
    r = scan_workspace(tmp_path, ["toml"])
    assert r.candidates == () and r.manual_review == ()


def test_gitignore_not_applied(tmp_path: Path) -> None:
    make(tmp_path, {".gitignore": "config/a.toml\n", "config/a.toml": "a = 1\n"})
    assert paths(scan_workspace(tmp_path, ["toml"])) == ["config/a.toml"]


def test_deterministic(tmp_path: Path) -> None:
    make(tmp_path, {f"config/{n}.toml": "a = 1\n" for n in "zyxabc"})
    first = scan_workspace(tmp_path, ["toml"])
    assert paths(first) == sorted(paths(first))
    assert scan_workspace(tmp_path, ["toml"]) == first
