"""IM facade — project-aware wrapper around IMStore.

Provides default sender injection and convenience methods so callers
don't need to pass ``sender=`` on every call.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from open_brain.im.store import IMMessage, IMStore


class IMFacade:
    """Thin wrapper around :class:`IMStore` with project-aware defaults.

    The facade sets ``sender`` automatically from the agent identity
    provided at construction time, eliminating boilerplate for the
    most common posting pattern.
    """

    def __init__(self, store: IMStore, default_sender: str) -> None:
        self._store = store
        self._sender = default_sender

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def post(
        self,
        channel: str,
        content: str,
        *,
        sender: Optional[str] = None,
        msg_type: str = "post",
        correlation_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        sign_fn: Optional[Any] = None,
        ttl_days: Optional[int] = None,
    ) -> IMMessage:
        """Post a message.  Uses *default_sender* when *sender* is ``None``."""
        return self._store.post(
            channel_id=channel,
            sender=sender or self._sender,
            content=content,
            msg_type=msg_type,
            correlation_id=correlation_id,
            metadata=metadata,
            sign_fn=sign_fn,
            ttl_days=ttl_days,
        )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def read(
        self,
        channel: str,
        *,
        limit: int = 50,
        before: Optional[str] = None,
        after: Optional[str] = None,
        sender: Optional[str] = None,
    ) -> List[IMMessage]:
        return self._store.read_channel(
            channel,
            limit=limit,
            before=before,
            after=after,
            sender=sender,
        )

    def recent(self, *, limit: int = 20) -> List[IMMessage]:
        return self._store.read_recent(limit=limit)

    def search(self, query: str, *, limit: int = 20) -> List[IMMessage]:
        return self._store.search(query, limit=limit)

    def thread(self, msg_id: str) -> List[IMMessage]:
        return self._store.read_thread(msg_id)

    def unread(
        self,
        recipient: Optional[str] = None,
        *,
        channel: Optional[str] = None,
    ) -> List[IMMessage]:
        return self._store.get_unread(
            recipient or self._sender,
            channel_id=channel,
        )

    def channels(self) -> List[Dict[str, Any]]:
        return self._store.list_channels()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def create_channel(
        self,
        channel_id: str,
        display_name: str,
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._store.create_channel(channel_id, display_name, metadata=metadata)

    def clear(self, channel: str) -> int:
        return self._store.clear_channel(channel)

    # ------------------------------------------------------------------
    # Internals (exposed for advanced use)
    # ------------------------------------------------------------------

    @property
    def store(self) -> IMStore:
        """Direct access to the underlying store for advanced operations."""
        return self._store
