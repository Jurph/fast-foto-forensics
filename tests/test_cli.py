"""Tests for the fff command-line interface."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fast_foto_forensics.main import main
from fast_foto_forensics.vision import OllamaVisionBackend


def test_cli_run_command_creates_run_directory() -> None:
    """The run subcommand should execute the pipeline and report the output path."""
    input_dir = Path(".tmp") / "cli-case"
    output_dir = Path(".tmp") / "cli-output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "001-wrt54g-router.jpg").write_bytes(b"router")

    exit_code = main(
        ["run", str(input_dir), "--output", str(output_dir), "--run-label", "cli-demo"]
    )

    assert exit_code == 0
    assert (output_dir / "cli-demo" / "reports" / "report.md").exists()


def test_cli_render_and_tag_commands_rebuild_artifacts() -> None:
    """Render and tag should recreate report and sidecars from stored artifacts."""
    input_dir = Path(".tmp") / "cli-render-case"
    output_dir = Path(".tmp") / "cli-render-output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    image_path = input_dir / "001-wrt54g-router.jpg"
    image_path.write_bytes(b"router")

    assert (
        main(["run", str(input_dir), "--output", str(output_dir), "--run-label", "render-demo"])
        == 0
    )

    run_dir = output_dir / "render-demo"
    report_path = run_dir / "reports" / "report.md"
    sidecar_path = image_path.with_suffix(".jpg.fff-tags.json")
    report_path.unlink()
    sidecar_path.unlink()

    assert main(["render", str(run_dir)]) == 0
    assert main(["tag", str(run_dir)]) == 0

    assert report_path.exists()
    assert sidecar_path.exists()


def test_cli_compose_command_writes_summary() -> None:
    """Compose should merge the identities from multiple runs into one summary."""
    input_dir = Path(".tmp") / "cli-compose-case"
    output_dir = Path(".tmp") / "cli-compose-output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "001-wrt54g-router.jpg").write_bytes(b"router")

    assert (
        main(["run", str(input_dir), "--output", str(output_dir), "--run-label", "compose-a"]) == 0
    )
    assert (
        main(["run", str(input_dir), "--output", str(output_dir), "--run-label", "compose-b"]) == 0
    )

    composed_path = output_dir / "combined.md"

    assert (
        main(
            [
                "compose",
                str(output_dir / "compose-a"),
                str(output_dir / "compose-b"),
                "--output",
                str(composed_path),
            ]
        )
        == 0
    )

    assert composed_path.exists()
    assert "Linksys WRT54G" in composed_path.read_text(encoding="utf-8")


def test_cli_run_with_ollama_backend_flag() -> None:
    """--vision-backend=ollama should select OllamaVisionBackend."""
    input_dir = Path(".tmp") / "cli-ollama-case"
    output_dir = Path(".tmp") / "cli-ollama-output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "001-wrt54g-router.jpg").write_bytes(b"router")

    # Patch OllamaVisionBackend.extract to behave like FilenameVisionBackend
    # so we don't need a real Ollama server
    from fast_foto_forensics.vision import FilenameVisionBackend

    filename_backend = FilenameVisionBackend()
    with patch.object(OllamaVisionBackend, "extract", side_effect=filename_backend.extract):
        exit_code = main(
            [
                "run",
                str(input_dir),
                "--output",
                str(output_dir),
                "--run-label",
                "ollama-demo",
                "--vision-backend",
                "ollama",
            ]
        )

    assert exit_code == 0
    assert (output_dir / "ollama-demo" / "reports" / "report.md").exists()
