import asyncio
import logging
from typing import List, Optional
from datetime import datetime, timezone
from schema import AsyncJobPayload, WorkflowExecutionLog, WorkflowIdentifier, FulfillmentStatus
from db_w1_pglite import w1_db

# Configure logger specifically for Worker
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("worker")

# Shared In-Memory Log History for UI & Audit Trail
execution_logs: List[WorkflowExecutionLog] = []


def record_log(
    workflow: WorkflowIdentifier,
    action: str,
    status: str,
    details: str,
    order_id: Optional[str] = None
) -> WorkflowExecutionLog:
    entry = WorkflowExecutionLog(
        workflow=workflow,
        action=action,
        status=status,
        details=details,
        order_id=order_id,
        timestamp=datetime.now(timezone.utc)
    )
    execution_logs.insert(0, entry)  # Prepend newest
    if len(execution_logs) > 100:
        execution_logs.pop()
    logger.info(f"[{workflow.value}] Action='{action}' Status='{status}' Details='{details}'")
    return entry


class Workflow1Worker:
    """
    Workflow 1 Async Queue & Background Worker:
    Receives background jobs for PGlite order status updates/inventory reconciliations,
    asynchronously processes them, and records explicit [WORKFLOW_1_WORKER] execution logs.
    """
    def __init__(self):
        self._queue: Optional[asyncio.Queue[AsyncJobPayload]] = None
        self._running: bool = False
        self._worker_task: Optional[asyncio.Task] = None

    @property
    def queue(self) -> asyncio.Queue[AsyncJobPayload]:
        if self._queue is None:
            self._queue = asyncio.Queue()
        return self._queue

    async def start(self):
        if not self._running:
            self._running = True
            # Always recreate the queue on start so it binds to the current running event loop
            self._queue = asyncio.Queue()
            self._worker_task = asyncio.create_task(self._process_queue())
            record_log(
                workflow=WorkflowIdentifier.WORKFLOW_1_PGLITE,
                action="WORKER_START",
                status="SUCCESS",
                details="[WORKFLOW_1_WORKER] Background queue worker started."
            )

    async def stop(self):
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
            self._queue = None
            record_log(
                workflow=WorkflowIdentifier.WORKFLOW_1_PGLITE,
                action="WORKER_STOP",
                status="SUCCESS",
                details="[WORKFLOW_1_WORKER] Background queue worker stopped."
            )

    async def enqueue_job(self, payload: AsyncJobPayload) -> str:
        await self.queue.put(payload)
        record_log(
            workflow=WorkflowIdentifier.WORKFLOW_1_PGLITE,
            action="JOB_ENQUEUED",
            status="QUEUED",
            details=f"[WORKFLOW_1_WORKER] Job {payload.job_id} queued for order {payload.order_id}",
            order_id=payload.order_id
        )
        return payload.job_id

    async def _process_queue(self):
        while self._running:
            try:
                job: AsyncJobPayload = await self.queue.get()
                await self._handle_job(job)
                self.queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[WORKFLOW_1_WORKER] Error processing queue: {e}", exc_info=True)

    async def _handle_job(self, job: AsyncJobPayload):
        record_log(
            workflow=WorkflowIdentifier.WORKFLOW_1_PGLITE,
            action="JOB_PROCESSING",
            status="IN_PROGRESS",
            details=f"[WORKFLOW_1_WORKER] Starting async fulfillment for order {job.order_id} (target: {job.target_status.value})",
            order_id=job.order_id
        )

        # Simulate async external Shopify API reconciliation delay
        await asyncio.sleep(0.5)

        # Update PGlite / fallback database
        updated_order = w1_db.update_fulfillment_status(job.order_id, job.target_status)

        if updated_order:
            record_log(
                workflow=WorkflowIdentifier.WORKFLOW_1_PGLITE,
                action="JOB_COMPLETED",
                status="SUCCESS",
                details=f"[WORKFLOW_1_WORKER] Order {job.order_id} successfully updated to {job.target_status.value} in PGlite store.",
                order_id=job.order_id
            )
        else:
            record_log(
                workflow=WorkflowIdentifier.WORKFLOW_1_PGLITE,
                action="JOB_FAILED",
                status="ERROR",
                details=f"[WORKFLOW_1_WORKER] Order {job.order_id} could not be found in PGlite store.",
                order_id=job.order_id
            )


# Singleton worker instance
w1_worker = Workflow1Worker()
