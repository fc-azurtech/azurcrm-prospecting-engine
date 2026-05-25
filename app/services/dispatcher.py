import hashlib
import hmac
import json
import time
import uuid
from datetime import date

import httpx

from ..config import settings


def _build_demo_signal(job_payload: dict) -> dict:
    campaign = job_payload.get("campaign") or {}
    scope = job_payload.get("scope") or {}
    target_profile = job_payload.get("target_profile") or {}
    keywords = job_payload.get("keywords") or {}

    country = scope.get("country") or "CL"
    city = scope.get("city") or "Santiago"
    region = scope.get("region") or "RM"

    high_intent = (keywords.get("high_intent") or [])
    positive = (keywords.get("positive") or [])
    matched = [k for k in (high_intent + positive) if k][:3]

    company_name = f"Prospecto {campaign.get('campaign_name', 'Lead Finder')}"
    signal_text = "Empresa solicita mejora operativa y evalua ERP en el corto plazo."

    signal_hash_base = f"https://example.org/{company_name}|{company_name}|{date.today().isoformat()}|{signal_text}"
    signal_hash = hashlib.sha256(signal_hash_base.encode("utf-8")).hexdigest()

    return {
        "signal_id": str(uuid.uuid4()),
        "signal_hash": signal_hash,
        "source_name": "manual_import",
        "source_url": "https://example.org/opportunity/erp",
        "source_date": date.today().isoformat(),
        "source_text_summary": signal_text,
        "detected_signal": "Busqueda activa de implementacion ERP",
        "matched_keywords": matched,
        "company": {
            "company_name": company_name,
            "industry": (target_profile.get("target_industry") or "Servicios"),
            "city": city,
            "region": region,
            "country": country,
            "company_size_estimated": target_profile.get("target_company_size") or "10-50",
            "website": "https://example.org",
            "linkedin_url": "https://www.linkedin.com/company/example",
        },
        "contact": {
            "contact_name": "Contacto Referencial",
            "contact_role": "Gerencia Operaciones",
            "email": "No disponible publicamente",
            "phone": "Requiere validacion manual",
        },
        "opportunity": {
            "opportunity_type": "ERP",
            "pain_point_detected": "Falta de integracion entre areas",
            "competitor_detected": "",
            "recommended_solution": "Implementacion Odoo con enfoque por fases",
            "modules_or_services_to_offer": "Ventas, Inventario, Contabilidad",
        },
        "scoring": {
            "priority": "Alta",
            "priority_reason": "Menciona necesidad actual y urgencia operativa",
            "confidence_score": 88,
            "recommended_sales_angle": "Reduccion de tiempos y trazabilidad",
        },
        "messages": {
            "whatsapp_message": "Vimos una señal publica sobre su evaluacion ERP. Podemos apoyarle con una ruta de implementacion segura.",
            "email_message": "Detectamos una señal publica de evaluacion ERP y proponemos una reunion corta para explorar un plan por etapas.",
            "call_script": "Hola, gracias por su tiempo. Vimos una señal publica relacionada a ERP y queria validar si tiene sentido revisar una propuesta en fases.",
        },
        "compliance": {
            "requires_manual_validation": True,
            "public_data_only": True,
            "validation_notes": "Contenido generado automaticamente a partir de datos publicos.",
        },
    }


def _build_signature(timestamp: str, raw_body: bytes) -> str:
    signature_base = f"{timestamp}.{raw_body.decode('utf-8')}"
    return hmac.new(settings.odoo_hmac_secret.encode("utf-8"), signature_base.encode("utf-8"), hashlib.sha256).hexdigest()


async def send_batch_to_odoo(
    job_payload: dict,
    external_job_id: str,
    correlation_id: str,
    callback_base_url: str | None = None,
) -> tuple[bool, str]:
    if not settings.callback_enabled:
        return True, "callback_disabled"
    target_base_url = (callback_base_url or settings.odoo_callback_url).rstrip("/")
    if not target_base_url:
        return False, "missing_odoo_callback_url"
    if not settings.odoo_key_id or not settings.odoo_hmac_secret:
        return False, "missing_odoo_hmac_credentials"

    batch_id = str(uuid.uuid4())
    batch_payload = {
        "batch_id": batch_id,
        "external_job_id": external_job_id,
        "campaign_uuid": (job_payload.get("campaign") or {}).get("campaign_uuid"),
        "source_run_started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_run_finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "signals": [_build_demo_signal(job_payload)],
    }

    raw_body = json.dumps(batch_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time()))
    signature = _build_signature(timestamp, raw_body)

    headers = {
        "Content-Type": "application/json",
        "X-Batch-Id": batch_id,
        "X-Correlation-Id": correlation_id,
        "X-Azur-Key-Id": settings.odoo_key_id,
        "X-Azur-Timestamp": timestamp,
        "X-Azur-Signature": signature,
    }

    callback_url = f"{target_base_url}/api/azurcrm_lead_finder/v1/signals/batch"

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(callback_url, content=raw_body, headers=headers)

    if response.status_code in (200, 207):
        return True, f"ok_{response.status_code}"
    return False, f"http_{response.status_code}: {response.text[:300]}"
