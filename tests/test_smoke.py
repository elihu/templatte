"""Smoke test ensuring templatte package can be imported."""

import templatte


def test_import_templatte() -> None:
    """Verify that templatte can be imported and exports version."""
    assert templatte is not None
    assert templatte.__version__ == "0.2.0"
