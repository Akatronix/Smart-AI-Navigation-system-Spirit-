"""
Groq model manager: picks the best available chat model at runtime so a
deprecated or removed model never takes Spirit down.
"""

import logging
import os
import re
import threading
import time

logger = logging.getLogger("spirit.models")

# Curated starting points, best first. A model is only used if Groq currently
# lists it. When all of these are gone, models are ranked automatically by size.
SMART_PREFERENCE = [
    "openai/gpt-oss-120b",
    "llama-3.3-70b-versatile",
    "qwen/qwen3-32b",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "openai/gpt-oss-20b",
]
FAST_PREFERENCE = [
    "openai/gpt-oss-20b",
    "llama-3.1-8b-instant",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "llama-3.3-70b-versatile",
]

_NON_CHAT_RE = re.compile(
    r"whisper|tts|playai|orpheus|guard|safeguard|embed|compound|moderation|transcri", re.I)
_SIZE_RE = re.compile(r"(?<![a-z0-9.])(\d+(?:\.\d+)?)b(?![a-z])", re.I)
_DEPRIORITIZE_RE = re.compile(r"allam", re.I)


class NoModelAvailableError(RuntimeError):
    pass


def is_model_gone(error) -> bool:
    """True if the error means 'this model no longer exists / is not usable'."""
    status = getattr(error, "status_code", None)
    text = str(error).lower()
    if status == 404:
        return True
    if status == 400 and any(h in text for h in (
            "decommission", "no longer supported", "model_not_found",
            "does not exist", "deprecated")):
        return True
    if status == 403 and "model" in text:
        return True
    return False


def _size_b(model_id: str):
    sizes = [float(s) for s in _SIZE_RE.findall(model_id)]
    return max(sizes) if sizes else None


# def _rank_rest(models, tier: str):
#     def key(m):
#         s = _size_b(m)
#         if tier == "smart":
#             return (s is None, -(s or 0), m)          # biggest first, unknown last
#         if s is None:
#             return (2, 0, m)
#         if s >= 7:
#             return (0, s, m)                          # smallest capable first
#         return (1, -s, m)
#     return sorted(models, key=key)


def _rank_rest(models, tier: str):
    def key(m):
        penalty = 1 if _DEPRIORITIZE_RE.search(m) else 0   # deprioritized models go last
        s = _size_b(m)
        if tier == "smart":
            return (penalty, s is None, -(s or 0), m)      # biggest first, unknown last
        if s is None:
            return (penalty, 2, 0, m)
        if s >= 7:
            return (penalty, 0, s, m)                      # smallest capable first
        return (penalty, 1, -s, m)
    return sorted(models, key=key)




class ModelManager:
    REFRESH_INTERVAL_SEC = 6 * 3600
    RETRY_AFTER_FAILED_REFRESH_SEC = 60
    DEAD_TTL_SEC = 3600

    def __init__(self, client):
        self._client = client
        self._lock = threading.Lock()
        self._available = None        # None = list not fetched yet
        self._dead = {}               # model -> expiry (monotonic)
        self._no_reasoning = set()
        self._last_used = {}
        self._next_refresh = 0.0
        self._refreshing = False
        self._override = {
            "fast": os.environ.get("GROQ_FAST_MODEL", "").strip() or None,
            "smart": os.environ.get("GROQ_SMART_MODEL", "").strip() or None,
        }

    # ------------------------------------------------------------------
    def refresh(self) -> bool:
        try:
            listing = self._client.with_options(timeout=6.0).models.list()
            ids = {m.id for m in listing.data if getattr(m, "active", True)}
        except Exception as e:
            logger.warning("Could not fetch Groq model list: %s", e)
            with self._lock:
                self._next_refresh = time.monotonic() + self.RETRY_AFTER_FAILED_REFRESH_SEC
            return False

        chat_ids = {i for i in ids if not _NON_CHAT_RE.search(i)}
        with self._lock:
            self._available = chat_ids
            self._next_refresh = time.monotonic() + self.REFRESH_INTERVAL_SEC
        logger.info("Groq chat models available (%d): %s", len(chat_ids), sorted(chat_ids))
        return True

    def refresh_async(self, force: bool = False):
        with self._lock:
            if self._refreshing:
                return
            if not force and time.monotonic() < self._next_refresh:
                return
            self._refreshing = True

        def run():
            try:
                self.refresh()
            finally:
                with self._lock:
                    self._refreshing = False

        threading.Thread(target=run, daemon=True, name="spirit-model-refresh").start()

    # ------------------------------------------------------------------
    def candidates(self, tier: str) -> list:
        """Usable models for this tier, best first."""
        self.refresh_async()      # cheap no-op unless the periodic refresh is due
        now = time.monotonic()
        with self._lock:
            self._dead = {m: t for m, t in self._dead.items() if t > now}
            dead = set(self._dead)
            available = None if self._available is None else set(self._available)
            override = self._override.get(tier)

        ordered = []

        def add(model):
            if model and model not in dead and model not in ordered:
                ordered.append(model)

        if override and (available is None or override in available):
            add(override)
        for model in (SMART_PREFERENCE if tier == "smart" else FAST_PREFERENCE):
            if available is None or model in available:
                add(model)
        if available:
            for model in _rank_rest(available - set(ordered) - dead, tier):
                add(model)
        return ordered

    def mark_dead(self, model: str):
        with self._lock:
            self._dead[model] = time.monotonic() + self.DEAD_TTL_SEC
        logger.warning("Model '%s' is no longer available. Switching to the next best.", model)
        self.refresh_async(force=True)

    def note_success(self, tier: str, model: str):
        previous = self._last_used.get(tier)
        if previous == model:
            return
        self._last_used[tier] = model
        if previous is None:
            logger.info("Using %s for the %s tier.", model, tier)
        else:
            logger.warning("Model for the %s tier changed: %s -> %s", tier, previous, model)

    # ------------------------------------------------------------------
    def supports_reasoning(self, model: str) -> bool:
        return "gpt-oss" in model and model not in self._no_reasoning

    def mark_no_reasoning(self, model: str):
        self._no_reasoning.add(model)