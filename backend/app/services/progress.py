"""Real-time inspection progress: emission side-channel + pollable store.

The compliance pipeline runs inside ``asyncio.to_thread`` — one OS thread per
HTTP request. A callback is bound to a *thread-local*, so concurrent
inspections can never cross-talk and no shared OCR service instance is
mutated. When no callback is bound, ``emit`` is a cheap no-op: the audit and
all existing callers behave byte-identically.

The store is in-memory with a TTL so the UI can poll a running request and
entries are dropped automatically afterwards.
"""
import threading
import time
from typing import Any, Callable, Dict, List, Optional

_progress_local = threading.local()

_store_lock = threading.Lock()
_store: Dict[str, "_Entry"] = {}
_TTL_SECONDS = 15 * 60


class _Entry:
    __slots__ = ("events", "created", "last_write")

    def __init__(self) -> None:
        self.events: List[Dict[str, Any]] = []
        self.created = time.time()
        self.last_write = self.created


def bind_progress(cb: Optional[Callable[[Dict[str, Any]], None]]) -> Optional[Callable]:
    """Bind a callback for the current thread; returns the previous binding."""
    prev = getattr(_progress_local, "cb", None)
    _progress_local.cb = cb
    return prev


def restore_progress(prev: Optional[Callable]) -> None:
    _progress_local.cb = prev


def emit(stage: str, **data: Any) -> None:
    """Emit a stage event for the current thread's bound callback (no-op otherwise)."""
    cb = getattr(_progress_local, "cb", None)
    if not callable(cb):
        return
    payload: Dict[str, Any] = {"stage": stage, "ts": time.time()}
    payload.update(data)
    try:
        cb(payload)
    except Exception:
        pass


# ── pollable store ──────────────────────────────────────────────────────────

def create(token: str) -> None:
    with _store_lock:
        _store[token] = _Entry()


def append(token: str, payload: Dict[str, Any]) -> None:
    with _store_lock:
        entry = _store.get(token)
        if entry is None:
            entry = _Entry()
            _store[token] = entry
        entry.events.append(payload)
        entry.last_write = time.time()


def get(token: str) -> Optional[List[Dict[str, Any]]]:
    """Return the events for a token, or None if it is unknown/expired."""
    with _store_lock:
        entry = _store.get(token)
        if entry is None:
            return None
        if time.time() - entry.last_write > _TTL_SECONDS and not entry.events:
            del _store[token]
            return None
        return list(entry.events)