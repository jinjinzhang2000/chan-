"""
Runtime configuration.

Secrets come from environment variables (or an optional local .env file).
This module is safe to commit: it contains no credentials.
"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

_ROOT = Path(__file__).resolve().parent


def _env(name: str, default: str = "") -> str:
    val = os.environ.get(name)
    return default if val is None else val


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# ── A-share East Money API ──
API_BASE_URL = _env(
    "API_BASE_URL",
    "https://datacenter-web.eastmoney.com/api/data/v1/get",
)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://data.eastmoney.com/",
    "Origin": "https://data.eastmoney.com",
}
PAGE_SIZE = _env_int("PAGE_SIZE", 50)
REQUEST_TIMEOUT = _env_int("REQUEST_TIMEOUT", 15)
DEFAULT_FETCH_DAYS = _env_int("DEFAULT_FETCH_DAYS", 3)
MIN_SCORE = _env_int("MIN_SCORE", 40)

# ── Portfolio ──
PORTFOLIO_FILE = _env(
    "PORTFOLIO_FILE",
    str(_ROOT / "portfolio.txt"),
)
PORTFOLIO_BONUS = _env_int("PORTFOLIO_BONUS", 30)

# ── HKEX Disclosure of Interests ──
HKEX_DI_BASE_URL = _env(
    "HKEX_DI_BASE_URL",
    "https://di.hkex.com.hk/di/NSAllFormList.aspx",
)
# Webb-site Database mirror (CC-BY 4.0). Used when HKEX DI is unavailable.
WEBB_SDI_URL = _env(
    "WEBB_SDI_URL",
    "https://webb-database.com/dbpub/sdilatest.asp",
)
HK_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    "Connection": "keep-alive",
}
HK_MAX_RETRIES = _env_int("HK_MAX_RETRIES", 3)
HK_PAGE_SIZE = _env_int("HK_PAGE_SIZE", 20)
HK_REQUEST_INTERVAL = float(_env("HK_REQUEST_INTERVAL", "1.0") or "1.0")

# ── Email (all optional; leave empty to skip sending) ──
EMAIL_SENDER = _env("EMAIL_SENDER")
EMAIL_PASSWORD = _env("EMAIL_PASSWORD")
EMAIL_RECEIVERS = [
    part.strip()
    for part in _env("EMAIL_RECEIVERS").split(",")
    if part.strip()
]
EMAIL_SMTP_HOST = _env("EMAIL_SMTP_HOST", "smtp.qq.com")
EMAIL_SMTP_PORT = _env_int("EMAIL_SMTP_PORT", 465)
EMAIL_USE_SSL = _env_bool("EMAIL_USE_SSL", True)
