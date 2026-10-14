"""Modèles de données échangés avec l'API Welleat.

Les modèles de requête exposent `to_json()` ; les modèles de réponse exposent
`from_json()`, qui valide la forme reçue et lève `ResponseFormatError`.
`FramePayload` (et `Detection`) exposent les deux, pour être rejoués depuis l'outbox.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from welleat_api_sdk._json import (
    as_bool,
    as_device_id,
    as_float,
    as_int,
    as_list,
    as_object,
    as_str,
)
from welleat_api_sdk.errors import ResponseFormatError
from welleat_api_sdk.request import JsonValue

type DeviceId = str | int
"""Identifiant à type mixte (`apiPlugId`, `TabletId`, `scaleId`), renvoyé tel que reçu."""

_BBOX_SIZE = 4


@dataclass(frozen=True, slots=True)
class Detection:
    """Une détection du modèle de vision.

    Attributes:
        label: Classe détectée (`tray`, ...).
        confidence: Confiance entre 0 et 1.
        bbox: Boîte `(x1, y1, x2, y2)` en pixels de l'image envoyée.
        track_id: Identifiant de suivi, présent surtout pour `tray`.
    """

    label: str
    confidence: float
    bbox: tuple[float, float, float, float]
    track_id: int | str | None = None

    def to_json(self) -> dict[str, JsonValue]:
        """Sérialise la détection ; `track_id` est omis s'il est absent.

        Returns:
            Représentation JSON de la détection.
        """
        data: dict[str, JsonValue] = {
            "label": self.label,
            "confidence": self.confidence,
            "bbox": list(self.bbox),
        }
        if self.track_id is not None:
            data["track_id"] = self.track_id
        return data

    @classmethod
    def from_json(cls, value: object) -> "Detection":
        """Relit une détection sérialisée par `to_json`.

        Args:
            value: Objet `{label, confidence, bbox, track_id?}`.

        Returns:
            La détection.

        Raises:
            ResponseFormatError: Si `bbox` n'a pas 4 nombres ou `track_id` un type invalide.
        """
        data = as_object(value, "Detection")
        bbox = [
            as_float(n, "Detection.bbox[]") for n in as_list(data.get("bbox"), "Detection.bbox")
        ]
        if len(bbox) != _BBOX_SIZE:
            raise ResponseFormatError("Detection.bbox : 4 nombres attendus")
        track_id = data.get("track_id")
        if isinstance(track_id, bool) or not isinstance(track_id, int | str | None):
            raise ResponseFormatError("Detection.track_id : entier ou chaîne attendu")
        return cls(
            label=as_str(data.get("label"), "Detection.label"),
            confidence=as_float(data.get("confidence"), "Detection.confidence"),
            bbox=(bbox[0], bbox[1], bbox[2], bbox[3]),
            track_id=track_id,
        )


@dataclass(frozen=True, slots=True)
class FramePayload:
    """Image normale envoyée par `sendFrame`.

    Attributes:
        image: Data-URI JPEG en base64.
        image_name: Nom `frame_YYYYMMDD_HHMMSS_ffffff.jpg`.
        detections: Détections de l'image.
        tray_id: Identifiant de plateau (UID NFC ou `"-1"`), si applicable.
    """

    image: str
    image_name: str
    detections: tuple[Detection, ...] = ()
    tray_id: str | None = None

    def to_json(self) -> dict[str, JsonValue]:
        """Sérialise l'image, sans les champs d'authentification.

        Returns:
            Représentation JSON de l'image.
        """
        data: dict[str, JsonValue] = {
            "image": self.image,
            "image_name": self.image_name,
            "detections": [d.to_json() for d in self.detections],
        }
        if self.tray_id is not None:
            data["tray_id"] = self.tray_id
        return data

    @classmethod
    def from_json(cls, value: object) -> "FramePayload":
        """Relit une image sérialisée par `to_json` (rejeu depuis l'outbox).

        Args:
            value: Objet `{image, image_name, detections, tray_id?}`.

        Returns:
            L'image.
        """
        data = as_object(value, "FramePayload")
        detections = as_list(data.get("detections", []), "FramePayload.detections")
        tray_id = data.get("tray_id")
        return cls(
            image=as_str(data.get("image"), "FramePayload.image"),
            image_name=as_str(data.get("image_name"), "FramePayload.image_name"),
            detections=tuple(Detection.from_json(item) for item in detections),
            tray_id=None if tray_id is None else as_str(tray_id, "FramePayload.tray_id"),
        )


@dataclass(frozen=True, slots=True)
class MultiCamOptions:
    """Options du coordinateur MultiCam pour `sendFrame` et `trayCount`.

    Active les en-têtes `Idempotency-Key` et `X-Welleat-Global-Tray-Id`
    (tous deux égaux à `global_tray_id`) et accepte 409 comme un succès.

    Attributes:
        global_tray_id: Identifiant global du plateau.
        source_camera_id: Caméra source de l'image (`sendFrame` seulement).
        rig_id: Identifiant du rig (`sendFrame` seulement).
        quality_score: Score de qualité de l'image (`sendFrame` seulement).
        quality_low: Score sous le seuil (`sendFrame` seulement).
    """

    global_tray_id: str
    source_camera_id: str | None = None
    rig_id: str | None = None
    quality_score: float | None = None
    quality_low: bool | None = None

    def headers(self) -> dict[str, str]:
        """Renvoie les en-têtes d'idempotence.

        Returns:
            En-têtes `Idempotency-Key` et associés.
        """
        return {
            "Idempotency-Key": self.global_tray_id,
            "X-Welleat-Global-Tray-Id": self.global_tray_id,
        }

    def frame_fields(self) -> dict[str, JsonValue]:
        """Renvoie les champs MultiCam du corps de `sendFrame`.

        Returns:
            Champs MultiCam à fusionner dans le corps JSON.
        """
        data: dict[str, JsonValue] = {"global_tray_id": self.global_tray_id}
        optional: dict[str, JsonValue] = {
            "sourceCameraId": self.source_camera_id,
            "rigId": self.rig_id,
            "quality_score": self.quality_score,
            "quality_low": self.quality_low,
        }
        data.update({key: value for key, value in optional.items() if value is not None})
        return data


@dataclass(frozen=True, slots=True)
class ChefImage:
    """Une image « chef » de `sendControlFrames`.

    Attributes:
        image: Data-URI JPEG en base64.
        image_name: Nom du fichier image.
        detections: Détections de l'image.
    """

    image: str
    image_name: str
    detections: tuple[Detection, ...] = ()

    def to_json(self) -> dict[str, JsonValue]:
        """Sérialise l'image.

        Returns:
            Représentation JSON de l'image.
        """
        return {
            "image": self.image,
            "image_name": self.image_name,
            "detections": [d.to_json() for d in self.detections],
        }


@dataclass(frozen=True, slots=True)
class ChefFramePayload:
    """Lot d'images « chef » demandé par une tablette.

    Attributes:
        tablet_id: Identifiant de tablette (entier ou chaîne), ou `None`.
        images: Images du lot.
    """

    tablet_id: int | str | None
    images: tuple[ChefImage, ...]

    def to_json(self) -> dict[str, JsonValue]:
        """Sérialise le lot, sans les champs d'authentification.

        Returns:
            Représentation JSON du lot.
        """
        return {"TabletId": self.tablet_id, "images": [i.to_json() for i in self.images]}


@dataclass(frozen=True, slots=True)
class ReportPayload:
    """Rapport d'activité d'une caméra.

    Attributes:
        last_image_date: Date de dernière image envoyée, telle que stockée.
        image_count: Nombre d'images envoyées.
        service_slot_id: Créneau de service courant (`0` hors créneau) ; omis si `None`.
    """

    last_image_date: str | None
    image_count: int
    service_slot_id: int | None = None

    def to_json(self) -> dict[str, JsonValue]:
        """Sérialise le rapport.

        Returns:
            Représentation JSON du rapport.
        """
        data: dict[str, JsonValue] = {
            "lastImageDate": self.last_image_date,
            "imageCount": self.image_count,
        }
        if self.service_slot_id is not None:
            data["ServiceSlotId"] = self.service_slot_id
        return data


@dataclass(frozen=True, slots=True)
class ServiceSlot:
    """Créneau de service d'une caméra.

    Attributes:
        service_slot_id: Identifiant du créneau.
        schedules: Horaires `HH:MM`.
    """

    service_slot_id: int
    schedules: tuple[str, ...]

    @classmethod
    def from_json(cls, value: object) -> "ServiceSlot":
        """Construit un créneau depuis un objet JSON.

        Args:
            value: Objet `{ServiceSlotId, schedules}`.

        Returns:
            Le créneau.
        """
        data = as_object(value, "ServiceSlot")
        schedules = as_list(data.get("schedules"), "ServiceSlot.schedules")
        return cls(
            service_slot_id=as_int(data.get("ServiceSlotId"), "ServiceSlot.ServiceSlotId"),
            schedules=tuple(as_str(item, "ServiceSlot.schedules[]") for item in schedules),
        )


@dataclass(frozen=True, slots=True)
class PlugProgramming:
    """Programmation horaire d'une prise.

    Attributes:
        turn_on: Heure d'allumage `HH:MM:SS`.
        turn_off: Heure d'extinction `HH:MM:SS`.
        days: Jours actifs, 1 = lundi … 7 = dimanche.
    """

    turn_on: str
    turn_off: str
    days: tuple[int, ...]

    @classmethod
    def from_json(cls, value: object) -> "PlugProgramming":
        """Construit une programmation depuis un objet JSON.

        Args:
            value: Objet `{turnOn, turnOff, days}`.

        Returns:
            La programmation.
        """
        data = as_object(value, "PlugProgramming")
        days = as_list(data.get("days"), "PlugProgramming.days")
        return cls(
            turn_on=as_str(data.get("turnOn"), "PlugProgramming.turnOn"),
            turn_off=as_str(data.get("turnOff"), "PlugProgramming.turnOff"),
            days=tuple(as_int(day, "PlugProgramming.days[]") for day in days),
        )


@dataclass(frozen=True, slots=True)
class PlugConfig:
    """Prise connectée (Tasmota) rattachée à une station.

    Attributes:
        api_plug_id: Identifiant de prise, entier ou chaîne tel que reçu.
        ip_address: Adresse IP de la prise.
        name: Nom de la prise.
        station_plug: Prise propre à la station.
        programmings: Programmations ; seule la première est exploitée aujourd'hui.
    """

    api_plug_id: DeviceId
    ip_address: str
    name: str
    station_plug: bool
    programmings: tuple[PlugProgramming, ...] = ()

    @classmethod
    def from_json(cls, value: object) -> "PlugConfig":
        """Construit une prise depuis un objet JSON.

        Args:
            value: Objet de `plugList`.

        Returns:
            La prise.
        """
        data = as_object(value, "PlugConfig")
        raw_programmings = data.get("PlugProgrammings")
        programmings = (
            ()
            if raw_programmings is None
            else tuple(
                PlugProgramming.from_json(item)
                for item in as_list(raw_programmings, "PlugConfig.PlugProgrammings")
            )
        )
        return cls(
            api_plug_id=as_device_id(data.get("apiPlugId"), "PlugConfig.apiPlugId"),
            ip_address=as_str(data.get("ipAddress"), "PlugConfig.ipAddress"),
            name=as_str(data.get("name"), "PlugConfig.name"),
            station_plug=as_bool(data.get("stationPlug"), "PlugConfig.stationPlug"),
            programmings=programmings,
        )


def _utc_iso(moment: datetime) -> str:
    """Formate une date en ISO-8601 UTC suffixée `Z`.

    Returns:
        Date au format `AAAA-MM-JJTHH:MM:SSZ`.
    """
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True, slots=True)
class SensorReading:
    """Mesure agrégée d'un capteur de température.

    Attributes:
        api_sensor_id: Identifiant du capteur.
        value: Température moyenne.
        date: Fin de la période agrégée (date avec fuseau).
        battery_level: Niveau de batterie, si connu.
        wifi_signal_dbm: Signal, si connu.
    """

    api_sensor_id: str
    value: float
    date: datetime
    battery_level: int | None = None
    wifi_signal_dbm: int | None = None

    def to_json(self) -> dict[str, JsonValue]:
        """Sérialise la mesure ; la date est en UTC suffixée `Z`.

        Returns:
            Représentation JSON de la mesure.
        """
        data: dict[str, JsonValue] = {
            "apiSensorId": self.api_sensor_id,
            "value": self.value,
            "date": _utc_iso(self.date),
        }
        if self.battery_level is not None:
            data["batteryLevel"] = self.battery_level
        if self.wifi_signal_dbm is not None:
            data["wifiSignalDbm"] = self.wifi_signal_dbm
        return data


@dataclass(frozen=True, slots=True)
class SensorStat:
    """État d'un capteur pour `sensorStatsTracking`.

    Attributes:
        api_sensor_id: Identifiant du capteur.
        battery_level: Niveau de batterie.
        wifi_signal_dbm: Signal reçu.
        is_connected: Capteur connecté.
    """

    api_sensor_id: str
    battery_level: int
    wifi_signal_dbm: int
    is_connected: bool = True

    def to_json(self) -> dict[str, JsonValue]:
        """Sérialise l'état.

        Returns:
            Représentation JSON de l'état.
        """
        return {
            "apiSensorId": self.api_sensor_id,
            "batteryLevel": self.battery_level,
            "wifiSignalDbm": self.wifi_signal_dbm,
            "isConnected": self.is_connected,
        }


@dataclass(frozen=True, slots=True)
class WeightReading:
    """Pesée d'une balance.

    Attributes:
        scale_id: Identifiant de balance.
        value: Poids net en kg.
        date: Date de la pesée, telle que transmise à l'API.
    """

    scale_id: str
    value: float
    date: str

    def to_json(self) -> dict[str, JsonValue]:
        """Sérialise la pesée.

        Returns:
            Représentation JSON de la pesée.
        """
        return {"scaleId": self.scale_id, "value": self.value, "date": self.date}


@dataclass(frozen=True, slots=True)
class ScaleRegistration:
    """Paramètres d'enregistrement d'une balance.

    Attributes:
        ip_address: Adresse IP de la balance.
        mac_address: Adresse MAC, `None` si inconnue.
    """

    ip_address: str
    mac_address: str | None = None

    def to_json(self) -> dict[str, JsonValue]:
        """Sérialise la demande.

        Returns:
            Représentation JSON de la demande.
        """
        return {"ipAddress": self.ip_address, "macAddress": self.mac_address}


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """Identité matérielle présentée à l'enrôlement.

    Attributes:
        mac: Adresse MAC `AA:BB:CC:DD:EE:FF`.
        hostname: Nom d'hôte.
    """

    mac: str
    hostname: str
