"""Événements Socket.IO de l'API Welleat : noms, charges utiles et décodage.

Les charges utiles entrantes arrivent sous forme d'objet ou de chaîne JSON ;
`decode_payload` normalise les deux. Les identifiants (`TabletId`, `scaleId`,
`apiPlugId`) ont des types mixtes entier/chaîne côté back-end et sont conservés
tels quels.
"""

import json
import re
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Self

from welleat_api_sdk._json import as_object
from welleat_api_sdk.errors import ResponseFormatError
from welleat_api_sdk.request import JsonValue

type DeviceId = str | int
"""Identifiant à type mixte (`TabletId`, `scaleId`, `apiPlugId`)."""

SCALE_NOT_REGISTERED = "Scale not registered to this station"
"""Message de refus des poids d'une balance non rattachée (comparé sans casse)."""

_GROSS = re.compile(r"AW\s*([-+]?\d+\.?\d*)")
_TARE = re.compile(r"T\s*([-+]?\d+\.?\d*)")
_GRAMS_PER_KG = 1000


class CameraEvent(StrEnum):
    """Noms des événements du canal caméra."""

    AUTHENTICATE = "authenticate"
    """Authentification applicative, émise à chaque connexion (client → serveur)."""
    CAMERA_CONNECT = "camera-connect"
    """Message libre de bienvenue (serveur → client)."""
    FRAME_ACK = "frame_ack"
    """Accusé d'image (libre côté serveur, `captured` côté client) (dans les deux sens)."""
    MANUAL_CAPTURE = "manual-camera-images-asking"
    """Demande de capture manuelle « chef » (serveur → client)."""


class StationEvent(StrEnum):
    """Noms des événements du canal station (balances et prises)."""

    SCALE_WEIGHT_UPDATE = "SCALE_STREAM_WEIGHT_UPDATE"
    """Trame de poids brute (client → serveur)."""
    SCALE_CONNECTION_STATE = "SCALE_CONNECTION_STATE"
    """Transition d'état de connexion d'une balance (client → serveur)."""
    HEARTBEAT = "station-heartbeat"
    """État périodique de toutes les balances (client → serveur)."""
    SCALE_CMD_SUCCESS = "SCALE_CMD_SUCCESS"
    """Succès d'une commande (client) ou accusé de poids (serveur) (deux sens)."""
    SCALE_CMD_ERROR = "SCALE_CMD_ERROR"
    """Échec d'une commande (client) ou refus de poids (serveur) (deux sens)."""
    PLUG_REFRESH = "PLUG REFRESH DATA"
    """La liste des prises doit être relue (nom avec espaces) (serveur → client)."""
    PLUG_ON = "PLUG_CMD_ON"
    """Allumer une prise (serveur → client)."""
    PLUG_OFF = "PLUG_CMD_OFF"
    """Éteindre une prise (serveur → client)."""


class ScaleCommandType(StrEnum):
    """Commandes matérielles envoyées par le serveur à une balance."""

    START_STREAM = "SCALE_CMD_START_STREAM"
    STOP_STREAM = "SCALE_CMD_STOP_STREAM"
    REBOOT = "SCALE_CMD_REBOOT"
    CALIBRATE_ZERO = "SCALE_CMD_CALIBRATE_ZERO"
    TARE_SET = "SCALE_CMD_TARE_SET"


class ScaleErrorCode(StrEnum):
    """Codes d'erreur d'une commande de balance."""

    COMMAND_FAILED = "SCALE_CMD_ERROR"
    """Échec après tous les essais."""
    HARDWARE_FAILURE = "SCALE_HARDWARE_FAILURE"
    """Balance ou adresse IP introuvable."""


def decode_payload(payload: object, event: str) -> dict[str, object]:
    """Normalise une charge utile entrante : objet, chaîne JSON ou absente.

    Args:
        payload: Charge utile reçue.
        event: Nom de l'événement, pour le message d'erreur.

    Returns:
        L'objet décodé ; vide si la charge utile est absente.

    Raises:
        ResponseFormatError: Si la charge utile n'est ni un objet ni un objet JSON en chaîne.
    """
    if payload is None or (isinstance(payload, str) and not payload.strip()):
        return {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ResponseFormatError(f"{event} : JSON invalide") from exc
    return as_object(payload, event)


def _device_id(data: dict[str, object], keys: tuple[str, ...], what: str) -> DeviceId:
    """Lit le premier identifiant présent parmi `keys`.

    Args:
        data: Charge utile décodée.
        keys: Clés acceptées, par ordre de préférence.
        what: Description de la valeur, pour le message d'erreur.

    Returns:
        L'identifiant, entier ou chaîne non vide.

    Raises:
        ResponseFormatError: Si aucune clé ne porte un identifiant valide.
    """
    value = _optional_device_id(data, keys)
    if value is None:
        raise ResponseFormatError(f"{what} : {' ou '.join(keys)} attendu")
    return value


def _optional_device_id(data: dict[str, object], keys: tuple[str, ...]) -> DeviceId | None:
    """Lit le premier identifiant présent parmi `keys`, s'il y en a un.

    Args:
        data: Charge utile décodée.
        keys: Clés acceptées, par ordre de préférence.

    Returns:
        L'identifiant, entier ou chaîne non vide, sinon `None`.
    """
    for key in keys:
        value = data.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int) or (isinstance(value, str) and value):
            return value
    return None


def parse_scale_weight(raw_data: str) -> float | None:
    """Extrait le poids net d'une trame brute de balance (ex. `AW 1.234 T 0.1`).

    Les caractères non imprimables sont retirés ; le poids net vaut brut - tare
    (tare 0 par défaut), arrondi à 3 décimales.

    Args:
        raw_data: Trame brute.

    Returns:
        Le poids net en kg, ou `None` si la trame ne contient pas de poids `AW`.
    """
    text = "".join(char for char in raw_data if char.isprintable())
    gross = _GROSS.search(text)
    if gross is None:
        return None
    tare = _TARE.search(text)
    return round(float(gross.group(1)) - (float(tare.group(1)) if tare else 0.0), 3)


# --- Événements entrants -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ManualCaptureRequest:
    """Demande de capture manuelle « chef » (`manual-camera-images-asking`).

    Attributes:
        tablet_id: Tablette demandeuse (`TabletId` ou `tablet_id`), `None` si absente.
        payload: Charge utile complète, pour les champs non typés.
    """

    tablet_id: DeviceId | None
    payload: dict[str, object] = field(default_factory=dict[str, object])

    @classmethod
    def from_payload(cls, payload: object) -> Self:
        """Décode la demande.

        Args:
            payload: Charge utile reçue.

        Returns:
            La demande décodée.
        """
        data = decode_payload(payload, CameraEvent.MANUAL_CAPTURE)
        return cls(_optional_device_id(data, ("TabletId", "tablet_id")), data)


@dataclass(frozen=True, slots=True)
class ScaleCommand:
    """Commande matérielle adressée à une balance (`SCALE_CMD_*`).

    Attributes:
        command: Commande demandée.
        scale_id: Balance visée (`scaleId`).
        ip: Adresse IP fournie par le serveur ; elle prime sur celle connue localement.
    """

    command: ScaleCommandType
    scale_id: DeviceId
    ip: str | None = None

    @classmethod
    def from_payload(cls, command: ScaleCommandType, payload: object) -> Self:
        """Décode la commande.

        Args:
            command: Commande portée par le nom de l'événement.
            payload: Charge utile reçue.

        Returns:
            La commande décodée.
        """
        data = decode_payload(payload, command)
        ip = data.get("ip")
        return cls(
            command,
            _device_id(data, ("scaleId",), command),
            ip if isinstance(ip, str) and ip else None,
        )


@dataclass(frozen=True, slots=True)
class WeightAck:
    """Accusé de réception des poids d'une balance (`SCALE_CMD_SUCCESS` reçu).

    Il confirme les poids envoyés et autorise de nouveau leur publication.

    Attributes:
        scale_id: Balance concernée (`scaleUuid` ou `scaleId`).
        payload: Charge utile complète.
    """

    scale_id: DeviceId
    payload: dict[str, object] = field(default_factory=dict[str, object])

    @classmethod
    def from_payload(cls, payload: object) -> Self | None:
        """Décode l'accusé.

        Args:
            payload: Charge utile reçue.

        Returns:
            L'accusé, ou `None` si le message porte `original_command`
            (retour de commande matérielle, pas un accusé de poids).
        """
        data = decode_payload(payload, StationEvent.SCALE_CMD_SUCCESS)
        if "original_command" in data:
            return None
        return cls(_device_id(data, ("scaleUuid", "scaleId"), "accusé de poids"), data)


@dataclass(frozen=True, slots=True)
class WeightRejection:
    """Refus des poids d'une balance (`SCALE_CMD_ERROR` reçu).

    Attributes:
        scale_id: Balance concernée (`scaleUuid` ou `scaleId`).
        message: Motif du refus (`error` ou `message`).
        payload: Charge utile complète.
    """

    scale_id: DeviceId
    message: str
    payload: dict[str, object] = field(default_factory=dict[str, object])

    @property
    def not_registered(self) -> bool:
        """Indique si la balance n'est pas rattachée à cette station."""
        return self.message.strip().casefold() == SCALE_NOT_REGISTERED.casefold()

    @classmethod
    def from_payload(cls, payload: object) -> Self | None:
        """Décode le refus.

        Args:
            payload: Charge utile reçue.

        Returns:
            Le refus, ou `None` si le message porte `original_command`
            (retour de commande matérielle, pas un refus de poids).
        """
        data = decode_payload(payload, StationEvent.SCALE_CMD_ERROR)
        if "original_command" in data:
            return None
        message = data.get("error", data.get("message"))
        return cls(
            _device_id(data, ("scaleUuid", "scaleId"), "refus de poids"),
            message if isinstance(message, str) else "",
            data,
        )


@dataclass(frozen=True, slots=True)
class PlugCommand:
    """Commande d'une prise connectée (`PLUG_CMD_ON` / `PLUG_CMD_OFF`).

    Attributes:
        api_plug_id: Prise visée (`apiPlugId`).
        on: `True` pour allumer, `False` pour éteindre.
    """

    api_plug_id: DeviceId
    on: bool

    @classmethod
    def from_payload(cls, on: bool, payload: object) -> Self | None:
        """Décode la commande.

        Args:
            on: Sens de la commande, porté par le nom de l'événement.
            payload: Charge utile reçue.

        Returns:
            La commande, ou `None` si `apiPlugId` est absent (commande ignorée).
        """
        event = StationEvent.PLUG_ON if on else StationEvent.PLUG_OFF
        plug_id = _optional_device_id(decode_payload(payload, event), ("apiPlugId",))
        return None if plug_id is None else cls(plug_id, on)


# --- Événements sortants -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ScaleWeightUpdate:
    """Trame de poids brute d'une balance (`SCALE_STREAM_WEIGHT_UPDATE`).

    Attributes:
        scale_id: Balance émettrice.
        raw_data: Trame brute, ex. `AW 1.234 T 0.1`.
    """

    scale_id: DeviceId
    raw_data: str

    def to_json(self) -> dict[str, JsonValue]:
        """Sérialise la trame.

        Returns:
            Représentation JSON de la trame.
        """
        return {"scaleId": self.scale_id, "raw_data": self.raw_data}


@dataclass(frozen=True, slots=True)
class ScaleConnectionState:
    """Transition d'état de connexion d'une balance (`SCALE_CONNECTION_STATE`).

    À n'émettre que sur transition ; `connected` seulement si la balance
    transporte réellement des trames.

    Attributes:
        scale_id: Balance concernée.
        connected: Nouvel état.
    """

    scale_id: DeviceId
    connected: bool

    def to_json(self) -> dict[str, JsonValue]:
        """Sérialise l'état (`state` vaut 0 ou 1).

        Returns:
            Représentation JSON de l'état.
        """
        return {"scaleId": self.scale_id, "state": int(self.connected)}


@dataclass(frozen=True, slots=True)
class ScaleHeartbeat:
    """État d'une balance dans `station-heartbeat`.

    Attributes:
        scale_uuid: Balance concernée.
        connected: Balance joignable.
        stream_active: Flux de poids actif.
        last_weight_kg: Dernier poids net ; `None` si inconnu ou balance refusée.
    """

    scale_uuid: DeviceId
    connected: bool
    stream_active: bool
    last_weight_kg: float | None = None

    def to_json(self) -> dict[str, JsonValue]:
        """Sérialise l'état ; `lastWeightGrams` vaut 0 si le flux est inactif.

        Returns:
            Représentation JSON de l'état.
        """
        grams = 0
        if self.stream_active and self.last_weight_kg is not None:
            grams = int(self.last_weight_kg * _GRAMS_PER_KG)
        return {
            "scaleUuid": self.scale_uuid,
            "connected": self.connected,
            "streamActive": self.stream_active,
            "lastWeightGrams": grams,
        }


@dataclass(frozen=True, slots=True)
class StationHeartbeat:
    """État périodique de toutes les balances (`station-heartbeat`).

    Attributes:
        scales: État de chaque balance.
        timestamp: Horodatage en secondes epoch ; l'instant présent par défaut.
    """

    scales: tuple[ScaleHeartbeat, ...]
    timestamp: float = field(default_factory=time.time)

    def to_json(self) -> dict[str, JsonValue]:
        """Sérialise le heartbeat.

        Returns:
            Représentation JSON du heartbeat.
        """
        return {"scales": [s.to_json() for s in self.scales], "timestamp": self.timestamp}


@dataclass(frozen=True, slots=True)
class ScaleCommandSuccess:
    """Succès d'une commande matérielle (`SCALE_CMD_SUCCESS` émis).

    Attributes:
        scale_id: Balance concernée.
        original_command: Commande exécutée.
        timestamp: Horodatage en secondes epoch ; l'instant présent par défaut.
    """

    scale_id: DeviceId
    original_command: ScaleCommandType
    timestamp: float = field(default_factory=time.time)

    def to_json(self) -> dict[str, JsonValue]:
        """Sérialise l'acquittement.

        Returns:
            Représentation JSON de l'acquittement.
        """
        return {
            "scaleId": self.scale_id,
            "original_command": self.original_command.value,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True, slots=True)
class ScaleCommandFailure:
    """Échec d'une commande matérielle (`SCALE_CMD_ERROR` émis).

    Attributes:
        scale_id: Balance concernée.
        original_command: Commande en échec.
        error_code: Nature de l'échec.
        message: Explication lisible.
    """

    scale_id: DeviceId
    original_command: ScaleCommandType
    error_code: ScaleErrorCode
    message: str

    def to_json(self) -> dict[str, JsonValue]:
        """Sérialise l'échec.

        Returns:
            Représentation JSON de l'échec.
        """
        return {
            "scaleId": self.scale_id,
            "original_command": self.original_command.value,
            "error_code": self.error_code.value,
            "message": self.message,
        }
