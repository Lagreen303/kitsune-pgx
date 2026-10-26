import sqlite3
import threading
from pathlib import Path

from kitsune_pgx.ledger import claim_next, connect, insert_run, init_db


def test_claim_exclusive(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    conn = connect(db)
    init_db(conn)
    insert_run(conn, srr="SRR1", gse="GSE1", sample_id="GSM_SRR1")
    insert_run(conn, srr="SRR2", gse="GSE1", sample_id="GSM_SRR2")

    claimed: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        c = connect(db)
        row = claim_next(c, worker_id="w")
        if row:
            with lock:
                claimed.append(row["srr"])
        c.close()

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(claimed) == 2
    assert len(set(claimed)) == 2
