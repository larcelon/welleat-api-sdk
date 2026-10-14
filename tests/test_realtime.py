"""Tests de contrat du canal temps réel, avec des transports Socket.IO simulés."""

import asyncio
import json
import logging
from collections.abc import Mapping

import pytest

from welleat_api_sdk import (
    CameraCredentials,
    ClientConfig,
    Environment,
    GatewayCredentials,
    RealtimeConnectionError,
)
from welleat_api_sdk.realtime import (
    CameraSocket,
    GatewaySocket,
    ManualCaptureRequest,
    PlugCommand,
    ReconnectPolicy,
    ScaleCommand,
    ScaleCommandFailure,
    ScaleCommandSuccess,
    ScaleCommandType,
    ScaleConnectionState,
    ScaleErrorCode,
    ScaleHeartbeat,
    ScaleWeightUpdate,
    StationHeartbeat,
    SyncCameraSocket,
    SyncGatewaySocket,
    WeightAck,
    WeightRejection,
    parse_scale_weight,
)
from welleat_api_sdk.realtime.transport import AsyncHandler, SyncHandler
from welleat_api_sdk.request import JsonValue

CAMERA = CameraCredentials("cam-1", "k-cam")
STATION = GatewayCredentials("st-1", "k-st")
CAMERA_AUTH = {"cameraId": "cam-1", "api_key": "k-cam"}  # pragma: allowlist secret
STATION_AUTH = {"station_id": "st-1", "api_key": "k-st"}  # pragma: allowlist secret
FAST = ReconnectPolicy(connect_timeout=1.0, retry_interval=0.0)


class FakeAsyncTransport:
    """Transport simulé : chaque élément de `outcomes` dit si la connexion réussit."""

    def __init__(self, outcomes: list[bool] | None = None) -> None:
        self.outcomes = outcomes or []
        self.connected = False
        self.handlers: dict[str, AsyncHandler] = {}
        self.connects: list[tuple[str, dict[str, str], dict[str, str]]] = []
        self.emitted: list[tuple[str, JsonValue]] = []

    def on(self, event: str, handler: AsyncHandler) -> None:
        self.handlers[event] = handler

    async def connect(self, url: str, headers: Mapping[str, str], auth: Mapping[str, str]) -> None:
        self.connects.append((url, dict(headers), dict(auth)))
        if self.outcomes and not self.outcomes.pop(0):
            raise RealtimeConnectionError("refusé")
        self.connected = True
        await self.handlers["connect"]()

    async def emit(self, event: str, data: JsonValue) -> None:
        if not self.connected:
            raise RealtimeConnectionError("déconnecté")
        self.emitted.append((event, data))

    async def wait(self) -> None:
        await self.disconnect()

    async def disconnect(self) -> None:
        if self.connected:
            self.connected = False
            await self.handlers["disconnect"]("io client disconnect")

    async def receive(self, event: str, *args: object) -> None:
        await self.handlers[event](*args)


class FakeSyncTransport:
    """Pendant synchrone de `FakeAsyncTransport`."""

    def __init__(self, outcomes: list[bool] | None = None) -> None:
        self.outcomes = outcomes or []
        self.connected = False
        self.handlers: dict[str, SyncHandler] = {}
        self.connects: list[tuple[str, dict[str, str], dict[str, str]]] = []
        self.emitted: list[tuple[str, JsonValue]] = []

    def on(self, event: str, handler: SyncHandler) -> None:
        self.handlers[event] = handler

    def connect(self, url: str, headers: Mapping[str, str], auth: Mapping[str, str]) -> None:
        self.connects.append((url, dict(headers), dict(auth)))
        if self.outcomes and not self.outcomes.pop(0):
            raise RealtimeConnectionError("refusé")
        self.connected = True
        self.handlers["connect"]()

    def emit(self, event: str, data: JsonValue) -> None:
        if not self.connected:
            raise RealtimeConnectionError("déconnecté")
        self.emitted.append((event, data))

    def wait(self) -> None:
        self.disconnect()

    def disconnect(self) -> None:
        if self.connected:
            self.connected = False
            self.handlers["disconnect"]("io client disconnect")

    def receive(self, event: str, *args: object) -> None:
        self.handlers[event](*args)


# --- Configuration ---------------------------------------------------------------------


def test_realtime_url_strips_api_suffix_or_uses_override() -> None:
    assert ClientConfig().realtime_base_url == "https://welleat-api.welleat.fr"
    dev = ClientConfig(Environment.DEVELOPMENT)
    assert dev.realtime_base_url == "https://welleat-api-dev.welleat.fr"
    custom = ClientConfig(realtime_url="https://ws.example.test/")
    assert custom.realtime_base_url == "https://ws.example.test"


def test_default_policies_follow_the_services() -> None:
    camera = SyncCameraSocket(CAMERA, transport=FakeSyncTransport())
    gateway = SyncGatewaySocket(STATION, transport=FakeSyncTransport())
    assert camera.policy == ReconnectPolicy(retry_interval=5.0)
    assert gateway.policy == ReconnectPolicy(20.0, 10.0, 6)
    assert not ReconnectPolicy().gives_up_after(1000)


# --- Caméra ----------------------------------------------------------------------------


def test_camera_connects_with_auth_then_emits_authenticate() -> None:
    transport = FakeAsyncTransport()
    socket = CameraSocket(CAMERA, ClientConfig(user_agent="ua/1"), transport=transport)
    order: list[str] = []

    async def connected() -> None:
        order.append(f"hook après {len(transport.emitted)} émission(s)")

    socket.on_connect(connected)
    asyncio.run(socket.connect())

    auth = CAMERA_AUTH
    assert transport.connects == [("https://welleat-api.welleat.fr", {"User-Agent": "ua/1"}, auth)]
    assert transport.emitted == [("authenticate", auth)]
    assert order == ["hook après 1 émission(s)"]
    assert socket.connected


def test_camera_decodes_manual_capture_from_object_or_json_string() -> None:
    transport = FakeAsyncTransport()
    socket = CameraSocket(CAMERA, transport=transport)
    received: list[ManualCaptureRequest] = []

    async def handler(request: ManualCaptureRequest) -> None:
        received.append(request)

    socket.on_manual_capture(handler)

    async def scenario() -> None:
        await transport.receive("manual-camera-images-asking", {"TabletId": 7, "x": 1})
        await transport.receive("manual-camera-images-asking", json.dumps({"tablet_id": "t-2"}))
        await transport.receive("manual-camera-images-asking", {"TabletId": ""})
        await transport.receive("manual-camera-images-asking")

    asyncio.run(scenario())
    assert [r.tablet_id for r in received] == [7, "t-2", None, None]
    assert received[0].payload == {"TabletId": 7, "x": 1}


def test_invalid_payload_is_logged_and_ignored(caplog: pytest.LogCaptureFixture) -> None:
    transport = FakeAsyncTransport()
    socket = CameraSocket(CAMERA, transport=transport)
    received: list[ManualCaptureRequest] = []

    async def handler(request: ManualCaptureRequest) -> None:
        received.append(request)

    socket.on_manual_capture(handler)
    with caplog.at_level(logging.WARNING):
        asyncio.run(transport.receive("manual-camera-images-asking", "{pas du json"))
        asyncio.run(transport.receive("manual-camera-images-asking", [1, 2]))
    assert received == []
    assert "JSON invalide" in caplog.text
    assert "objet JSON attendu" in caplog.text


def test_failing_handler_does_not_block_the_next_one(caplog: pytest.LogCaptureFixture) -> None:
    transport = FakeAsyncTransport()
    socket = CameraSocket(CAMERA, transport=transport)
    received: list[object] = []

    async def broken(_message: object) -> None:
        raise ValueError

    async def working(message: object) -> None:
        received.append(message)

    socket.on_camera_connect(broken)
    socket.on_camera_connect(working)
    socket.on_frame_ack(working)
    asyncio.run(transport.receive("camera-connect", "bienvenue"))
    asyncio.run(transport.receive("frame_ack", {"ok": True}))
    assert received == ["bienvenue", {"ok": True}]
    assert "Gestionnaire de camera-connect en échec" in caplog.text


def test_camera_frame_ack_and_emit_requires_connection() -> None:
    transport = FakeAsyncTransport()
    socket = CameraSocket(CAMERA, transport=transport)
    with pytest.raises(RealtimeConnectionError):
        asyncio.run(socket.send_frame_ack())
    asyncio.run(socket.connect())
    asyncio.run(socket.send_frame_ack())
    assert transport.emitted[-1] == ("frame_ack", {"cameraId": "cam-1", "status": "captured"})


def test_sync_camera_mirrors_async_camera() -> None:
    transport = FakeSyncTransport()
    socket = SyncCameraSocket(CAMERA, transport=transport)
    requests: list[ManualCaptureRequest] = []
    messages: list[object] = []
    socket.on_manual_capture(requests.append)
    socket.on_camera_connect(messages.append)
    socket.on_frame_ack(messages.append)

    socket.connect()
    transport.receive("manual-camera-images-asking", '{"TabletId": "t"}')
    transport.receive("camera-connect", "salut")
    transport.receive("frame_ack", None)
    socket.send_frame_ack("failed")

    assert transport.connects[0][2] == CAMERA_AUTH
    assert transport.emitted == [
        ("authenticate", CAMERA_AUTH),
        ("frame_ack", {"cameraId": "cam-1", "status": "failed"}),
    ]
    assert [r.tablet_id for r in requests] == ["t"]
    assert messages == ["salut", None]


# --- Gateway ---------------------------------------------------------------------------


def test_gateway_authenticates_with_station_id_only_in_auth() -> None:
    transport = FakeAsyncTransport()
    socket = GatewaySocket(STATION, transport=transport)
    asyncio.run(socket.connect())
    assert transport.connects[0][2] == STATION_AUTH
    assert transport.emitted == []


def test_gateway_decodes_all_scale_commands() -> None:
    transport = FakeAsyncTransport()
    socket = GatewaySocket(STATION, transport=transport)
    received: list[ScaleCommand] = []

    async def handler(command: ScaleCommand) -> None:
        received.append(command)

    socket.on_scale_command(handler)

    async def scenario() -> None:
        for command in ScaleCommandType:
            await transport.receive(command.value, {"scaleId": 3, "ip": "10.0.0.2"})
        await transport.receive("SCALE_CMD_REBOOT", '{"scaleId": "s-9", "ip": ""}')
        await transport.receive("SCALE_CMD_REBOOT")

    asyncio.run(scenario())
    assert [c.command for c in received[:5]] == list(ScaleCommandType)
    assert received[0] == ScaleCommand(ScaleCommandType.START_STREAM, 3, "10.0.0.2")
    assert received[5] == ScaleCommand(ScaleCommandType.REBOOT, "s-9", None)
    assert len(received) == 6


def test_gateway_tells_weight_acks_from_command_echoes() -> None:
    transport = FakeAsyncTransport()
    socket = GatewaySocket(STATION, transport=transport)
    acks: list[WeightAck] = []
    rejections: list[WeightRejection] = []

    async def on_ack(ack: WeightAck) -> None:
        acks.append(ack)

    async def on_rejection(rejection: WeightRejection) -> None:
        rejections.append(rejection)

    socket.on_weight_ack(on_ack)
    socket.on_weight_rejection(on_rejection)

    async def scenario() -> None:
        await transport.receive("SCALE_CMD_SUCCESS", {"scaleUuid": "u-1", "scaleId": "ignored"})
        await transport.receive("SCALE_CMD_SUCCESS", {"scaleId": 4})
        await transport.receive("SCALE_CMD_SUCCESS", {"scaleId": 4, "original_command": "x"})
        await transport.receive(
            "SCALE_CMD_ERROR", {"error": "SCALE NOT REGISTERED to this station ", "scaleId": 4}
        )
        await transport.receive("SCALE_CMD_ERROR", {"message": "autre", "scaleUuid": "u-1"})
        await transport.receive("SCALE_CMD_ERROR", {"scaleUuid": "u-2"})
        await transport.receive("SCALE_CMD_ERROR", {"scaleId": 4, "original_command": "x"})
        await transport.receive("SCALE_CMD_ERROR", {"scaleId": True})

    asyncio.run(scenario())
    assert [a.scale_id for a in acks] == ["u-1", 4]
    assert [(r.scale_id, r.not_registered) for r in rejections] == [
        (4, True),
        ("u-1", False),
        ("u-2", False),
    ]


def test_gateway_plug_events() -> None:
    transport = FakeAsyncTransport()
    socket = GatewaySocket(STATION, transport=transport)
    commands: list[PlugCommand] = []
    refreshes: list[object] = []

    async def on_command(command: PlugCommand) -> None:
        commands.append(command)

    async def on_refresh(message: object) -> None:
        refreshes.append(message)

    socket.on_plug_command(on_command)
    socket.on_plug_refresh(on_refresh)

    async def scenario() -> None:
        await transport.receive("PLUG_CMD_ON", {"apiPlugId": "p-1"})
        await transport.receive("PLUG_CMD_OFF", '{"apiPlugId": 12}')
        await transport.receive("PLUG_CMD_OFF", {})
        await transport.receive("PLUG REFRESH DATA")

    asyncio.run(scenario())
    assert commands == [PlugCommand("p-1", on=True), PlugCommand(12, on=False)]
    assert refreshes == [None]


def test_gateway_outgoing_events() -> None:
    transport = FakeAsyncTransport()
    socket = GatewaySocket(STATION, transport=transport)
    heartbeat = StationHeartbeat(
        (
            ScaleHeartbeat("u-1", connected=True, stream_active=True, last_weight_kg=1.2345),
            ScaleHeartbeat("u-2", connected=True, stream_active=False, last_weight_kg=3.0),
            ScaleHeartbeat("u-3", connected=False, stream_active=True),
        ),
        timestamp=1700000000.5,
    )

    async def scenario() -> None:
        await socket.connect()
        await socket.send_weight_update(ScaleWeightUpdate(3, "AW 1.234 T 0.1"))
        await socket.send_connection_state(ScaleConnectionState(3, connected=True))
        await socket.send_connection_state(ScaleConnectionState(3, connected=False))
        await socket.send_heartbeat(heartbeat)
        await socket.send_command_success(
            ScaleCommandSuccess(3, ScaleCommandType.TARE_SET, timestamp=1.0)
        )
        await socket.send_command_failure(
            ScaleCommandFailure(
                3, ScaleCommandType.REBOOT, ScaleErrorCode.HARDWARE_FAILURE, "IP introuvable"
            )
        )

    asyncio.run(scenario())
    assert transport.emitted == [
        ("SCALE_STREAM_WEIGHT_UPDATE", {"scaleId": 3, "raw_data": "AW 1.234 T 0.1"}),
        ("SCALE_CONNECTION_STATE", {"scaleId": 3, "state": 1}),
        ("SCALE_CONNECTION_STATE", {"scaleId": 3, "state": 0}),
        (
            "station-heartbeat",
            {
                "scales": [
                    {
                        "scaleUuid": "u-1",
                        "connected": True,
                        "streamActive": True,
                        "lastWeightGrams": 1234,
                    },
                    {
                        "scaleUuid": "u-2",
                        "connected": True,
                        "streamActive": False,
                        "lastWeightGrams": 0,
                    },
                    {
                        "scaleUuid": "u-3",
                        "connected": False,
                        "streamActive": True,
                        "lastWeightGrams": 0,
                    },
                ],
                "timestamp": 1700000000.5,
            },
        ),
        (
            "SCALE_CMD_SUCCESS",
            {"scaleId": 3, "original_command": "SCALE_CMD_TARE_SET", "timestamp": 1.0},
        ),
        (
            "SCALE_CMD_ERROR",
            {
                "scaleId": 3,
                "original_command": "SCALE_CMD_REBOOT",
                "error_code": "SCALE_HARDWARE_FAILURE",
                "message": "IP introuvable",
            },
        ),
    ]


def test_sync_gateway_mirrors_async_gateway() -> None:
    transport = FakeSyncTransport()
    socket = SyncGatewaySocket(STATION, transport=transport)
    received: list[object] = []
    socket.on_scale_command(received.append)
    socket.on_weight_ack(received.append)
    socket.on_weight_rejection(received.append)
    socket.on_plug_command(received.append)
    socket.on_plug_refresh(received.append)

    socket.connect()
    transport.receive("SCALE_CMD_TARE_SET", {"scaleId": 1})
    transport.receive("SCALE_CMD_SUCCESS", {"scaleUuid": "u"})
    transport.receive("SCALE_CMD_ERROR", {"error": "non", "scaleId": 1})
    transport.receive("PLUG_CMD_ON", {"apiPlugId": 5})
    transport.receive("PLUG REFRESH DATA", "go")
    socket.send_weight_update(ScaleWeightUpdate(1, "AW 2"))
    socket.send_connection_state(ScaleConnectionState(1, connected=True))
    socket.send_heartbeat(StationHeartbeat((), timestamp=2.0))
    socket.send_command_success(ScaleCommandSuccess(1, ScaleCommandType.REBOOT, timestamp=3.0))
    socket.send_command_failure(
        ScaleCommandFailure(1, ScaleCommandType.REBOOT, ScaleErrorCode.COMMAND_FAILED, "3 essais")
    )

    assert transport.connects[0][2] == STATION_AUTH
    assert received == [
        ScaleCommand(ScaleCommandType.TARE_SET, 1),
        WeightAck("u", {"scaleUuid": "u"}),
        WeightRejection(1, "non", {"error": "non", "scaleId": 1}),
        PlugCommand(5, on=True),
        "go",
    ]
    assert [event for event, _ in transport.emitted] == [
        "SCALE_STREAM_WEIGHT_UPDATE",
        "SCALE_CONNECTION_STATE",
        "station-heartbeat",
        "SCALE_CMD_SUCCESS",
        "SCALE_CMD_ERROR",
    ]


# --- Poids -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("AW 1.234 T 0.1", 1.134),
        ("AW1.5", 1.5),
        ("\x02AW -0.250 T0.05\r\n", -0.3),
        ("AW +2 T 0.0004", 2.0),
        ("T 0.1", None),
        ("", None),
    ],
)
def test_parse_scale_weight(raw: str, expected: float | None) -> None:
    assert parse_scale_weight(raw) == expected


# --- Reconnexion -----------------------------------------------------------------------


def test_run_gives_up_after_threshold_and_reports_reasons() -> None:
    transport = FakeAsyncTransport([False] * 3)
    policy = ReconnectPolicy(connect_timeout=1.0, retry_interval=0.0, failure_threshold=3)
    socket = GatewaySocket(STATION, policy=policy, transport=transport)
    reasons: list[str] = []
    gave_up: list[bool] = []

    async def on_error(reason: str) -> None:
        reasons.append(reason)

    async def on_give_up() -> None:
        gave_up.append(True)

    socket.on_connect_error(on_error)
    socket.on_give_up(on_give_up)
    asyncio.run(socket.run())
    assert reasons == ["refusé"] * 3
    assert gave_up == [True]


def test_run_resets_failures_after_a_session() -> None:
    transport = FakeAsyncTransport([False, False, True, False, False, False])
    policy = ReconnectPolicy(connect_timeout=1.0, retry_interval=0.0, failure_threshold=3)
    socket = GatewaySocket(STATION, policy=policy, transport=transport)
    events: list[str] = []

    async def on_connect() -> None:
        events.append("connect")

    async def on_disconnect() -> None:
        events.append("disconnect")

    socket.on_connect(on_connect)
    socket.on_disconnect(on_disconnect)
    asyncio.run(socket.run())
    assert len(transport.connects) == 6
    assert events == ["connect", "disconnect"]


def test_stop_ends_run_without_waiting_for_the_retry_interval() -> None:
    transport = FakeAsyncTransport([False, False])
    policy = ReconnectPolicy(connect_timeout=1.0, retry_interval=3600.0)
    socket = CameraSocket(CAMERA, policy=policy, transport=transport)

    async def scenario() -> None:
        task = asyncio.create_task(socket.run())
        await asyncio.sleep(0)
        async with socket:
            pass
        await asyncio.wait_for(task, 1.0)

    asyncio.run(scenario())
    assert len(transport.connects) == 1


def test_stop_disconnects_an_open_session() -> None:
    transport = FakeAsyncTransport()
    socket = CameraSocket(CAMERA, policy=FAST, transport=transport)
    asyncio.run(socket.connect())
    asyncio.run(socket.stop())
    assert not socket.connected


def test_failing_hooks_are_logged(caplog: pytest.LogCaptureFixture) -> None:
    transport = FakeAsyncTransport([False])
    policy = ReconnectPolicy(connect_timeout=1.0, retry_interval=0.0, failure_threshold=1)
    socket = CameraSocket(CAMERA, policy=policy, transport=transport)

    async def broken_error(_reason: str) -> None:
        raise ValueError

    async def broken() -> None:
        raise ValueError

    socket.on_connect_error(broken_error)
    socket.on_give_up(broken)
    socket.on_connect(broken)
    asyncio.run(socket.run())
    asyncio.run(socket.connect())
    assert "Hook on_connect_error en échec" in caplog.text
    assert "Hook on_give_up en échec" in caplog.text
    assert "Hook on_connect en échec" in caplog.text


def test_authenticate_failure_is_logged_without_breaking_connect(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class Unreachable(FakeAsyncTransport):
        async def emit(self, event: str, data: JsonValue) -> None:
            raise RealtimeConnectionError(event)

    socket = CameraSocket(CAMERA, transport=Unreachable())
    asyncio.run(socket.connect())
    assert "Initialisation de la connexion en échec : authenticate" in caplog.text


def test_sync_run_reconnects_then_gives_up() -> None:
    transport = FakeSyncTransport([True, False, False])
    policy = ReconnectPolicy(connect_timeout=1.0, retry_interval=0.0, failure_threshold=2)
    socket = SyncGatewaySocket(STATION, policy=policy, transport=transport)
    events: list[str] = []
    socket.on_connect(lambda: events.append("connect"))
    socket.on_disconnect(lambda: events.append("disconnect"))
    socket.on_connect_error(events.append)
    socket.on_give_up(lambda: events.append("give up"))
    socket.run()
    assert events == ["connect", "disconnect", "refusé", "refusé", "give up"]


def test_sync_stop_from_a_hook_ends_run(caplog: pytest.LogCaptureFixture) -> None:
    transport = FakeSyncTransport([False])
    policy = ReconnectPolicy(connect_timeout=1.0, retry_interval=3600.0)
    socket = SyncCameraSocket(CAMERA, policy=policy, transport=transport)

    def broken() -> None:
        raise ValueError

    def broken_error(_reason: str) -> None:
        raise ValueError

    socket.on_connect_error(broken_error)
    socket.on_connect_error(lambda _reason: socket.stop())
    socket.on_connect(broken)
    socket.run()
    with socket:
        socket.connect()
    assert not socket.connected
    assert "Hook on_connect_error en échec" in caplog.text
    assert "Hook on_connect en échec" in caplog.text


def test_sync_failures_in_handlers_and_authenticate_are_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class Unreachable(FakeSyncTransport):
        def emit(self, event: str, data: JsonValue) -> None:
            raise RealtimeConnectionError(event)

    transport = Unreachable()
    socket = SyncCameraSocket(CAMERA, transport=transport)

    def broken(_message: object) -> None:
        raise ValueError

    socket.on_event("custom", broken)
    socket.connect()
    transport.receive("custom", 1)
    assert "Initialisation de la connexion en échec : authenticate" in caplog.text
    assert "Gestionnaire de custom en échec" in caplog.text


def test_disconnect_hooks_run_once_per_session() -> None:
    transport = FakeAsyncTransport()
    socket = CameraSocket(CAMERA, transport=transport)
    sync_transport = FakeSyncTransport()
    sync_socket = SyncCameraSocket(CAMERA, transport=sync_transport)
    events: list[str] = []

    async def on_disconnect() -> None:
        events.append("async")

    socket.on_disconnect(on_disconnect)
    sync_socket.on_disconnect(lambda: events.append("sync"))

    async def scenario() -> None:
        await socket.connect()
        await transport.receive("disconnect", "server disconnect")
        await transport.receive("disconnect", "client disconnect")

    asyncio.run(scenario())
    sync_socket.connect()
    sync_transport.receive("disconnect", "server disconnect")
    sync_transport.receive("disconnect", "client disconnect")
    assert events == ["async", "sync"]
