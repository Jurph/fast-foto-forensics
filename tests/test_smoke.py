"""Basic smoke tests for the template project."""

from fast_foto_forensics.main import main


def test_main_runs(capsys) -> None:
    """Calling the entry point without arguments should show the top-level help."""
    exit_code = main([])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Fast Foto Forensics" in captured.out
    assert "run" in captured.out
