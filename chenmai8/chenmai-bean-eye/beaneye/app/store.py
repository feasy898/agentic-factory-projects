"""M13 应用壳 · 进程内作业与结果存储。

- 作业队列：``ThreadPoolExecutor``（spec 约定进程内队列）；
- 作业/结果记录存内存（演示 MVP 语义；扫描图/证据/护照文件持久在数据根目录，
  进程重启后结果列表清空属预期，文件仍在盘）；
- 线程安全：所有读写走 ``threading.Lock``。
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from beaneye.app.pipeline import PipelineOutcome, PipelineRequest, PipelineStageError, run_pipeline
from beaneye.app.components import Components
from beaneye.schemas import BatchResult, PassportReport, TrayScan

__all__ = ["JobRecord", "ResultRecord", "AppStore", "new_id"]

JOB_QUEUED = "queued"
JOB_RUNNING = "running"
JOB_DONE = "done"
JOB_FAILED = "failed"


def new_id() -> str:
    return uuid.uuid4().hex


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


@dataclass
class JobRecord:
    """一次扫描作业的状态机记录（queued → running → done|failed）。"""

    job_id: str
    sample_id: str
    tray_id: str
    standard_id: str
    status: str = JOB_QUEUED
    stage: str = "queued"
    scan_id: str = ""
    result_id: str | None = None
    error: str | None = None
    error_stage: str | None = None
    created_at: str = field(default_factory=_now)
    finished_at: str | None = None

    def public_view(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "stage": self.stage,
            "sample_id": self.sample_id,
            "tray_id": self.tray_id,
            "standard_id": self.standard_id,
            "scan_id": self.scan_id,
            "result_id": self.result_id,
            "error": self.error,
            "error_stage": self.error_stage,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


@dataclass
class ResultRecord:
    """已完成作业的产物登记（契约模型 + 降级元数据 + 文件根）。"""

    result: BatchResult
    passport: PassportReport | None
    scan: TrayScan
    degraded_stages: list[str]
    degraded_reasons: dict[str, str]
    pairing_summary: dict[str, int]
    data_root: str
    created_at: str = field(default_factory=_now)

    def summary_view(self) -> dict[str, Any]:
        g = self.result.grading
        m = self.result.measurements
        return {
            "result_id": self.result.result_id,
            "sample_id": self.result.sample_id,
            "scan_ids": list(self.result.scan_ids),
            "standard_id": g.standard_id,
            "grade": g.grade,
            "passed": g.passed,
            "bean_count": m.bean_count,
            "primary_count": g.primary_count,
            "secondary_count": g.secondary_count,
            "defect_counts": dict(g.defect_counts),
            "degraded": bool(self.degraded_stages),
            "degraded_stages": list(self.degraded_stages),
            "has_passport": self.passport is not None,
            "created_at": self.created_at,
        }


class AppStore:
    """进程内作业/结果存储 + 线程池执行器。"""

    def __init__(
        self,
        components: Components,
        *,
        data_root: str,
        max_workers: int = 2,
        agent: Any | None = None,
    ) -> None:
        self._components = components
        self._agent = agent
        self._lock = threading.Lock()
        self._jobs: dict[str, JobRecord] = {}
        self._results: dict[str, ResultRecord] = {}
        self._pool = ThreadPoolExecutor(max_workers=max(1, max_workers), thread_name_prefix="beaneye-job")
        self.data_root = data_root

    # -- 生命周期 ----------------------------------------------------------
    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    # -- 作业 --------------------------------------------------------------
    def submit(self, req: PipelineRequest) -> JobRecord:
        job = JobRecord(
            job_id=new_id(),
            sample_id=req.scan.sample_id,
            tray_id=req.scan.tray_id,
            standard_id=req.standard_id,
        )
        with self._lock:
            self._jobs[job.job_id] = job
        self._pool.submit(self._run, job.job_id, req)
        return job

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._lock:
            return self._jobs.get(job_id)

    # -- 结果 --------------------------------------------------------------
    def get_result(self, result_id: str) -> ResultRecord | None:
        with self._lock:
            return self._results.get(result_id)

    def list_results(self) -> list[ResultRecord]:
        with self._lock:
            return sorted(self._results.values(), key=lambda r: r.created_at, reverse=True)

    # -- 执行体（线程池内） -------------------------------------------------
    def _run(self, job_id: str, req: PipelineRequest) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = JOB_RUNNING
            job.stage = "ingest"
        try:
            outcome: PipelineOutcome = run_pipeline(req, self._components, agent=self._agent)
        except PipelineStageError as exc:
            with self._lock:
                job.status = JOB_FAILED
                job.stage = exc.stage
                job.error = exc.message
                job.error_stage = exc.stage
                job.finished_at = _now()
            return
        except Exception as exc:  # 未预期异常也要落到作业状态，不能静默丢
            with self._lock:
                job.status = JOB_FAILED
                job.stage = "internal"
                job.error = f"内部错误（{exc.__class__.__name__}: {exc}）"
                job.error_stage = "internal"
                job.finished_at = _now()
            return

        record = ResultRecord(
            result=outcome.result,
            passport=outcome.passport,
            scan=outcome.scan,
            degraded_stages=outcome.degraded_stages,
            degraded_reasons=outcome.degraded_reasons,
            pairing_summary=outcome.pairing_summary,
            data_root=str(req.data_root),
        )
        with self._lock:
            self._results[outcome.result.result_id] = record
            job.status = JOB_DONE
            job.stage = "done"
            job.scan_id = outcome.scan.scan_id
            job.result_id = outcome.result.result_id
            job.finished_at = _now()
