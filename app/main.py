import asyncio
import uuid
from urllib.parse import quote_plus
from typing import Annotated

from fastapi import Depends, FastAPI, Form, Header, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .config import settings
from .models import HealthResponse, JobCreateRequest, JobCreateResponse, JobStatusResponse
from .security import require_bearer
from .services.dispatcher import send_batch_to_odoo
from .storage import InMemoryJobStore, StoredJob

app = FastAPI(title=settings.app_name, version=settings.app_version)
app.add_middleware(SessionMiddleware, secret_key=settings.web_session_secret)

templates = Jinja2Templates(directory="app/templates")
store = InMemoryJobStore()


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(ok=True, service=settings.app_name, version=settings.app_version)


async def _background_process(job_payload: dict, external_job_id: str, correlation_id: str) -> None:
    await asyncio.sleep(max(0, settings.default_eta_seconds))
    ok, callback_status = await send_batch_to_odoo(job_payload, external_job_id, correlation_id)
    store.update_status(external_job_id, "done" if ok else "error", callback_status)


def _build_job_payload(request_id: str, campaign_name: str) -> JobCreateRequest:
    return JobCreateRequest(
        request_id=request_id,
        campaign={"name": campaign_name},
        scope={},
        target_profile={},
        offer={},
        keywords={},
        sources={},
        execution={},
        assignment={},
        query_templates=[],
    )


def _enqueue_job(
    payload: JobCreateRequest,
    idempotency_key: str,
    correlation_id: str,
    eta_seconds: int,
    is_deduplicated: bool,
    external_job_id: str,
    accepted_at: str,
) -> JobCreateResponse:
    return JobCreateResponse(
        external_job_id=external_job_id,
        status="accepted",
        accepted_at=accepted_at,
        deduplicated=is_deduplicated,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        polling_url=f"/v1/prospecting/jobs/{external_job_id}",
        eta_seconds=eta_seconds,
    )


def _submit_job(payload: JobCreateRequest, idempotency_key: str, correlation_id: str) -> tuple[JobCreateResponse, int]:
    if not idempotency_key:
        raise HTTPException(status_code=422, detail="X-Idempotency-Key is required")

    payload_dict = payload.model_dump(mode="json")
    payload_hash = store.compute_hash(payload_dict)

    existing = store.get_by_idempotency(idempotency_key)
    if existing:
        if existing.payload_hash != payload_hash:
            raise HTTPException(status_code=409, detail="conflict_payload_mismatch")
        return (
            _enqueue_job(
                payload=payload,
                idempotency_key=idempotency_key,
                correlation_id=existing.correlation_id,
                eta_seconds=0,
                is_deduplicated=True,
                external_job_id=existing.external_job_id,
                accepted_at=existing.accepted_at,
            ),
            200,
        )

    external_job_id = str(uuid.uuid4())
    accepted_at = store.utc_now_iso()
    job = StoredJob(
        external_job_id=external_job_id,
        request_id=payload.request_id,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload_hash=payload_hash,
        accepted_at=accepted_at,
        status="accepted",
    )
    store.save(job)

    asyncio.create_task(_background_process(payload_dict, external_job_id, correlation_id))

    return (
        _enqueue_job(
            payload=payload,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            eta_seconds=settings.default_eta_seconds,
            is_deduplicated=False,
            external_job_id=external_job_id,
            accepted_at=accepted_at,
        ),
        202,
    )


def require_web_session(request: Request) -> None:
    if request.session.get("user"):
        return
    raise HTTPException(status_code=401, detail="Web login required")


@app.get("/", response_class=HTMLResponse)
def root() -> RedirectResponse:
    return RedirectResponse(url="/web/jobs", status_code=status.HTTP_302_FOUND)


@app.get("/web/login", response_class=HTMLResponse)
def web_login_form(request: Request):
    if request.session.get("user"):
        return RedirectResponse(url="/web/jobs", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/web/login", response_class=HTMLResponse)
def web_login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    if username == settings.web_login_user and password == settings.web_login_password:
        request.session["user"] = username
        return RedirectResponse(url="/web/jobs", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(request, "login.html", {"error": "Credenciales invalidas"})


@app.post("/web/logout")
def web_logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/web/login", status_code=status.HTTP_302_FOUND)


@app.get("/web/jobs", response_class=HTMLResponse)
def web_jobs(request: Request, _auth: None = Depends(require_web_session)):
    jobs = store.list_jobs()
    return templates.TemplateResponse(
        request,
        "jobs.html",
        {
            "jobs": jobs,
            "user": request.session.get("user"),
            "default_request_id": str(uuid.uuid4()),
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
        },
    )


@app.post("/web/jobs")
def web_create_job(
    request: Request,
    _auth: None = Depends(require_web_session),
    request_id: str = Form(...),
    campaign_name: str = Form("Manual Job"),
    idempotency_key: str = Form(...),
):
    payload = _build_job_payload(request_id=request_id.strip(), campaign_name=campaign_name.strip() or "Manual Job")
    correlation_id = str(uuid.uuid4())
    try:
        result, _status_code = _submit_job(payload, idempotency_key.strip(), correlation_id)
    except HTTPException as exc:
        error = exc.detail if isinstance(exc.detail, str) else "Error creando job"
        return RedirectResponse(url=f"/web/jobs?error={quote_plus(error)}", status_code=status.HTTP_302_FOUND)

    message = quote_plus(f"Job {result.external_job_id} aceptado")
    return RedirectResponse(
        url=f"/web/jobs?message={message}",
        status_code=status.HTTP_302_FOUND,
    )


@app.post(
    "/v1/prospecting/jobs",
    response_model=JobCreateResponse,
    dependencies=[Depends(require_bearer)],
)
async def create_job(
    payload: JobCreateRequest,
    response: Response,
    x_idempotency_key: Annotated[str | None, Header(alias="X-Idempotency-Key")] = None,
    x_correlation_id: Annotated[str | None, Header(alias="X-Correlation-Id")] = None,
):
    idempotency_key = (x_idempotency_key or payload.request_id or "").strip()
    correlation_id = (x_correlation_id or str(uuid.uuid4())).strip()
    result, status_code = _submit_job(payload, idempotency_key, correlation_id)
    response.status_code = status_code
    return result


@app.get(
    "/v1/prospecting/jobs/{external_job_id}",
    response_model=JobStatusResponse,
    dependencies=[Depends(require_bearer)],
)
def get_job_status(external_job_id: str):
    job = store.get_by_external(external_job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatusResponse(
        external_job_id=job.external_job_id,
        status=job.status,
        request_id=job.request_id,
        idempotency_key=job.idempotency_key,
        correlation_id=job.correlation_id,
        accepted_at=job.accepted_at,
        completed_at=job.completed_at,
        callback_status=job.callback_status,
    )
