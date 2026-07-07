"""Command-line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .io import read_network, write_result_json
from .models import NetworkError
from .report import format_report, write_report
from .solver import adjust_network


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gnss-adjust",
        description="Weighted least-squares adjustment of a 3D GNSS baseline network.",
    )
    parser.add_argument("input", type=Path, help="legacy .txt or documented .json network file")
    parser.add_argument("--report", "-o", type=Path, help="write a text report")
    parser.add_argument("--json", type=Path, help="write all results as JSON")
    parser.add_argument(
        "--apriori-variance-factor",
        type=float,
        default=1.0,
        help="a-priori variance factor used by statistical tests (default: 1)",
    )
    parser.add_argument(
        "--global-alpha", type=float, default=0.05, help="global chi-square significance (default: 0.05)"
    )
    parser.add_argument(
        "--local-alpha", type=float, default=0.001, help="two-sided data-snooping significance (default: 0.001)"
    )
    parser.add_argument(
        "--csharp-compatible",
        action="store_true",
        help="replicate Adj.cs variance floor and legacy reference-standard-deviation scale",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = adjust_network(
            read_network(args.input),
            a_priori_variance_factor=args.apriori_variance_factor,
            global_significance=args.global_alpha,
            local_significance=args.local_alpha,
            csharp_compatible=args.csharp_compatible,
        )
        if args.report:
            write_report(result, args.report)
        if args.json:
            write_result_json(result, args.json)
        if not args.report:
            sys.stdout.write(format_report(result))
        return 0
    except (OSError, NetworkError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
