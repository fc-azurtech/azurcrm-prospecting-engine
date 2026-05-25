import os


class Settings:
    app_name = "AzurCRM Prospecting Engine"
    app_version = "1.0.0"

    # Incoming auth from Odoo
    inbound_bearer_token = os.getenv("ENGINE_INBOUND_BEARER_TOKEN", "")

    # Web UI auth/session
    web_login_user = os.getenv("ENGINE_WEB_LOGIN_USER", "admin")
    web_login_password = os.getenv("ENGINE_WEB_LOGIN_PASSWORD", "admin")
    web_session_secret = os.getenv("ENGINE_WEB_SESSION_SECRET", "change-me-session-secret")

    # Outbound callback to Odoo
    callback_enabled = os.getenv("ODOO_CALLBACK_ENABLED", "true").lower() == "true"
    odoo_callback_url = os.getenv("ODOO_CALLBACK_URL", "").rstrip("/")
    odoo_key_id = os.getenv("ODOO_KEY_ID", "")
    odoo_hmac_secret = os.getenv("ODOO_HMAC_SECRET", "")

    # Engine runtime
    default_eta_seconds = int(os.getenv("ENGINE_DEFAULT_ETA_SECONDS", "2"))


settings = Settings()
