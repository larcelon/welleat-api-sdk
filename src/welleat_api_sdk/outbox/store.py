"""Entrées de l'outbox et stockage fichier, au format `schema_version: 2` de camera-soft.

Une entrée par fichier `<id>.json`, écrit de façon atomique (fichier temporaire,
`fsync`, puis `os.replace`) pour survivre à une coupure de courant. Un fichier
illisible est mis en quarantaine (`.invalid`), une entrée non certifiée
« privacy » aussi (`.privacy_blocked`) : elles ne sont jamais envoyées.
"""

import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

from welleat_api_sdk._json import as_object
from welleat_api_sdk.errors import ResponseFormatError
from welleat_api_sdk.request import JsonValue

_LOG = logging.getLogger(__name__)

SCHEMA_VERSION = 2
"""Version du format de fichier, identique à l'outbox de camera-soft."""

INVALID_SUFFIX = ".invalid"
"""Suffixe ajouté à un fichier illisible."""

PRIVACY_BLOCKED_SUFFIX = ".privacy_blocked"
"""Suffixe ajouté à une entrée non certifiée « privacy »."""


def as_json_value(value: object, what: str) -> JsonValue:
    """Vérifie récursivement qu'une valeur décodée est du JSON.

    Args:
        value: Valeur décodée.
        what: Description de la valeur, pour le message d'erreur.

    Returns:
        La valeur, typée JSON.

    Raises:
        ResponseFormatError: Si la valeur contient un type non JSON.
    """
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list):
        return [as_json_value(item, what) for item in value]
    if isinstance(value, dict):
        return {str(key): as_json_value(item, what) for key, item in value.items()}
    raise ResponseFormatError(f"{what} : valeur non JSON")


def _json_object(value: object, what: str) -> dict[str, JsonValue]:
    """Exige un objet JSON et type ses valeurs.

    Args:
        value: Valeur décodée.
        what: Description de la valeur, pour le message d'erreur.

    Returns:
        L'objet JSON.
    """
    return {key: as_json_value(item, what) for key, item in as_object(value, what).items()}


def _optional_moment(value: object, what: str) -> datetime | None:
    """Lit une date : epoch secondes (nombre) ou ISO-8601 ; une date ISO naïve est en UTC.

    Args:
        value: Valeur décodée.
        what: Description de la valeur, pour le message d'erreur.

    Returns:
        La date (avec fuseau), ou `None` si la valeur est absente.

    Raises:
        ResponseFormatError: Si la valeur n'est ni un nombre ni une date ISO-8601.
    """
    if value is None:
        return None
    if isinstance(value, int | float) and not isinstance(value, bool):
        return datetime.fromtimestamp(value, UTC)
    if isinstance(value, str):
        try:
            moment = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ResponseFormatError(f"{what} : date ISO-8601 invalide") from exc
        return moment if moment.tzinfo else moment.replace(tzinfo=UTC)
    raise ResponseFormatError(f"{what} : date attendue")


def _optional_int(value: object, what: str) -> int | None:
    """Lit un entier facultatif ; les booléens sont refusés.

    Args:
        value: Valeur décodée.
        what: Description de la valeur, pour le message d'erreur.

    Returns:
        L'entier, ou `None` si la valeur est absente.

    Raises:
        ResponseFormatError: Si la valeur n'est pas un entier.
    """
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ResponseFormatError(f"{what} : entier attendu")
    return value


def _epoch(moment: datetime | None) -> float | None:
    """Convertit une date en epoch secondes.

    Args:
        moment: Date avec fuseau, ou `None`.

    Returns:
        Les secondes epoch, ou `None`.
    """
    return None if moment is None else moment.timestamp()


@dataclass(frozen=True, slots=True)
class OutboxEntry:
    """Envoi en attente de rejeu.

    Attributes:
        entry_id: Identifiant, nom du fichier sans `.json`.
        payload: Charge utile JSON à rejouer.
        retries: Nombre d'échecs.
        next_attempt_at: Prochaine tentative ; `None` = dès que possible.
        first_failed_at: Premier échec, base de la péremption et du blackout.
        last_error: Dernière erreur, lisible.
        last_status: Dernier statut HTTP reçu, si l'échec en comportait un.
        privacy_verified: Trame certifiée anonymisée ; sinon jamais envoyée.
    """

    entry_id: str
    payload: dict[str, JsonValue]
    retries: int = 0
    next_attempt_at: datetime | None = None
    first_failed_at: datetime | None = None
    last_error: str | None = None
    last_status: int | None = None
    privacy_verified: bool = True

    def to_json(self) -> dict[str, JsonValue]:
        """Sérialise l'entrée au format `schema_version: 2` (dates en epoch secondes).

        Returns:
            Représentation JSON de l'entrée.
        """
        return {
            "schema_version": SCHEMA_VERSION,
            "payload": self.payload,
            "retries": self.retries,
            "next_attempt_at": _epoch(self.next_attempt_at),
            "first_failed_at": _epoch(self.first_failed_at),
            "last_error": self.last_error,
            "last_status": self.last_status,
            "privacy_verified": self.privacy_verified,
        }

    @classmethod
    def from_json(cls, entry_id: str, value: object) -> Self:
        """Lit une entrée `schema_version: 2`.

        Un `privacy_verified` absent vaut `False` : dans le doute, la trame
        n'est pas envoyée.

        Args:
            entry_id: Identifiant de l'entrée.
            value: Objet JSON décodé.

        Returns:
            L'entrée.

        Raises:
            ResponseFormatError: Si la version ou un champ est invalide.
        """
        data = as_object(value, entry_id)
        if data.get("schema_version") != SCHEMA_VERSION:
            raise ResponseFormatError(f"{entry_id} : schema_version {SCHEMA_VERSION} attendue")
        last_error = data.get("last_error")
        return cls(
            entry_id=entry_id,
            payload=_json_object(data.get("payload"), f"{entry_id}.payload"),
            retries=_optional_int(data.get("retries"), f"{entry_id}.retries") or 0,
            next_attempt_at=_optional_moment(data.get("next_attempt_at"), entry_id),
            first_failed_at=_optional_moment(data.get("first_failed_at"), entry_id),
            last_error=None if last_error is None else str(last_error),
            last_status=_optional_int(data.get("last_status"), f"{entry_id}.last_status"),
            privacy_verified=data.get("privacy_verified") is True,
        )


class FileOutboxStore:
    """Outbox persistée dans un répertoire, une entrée par fichier `<id>.json`.

    Attributes:
        directory: Répertoire de l'outbox, créé au besoin.
    """

    def __init__(self, directory: Path | str) -> None:
        """Ouvre (et crée au besoin) le répertoire de l'outbox.

        Args:
            directory: Répertoire de l'outbox, propre à cet usage.
        """
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, entry_id: str) -> Path:
        """Chemin du fichier d'une entrée.

        Args:
            entry_id: Identifiant de l'entrée.

        Returns:
            Le chemin `<répertoire>/<id>.json`.
        """
        return self.directory / f"{entry_id}.json"

    def save(self, entry: OutboxEntry) -> None:
        """Écrit une entrée de façon atomique (remplace la version précédente).

        Args:
            entry: Entrée à écrire.
        """
        path = self._path(entry.entry_id)
        tmp = path.with_name(f".{path.name}.tmp")
        with tmp.open("w", encoding="utf-8") as stream:
            json.dump(entry.to_json(), stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        tmp.replace(path)

    def delete(self, entry_id: str) -> None:
        """Supprime une entrée, si elle existe encore.

        Args:
            entry_id: Identifiant de l'entrée.
        """
        self._path(entry_id).unlink(missing_ok=True)

    def load(self) -> list[OutboxEntry]:
        """Lit toutes les entrées valides ; met en quarantaine les autres.

        Returns:
            Les entrées envoyables, par identifiant croissant.
        """
        entries: list[OutboxEntry] = []
        for path in sorted(self.directory.glob("*.json")):
            entry = self._read(path)
            if entry is None:
                continue
            if not entry.privacy_verified:
                self._quarantine(path, PRIVACY_BLOCKED_SUFFIX, "non certifiée privacy")
                continue
            entries.append(entry)
        return entries

    def _read(self, path: Path) -> OutboxEntry | None:
        """Lit un fichier d'entrée ; un fichier illisible est mis en quarantaine.

        Args:
            path: Fichier à lire.

        Returns:
            L'entrée, ou `None` si le fichier est invalide.
        """
        try:
            return OutboxEntry.from_json(path.stem, json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, ResponseFormatError) as exc:
            self._quarantine(path, INVALID_SUFFIX, str(exc))
            return None

    @staticmethod
    def _quarantine(path: Path, suffix: str, reason: str) -> None:
        """Renomme un fichier pour qu'il ne soit plus relu.

        Args:
            path: Fichier à écarter.
            suffix: Suffixe de quarantaine.
            reason: Motif, pour le journal.
        """
        _LOG.warning("Outbox : %s mis en quarantaine (%s)", path.name, reason)
        path.replace(path.with_name(path.name + suffix))
