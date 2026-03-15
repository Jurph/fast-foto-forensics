"""Argparse-based command line interface for Fast Foto Forensics."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from fast_foto_forensics.pipeline import (
    compose_runs,
    rerender_run,
    rewrite_sidecars,
    run_pipeline,
)
from fast_foto_forensics.vision import FilenameVisionBackend, OllamaVisionBackend, VisionBackend
from fast_foto_forensics.search import (
    DuckDuckGoSearchProvider,
    SearchProvider,
    StaticSearchProvider,
)
from fast_foto_forensics.synthesis import HeuristicSynthesisBackend


def build_parser() -> argparse.ArgumentParser:
    """Create the top-level CLI parser."""
    parser = argparse.ArgumentParser(prog="fff", description="Fast Foto Forensics")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Process a folder of evidence")
    run_parser.add_argument("input_path")
    run_parser.add_argument("--output", required=True)
    run_parser.add_argument("--run-label", default="run-001")
    run_parser.add_argument("--profile", default="default")
    run_parser.add_argument(
        "--vision-backend",
        choices=("filename", "ollama"),
        default="filename",
        help="Vision backend: filename (heuristic) or ollama (real model)",
    )
    run_parser.add_argument("--vision-model", default="qwen2.5vl:7b", help="Ollama model name")
    run_parser.add_argument("--search-provider", choices=("static", "duckduckgo"), default="static")
    run_parser.add_argument("--proxy")
    run_parser.add_argument("--offline", action="store_true")

    worker_parser = subparsers.add_parser("worker", help="Run a queue worker")
    worker_parser.add_argument("queue_name", choices=("vision", "search"))

    render_parser = subparsers.add_parser("render", help="Rebuild a report from a prior run")
    render_parser.add_argument("run_dir")

    compose_parser = subparsers.add_parser("compose", help="Merge multiple runs into one summary")
    compose_parser.add_argument("run_dirs", nargs="+")
    compose_parser.add_argument("--output", required=True)

    tag_parser = subparsers.add_parser("tag", help="Regenerate sidecar tags from a prior run")
    tag_parser.add_argument("run_dir")
    return parser


def run_cli(argv: list[str] | None = None) -> int:
    """Execute the CLI for the provided argument vector."""
    parser = build_parser()
    raw_args = sys.argv[1:] if argv is None else argv
    if not raw_args:
        parser.print_help()
        return 0

    args = parser.parse_args(raw_args)

    if args.command == "run":
        vision_backend: VisionBackend
        if args.vision_backend == "ollama":
            vision_backend = OllamaVisionBackend(model=args.vision_model)
        else:
            vision_backend = FilenameVisionBackend()

        search_provider: SearchProvider
        if args.offline or args.search_provider == "static":
            search_provider = StaticSearchProvider(fixtures={})
        else:
            search_provider = DuckDuckGoSearchProvider(proxy_url=args.proxy)
        result = run_pipeline(
            input_path=Path(args.input_path),
            output_root=Path(args.output),
            run_label=args.run_label,
            vision_backend=vision_backend,
            search_provider=search_provider,
            synthesis_backend=HeuristicSynthesisBackend(),
        )
        print(f"Run complete: {result.run_dir}")
        print(f"Report: {result.report_path}")
        print(f"Sidecars: {len(result.sidecar_paths)} written")
        return 0

    if args.command == "worker":
        print(f"Worker ready: {args.queue_name}")
        return 0

    if args.command == "render":
        report_path = rerender_run(Path(args.run_dir))
        print(f"Report rebuilt: {report_path}")
        return 0

    if args.command == "tag":
        sidecar_paths = rewrite_sidecars(Path(args.run_dir))
        print(f"Regenerated {len(sidecar_paths)} sidecars")
        return 0

    if args.command == "compose":
        output_path = compose_runs([Path(run_dir) for run_dir in args.run_dirs], Path(args.output))
        print(f"Composition written: {output_path}")
        return 0

    parser.error(f"Unsupported subcommand '{args.command}'.")
    return 2
