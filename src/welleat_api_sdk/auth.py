"""Identifiants d'appareil et modes d'authentification par endpoint."""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Protocol


class AuthMode(Enum):
    """Façon dont un endpoint attend l'authentification."""

    NONE = auto()
    """Aucune authentification."""
    KEY_HEADER = auto()
    """En-tête `api-key` seul."""
    IDENTITY_HEADER = auto()
    """En-têtes d'identité de l'appareil (`api-key`, + `apiStationId` pour une gateway)."""
    BODY = auto()
    """Identité et clé dans le corps JSON."""
    KEY_HEADER_AND_BODY = auto()
    """En-tête `api-key` et clé `api_key` dans le corps JSON."""


class Credentials(Protocol):
    """Identifiants d'un appareil enrôlé."""

    @property
    def identifier(self) -> str:
        """Identifiant d'appareil, utilisé dans les chemins (`{identity}`)."""
        ...

    @property
    def api_key(self) -> str:
        """Clé d'API de l'appareil."""
        ...

    def identity_headers(self) -> dict[str, str]:
        """Renvoie les en-têtes du mode `IDENTITY_HEADER`."""
        ...

    def body_fields(self) -> dict[str, str]:
        """Renvoie les champs injectés dans le corps (modes `BODY`, `KEY_HEADER_AND_BODY`)."""
        ...


@dataclass(frozen=True, slots=True)
class CameraCredentials:
    """Identifiants d'une caméra (`cameraId` + `api_key`).

    Attributes:
        camera_id: Identifiant de la caméra.
        api_key: Clé d'API de la caméra.
    """

    camera_id: str
    api_key: str = field(repr=False)

    @property
    def identifier(self) -> str:
        """Identifiant de la caméra."""
        return self.camera_id

    def identity_headers(self) -> dict[str, str]:
        """Renvoie `api-key`.

        Returns:
            En-têtes d'identification de la caméra.
        """
        return {"api-key": self.api_key}

    def body_fields(self) -> dict[str, str]:
        """Renvoie `cameraId` et `api_key`.

        Returns:
            Champs d'authentification à fusionner dans le corps JSON.
        """
        return {"cameraId": self.camera_id, "api_key": self.api_key}


@dataclass(frozen=True, slots=True)
class GatewayCredentials:
    """Identifiants d'une gateway, nommée « station » côté API (`apiStationId` + `api_key`).

    Attributes:
        api_station_id: Identifiant de station.
        api_key: Clé d'API de la station.
    """

    api_station_id: str
    api_key: str = field(repr=False)

    @property
    def identifier(self) -> str:
        """Identifiant de la station."""
        return self.api_station_id

    def identity_headers(self) -> dict[str, str]:
        """Renvoie `api-key` et `apiStationId`.

        Returns:
            En-têtes d'identification de la station.
        """
        return {"api-key": self.api_key, "apiStationId": self.api_station_id}

    def body_fields(self) -> dict[str, str]:
        """Renvoie `api_key` seul.

        Returns:
            Champs d'authentification à fusionner dans le corps JSON.
        """
        return {"api_key": self.api_key}


@dataclass(frozen=True, slots=True)
class EnrollmentSecrets:
    """Clé et secret globaux d'enrôlement, toujours fournis par l'appelant.

    Attributes:
        api_key: Clé globale d'enrôlement.
        api_secret: Secret global d'enrôlement.
    """

    api_key: str = field(repr=False)
    api_secret: str = field(repr=False)
