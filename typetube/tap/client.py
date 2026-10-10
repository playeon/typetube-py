"""
TapClient wrapper providing automatic reconnection, connection pooling, and retry logic.
Matches src/tap/client.ts.
"""
from __future__ import annotations
import asyncio
from typing import Optional, Union, Dict, Any
from .connection import TapConnection, parse_tap_host
from .protocol import TapOrigin

class TapClient:
    def __init__(
        self,
        target: Optional[str] = None,
        port: int = 8443,
        auth_key: Optional[str] = None,
        origin: int = TapOrigin.TYPETUBE_PY,
        encrypted: Optional[bool] = None,
        server_identity_key: Optional[Union[bytes, str]] = None,
        timeout_ms: int = 15000,
        compression: Optional[bool] = None,
        auto_retry: bool = True,
        socket_path: Optional[str] = None,
        psk: Optional[str] = None
    ) -> None:
        self.target = target or "sg.clusters.typetube.xyz"
        self.port = port
        self.auth_key = auth_key
        self.origin = origin
        self.encrypted = encrypted
        self.server_identity_key = server_identity_key
        self.timeout_ms = timeout_ms
        self.compression = compression
        self.auto_retry = auto_retry
        self.socket_path = socket_path
        self.psk = psk

        self._connection: Optional[TapConnection] = None
        self._is_closed = False
        self._lock = asyncio.Lock()

    async def _acquire_connection(self) -> TapConnection:
        if self._is_closed:
            raise RuntimeError("TapClient is closed")

        if (
            self._connection
            and self._connection.writer
            and not self._connection.writer.is_closing()
            and self._connection.authenticated
            and not self._connection.is_draining
        ):
            return self._connection

        async with self._lock:
            if (
                self._connection
                and self._connection.writer
                and not self._connection.writer.is_closing()
                and self._connection.authenticated
                and not self._connection.is_draining
            ):
                return self._connection

            if self._connection:
                self._connection.close()
                self._connection = None

            conn = TapConnection(
                host=self.target,
                port=self.port,
                url=self.target,
                socket_path=self.socket_path,
                auth_key=self.auth_key,
                psk=self.psk,
                origin=self.origin,
                encrypted=self.encrypted,
                server_identity_key=self.server_identity_key,
                timeout_ms=self.timeout_ms,
                compression=self.compression if self.compression is not None else True
            )
            await conn.connect()
            self._connection = conn
            return conn

    async def invoke(self, method: str, payload: Union[bytes, str, dict] = b"") -> bytes:
        try:
            conn = await self._acquire_connection()
            return await conn.invoke(method, payload)
        except Exception as e:
            if self.auto_retry and not self._is_closed and self._is_transient_error(e):
                if self._connection:
                    self._connection.close()
                    self._connection = None
                retry_conn = await self._acquire_connection()
                return await retry_conn.invoke(method, payload)
            raise e

    async def ping(self) -> float:
        try:
            conn = await self._acquire_connection()
            return await conn.ping()
        except Exception as e:
            if self.auto_retry and not self._is_closed and self._is_transient_error(e):
                if self._connection:
                    self._connection.close()
                    self._connection = None
                retry_conn = await self._acquire_connection()
                return await retry_conn.ping()
            raise e

    def _is_transient_error(self, err: Exception) -> bool:
        msg = str(err)
        if "CONNECTION_TERMINATED" in msg or "UNAUTHORIZED" in msg or "AUTH_REJECTED" in msg:
            return False
        return (
            "TAP Connection closed" in msg
            or "ConnectionResetError" in msg
            or "BrokenPipeError" in msg
            or "ConnectionRefusedError" in msg
        )

    def close(self) -> None:
        self._is_closed = True
        if self._connection:
            self._connection.close()
            self._connection = None
