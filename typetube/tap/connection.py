"""
TAP TCP Connection manager handling asynchronous multiplexing over a single persistent socket.
Matches src/tap/connection.ts.
"""
from __future__ import annotations
import asyncio
import os
import struct
import time
import socket
from typing import Optional, Dict, Any, Union
from urllib.parse import urlparse

from .protocol import (
    TAP_HEADER_SIZE,
    TapOrigin,
    TapIntent,
    TapFlags,
    TapFrame,
    encode_frame,
    get_frame_header_aad
)
from .parser import StreamParser
from .compression import decompress_payload
from .crypto import (
    TapCryptoSession,
    generate_ecdh_key_pair,
    compute_shared_secret,
    compute_handshake_proof,
    verify_handshake_proof,
    verify_signature
)


def parse_tap_host(target: str, default_port: int = 8443) -> tuple[str, int]:
    cleaned = target.strip()
    if cleaned.startswith("tap://"):
        cleaned = cleaned[6:]
    if "/" in cleaned:
        cleaned = cleaned.split("/", 1)[0]
    if cleaned.startswith("[") and "]" in cleaned:
        end = cleaned.index("]")
        host = cleaned[1:end]
        rest = cleaned[end + 1:]
        if rest.startswith(":"):
            try:
                return host, int(rest[1:])
            except ValueError:
                return host, default_port
        return host, default_port
    if ":" in cleaned:
        parts = cleaned.split(":")
        if len(parts) == 2:
            try:
                return parts[0], int(parts[1])
            except ValueError:
                return parts[0], default_port
    return cleaned, default_port


class PendingRequest:
    def __init__(self, trace_id: int, future: asyncio.Future[bytes], start_time: float) -> None:
        self.trace_id = trace_id
        self.future = future
        self.start_time = start_time


class TapConnection:
    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        url: Optional[str] = None,
        socket_path: Optional[str] = None,
        auth_key: Optional[str] = None,
        psk: Optional[str] = None,
        origin: int = TapOrigin.TYPETUBE_PY,
        encrypted: Optional[bool] = None,
        server_identity_key: Optional[Union[bytes, str]] = None,
        timeout_ms: int = 15000,
        compression: bool = True
    ) -> None:
        self.auth_key = auth_key
        self.psk = psk
        self.origin = origin
        self.server_identity_key = server_identity_key
        self.timeout_ms = timeout_ms
        self.compression = compression

        raw_target = url or host or ""
        default_sock = os.environ.get("TYPETUBE_TAP_SOCKET", "/tmp/typetube-tap.sock")

        if socket_path:
            self.target_socket_path: Optional[str] = socket_path
            self.target_host = "unix"
            self.target_port = 0
        elif raw_target.startswith("tap:///") or raw_target.startswith("unix://") or (raw_target.startswith("/") and not raw_target.startswith("//")):
            self.target_socket_path = (
                raw_target[6:] if raw_target.startswith("tap:///")
                else raw_target[7:] if raw_target.startswith("unix://")
                else raw_target
            )
            self.target_host = "unix"
            self.target_port = 0
        else:
            p_host, p_port = parse_tap_host(raw_target or "sg.clusters.typetube.xyz", port or 8443)
            is_local = p_host in ("127.0.0.1", "localhost", "::1")
            if is_local and (os.path.exists(default_sock) or os.environ.get("TYPETUBE_TAP_FORCE_SOCKET") == "true"):
                self.target_socket_path = default_sock
                self.target_host = "unix"
                self.target_port = 0
            else:
                self.target_socket_path = None
                self.target_host = p_host
                self.target_port = port or p_port

        is_localhost = bool(self.target_socket_path) or self.target_host in ("localhost", "127.0.0.1", "::1")
        self.encrypted = encrypted if encrypted is not None else (not is_localhost)
        if compression is None:
            self.compression = not is_localhost

        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.authenticated = False
        self.active_requests = 0
        self.last_active_at = time.time()
        self.crypto_session: Optional[TapCryptoSession] = None
        self.is_permanently_revoked = False
        self.is_draining = False

        self._parser = StreamParser()
        self._pending: Dict[int, PendingRequest] = {}
        self._trace_counter = 1
        self._connect_lock = asyncio.Lock()
        self._read_task: Optional[asyncio.Task[None]] = None

    def _next_trace_id(self) -> int:
        tid = self._trace_counter
        self._trace_counter += 1
        if self._trace_counter > 65535:
            self._trace_counter = 1
        return tid

    async def connect(self) -> None:
        if self.writer and not self.writer.is_closing() and self.authenticated:
            return

        async with self._connect_lock:
            if self.writer and not self.writer.is_closing() and self.authenticated:
                return

            timeout_sec = self.timeout_ms / 1000.0

            async def _do_connect() -> None:
                if self.target_socket_path:
                    reader, writer = await asyncio.open_unix_connection(self.target_socket_path)
                else:
                    reader, writer = await asyncio.open_connection(self.target_host, self.target_port)

                # TCP_NODELAY and QuickACK optimizations
                sock = writer.get_extra_info("socket")
                if sock and hasattr(sock, "setsockopt"):
                    try:
                        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                        # TCP_QUICKACK on Linux
                        quickack_opt = getattr(socket, "TCP_QUICKACK", 12)
                        sock.setsockopt(socket.IPPROTO_TCP, quickack_opt, 1)
                    except Exception:
                        pass

                self.reader = reader
                self.writer = writer
                self.authenticated = False
                self.crypto_session = None
                self._parser.reset()

                # Start reader loop
                self._read_task = asyncio.create_task(self._reader_loop())

                if self.encrypted:
                    await self._execute_negotiation()

                if self.auth_key:
                    await self._execute_auth_handshake(self.auth_key)

                self.authenticated = True

            try:
                await asyncio.wait_for(_do_connect(), timeout=timeout_sec)
            except Exception as e:
                self.close()
                raise ConnectionError(f"TAP connect/handshake failed: {e}") from e

    async def _reader_loop(self) -> None:
        reader = self.reader
        try:
            while reader and not reader.at_eof():
                chunk = await reader.read(65536)
                if not chunk:
                    break
                self.last_active_at = time.time()
                self._parser.push(chunk)
                while True:
                    frame = self._parser.next_frame()
                    if not frame:
                        break
                    self._handle_incoming_frame(frame)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self._cleanup_pending(ConnectionError(f"Protocol parsing or socket error: {e}"))
        finally:
            self.authenticated = False
            self.crypto_session = None
            self._cleanup_pending(ConnectionError("TAP Connection closed"))

    def _handle_incoming_frame(self, frame: TapFrame) -> None:
        intent = frame.intent
        trace_id = frame.trace_id
        flags = frame.flags
        payload = frame.payload

        if (flags & TapFlags.ENCRYPTED) != 0:
            if not self.crypto_session:
                self._cleanup_pending(RuntimeError("Received encrypted frame without negotiated session"))
                self.close()
                return
            try:
                aad = get_frame_header_aad(frame.origin, intent, flags, trace_id, len(payload))
                payload = self.crypto_session.decrypt(payload, aad)
            except Exception as e:
                self._cleanup_pending(RuntimeError(f"Decryption / AAD verification failed: {e}"))
                self.close()
                return

        if intent == TapIntent.GOAWAY:
            self.is_draining = True
            return

        if intent == TapIntent.DISCONNECT:
            self.is_permanently_revoked = True
            reason = payload.decode("utf-8", errors="replace")
            self._cleanup_pending(PermissionError(f"CONNECTION_TERMINATED: {reason}"))
            self.close()
            return

        req = self._pending.pop(trace_id, None)
        if not req:
            return

        self.active_requests = max(0, self.active_requests - 1)

        if (flags & TapFlags.COMPRESSED) != 0:
            try:
                payload = decompress_payload(payload)
            except Exception as e:
                req.future.set_exception(RuntimeError(f"Decompression failed: {e}"))
                return

        if (flags & TapFlags.ERROR) != 0:
            err_msg = payload.decode("utf-8", errors="replace")
            req.future.set_exception(RuntimeError(err_msg))
        else:
            req.future.set_result(payload)

    async def _execute_negotiation(self) -> None:
        ecdh_key, client_public_bytes = generate_ecdh_key_pair()
        trace_id = self._next_trace_id()

        loop = asyncio.get_running_loop()
        future: asyncio.Future[bytes] = loop.create_future()
        self._pending[trace_id] = PendingRequest(trace_id, future, time.time())

        client_psk = self.psk or self.auth_key
        if client_psk:
            client_proof = compute_handshake_proof(client_psk, client_public_bytes)
            request_payload = struct.pack(">H", len(client_public_bytes)) + client_public_bytes + client_proof
        else:
            request_payload = client_public_bytes

        frame = encode_frame(TapIntent.NEGOTIATE, trace_id, TapFlags.REQUEST, request_payload, self.origin)
        self.writer.write(frame)
        await self.writer.drain()

        response_payload = await future

        server_public_key: bytes
        server_proof: Optional[bytes] = None

        if self.server_identity_key:
            expected_key_der = bytes.fromhex(self.server_identity_key) if isinstance(self.server_identity_key, str) else self.server_identity_key
            if len(response_payload) < 4:
                raise ValueError("Server response too short for signed negotiation")
            offset = 0
            pub_key_len = struct.unpack_from(">H", response_payload, offset)[0]
            offset += 2
            server_public_key = response_payload[offset : offset + pub_key_len]
            offset += pub_key_len
            sig_len = struct.unpack_from(">H", response_payload, offset)[0]
            offset += 2
            signature = response_payload[offset : offset + sig_len]
            offset += sig_len
            if len(response_payload) >= offset + 32:
                server_proof = response_payload[offset : offset + 32]
            
            data_to_verify = server_public_key + client_public_bytes
            if not verify_signature(expected_key_der, data_to_verify, signature):
                raise SecurityError("SECURITY_ALERT: Server identity signature verification failed.")
        else:
            if len(response_payload) > 70 and struct.unpack_from(">H", response_payload, 0)[0] == 65:
                pub_key_len = struct.unpack_from(">H", response_payload, 0)[0]
                server_public_key = response_payload[2 : 2 + pub_key_len]
                offset = 2 + pub_key_len
                if len(response_payload) >= offset + 2:
                    sig_len = struct.unpack_from(">H", response_payload, offset)[0]
                    offset += 2 + sig_len
                    if len(response_payload) >= offset + 32:
                        server_proof = response_payload[offset : offset + 32]
                elif len(response_payload) >= 2 + pub_key_len + 32:
                    server_proof = response_payload[2 + pub_key_len : 2 + pub_key_len + 32]
            elif len(response_payload) == 65 + 32:
                server_public_key = response_payload[:65]
                server_proof = response_payload[65 : 65 + 32]
            else:
                server_public_key = response_payload

        psk = self.psk
        if psk:
            expected_proof_data = server_public_key + client_public_bytes
            if not server_proof or not verify_handshake_proof(psk, expected_proof_data, server_proof):
                raise SecurityError("SECURITY_ALERT: Server handshake PSK proof verification failed.")
        elif server_proof and self.auth_key:
            expected_proof_data = server_public_key + client_public_bytes
            if not verify_handshake_proof(self.auth_key, expected_proof_data, server_proof):
                raise SecurityError("SECURITY_ALERT: Server handshake PSK proof verification failed.")

        shared_secret = compute_shared_secret(ecdh_key, server_public_key)
        binding_key = psk or (self.auth_key if server_proof else None)
        self.crypto_session = TapCryptoSession(shared_secret, is_server=False, psk=binding_key)

    async def _execute_auth_handshake(self, token: str) -> None:
        trace_id = self._next_trace_id()
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bytes] = loop.create_future()
        self._pending[trace_id] = PendingRequest(trace_id, future, time.time())

        payload = token.encode("utf-8")
        self._write_frame(TapIntent.AUTH, trace_id, TapFlags.REQUEST, payload)
        await self.writer.drain()

        await future

    def _write_frame(self, intent: int, trace_id: int, flags: int, payload: bytes) -> None:
        if not self.writer or self.writer.is_closing():
            raise ConnectionError("TAP socket is not writable")

        if self.crypto_session:
            flags |= TapFlags.ENCRYPTED
            encrypted_len = len(payload) + 16
            aad = get_frame_header_aad(self.origin, intent, flags, trace_id, encrypted_len)
            encrypted_payload = self.crypto_session.encrypt(payload, aad)
            data = encode_frame(intent, trace_id, flags, encrypted_payload, self.origin)
        else:
            data = encode_frame(intent, trace_id, flags, payload, self.origin)

        self.writer.write(data)

    async def invoke(self, method: str, payload: Union[bytes, str, dict] = b"") -> bytes:
        if self.is_permanently_revoked:
            raise PermissionError("TAP Connection has been permanently revoked by the server")

        if not self.authenticated or not self.writer or self.writer.is_closing():
            await self.connect()

        method_bytes = method.encode("utf-8")
        if len(method_bytes) > 255:
            raise ValueError("TAP method name cannot exceed 255 bytes")

        if isinstance(payload, bytes):
            payload_bytes = payload
        elif isinstance(payload, str):
            payload_bytes = payload.encode("utf-8")
        else:
            import json
            payload_bytes = json.dumps(payload).encode("utf-8")

        packet_payload = bytes([len(method_bytes)]) + method_bytes + payload_bytes

        trace_id = self._next_trace_id()
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bytes] = loop.create_future()
        self._pending[trace_id] = PendingRequest(trace_id, future, time.time())
        self.active_requests += 1
        self.last_active_at = time.time()

        flags = TapFlags.REQUEST if not self.compression else (TapFlags.REQUEST | TapFlags.ACCEPT_COMPRESSED)
        self._write_frame(TapIntent.RPC_CALL, trace_id, flags, packet_payload)
        await self.writer.drain()

        timeout_sec = self.timeout_ms / 1000.0
        try:
            return await asyncio.wait_for(future, timeout=timeout_sec)
        except asyncio.TimeoutError:
            self._pending.pop(trace_id, None)
            self.active_requests = max(0, self.active_requests - 1)
            raise TimeoutError(f"TAP RPC invoke '{method}' timed out after {self.timeout_ms}ms")

    async def ping(self) -> float:
        if not self.authenticated or not self.writer or self.writer.is_closing():
            await self.connect()

        trace_id = self._next_trace_id()
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bytes] = loop.create_future()
        t0 = time.perf_counter()
        self._pending[trace_id] = PendingRequest(trace_id, future, t0)

        self._write_frame(TapIntent.PING, trace_id, TapFlags.REQUEST, b"")
        await self.writer.drain()

        try:
            await asyncio.wait_for(future, timeout=5.0)
            return (time.perf_counter() - t0) * 1000.0
        except asyncio.TimeoutError:
            self._pending.pop(trace_id, None)
            raise TimeoutError("TAP Ping timed out after 5000ms")

    def _cleanup_pending(self, exc: Exception) -> None:
        for p in list(self._pending.values()):
            if not p.future.done():
                p.future.set_exception(exc)
        self._pending.clear()
        self.active_requests = 0

    def close(self) -> None:
        if self._read_task:
            self._read_task.cancel()
            self._read_task = None
        if self.writer:
            try:
                self.writer.close()
            except Exception:
                pass
            self.writer = None
        self.reader = None
        self.authenticated = False
        self.crypto_session = None
        self._cleanup_pending(ConnectionError("TAP Connection closed by client"))


class SecurityError(Exception):
    pass
