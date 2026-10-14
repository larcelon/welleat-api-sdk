"""Constructeurs des requêtes de l'API caméra (`/cameras/...`).

Fonctions pures, partagées par `CameraClient` et `SyncCameraClient`. La casse
des chemins est celle du back-end (`temptracking`, `Reports`, `StateUpdate`...).
"""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from welleat_api_sdk._json import as_float, as_list, as_object, as_str
from welleat_api_sdk.auth import AuthMode, CameraCredentials, EnrollmentSecrets
from welleat_api_sdk.config import Timeouts
from welleat_api_sdk.errors import ApiError, ResponseFormatError
from welleat_api_sdk.models import (
    ChefFramePayload,
    DeviceInfo,
    FramePayload,
    MultiCamOptions,
    ReportPayload,
    ServiceSlot,
)
from welleat_api_sdk.request import (
    OK_STATUSES,
    Reply,
    Request,
    ignore_reply,
)

if TYPE_CHECKING:
    from welleat_api_sdk.request import JsonValue

_JSON_HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}
_TRAY_COUNT_ACK = "Count save"


def enrollment_headers(secrets: EnrollmentSecrets, device: DeviceInfo) -> dict[str, str]:
    """Construit les en-têtes d'enrôlement, communs aux caméras et aux stations.

    Args:
        secrets: Clé et secret globaux d'enrôlement.
        device: Identité matérielle de l'appareil.

    Returns:
        Les en-têtes `api-key`, `api-secret`, `X-Device-Mac` et `hostname`.
    """
    return {
        "api-key": secrets.api_key,
        "api-secret": secrets.api_secret,
        "X-Device-Mac": device.mac,
        "hostname": device.hostname,
    }


def _parse_credentials(reply: Reply) -> CameraCredentials:
    """Lit `{cameraId, api_key}`.

    Returns:
        Identifiants de la caméra enrôlée.
    """
    data = as_object(reply.json(), "connectCamera")
    return CameraCredentials(
        camera_id=as_str(data.get("cameraId"), "connectCamera.cameraId"),
        api_key=as_str(data.get("api_key"), "connectCamera.api_key"),
    )


def connect_camera(secrets: EnrollmentSecrets, device: DeviceInfo) -> Request[CameraCredentials]:
    """Enrôle une caméra (`POST cameras/connectCamera/`, sans corps).

    Args:
        secrets: Clé et secret globaux d'enrôlement.
        device: Identité matérielle de la caméra.

    Returns:
        La requête, qui produit les identifiants de la caméra.
    """
    return Request(
        "POST",
        "cameras/connectCamera/",
        _parse_credentials,
        headers=enrollment_headers(secrets, device),
        timeouts=Timeouts(connect=3.0, read=10.0),
    )


def send_frame(frame: FramePayload, multicam: MultiCamOptions | None = None) -> Request[None]:
    """Envoie une image normale (`POST cameras/sendFrame`, auth dans le corps).

    Args:
        frame: Image et détections.
        multicam: Options MultiCam ; active l'idempotence et accepte 409.

    Returns:
        La requête.
    """
    body = frame.to_json()
    headers = dict(_JSON_HEADERS)
    success = OK_STATUSES
    if multicam is not None:
        body.update(multicam.frame_fields())
        headers.update(multicam.headers())
        success = success | {409}
    return Request("POST", "cameras/sendFrame", ignore_reply, AuthMode.BODY, body, headers, success)


def send_control_frames(payload: ChefFramePayload) -> Request[None]:
    """Envoie des images « chef » (`POST cameras/sendControlFrames`, auth dans le corps).

    Args:
        payload: Tablette demandeuse et images.

    Returns:
        La requête.
    """
    return Request(
        "POST",
        "cameras/sendControlFrames",
        ignore_reply,
        AuthMode.BODY,
        payload.to_json(),
        _JSON_HEADERS,
    )


def _check_count_ack(reply: Reply) -> None:
    """Exige le texte `Count save` sur un 200/201 ; un 409 MultiCam (doublon) est accepté tel quel.

    Raises:
        ApiError: Si l'acquittement est absent.
    """
    if reply.status in OK_STATUSES and _TRAY_COUNT_ACK not in reply.text:
        raise ApiError(reply.status, reply.text, f"trayCount sans acquittement {_TRAY_COUNT_ACK!r}")


def tray_count(multicam: MultiCamOptions | None = None) -> Request[None]:
    """Incrémente le comptage de plateaux (`POST cameras/trayCount/{id}`, sans corps).

    Args:
        multicam: Options MultiCam ; active l'idempotence et accepte 409.

    Returns:
        La requête. Un 200/201 sans le texte `Count save` est une erreur.
    """
    if multicam is None:
        return Request(
            "POST", "cameras/trayCount/{identity}", _check_count_ack, AuthMode.KEY_HEADER
        )
    return Request(
        "POST",
        "cameras/trayCount/{identity}",
        _check_count_ack,
        AuthMode.KEY_HEADER,
        headers=multicam.headers(),
        success=OK_STATUSES | {409},
    )


def report(payload: ReportPayload) -> Request[None]:
    """Envoie un rapport d'activité (`POST cameras/Reports/{id}`).

    Args:
        payload: Contenu du rapport.

    Returns:
        La requête.
    """
    return Request(
        "POST",
        "cameras/Reports/{identity}",
        ignore_reply,
        AuthMode.KEY_HEADER,
        payload.to_json(),
        _JSON_HEADERS,
    )


def temp_tracking(temperature: float, soft_version: str | None = None) -> Request[None]:
    """Envoie la température (`POST cameras/temptracking/{id}`).

    Args:
        temperature: Température en °C, arrondie à une décimale.
        soft_version: Version logicielle, omise si `None`.

    Returns:
        La requête.
    """
    body: dict[str, JsonValue] = {"temperature": round(temperature, 1)}
    if soft_version is not None:
        body["softVersion"] = soft_version
    return Request(
        "POST",
        "cameras/temptracking/{identity}",
        ignore_reply,
        AuthMode.KEY_HEADER,
        body,
        _JSON_HEADERS,
        timeouts=Timeouts(connect=3.0, read=10.0),
    )


def state_update(active: bool) -> Request[None]:
    """Signale si la caméra est dans un créneau (`PUT cameras/StateUpdate/{id}`).

    Args:
        active: `True` si l'heure courante est dans un créneau de service.

    Returns:
        La requête (204 accepté).
    """
    return Request(
        "PUT",
        "cameras/StateUpdate/{identity}",
        ignore_reply,
        AuthMode.KEY_HEADER,
        {"state": int(active)},
        _JSON_HEADERS,
        OK_STATUSES | {204},
        Timeouts(connect=3.0, read=10.0),
    )


def speed_perf(bytes_per_second: int) -> Request[None]:
    """Envoie le débit mesuré (`POST cameras/SpeedPerfs/{id}`).

    Args:
        bytes_per_second: Débit en octets par seconde.

    Returns:
        La requête.
    """
    return Request(
        "POST",
        "cameras/SpeedPerfs/{identity}",
        ignore_reply,
        AuthMode.KEY_HEADER,
        {"speedPerf": bytes_per_second},
        _JSON_HEADERS,
        timeouts=Timeouts(connect=3.0, read=10.0),
    )


def _parse_service_slots(reply: Reply) -> list[ServiceSlot]:
    """Lit un objet ou une liste d'objets `ServiceSlot`.

    Returns:
        Créneaux de service lus dans la réponse.
    """
    value = reply.json()
    items = as_list(value, "ServiceSlots") if isinstance(value, list) else [value]
    return [ServiceSlot.from_json(item) for item in items]


def service_slots() -> Request[list[ServiceSlot]]:
    """Récupère les créneaux de service (`GET cameras/ServiceSlots/{id}`).

    Returns:
        La requête. Le corps peut être un objet ou une liste ; la liste peut être vide.
    """
    return Request(
        "GET",
        "cameras/ServiceSlots/{identity}",
        _parse_service_slots,
        AuthMode.KEY_HEADER,
        timeouts=Timeouts(connect=3.05, read=15.0),
    )


def _parse_last_chef_image(reply: Reply) -> datetime | None:
    """Lit `{timestamp}` (secondes epoch) ; `None` si absent ou invalide.

    Returns:
        Date UTC de la dernière image chef, ou `None`.
    """
    try:
        data = as_object(reply.json(), "fetchLastChefImage")
        return datetime.fromtimestamp(as_float(data.get("timestamp"), "timestamp"), UTC)
    except (ResponseFormatError, ValueError, OverflowError, OSError):
        return None


def last_chef_image() -> Request[datetime | None]:
    """Date de la dernière image « chef » (`GET cameras/fetchLastChefImage/{id}`, sans auth).

    Returns:
        La requête, qui produit la date UTC ou `None` s'il n'y a pas d'image récente.
    """
    return Request(
        "GET",
        "cameras/fetchLastChefImage/{identity}",
        _parse_last_chef_image,
        timeouts=Timeouts(connect=3.0, read=5.0),
    )


__all__ = [
    "connect_camera",
    "enrollment_headers",
    "last_chef_image",
    "report",
    "send_control_frames",
    "send_frame",
    "service_slots",
    "speed_perf",
    "state_update",
    "temp_tracking",
    "tray_count",
]
