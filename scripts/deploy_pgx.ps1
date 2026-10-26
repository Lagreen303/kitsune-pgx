# Sync src + tests + scripts to PGX and reinstall (run from repo root on Windows).
# Set $env:KITSUNE_PGX_REMOTE to the repo path on the fetch host (default: ~/kitsune-pgx).
$RemoteRoot = if ($env:KITSUNE_PGX_REMOTE) { $env:KITSUNE_PGX_REMOTE } else { "~/kitsune-pgx" }
$SshHost = if ($env:KITSUNE_PGX_SSH) { $env:KITSUNE_PGX_SSH } else { "pgx" }

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
  $remote = "$RemoteRoot/$f"
  Get-Content -Raw $local | ssh $SshHost "mkdir -p `$(dirname $remote) 2>/dev/null; cat > $remote"
}
ssh $SshHost "$RemoteRoot/.venv/bin/pip install -q -e $RemoteRoot"
