# AzurCRM Prospecting Engine (Linux)

Motor externo para AzurCRM Lead Finder en Odoo 18.

## Que hace

- Recibe jobs desde Odoo: `POST /v1/prospecting/jobs`
- Soporta idempotencia por `X-Idempotency-Key`
- Expone estado de job: `GET /v1/prospecting/jobs/{external_job_id}`
- Incluye interfaz web minima con login por usuario/clave
- Panel web para listar jobs y crear job manual
- Proteccion por sesion/cookie en rutas web
- Modo multi-tenant: callback por tenant con whitelist de dominios
- Envia un batch demo firmado a Odoo: `POST /api/azurcrm_lead_finder/v1/signals/batch`
- Health check: `GET /health`

## Estructura

- `app/main.py`: API principal FastAPI
- `app/services/dispatcher.py`: generacion de senal demo y callback firmado
- `app/storage.py`: almacenamiento en memoria con indice de idempotencia
- `docker-compose.engine.yml`: despliegue container Linux
- `deploy/systemd/azurcrm-prospecting-engine.service`: ejemplo para servidor Linux

## Variables de entorno

- `ENGINE_INBOUND_BEARER_TOKEN`: token que Odoo enviara como Bearer al crear jobs
- `ENGINE_WEB_LOGIN_USER`: usuario login web
- `ENGINE_WEB_LOGIN_PASSWORD`: clave login web
- `ENGINE_WEB_SESSION_SECRET`: secreto para firma de cookie de sesion
- `ODOO_CALLBACK_ENABLED`: `true|false`
- `ODOO_CALLBACK_URL`: URL base Odoo, por ejemplo `http://127.0.0.1:8069`
- `ODOO_TENANT_CALLBACKS_JSON`: mapa JSON tenant -> URL callback base
- `ODOO_CALLBACK_ALLOWED_DOMAINS`: lista separada por coma de dominios permitidos
- `ODOO_KEY_ID`: key id configurado en Odoo para inbound
- `ODOO_HMAC_SECRET`: secreto HMAC configurado en Odoo
- `ENGINE_DEFAULT_ETA_SECONDS`: tiempo de simulacion antes de callback

Ejemplo multi-tenant:

```env
ODOO_TENANT_CALLBACKS_JSON={"cliente_azursoft":"https://cliente.azur-soft.com","cliente_antik":"https://antik.cl"}
ODOO_CALLBACK_ALLOWED_DOMAINS=cliente.azur-soft.com,antik.cl
```

Prioridad de callback por job:

1. `execution.callback_url` (o `callback_url` en raíz)
2. Mapa por `execution.tenant_key` (o `tenant_key` en raíz)
3. `ODOO_CALLBACK_URL`

Si `ODOO_CALLBACK_ALLOWED_DOMAINS` está definido, cualquier callback debe caer en esa whitelist.

## Interfaz web

- Login: `GET /web/login`
- Panel jobs: `GET /web/jobs`
- Crear job manual (form): `POST /web/jobs`
- Logout: `POST /web/logout`

Notas de seguridad:

- API de jobs mantiene proteccion Bearer en `POST /v1/prospecting/jobs` y `GET /v1/prospecting/jobs/{external_job_id}`.
- Rutas web exigen sesion activa con cookie firmada.
- El callback saliente valida dominio permitido (whitelist) para mitigar SSRF.

## Ejecutar en Linux con Docker

```bash
cd /opt/azurcrm-prospecting-engine
docker compose -f docker-compose.engine.yml up -d --build
```

## Instalacion rapida (script)

```bash
cd /opt/azurcrm-prospecting-engine
chmod +x scripts/install_linux.sh
./scripts/install_linux.sh
```

En Debian/Ubuntu sin Docker (modo nativo Python):

```bash
cd /opt/azurcrm-prospecting-engine
chmod +x scripts/install_linux.sh
./scripts/install_linux.sh --mode native
```

Si tienes multiples versiones de Python, puedes forzar una:

```bash
PYTHON_BIN=python3.11 ./scripts/install_linux.sh --mode native
```

Requisito de runtime en modo nativo:

- Python 3.10 o superior.

Con autoarranque por systemd:

```bash
cd /opt/azurcrm-prospecting-engine
sudo ./scripts/install_linux.sh --mode native --with-systemd
```

## Ejecutar local sin Docker

```bash
cd /opt/azurcrm-prospecting-engine
chmod +x scripts/run_local.sh
./scripts/run_local.sh
```

## Configuracion en Odoo

En Ajustes > AzurCRM Lead Finder:

- External engine URL: `http://<HOST_ENGINE>:8090`
- External engine token: valor de `ENGINE_INBOUND_BEARER_TOKEN`
- Inbound key ID: valor de `ODOO_KEY_ID`
- Inbound HMAC secret: valor de `ODOO_HMAC_SECRET`

## Flujo esperado

1. En campana activa, clic en `Trabajo externo en cola`.
2. Odoo crea job `queued`.
3. Cron de dispatch envia job al engine.
4. Engine responde `accepted` y luego envia un batch demo a Odoo.
5. Odoo crea signal/prospect.
6. Si aplica umbral y auto-create, se crea lead CRM.

## Notas

- Este motor es MVP funcional para Linux y pruebas UAT.
- Persistencia actual en memoria: al reiniciar, se pierde historial de jobs.
- Si quieres, siguiente iteracion: PostgreSQL + worker de cola + filtros reales por fuentes.
