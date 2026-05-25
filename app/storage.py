import hashlib
import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class StoredJob:
    external_job_id: str
    request_id: str
    idempotency_key: str
    correlation_id: str
    payload_hash: str
    accepted_at: str
    status: str = "accepted"
    completed_at: str | None = None
    callback_status: str | None = None


class InMemoryJobStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._jobs_by_external: dict[str, StoredJob] = {}
        self._idempotency_index: dict[str, StoredJob] = {}

    @staticmethod
    def compute_hash(payload: dict) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def utc_now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def get_by_external(self, external_job_id: str) -> StoredJob | None:
        with self._lock:
            return self._jobs_by_external.get(external_job_id)

    def get_by_idempotency(self, key: str) -> StoredJob | None:
        with self._lock:
            return self._idempotency_index.get(key)

    def save(self, job: StoredJob) -> None:
        with self._lock:
            self._jobs_by_external[job.external_job_id] = job
            self._idempotency_index[job.idempotency_key] = job

    def update_status(self, external_job_id: str, status: str, callback_status: str | None = None) -> None:
        with self._lock:
            job = self._jobs_by_external.get(external_job_id)
            if not job:
                return
            job.status = status
            job.callback_status = callback_status
            if status in {"done", "error"}:
                job.completed_at = self.utc_now_iso()

    def list_jobs(self) -> list[StoredJob]:
        with self._lock:
            return sorted(
                self._jobs_by_external.values(),
                key=lambda j: j.accepted_at,
                reverse=True,
            )
