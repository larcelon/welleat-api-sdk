"""Tests de contrat des clients, avec un transport httpx simulé."""

import asyncio
import json
from datetime import UTC, datetime

import httpx
import pytest

from welleat_api_sdk import (
    ApiError,
    CameraClient,
    CameraCredentials,
    ClientConfig,
    EnrollmentSecrets,
    Environment,
    GatewayCredentials,
    NetworkError,
    NotEnrolledError,
    ResponseFormatError,
    ServerError,
    SyncCameraClient,
    SyncGatewayClient,
)
from welleat_api_sdk.models import (
    ChefFramePayload,
    ChefImage,
    Detection,
    DeviceInfo,
    FramePayload,
    MultiCamOptions,
    PlugConfig,
    ReportPayload,
    ScaleRegistration,
    SensorReading,
)

CAMERA = CameraCredentials("cam 1", "k-cam")
STATION = GatewayCredentials("st-1", "k-st")
SECRETS = EnrollmentSecrets("global-key", "global-secret")
DEVICE = DeviceInfo("AA:BB:CC:DD:EE:FF", "host")


class Recorder:
    """Transport simulé qui mémorise les requêtes et rejoue une réponse."""

    def __init__(self, response: httpx.Response | None = None) -> None:
        self.response = response or httpx.Response(200, json={})
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.response

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]

    def body(self) -> dict[str, object]:
        loaded: dict[str, object] = json.loads(self.last.content)
        return loaded


def camera(rec: Recorder, creds: CameraCredentials | None = CAMERA) -> SyncCameraClient:
    http = httpx.Client(transport=httpx.MockTransport(rec))
    return SyncCameraClient(ClientConfig(), creds, http=http)


def gateway(rec: Recorder, creds: GatewayCredentials | None = STATION) -> SyncGatewayClient:
    http = httpx.Client(transport=httpx.MockTransport(rec))
    config = ClientConfig(environment=Environment.DEVELOPMENT)
    return SyncGatewayClient(config, creds, http=http)


def test_connect_camera_sends_enrollment_headers_and_returns_credentials() -> None:
    rec = Recorder(httpx.Response(200, json={"cameraId": "c9", "api_key": "k9"}))
    creds = camera(rec, None).connect_camera(SECRETS, DEVICE)
    assert creds == CameraCredentials("c9", "k9")
    assert str(rec.last.url) == "https://welleat-api.welleat.fr/api/cameras/connectCamera/"
    assert rec.last.headers["api-secret"] == "global-secret"  # pragma: allowlist secret
    assert rec.last.headers["x-device-mac"] == "AA:BB:CC:DD:EE:FF"
    assert rec.last.content == b""


def test_send_frame_puts_credentials_in_body_only() -> None:
    rec = Recorder()
    frame = FramePayload(
        "data:image/jpeg;base64,xx", "f.jpg", (Detection("tray", 0.9, (1, 2, 3, 4), 3),)
    )
    camera(rec).send_frame(frame)
    assert rec.body()["cameraId"] == "cam 1"
    assert rec.body()["api_key"] == "k-cam"  # pragma: allowlist secret
    assert "api-key" not in rec.last.headers
    assert rec.body()["detections"] == [
        {"label": "tray", "confidence": 0.9, "bbox": [1, 2, 3, 4], "track_id": 3}
    ]


def test_multicam_adds_headers_fields_and_accepts_conflict() -> None:
    rec = Recorder(httpx.Response(409, text="dup"))
    options = MultiCamOptions(
        "g1", source_camera_id="c2", rig_id="r", quality_score=0.4, quality_low=True
    )
    camera(rec).send_frame(FramePayload("i", "n.jpg"), options)
    assert rec.last.headers["idempotency-key"] == "g1"
    assert rec.last.headers["x-welleat-global-tray-id"] == "g1"
    assert rec.body()["sourceCameraId"] == "c2"
    assert rec.body()["quality_low"] is True


def test_send_frame_conflict_is_an_error_without_multicam() -> None:
    with pytest.raises(ApiError) as info:
        camera(Recorder(httpx.Response(409, text="dup"))).send_frame(FramePayload("i", "n.jpg"))
    assert info.value.status == 409


def test_tray_count_requires_ack_text() -> None:
    rec = Recorder(httpx.Response(200, text="Count save"))
    camera(rec).tray_count()
    assert rec.last.url.raw_path.decode() == "/api/cameras/trayCount/cam%201"
    assert rec.last.headers["api-key"] == "k-cam"
    assert rec.last.content == b""
    with pytest.raises(ApiError):
        camera(Recorder(httpx.Response(200, text="ok"))).tray_count()


def test_tray_count_multicam_accepts_conflict() -> None:
    camera(Recorder(httpx.Response(409))).tray_count(MultiCamOptions("g1"))


def test_chef_frames_use_tablet_id_and_json_headers() -> None:
    rec = Recorder()
    camera(rec).send_control_frames(ChefFramePayload(12, (ChefImage("i", "n.jpg"),)))
    assert rec.body()["TabletId"] == 12
    assert rec.last.headers["accept"] == "application/json"


def test_report_and_monitoring_verbs_and_paths() -> None:
    rec = Recorder(httpx.Response(204))
    client = camera(rec)
    client.state_update(True)
    assert (rec.last.method, rec.last.url.raw_path.decode()) == (
        "PUT",
        "/api/cameras/StateUpdate/cam%201",
    )
    assert rec.body() == {"state": 1}
    client = camera(Recorder())
    client.temp_tracking(41.26, "1.2.3")
    assert client.credentials is CAMERA
    rec = Recorder()
    camera(rec).temp_tracking(41.26, "1.2.3")
    assert rec.last.url.raw_path.decode() == "/api/cameras/temptracking/cam%201"
    assert rec.body() == {"temperature": 41.3, "softVersion": "1.2.3"}
    camera(rec).report(ReportPayload(None, 42))
    assert rec.body() == {"lastImageDate": None, "imageCount": 42}
    camera(rec).speed_perf(1000)
    assert rec.last.url.raw_path.decode() == "/api/cameras/SpeedPerfs/cam%201"


@pytest.mark.parametrize(
    "payload",
    [
        {"ServiceSlotId": "12", "schedules": ["11:00", "15:00"]},
        [{"ServiceSlotId": 12, "schedules": ["11:00", "15:00"]}],
    ],
)
def test_service_slots_accept_object_or_list(payload: object) -> None:
    slots = camera(Recorder(httpx.Response(200, json=payload))).service_slots()
    assert [(s.service_slot_id, s.schedules) for s in slots] == [(12, ("11:00", "15:00"))]


def test_service_slots_reject_boolean_id() -> None:
    reply = httpx.Response(200, json={"ServiceSlotId": True, "schedules": []})
    with pytest.raises(ResponseFormatError):
        camera(Recorder(reply)).service_slots()


def test_last_chef_image_is_unauthenticated_and_lenient() -> None:
    rec = Recorder(httpx.Response(200, json={"timestamp": 86400}))
    assert camera(rec).last_chef_image() == datetime(1970, 1, 2, tzinfo=UTC)
    assert "api-key" not in rec.last.headers
    assert camera(Recorder(httpx.Response(200, json={}))).last_chef_image() is None


def test_authenticated_call_without_credentials_raises() -> None:
    with pytest.raises(NotEnrolledError):
        camera(Recorder(), None).tray_count()


@pytest.mark.parametrize(
    ("status", "error"), [(500, ServerError), (429, ServerError), (400, ApiError)]
)
def test_error_statuses(status: int, error: type[ApiError]) -> None:
    with pytest.raises(error):
        camera(Recorder(httpx.Response(status, text="x"))).report(ReportPayload(None, 1))


def test_transport_failure_is_network_error() -> None:
    def boom(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow")

    http = httpx.Client(transport=httpx.MockTransport(boom))
    with pytest.raises(NetworkError):
        SyncCameraClient(ClientConfig(), CAMERA, http=http).tray_count()


def test_gateway_header_modes() -> None:
    rec = Recorder(httpx.Response(200, json={"apiSensorId": "s1"}))
    client = gateway(rec)
    assert str(rec.requests) == "[]"
    assert client.add_sensor("BLE-1") == "s1"
    assert rec.last.url.host == "welleat-api-dev.welleat.fr"
    assert rec.last.headers["apistationid"] == "st-1"
    client.send_temperatures(
        [SensorReading("s1", 4.2, datetime(2026, 10, 14, 12, tzinfo=UTC), 87)], 51.2
    )
    assert "apistationid" not in rec.last.headers
    assert rec.last.headers["api-key"] == "k-st"
    assert rec.body() == {
        "datas": [
            {"apiSensorId": "s1", "value": 4.2, "date": "2026-10-14T12:00:00Z", "batteryLevel": 87}
        ],
        "tempTracking": 51.2,
    }


def test_plug_calls_use_put_with_key_in_header_and_body() -> None:
    rec = Recorder()
    gateway(rec).plug_status("p1", True)
    assert rec.last.method == "PUT"
    assert rec.last.headers["api-key"] == "k-st"
    assert rec.body() == {
        "apiPlugId": "p1",
        "status": True,
        "api_key": "k-st",  # pragma: allowlist secret
    }
    gateway(rec).plug_consumption("p1", 1.0, 2.0, 3.0)
    assert rec.last.url.raw_path.decode() == "/api/stations/plugConsumption/st-1"


def test_plug_calls_keep_integer_plug_ids() -> None:
    rec = Recorder()
    gateway(rec).plug_status(12, False)
    assert rec.body()["apiPlugId"] == 12
    gateway(rec).plug_consumption(12, 1.0, 2.0, 3.0)
    assert rec.body()["apiPlugId"] == 12


@pytest.mark.parametrize(
    ("plug_id", "valid"), [(12, True), ("p-1", True), (True, False), ("", False)]
)
def test_plug_list_keeps_plug_id_type(plug_id: object, valid: bool) -> None:
    plug = {"apiPlugId": plug_id, "ipAddress": "10.0.0.5", "name": "n", "stationPlug": True}
    rec = Recorder(httpx.Response(200, json=[plug]))
    if valid:
        assert gateway(rec).plug_list()[0].api_plug_id == plug_id
    else:
        with pytest.raises(ResponseFormatError):
            gateway(rec).plug_list()


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"scaleId": "a"}),
        httpx.Response(200, json={"_id": "a"}),
        httpx.Response(201, text="a"),
    ],
)
def test_add_scale_accepts_all_id_shapes(response: httpx.Response) -> None:
    assert gateway(Recorder(response)).add_scale(ScaleRegistration("10.0.0.2")) == "a"


def test_add_scale_without_id_fails() -> None:
    with pytest.raises(ResponseFormatError):
        gateway(Recorder(httpx.Response(200, json={}))).add_scale(ScaleRegistration("10.0.0.2"))


def test_plug_list_and_ignored_sensors() -> None:
    plugs = [
        {
            "apiPlugId": "p1",
            "ipAddress": "10.0.0.5",
            "name": "n",
            "stationPlug": False,
            "PlugProgrammings": [{"turnOn": "08:00:00", "turnOff": "18:00:00", "days": [1, 7]}],
        }
    ]
    result = gateway(Recorder(httpx.Response(200, json=plugs))).plug_list()
    assert result == [PlugConfig("p1", "10.0.0.5", "n", False, result[0].programmings)]
    assert result[0].programmings[0].days == (1, 7)
    ignored = gateway(Recorder(httpx.Response(200, json={"ignored_hardware_ids": ["a"]})))
    assert ignored.ignored_sensors() == ["a"]


def test_add_new_station_and_task_list() -> None:
    rec = Recorder(httpx.Response(200, json={"apiStationId": "s", "api_key": "k"}))
    assert gateway(rec, None).add_new_station(SECRETS, DEVICE) == GatewayCredentials("s", "k")
    assert gateway(Recorder(httpx.Response(200, json=[1]))).task_list("a/b") == [1]


def test_async_client_shares_the_same_contract() -> None:
    rec = Recorder(httpx.Response(200, text="Count save"))

    async def run() -> None:
        http = httpx.AsyncClient(transport=httpx.MockTransport(rec))
        async with CameraClient(ClientConfig(), CAMERA, http=http) as client:
            await client.tray_count()
        await http.aclose()

    asyncio.run(run())
    assert rec.last.url.raw_path.decode() == "/api/cameras/trayCount/cam%201"


def test_custom_base_url_and_secret_masking() -> None:
    assert ClientConfig(base_url="http://x/api/").api_base_url == "http://x/api"
    assert "k-cam" not in repr(CAMERA)
    assert "global-secret" not in repr(SECRETS)
