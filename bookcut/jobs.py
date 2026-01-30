from __future__ import annotations
import uuid
import time
from enum import Enum
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Optional, List

class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class Job:
    id: str
    status: JobStatus
    created_at: float
    query: str
    message: List[str] = field(default_factory=list)
    result_path: Optional[str] = None
    error: Optional[str] = None

class JobStore:
    def __init__(self):
        self._jobs: Dict[str, Job] = {}

    def create_job(self, query: str) -> str:
        job_id = str(uuid.uuid4())
        self._jobs[job_id] = Job(
            id=job_id,
            status=JobStatus.PENDING,
            created_at=time.time(),
            query=query
        )
        return job_id

    def get_job(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def update_status(self, job_id: str, status: JobStatus, message: Optional[str] = None):
        if job_id in self._jobs:
            self._jobs[job_id].status = status
            if message:
                self._jobs[job_id].message.append(message)

    def complete_job(self, job_id: str, result_path: str):
        if job_id in self._jobs:
            self._jobs[job_id].status = JobStatus.COMPLETED
            self._jobs[job_id].result_path = result_path
            self._jobs[job_id].message.append("Job completed successfully.")

    def fail_job(self, job_id: str, error: str):
        if job_id in self._jobs:
            self._jobs[job_id].status = JobStatus.FAILED
            self._jobs[job_id].error = error
            self._jobs[job_id].message.append(f"Job failed: {error}")

    def append_log(self, job_id: str, message: str):
        if job_id in self._jobs:
            # Keep log size reasonable
            if len(self._jobs[job_id].message) > 100:
                 self._jobs[job_id].message.pop(0)
            self._jobs[job_id].message.append(message)
