# Sync src + tests + scripts to PGX and reinstall (run from repo root on Windows).
$files = @(
  "src/kitsune_pgx/fetch/chemistry.py",
  "src/kitsune_pgx/fetch/fastq_layout.py",
  "src/kitsune_pgx/fetch/pipeline.py",
  "src/kitsune_pgx/fetch/sra_fallback.py",
  "src/kitsune_pgx/sync/iridis.py",
  "src/kitsune_pgx/worker.py",
  "scripts/pgx-worker-loop.sh",
  "tests/test_chemistry.py"
)
foreach ($f in $files) {
  $local = Join-Path $PSScriptRoot ".." $f
  $remote = "/home/lag1e24/kitsune-pgx/$f"
  Get-Content -Raw $local | ssh pgx "mkdir -p `$(dirname $remote) 2>/dev/null; cat > $remote"
}
ssh pgx "/home/lag1e24/kitsune-pgx/.venv/bin/pip install -q -e /home/lag1e24/kitsune-pgx"
