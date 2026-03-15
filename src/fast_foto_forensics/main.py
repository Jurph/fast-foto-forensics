"""CLI entry point for the project."""

from __future__ import annotations

from fast_foto_forensics.cli import run_cli


def main(argv: list[str] | None = None) -> int:
    """Run the Fast Foto Forensics CLI."""
    return run_cli(argv)


if __name__ == "__main__":
    raise SystemExit(main())
