"""
logger.py — Centralized Logging for Treasury Signal Intelligence
-----------------------------------------------------------------
Replaces all print() calls across the codebase with structured,
leveled logging that writes to console, file, and optionally Telegram.

Usage in any module:
    from logger import get_logger
    logger = get_logger(__name__)

    logger.info("Scan started")
    logger.warning("STRC data stale")
    logger.error("CoinGecko API failed", exc_info=True)
    logger.critical("Database connection lost")

Levels:
    DEBUG    — Verbose internal details (not shown in console by default)
    INFO     — Normal operations: scans, fetches, saves
    WARNING  — Degraded state: using fallback data, stale cache, retries
    ERROR    — Something failed but the system continues
    CRITICAL — System-breaking failures (also sends Telegram alert)
"""

import os
import logging
import traceback
from logging.handlers import RotatingFileHandler
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ============================================
# CONFIGURATION
# ============================================

LOG_DIR = os.getenv("LOG_DIR", "logs")
LOG_FILE = os.path.join(LOG_DIR, "treasury_signals.log")
LOG_LEVEL_CONSOLE = os.getenv("LOG_LEVEL_CONSOLE", "INFO").upper()
LOG_LEVEL_FILE = os.getenv("LOG_LEVEL_FILE", "DEBUG").upper()
LOG_MAX_BYTES = 10 * 1024 * 1024  # 10 MB per log file
LOG_BACKUP_COUNT = 5               # Keep 5 rotated files

# Telegram error alerts (optional)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_ALERT_CHAT_ID = os.getenv("TELEGRAM_PAID_CHANNEL_ID")  # Reuse paid channel for error alerts
TELEGRAM_ERROR_ALERTS = os.getenv("TELEGRAM_ERROR_ALERTS", "true").lower() == "true"

# Ensure log directory exists
os.makedirs(LOG_DIR, exist_ok=True)


# ============================================
# CUSTOM FORMATTER
# ============================================

class TreasuryFormatter(logging.Formatter):
    """
    Clean, readable log format.
    Console: colored level indicators with module context.
    File:    full timestamp + level + module + message.
    """

    LEVEL_ICONS = {
        "DEBUG":    "🔍",
        "INFO":     "ℹ️ ",
        "WARNING":  "⚠️ ",
        "ERROR":    "❌",
        "CRITICAL": "🚨",
    }

    LEVEL_COLORS = {
        "DEBUG":    "\033[90m",     # Gray
        "INFO":     "\033[0m",      # Default
        "WARNING":  "\033[93m",     # Yellow
        "ERROR":    "\033[91m",     # Red
        "CRITICAL": "\033[91;1m",   # Bold Red
    }
    RESET = "\033[0m"

    def __init__(self, use_color=False):
        super().__init__()
        self.use_color = use_color

    def format(self, record):
        timestamp = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        level = record.levelname
        module = record.name.replace("__main__", "main")

        # Shorten module names for readability
        if "." in module:
            module = module.split(".")[-1]

        icon = self.LEVEL_ICONS.get(level, "  ")
        message = record.getMessage()

        if self.use_color:
            color = self.LEVEL_COLORS.get(level, self.RESET)
            formatted = f"{color}{icon} [{module}] {message}{self.RESET}"
        else:
            formatted = f"{timestamp} | {level:<8} | {module:<25} | {message}"

        # Append exception info if present
        if record.exc_info and record.exc_info[0] is not None:
            if not self.use_color:
                formatted += "\n" + self.formatException(record.exc_info)
            else:
                exc_text = self.formatException(record.exc_info)
                formatted += f"\n\033[90m{exc_text}\033[0m"

        return formatted


# ============================================
# TELEGRAM ERROR HANDLER
# ============================================

class TelegramHandler(logging.Handler):
    """
    Sends ERROR and CRITICAL log messages to Telegram.
    Rate-limited to avoid flooding: max 1 message per 60 seconds per module.
    """

    def __init__(self, bot_token, chat_id):
        super().__init__(level=logging.ERROR)
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._last_sent = {}  # module -> timestamp
        self._rate_limit_seconds = 60

    def emit(self, record):
        if not self.bot_token or not self.chat_id:
            return

        # Rate limit: skip if we sent for this module recently
        module = record.name
        now = datetime.now().timestamp()
        last = self._last_sent.get(module, 0)
        if (now - last) < self._rate_limit_seconds:
            return

        try:
            import requests
            level = record.levelname
            icon = "🚨" if level == "CRITICAL" else "❌"
            message = record.getMessage()
            module_short = module.replace("__main__", "main").split(".")[-1]

            exc_text = ""
            if record.exc_info and record.exc_info[0] is not None:
                exc_text = f"\n\nTraceback:\n{traceback.format_exception(*record.exc_info)[-1][:200]}"

            alert = (
                f"{icon} SYSTEM {level}\n\n"
                f"Module: {module_short}\n"
                f"Error: {message[:300]}"
                f"{exc_text}\n\n"
                f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"---\nTreasury Signal Intelligence — Error Monitor"
            )

            requests.post(
                f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                json={"chat_id": self.chat_id, "text": alert},
                timeout=5,
            )
            self._last_sent[module] = now

        except Exception:
            # Never let logging errors crash the application
            pass


# ============================================
# LOGGER FACTORY
# ============================================

# Track which loggers have already been configured
_configured_loggers = set()


def get_logger(name: str) -> logging.Logger:
    """
    Get a configured logger for a module.

    Args:
        name: Typically __name__ from the calling module.

    Returns:
        A logging.Logger instance with console, file, and
        optional Telegram handlers attached.

    Example:
        from logger import get_logger
        logger = get_logger(__name__)
        logger.info("Scanner started")
    """
    logger = logging.getLogger(name)

    # Only configure handlers once per logger
    if name in _configured_loggers:
        return logger

    logger.setLevel(logging.DEBUG)  # Capture everything; handlers filter by level
    logger.propagate = False        # Don't duplicate to root logger

    # Console handler — human-readable with colors
    console = logging.StreamHandler()
    console.setLevel(getattr(logging, LOG_LEVEL_CONSOLE, logging.INFO))
    console.setFormatter(TreasuryFormatter(use_color=True))
    logger.addHandler(console)

    # File handler — detailed, rotated
    try:
        file_handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(getattr(logging, LOG_LEVEL_FILE, logging.DEBUG))
        file_handler.setFormatter(TreasuryFormatter(use_color=False))
        logger.addHandler(file_handler)
    except Exception as e:
        # If file logging fails (permissions, etc.), continue with console only
        logger.warning(f"Could not set up file logging: {e}")

    # Telegram handler — errors and critical only
    if TELEGRAM_ERROR_ALERTS and TELEGRAM_BOT_TOKEN and TELEGRAM_ALERT_CHAT_ID:
        telegram = TelegramHandler(TELEGRAM_BOT_TOKEN, TELEGRAM_ALERT_CHAT_ID)
        logger.addHandler(telegram)

    _configured_loggers.add(name)
    return logger


# ============================================
# CONVENIENCE: SCAN CONTEXT MANAGER
# ============================================

class ScanContext:
    """
    Context manager for wrapping scan cycles with automatic
    start/end logging and error capture.

    Usage:
        with ScanContext(logger, scan_number=5, step="Fetching tweets"):
            # your code here
            # errors are automatically logged with full context
    """

    def __init__(self, logger, scan_number=None, step=""):
        self.logger = logger
        self.scan_number = scan_number
        self.step = step
        self.start_time = None

    def __enter__(self):
        self.start_time = datetime.now()
        prefix = f"Scan #{self.scan_number} | " if self.scan_number else ""
        self.logger.info(f"{prefix}{self.step}...")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed = (datetime.now() - self.start_time).total_seconds()
        prefix = f"Scan #{self.scan_number} | " if self.scan_number else ""

        if exc_type is not None:
            self.logger.error(
                f"{prefix}{self.step} FAILED after {elapsed:.1f}s: {exc_val}",
                exc_info=(exc_type, exc_val, exc_tb),
            )
            # Return True to suppress the exception and continue the scan
            return True
        else:
            self.logger.debug(f"{prefix}{self.step} completed in {elapsed:.1f}s")
            return False


# ============================================
# QUICK TEST
# ============================================
if __name__ == "__main__":
    logger = get_logger("test")

    logger.debug("This is a DEBUG message (console hidden by default, written to file)")
    logger.info("Scanner started — monitoring 24 accounts")
    logger.warning("CoinGecko returned stale data, using cached leaderboard")
    logger.error("SEC EDGAR API returned 503 — retrying in 60s")

    try:
        result = 1 / 0
    except Exception as e:
        logger.error(f"Division by zero in test: {e}", exc_info=True)

    logger.critical("Database connection lost — all writes failing")

    # Test ScanContext
    with ScanContext(logger, scan_number=1, step="Test step"):
        logger.info("Inside scan context")

    with ScanContext(logger, scan_number=2, step="Failing step"):
        raise ValueError("Simulated failure")

    logger.info("Test complete — logger is working")
