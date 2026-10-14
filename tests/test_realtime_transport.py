"""Tests des adaptateurs `python-socketio`, avec la bibliothèque simulée."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
import socketio  # type: ignore[import-untyped]  # python-socketio ne publie pas de py.typed
from pytest_mock import MockerFixture

from welleat_api_sdk import RealtimeConnectionError
from welleat_api_sdk.realtime import RealtimeSocket
from welleat_api_sdk.realtime.transport import (
    SocketIOAsyncTransport,
    SocketIOSyncTransport,
    connect_error_reason,
)


def _handler(sio: MagicMock, event: str) -> object:
    for call in sio.on.call_args_list:
        if call.args[0] == event:
            return call.args[1]
    raise AssertionError(event)


@pytest.fixture
def async_sio(mocker: MockerFixture) -> MagicMock:
    sio = MagicMock(connected=False)
    sio.connect = AsyncMock()
    sio.emit = AsyncMock()
    sio.wait = AsyncMock()
    sio.disconnect = AsyncMock()
    mocker.patch.object(socketio, "AsyncClient", return_value=sio)
    return sio


@pytest.fixture
def sync_sio(mocker: MockerFixture) -> MagicMock:
    sio = MagicMock(connected=False)
    mocker.patch.object(socketio, "Client", return_value=sio)
    return sio


def test_connect_error_reason() -> None:
    assert connect_error_reason({"message": "clé invalide"}) == "clé invalide"
    assert connect_error_reason({"code": 1}) == "{'code': 1}"
    assert connect_error_reason("refus") == "refus"


def test_async_transport_configures_websocket_without_reconnection(async_sio: MagicMock) -> None:
    transport = SocketIOAsyncTransport(20.0)
    socketio.AsyncClient.assert_called_once_with(
        reconnection=False, handle_sigint=False, request_timeout=20.0
    )

    async def handler(*_args: object) -> None:
        return None

    transport.on("evt", handler)
    asyncio.run(transport.connect("https://h", {"User-Agent": "ua"}, {"k": "v"}))
    async_sio.connect.assert_awaited_once_with(
        "https://h",
        headers={"User-Agent": "ua"},
        auth={"k": "v"},
        transports=["websocket"],
        wait_timeout=20.0,
    )
    async_sio.on.assert_any_call("evt", handler)
    async_sio.connected = True
    assert transport.connected
    asyncio.run(transport.emit("evt", {"a": 1}))
    asyncio.run(transport.wait())
    asyncio.run(transport.disconnect())
    async_sio.emit.assert_awaited_once_with("evt", {"a": 1})
    async_sio.wait.assert_awaited_once()
    async_sio.disconnect.assert_awaited_once()


def test_async_transport_reports_server_reason(async_sio: MagicMock) -> None:
    transport = SocketIOAsyncTransport(1.0)
    record = _handler(async_sio, "connect_error")
    assert isinstance(record, type(transport._record_error))

    async def refuse(*_args: object, **_kwargs: object) -> None:
        await transport._record_error({"message": "clé invalide"})
        raise socketio.exceptions.ConnectionError("namespace failed")

    async_sio.connect.side_effect = refuse
    with pytest.raises(RealtimeConnectionError, match="clé invalide"):
        asyncio.run(transport.connect("https://h", {}, {}))

    async_sio.connect.side_effect = socketio.exceptions.ConnectionError("timeout")
    with pytest.raises(RealtimeConnectionError, match="timeout"):
        asyncio.run(transport.connect("https://h", {}, {}))


def test_async_transport_emit_errors(async_sio: MagicMock) -> None:
    transport = SocketIOAsyncTransport(1.0)
    async_sio.emit.side_effect = socketio.exceptions.BadNamespaceError("/")
    with pytest.raises(RealtimeConnectionError, match="evt"):
        asyncio.run(transport.emit("evt", None))


def test_sync_transport_delegates_and_maps_errors(sync_sio: MagicMock) -> None:
    transport = SocketIOSyncTransport(5.0)
    socketio.Client.assert_called_once_with(
        reconnection=False, handle_sigint=False, request_timeout=5.0
    )

    def handler(*_args: object) -> None:
        return None

    transport.on("evt", handler)
    transport.connect("https://h", {}, {"k": "v"})
    sync_sio.connect.assert_called_once_with(
        "https://h", headers={}, auth={"k": "v"}, transports=["websocket"], wait_timeout=5.0
    )
    sync_sio.connected = True
    assert transport.connected
    transport.emit("evt", [1])
    transport.wait()
    transport.disconnect()
    sync_sio.emit.assert_called_once_with("evt", [1])
    sync_sio.wait.assert_called_once()
    sync_sio.disconnect.assert_called_once()

    sync_sio.emit.side_effect = socketio.exceptions.BadNamespaceError("/")
    with pytest.raises(RealtimeConnectionError):
        transport.emit("evt", None)

    def refuse(*_args: object, **_kwargs: object) -> None:
        transport._record_error("non autorisé")
        raise socketio.exceptions.ConnectionError("namespace failed")

    sync_sio.connect.side_effect = refuse
    with pytest.raises(RealtimeConnectionError, match="non autorisé"):
        transport.connect("https://h", {}, {})


def test_generic_socket_requires_a_specialisation(async_sio: MagicMock) -> None:
    socket = RealtimeSocket[object](object())
    assert not socket.connected
    with pytest.raises(NotImplementedError):
        asyncio.run(socket.connect())
    async_sio.connect.assert_not_awaited()
