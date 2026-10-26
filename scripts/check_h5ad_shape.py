#!/usr/bin/env python3
import glob
import sys

import anndata as ad

paths = sys.argv[1:] or [
    "/iridisfs/scratch/lag1e24/kitsune/results/GSE291294/GSE291294_gencode_merged.h5ad",
    "/iridisfs/scratch/lag1e24/kitsune/results/GSE147989/GSE147989_gencode_merged.h5ad",
]
for p in paths:
    a = ad.read_h5ad(p)
    print(f"{p}: cells={a.n_obs} genes={a.n_vars}")
samples = glob.glob("/iridisfs/scratch/lag1e24/kitsune/results/GSE291294/*/gencode/matrix.h5ad")
for p in samples[:3]:
    a = ad.read_h5ad(p)
    print(f"sample {p}: cells={a.n_obs} genes={a.n_vars}")
    if a.n_vars < 100:
        print("  var head:", list(a.var_names[:10]))
        print("  var cols:", list(a.var.columns))
