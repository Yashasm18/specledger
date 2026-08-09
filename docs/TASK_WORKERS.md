# Document processing workers

The API should remain fast even when a supplier uploads a large catalogue. It registers document metadata and enqueues work; workers perform extraction, normalization, validation, and enrichment asynchronously.

## Task lifecycle

```text
queued → processing → completed
                    ↘ failed
```

Workers claim tasks using PostgreSQL row locks with `FOR UPDATE SKIP LOCKED`, so multiple workers can process tasks concurrently without claiming the same task.

## Worker contract

1. Claim one task with a unique worker ID.
2. Load the document from object storage.
3. Extract structured facts and evidence.
4. Persist results transactionally.
5. Mark the task completed.
6. On failure, record the error and apply retry policy.

The task queue is a coordination mechanism, not a replacement for a dedicated queue at very high throughput. The interface can later be backed by Kafka, SQS, Pub/Sub, or RabbitMQ without changing the processing worker contract.

