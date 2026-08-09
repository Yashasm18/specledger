"""Run a long-lived SpecLedger document worker locally or in a container."""

from __future__ import annotations

import os
import signal
import time

from specledger.object_store import LocalObjectStore
from specledger.tasks import TaskQueue
from specledger.worker import DocumentProcessingWorker


def main() -> None:
    queue = TaskQueue(os.environ["DATABASE_URL"])
    worker = DocumentProcessingWorker(queue, LocalObjectStore(os.getenv("SPECLEDGER_OBJECT_STORE", "object-data")))
    stopping = False

    def stop(_signal: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    print(f"SpecLedger worker {worker.worker_id} listening", flush=True)
    try:
        while not stopping:
            result = worker.run_once()
            if result is None:
                time.sleep(float(os.getenv("WORKER_POLL_SECONDS", "1.0")))
            else:
                print(f"processed document {result.document_id}", flush=True)
    finally:
        queue.close()
        print("SpecLedger worker stopped", flush=True)


if __name__ == "__main__":
    main()
