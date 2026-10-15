"""Constructeurs des requêtes de l'API gateway (`/stations/...`).

La gateway s'appelle « station » côté API. Fonctions pures, partagées par
`GatewayClient` et `SyncGatewayClient`.
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING
from urllib.parse import quote

from welleat_api_sdk._json import as_list, as_object, as_str
from welleat_api_sdk.auth import AuthMode, EnrollmentSecrets, GatewayCredentials
from welleat_api_sdk.camera_requests import enrollment_headers
from welleat_api_sdk.config import Timeouts
from welleat_api_sdk.errors import ResponseFormatError
from welleat_api_sdk.models import (
    DeviceId,
    DeviceInfo,
    PlugConfig,
    ScaleRegistration,
    SensorReading,
    SensorStat,
    WeightReading,
)
from welleat_api_sdk.request import Reply, Request, ignore_reply

if TYPE_CHECKING:
    from welleat_api_sdk.request import JsonValue

_JSON_HEADERS = {"Content-Type": "application/json"}
_SCALE_ID_KEYS = ("scaleId", "id", "_id")


def _parse_credentials(reply: Reply) -> GatewayCredentials:
    """Lit `{apiStationId, api_key}`.

    Returns:
        Identifiants de la station enrôlée.
    """
    data = as_object(reply.json(), "addNewStation")
    return GatewayCredentials(
        api_station_id=as_str(data.get("apiStationId"), "addNewStation.apiStationId"),
        api_key=as_str(data.get("api_key"), "addNewStation.api_key"),
    )


def add_new_station(secrets: EnrollmentSecrets, device: DeviceInfo) -> Request[GatewayCredentials]:
    """Enrôle une gateway (`POST stations/addNewStation`, sans corps).

    Args:
        secrets: Clé et secret globaux d'enrôlement.
        device: Identité matérielle de la gateway.

    Returns:
        La requête, qui produit les identifiants de la station.
    """
    return Request(
        "POST",
        "stations/addNewStation",
        _parse_credentials,
        headers=enrollment_headers(secrets, device),
        timeouts=Timeouts(connect=3.0, read=10.0),
    )


def temp_tracking(cpu_temperature: float) -> Request[None]:
    """Envoie la température CPU (`POST stations/tempTracking/{id}`).

    Args:
        cpu_temperature: Température CPU en °C.

    Returns:
        La requête.
    """
    return Request(
        "POST",
        "stations/tempTracking/{identity}",
        ignore_reply,
        AuthMode.IDENTITY_HEADER,
        {"tempTracking": cpu_temperature},
        _JSON_HEADERS,
    )


def _parse_scale_id(reply: Reply) -> str:
    """Lit l'identifiant de balance : JSON (`scaleId`, `id`, `_id`) ou texte brut.

    Returns:
        L'identifiant de balance.

    Raises:
        ResponseFormatError: Si aucun identifiant n'est présent.
    """
    try:
        value = reply.json()
    except ResponseFormatError:
        return as_str(reply.text.strip(), "addNewScale")
    if isinstance(value, str):
        return as_str(value, "addNewScale")
    data = as_object(value, "addNewScale")
    for key in _SCALE_ID_KEYS:
        if key in data:
            return as_str(data[key], f"addNewScale.{key}")
    raise ResponseFormatError("addNewScale : aucun identifiant de balance")


def add_scale(scale: ScaleRegistration) -> Request[str]:
    """Enregistre une balance (`POST stations/addNewScale/{id}`), idempotent.

    Args:
        scale: Adresses IP et MAC de la balance.

    Returns:
        La requête, qui produit l'identifiant de balance.
    """
    return Request(
        "POST",
        "stations/addNewScale/{identity}",
        _parse_scale_id,
        AuthMode.IDENTITY_HEADER,
        scale.to_json(),
        _JSON_HEADERS,
    )


def send_weights(readings: Sequence[WeightReading], speed_perf: int | None = None) -> Request[None]:
    """Envoie des pesées (`POST stations/sendWeights/{id}`, `api-key` seul).

    Le flux nominal des poids passe par Socket.IO ; cet endpoint est peu utilisé.

    Args:
        readings: Pesées à envoyer.
        speed_perf: Débit mesuré en octets/s, omis si `None`.

    Returns:
        La requête.
    """
    body: dict[str, JsonValue] = {"datas": [r.to_json() for r in readings]}
    if speed_perf is not None:
        body["speedPerf"] = speed_perf
    return Request(
        "POST",
        "stations/sendWeights/{identity}",
        ignore_reply,
        AuthMode.KEY_HEADER,
        body,
        _JSON_HEADERS,
    )


def add_sensor(hardware_id: str) -> Request[str]:
    """Enregistre un capteur BLE (`POST stations/addNewSensor/{id}`).

    Args:
        hardware_id: Nom BLE du capteur.

    Returns:
        La requête, qui produit `apiSensorId`.
    """

    def parse(reply: Reply) -> str:
        data = as_object(reply.json(), "addNewSensor")
        return as_str(data.get("apiSensorId"), "addNewSensor.apiSensorId")

    return Request(
        "POST",
        "stations/addNewSensor/{identity}",
        parse,
        AuthMode.IDENTITY_HEADER,
        {"hardwareId": hardware_id},
        _JSON_HEADERS,
    )


def send_temperatures(
    readings: Sequence[SensorReading],
    cpu_temperature: float | None = None,
    speed_perf: int | None = None,
) -> Request[None]:
    """Envoie des mesures de capteurs (`POST stations/sendTemperatures/{id}`, `api-key` seul).

    Args:
        readings: Mesures agrégées.
        cpu_temperature: Température CPU de la station, omise si `None`.
        speed_perf: Débit mesuré en octets/s, omis si `None`.

    Returns:
        La requête (délai de lecture de 15 s).
    """
    body: dict[str, JsonValue] = {"datas": [r.to_json() for r in readings]}
    if cpu_temperature is not None:
        body["tempTracking"] = cpu_temperature
    if speed_perf is not None:
        body["speedPerf"] = speed_perf
    return Request(
        "POST",
        "stations/sendTemperatures/{identity}",
        ignore_reply,
        AuthMode.KEY_HEADER,
        body,
        _JSON_HEADERS,
        timeouts=Timeouts(connect=3.0, read=15.0),
    )


def sensor_stats(stats: Sequence[SensorStat]) -> Request[None]:
    """Envoie l'état des capteurs (`POST stations/sensorStatsTracking/{id}`).

    Args:
        stats: États des capteurs.

    Returns:
        La requête (la réponse n'est pas lue).
    """
    return Request(
        "POST",
        "stations/sensorStatsTracking/{identity}",
        ignore_reply,
        AuthMode.IDENTITY_HEADER,
        {"datas": [s.to_json() for s in stats]},
        _JSON_HEADERS,
    )


def ignored_sensors() -> Request[list[str]]:
    """Liste les capteurs ignorés (`GET stations/ignored/{id}`).

    Returns:
        La requête, qui produit les `hardwareId` ignorés.
    """

    def parse(reply: Reply) -> list[str]:
        data = as_object(reply.json(), "ignored")
        raw = as_list(data.get("ignored_hardware_ids"), "ignored.ignored_hardware_ids")
        return [as_str(item, "ignored_hardware_ids[]") for item in raw]

    return Request("GET", "stations/ignored/{identity}", parse, AuthMode.IDENTITY_HEADER)


def task_list(api_sensor_id: str) -> Request[object]:
    """Tâches d'un capteur (`GET dataAccess/sensors/taskList/{apiSensorId}`).

    Seul endpoint hors `/stations` et `/cameras`. Le contrat n'est pas observé :
    la réponse JSON est renvoyée telle quelle. Authentification par en-têtes
    `api-key` et `apiStationId`, comme le legacy.

    Args:
        api_sensor_id: Identifiant de capteur.

    Returns:
        La requête, qui produit le JSON non typé.
    """
    return Request(
        "GET",
        f"dataAccess/sensors/taskList/{quote(api_sensor_id, safe='')}",
        lambda reply: reply.json(),
        AuthMode.IDENTITY_HEADER,
    )


def plug_list() -> Request[list[PlugConfig]]:
    """Liste les prises connectées (`GET stations/plugList/{id}`).

    Returns:
        La requête.
    """

    def parse(reply: Reply) -> list[PlugConfig]:
        return [PlugConfig.from_json(item) for item in as_list(reply.json(), "plugList")]

    return Request("GET", "stations/plugList/{identity}", parse, AuthMode.KEY_HEADER)


def plug_status(api_plug_id: DeviceId, status: bool) -> Request[None]:
    """Remonte l'état d'une prise (`PUT stations/plugStatus/{id}`).

    Args:
        api_plug_id: Identifiant de prise (entier ou chaîne), tel que reçu de `plugList`.
        status: `True` si allumée.

    Returns:
        La requête (`api-key` en en-tête et `api_key` dans le corps ; délai 5 s).
    """
    return Request(
        "PUT",
        "stations/plugStatus/{identity}",
        ignore_reply,
        AuthMode.KEY_HEADER_AND_BODY,
        {"apiPlugId": api_plug_id, "status": status},
        _JSON_HEADERS,
        timeouts=Timeouts(connect=3.0, read=5.0),
    )


def plug_consumption(
    api_plug_id: DeviceId, power: float, energy: float, current: float
) -> Request[None]:
    """Remonte la consommation d'une prise (`PUT stations/plugConsumption/{id}`).

    Args:
        api_plug_id: Identifiant de prise (entier ou chaîne), tel que reçu de `plugList`.
        power: Puissance instantanée.
        energy: Énergie cumulée.
        current: Courant.

    Returns:
        La requête (`api-key` en en-tête et `api_key` dans le corps ; délai 5 s).
    """
    return Request(
        "PUT",
        "stations/plugConsumption/{identity}",
        ignore_reply,
        AuthMode.KEY_HEADER_AND_BODY,
        {"apiPlugId": api_plug_id, "power": power, "energy": energy, "current": current},
        _JSON_HEADERS,
        timeouts=Timeouts(connect=3.0, read=5.0),
    )
