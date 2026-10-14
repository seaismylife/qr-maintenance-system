import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent / ".env"
    if _env_path.exists():
        load_dotenv(dotenv_path=_env_path)
except ImportError:
    pass

ENV = os.environ.get("FLASK_ENV", os.environ.get("ENV", "development"))
DEBUG = os.environ.get("FLASK_DEBUG", "1").lower() in ("1", "true", "yes")

import urllib.parse

_raw_db_url = os.environ.get("DATABASE_URL") or os.environ.get("MYSQL_URL") or os.environ.get("TIDB_URL") or ""
_parsed_url = urllib.parse.urlsplit(_raw_db_url) if _raw_db_url else None

MYSQL_HOST = os.environ.get("MYSQL_HOST") or (_parsed_url.hostname if _parsed_url else None) or "127.0.0.1"
MYSQL_PORT = int(os.environ.get("MYSQL_PORT") or (_parsed_url.port if _parsed_url and _parsed_url.port else None) or 3306)
MYSQL_USER = os.environ.get("MYSQL_USER") or (urllib.parse.unquote(_parsed_url.username) if _parsed_url and _parsed_url.username else None) or "root"
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD") or (urllib.parse.unquote(_parsed_url.password) if _parsed_url and _parsed_url.password else None) or ""
MYSQL_DB = os.environ.get("MYSQL_DB") or (_parsed_url.path.lstrip("/") if _parsed_url and _parsed_url.path else None) or "qr_maintenance_db"
MYSQL_POOL_SIZE = int(os.environ.get("MYSQL_POOL_SIZE", "10"))

_default_ssl_disabled = "1" if MYSQL_HOST in ("127.0.0.1", "localhost", "db") else "0"
MYSQL_SSL_DISABLED = os.environ.get("MYSQL_SSL_DISABLED", _default_ssl_disabled).lower() in ("1", "true", "yes")
MYSQL_SSL_CA = os.environ.get("MYSQL_SSL_CA", "").strip()
MYSQL_SSL_VERIFY = os.environ.get("MYSQL_SSL_VERIFY", "1").lower() in ("1", "true", "yes")

SECRET_KEY = os.environ.get("SECRET_KEY", "qr_maintenance_super_secret_key_change_me")
SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0").lower() in ("1", "true", "yes")

BEHIND_PROXY = os.environ.get("BEHIND_PROXY", "0").lower() in ("1", "true", "yes")
PROXY_FIX_NUM_PROXIES = int(os.environ.get("PROXY_FIX_NUM_PROXIES", "1"))

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "5000"))

UPLOAD_FOLDER = os.environ.get(
    "UPLOAD_FOLDER",
    os.path.join(os.path.dirname(__file__), "uploads")
)
MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", 8 * 1024 * 1024))

PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")

