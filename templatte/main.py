"""Package entry point (``[project.scripts]`` -> ``templatte.main:app``)."""

from templatte.cli.app import app

__all__ = ["app"]

if __name__ == "__main__":
    app()
