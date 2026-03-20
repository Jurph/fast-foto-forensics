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
from fast_foto_forensics.search import (
    DDGSSearchProvider,
    DuckDuckGoSearchProvider,
    SearchProvider,
    SearXNGSearchProvider,
    StaticSearchProvider,
)
from fast_foto_forensics.synthesis import (
    HeuristicSynthesisBackend,
    OllamaDatasheetSynthesisBackend,
    RemoteDatasheetSynthesisBackend,
    SynthesisBackend,
)
from fast_foto_forensics.vision import FilenameVisionBackend, OllamaVisionBackend, VisionBackend


_DEFAULT_MODEL = "qwen2.5vl:7b"


def _add_model_arg(parser: argparse.ArgumentParser) -> None:
    """Add the shared --model flag used by both vision and synthesis."""
    parser.add_argument(
        "--model",
        default=_DEFAULT_MODEL,
        help=f"Ollama model for vision and synthesis (default: {_DEFAULT_MODEL})",
    )


def _add_vision_args(parser: argparse.ArgumentParser) -> None:
    """Add shared --vision-backend and --vision-model flags to a subparser."""
    parser.add_argument(
        "--vision-backend",
        choices=("filename", "ollama"),
        default="filename",
        help="Vision backend: filename (heuristic) or ollama (real model)",
    )
    parser.add_argument("--vision-model", default=None, help=argparse.SUPPRESS)


def _resolve_model(args: argparse.Namespace) -> str:
    """Return the effective Ollama model name from CLI flags."""
    return getattr(args, "model", None) or _DEFAULT_MODEL


def _build_vision_backend(args: argparse.Namespace) -> VisionBackend:
    """Instantiate the vision backend selected by CLI flags."""
    if args.vision_backend == "ollama":
        model = args.vision_model or _resolve_model(args)
        return OllamaVisionBackend(model=model)
    return FilenameVisionBackend()


def _add_synthesis_args(parser: argparse.ArgumentParser) -> None:
    """Add synthesis backend flags to a subparser."""
    parser.add_argument(
        "--synthesis-backend",
        choices=("ollama", "remote", "heuristic"),
        default="ollama",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--synthesis-model", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--api-base", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--api-key", default=None, help=argparse.SUPPRESS)


def _build_synthesis_backend(args: argparse.Namespace) -> SynthesisBackend:
    """Instantiate the synthesis backend selected by CLI flags."""
    if args.synthesis_backend == "remote":
        model = args.synthesis_model or "gpt-4o-mini"
        return RemoteDatasheetSynthesisBackend(
            model=model,
            api_base=args.api_base,
            api_key=args.api_key,
        )
    if args.synthesis_backend == "heuristic":
        return HeuristicSynthesisBackend()
    model = args.synthesis_model or _resolve_model(args)
    return OllamaDatasheetSynthesisBackend(model=model)


def build_parser() -> argparse.ArgumentParser:
    """Create the top-level CLI parser."""
    parser = argparse.ArgumentParser(prog="fff", description="Fast Foto Forensics")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- scan: quick inventory table from a directory of images ---
    scan_parser = subparsers.add_parser(
        "scan",
        help="Scan a folder of images and print an inventory table",
    )
    scan_parser.add_argument("input_path", help="Directory (or single file) to scan")
    _add_model_arg(scan_parser)
    _add_vision_args(scan_parser)
    scan_parser.add_argument(
        "--format",
        choices=("table", "csv", "json"),
        default="table",
        help="Output format (default: rich table)",
    )

    # --- run: full pipeline ---
    run_parser = subparsers.add_parser("run", help="Process a folder of evidence")
    run_parser.add_argument("input_path")
    run_parser.add_argument("--output", required=True)
    run_parser.add_argument("--run-label", default="run-001")
    run_parser.add_argument("--profile", default="default")
    _add_model_arg(run_parser)
    _add_vision_args(run_parser)
    _add_synthesis_args(run_parser)
    run_parser.add_argument(
        "--search-provider",
        choices=("static", "duckduckgo", "ddgs", "searxng"),
        default="ddgs",
    )
    run_parser.add_argument(
        "--searxng-url", default="http://localhost:8888", help="SearXNG instance URL"
    )
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


def _run_scan(args: argparse.Namespace) -> int:
    """Scan images and print an inventory table.

    Calls the vision backend directly (not through the full pipeline) so
    we get access to VisionResult.vendor and .object_class, which don't
    survive the enrichment step onto EvidenceObservation.

    All fields are passed through from the backend as-is — no heuristic
    overrides.  If the backend returns empty fields, they show as blanks.
    """
    import logging

    from fast_foto_forensics.ingest import ingest_path
    from fast_foto_forensics.vision import VisionExtractionError

    logger = logging.getLogger(__name__)
    vision_backend = _build_vision_backend(args)
    observations = list(ingest_path(Path(args.input_path)))

    rows: list[dict[str, str]] = []
    for obs in observations:
        try:
            result = vision_backend.extract(obs)
        except VisionExtractionError as exc:
            logger.warning("Skipping %s: %s", obs.source_path, exc)
            continue

        rows.append(
            {
                "filename": Path(obs.source_path).name,
                "function": result.object_class or "",
                "manufacturer": result.vendor or "",
                "model_no": ", ".join(result.candidate_identifiers),
                "serial": ", ".join(result.serial_numbers),
            }
        )

    if not rows:
        print("No supported images found.")
        return 0

    output_format = getattr(args, "format", "table")

    if output_format == "json":
        import json

        print(json.dumps(rows, indent=2))
        return 0

    if output_format == "csv":
        import csv
        import io

        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
        print(buf.getvalue(), end="")
        return 0

    # Default: rich table
    try:
        from rich.console import Console
        from rich.table import Table
    except ImportError:
        # Graceful fallback if rich is not installed
        header = (
            f"{'Filename':<40} {'Function':<18} {'Manufacturer':<16} "
            f"{'Model No.':<16} {'Serial / ID'}"
        )
        print(header)
        print("-" * len(header))
        for row in rows:
            print(
                f"{row['filename']:<40} {row['function']:<18} "
                f"{row['manufacturer']:<16} {row['model_no']:<16} {row['serial']}"
            )
        return 0

    table = Table(title="Evidence Inventory", show_lines=True)
    table.add_column("Filename", style="cyan", no_wrap=True)
    table.add_column("Function / Role", style="green")
    table.add_column("Manufacturer", style="yellow")
    table.add_column("Model No.", style="magenta")
    table.add_column("Serial / Property ID", style="red")

    for row in rows:
        table.add_row(
            row["filename"],
            row["function"],
            row["manufacturer"],
            row["model_no"],
            row["serial"],
        )

    console = Console()
    console.print(table)
    return 0


def _print_run_summary(result) -> None:
    """Print a concise post-run summary to the console."""

    # Header
    status = "PARTIAL" if result.failures else "OK"
    print(f"\n=== Run {status} ===")
    print(f"  Images processed : {result.observation_count}")
    print(f"  Clusters found   : {result.cluster_count}")
    print(f"  Sidecars written : {len(result.sidecar_paths)}")

    # Per-cluster results
    if result.cluster_summaries:
        print()
        print("  Identified items:")
        for cs in result.cluster_summaries:
            conf = f"{cs.confidence:.0%}" if cs.confidence else "n/a"
            hits_label = f"{cs.search_hits} hits" if cs.search_hits else "no hits"
            print(f"    - {cs.identity}  ({cs.evidence_count} images, {hits_label}, conf {conf})")

    # Failures
    if result.failures:
        print()
        print("  Failures:")
        for f in result.failures:
            print(f"    ! [{f.stage}] cluster {f.cluster_id}: {f.error}")

    # Artifact pointers
    print()
    print(f"  Report  : {result.report_path}")
    print(f"  Run dir : {result.run_dir}")
    print()


def run_cli(argv: list[str] | None = None) -> int:
    """Execute the CLI for the provided argument vector."""
    parser = build_parser()
    raw_args = sys.argv[1:] if argv is None else argv
    if not raw_args:
        parser.print_help()
        return 0

    args = parser.parse_args(raw_args)

    if args.command == "scan":
        return _run_scan(args)

    if args.command == "run":
        vision_backend = _build_vision_backend(args)
        synthesis_backend = _build_synthesis_backend(args)

        search_provider: SearchProvider
        if args.offline or args.search_provider == "static":
            search_provider = StaticSearchProvider(fixtures={})
        elif args.search_provider == "searxng":
            search_provider = SearXNGSearchProvider(
                instance_url=args.searxng_url, proxy_url=args.proxy
            )
        elif args.search_provider == "ddgs":
            search_provider = DDGSSearchProvider(proxy=args.proxy)
        else:
            search_provider = DuckDuckGoSearchProvider(proxy_url=args.proxy)
        result = run_pipeline(
            input_path=Path(args.input_path),
            output_root=Path(args.output),
            run_label=args.run_label,
            vision_backend=vision_backend,
            search_provider=search_provider,
            synthesis_backend=synthesis_backend,
        )
        _print_run_summary(result)
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
