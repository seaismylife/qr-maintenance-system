import os
from pathlib import Path

# Load .env file automatically if present
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent / ".env"
    if _env_path.exists():
        load_dotenv(dotenv_path=_env_path)
except ImportError:
    pass

# Environment and Debug mode
ENV = os.environ.get("FLASK_ENV", os.environ.get("ENV", "development"))
DEBUG = os.environ.get("FLASK_DEBUG", "1").lower() in ("1", "true", "yes")

import urllib.parse

# Database configuration (supports individual vars or DATABASE_URL/MYSQL_URL/TIDB_URL)
_raw_db_url = os.environ.get("DATABASE_URL") or os.environ.get("MYSQL_URL") or os.environ.get("TIDB_URL") or ""
_parsed_url = urllib.parse.urlsplit(_raw_db_url) if _raw_db_url else None

MYSQL_HOST = os.environ.get("MYSQL_HOST") or (_parsed_url.hostname if _parsed_url else None) or "127.0.0.1"
MYSQL_PORT = int(os.environ.get("MYSQL_PORT") or (_parsed_url.port if _parsed_url and _parsed_url.port else None) or 3306)
MYSQL_USER = os.environ.get("MYSQL_USER") or (urllib.parse.unquote(_parsed_url.username) if _parsed_url and _parsed_url.username else None) or "root"
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD") or (urllib.parse.unquote(_parsed_url.password) if _parsed_url and _parsed_url.password else None) or ""
MYSQL_DB = os.environ.get("MYSQL_DB") or (_parsed_url.path.lstrip("/") if _parsed_url and _parsed_url.path else None) or "qr_maintenance_db"
MYSQL_POOL_SIZE = int(os.environ.get("MYSQL_POOL_SIZE", "10"))

# Remote Cloud Database SSL settings (e.g. TiDB Serverless, Aiven, Clever Cloud)
# Automatically enables SSL when connecting to any remote host (e.g. tidbcloud.com)
_default_ssl_disabled = "1" if MYSQL_HOST in ("127.0.0.1", "localhost", "db") else "0"
MYSQL_SSL_DISABLED = os.environ.get("MYSQL_SSL_DISABLED", _default_ssl_disabled).lower() in ("1", "true", "yes")
MYSQL_SSL_CA = os.environ.get("MYSQL_SSL_CA", "").strip()
MYSQL_SSL_VERIFY = os.environ.get("MYSQL_SSL_VERIFY", "1").lower() in ("1", "true", "yes")

# Security settings
SECRET_KEY = os.environ.get("SECRET_KEY", "qr_maintenance_super_secret_key_change_me")
SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0").lower() in ("1", "true", "yes")

# Reverse proxy support (e.g. Nginx, Cloudflare, AWS ALB)
BEHIND_PROXY = os.environ.get("BEHIND_PROXY", "0").lower() in ("1", "true", "yes")
PROXY_FIX_NUM_PROXIES = int(os.environ.get("PROXY_FIX_NUM_PROXIES", "1"))

# Server bind settings
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "5000"))

# Upload settings
UPLOAD_FOLDER = os.environ.get(
    "UPLOAD_FOLDER",
    os.path.join(os.path.dirname(__file__), "uploads")
)
MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", 8 * 1024 * 1024))

# Public URL phones use when opening QR codes (no trailing slash).
# Example: http://192.168.1.10:5000 or https://maintenance.school.edu
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")

