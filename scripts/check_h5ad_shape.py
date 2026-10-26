#!/usr/bin/env python3
"""Print h5ad shapes. Pass paths as arguments, or --gse GSE under $KITSUNE_ROOT/results."""
import argparse
import glob
import os
from pathlib import Path

import anndata as ad


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("paths", nargs="*", help="h5ad files to inspect")
    p.add_argument("--gse", help="Also print up to 3 per-sample matrices under results/<GSE>")
    p.add_argument(
        "--results",
        type=Path,
        default=Path(os.environ.get("KITSUNE_ROOT", ".")) / "results",
    )
    args = p.parse_args()
    paths = args.paths
    if not paths and not args.gse:
        p.error("pass h5ad path(s) or --gse")
    for path in paths:
        a = ad.read_h5ad(path)
        print(f"{path}: cells={a.n_obs} genes={a.n_vars}")
    if args.gse:
        pattern = str(args.results / args.gse / "*" / "gencode" / "matrix.h5ad")
        for path in glob.glob(pattern)[:3]:
            a = ad.read_h5ad(path)
            print(f"sample {path}: cells={a.n_obs} genes={a.n_vars}")
            if a.n_vars < 100:
                print("  var head:", list(a.var_names[:10]))
                print("  var cols:", list(a.var.columns))


if __name__ == "__main__":
    main()
