"""Compteur persistant des `trayCount` non envoyés, limité au jour courant.

Comme `_add_pending_tray_count` de camera-soft : un comptage en échec est
mémorisé, puis rattrapé (l'appelant appelle `flush` toutes les 60 s) ; les
comptages d'un jour précédent sont abandonnés. Fichier `{"date", "count"}`
écrit de façon atomique.
"""

import json
import logging
import os
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from pathlib import Path

from welleat_api_sdk.errors import WelleatError

_LOG = logging.getLogger(__name__)


def _local_now() -> datetime:
    """Heure locale courante, avec fuseau.

    Returns:
        L'heure courante.
    """
    return datetime.now().astimezone()


class _TrayCounterCore:
    """Stockage commun aux compteurs async et sync.

    Attributes:
        path: Fichier du compteur.
    """

    def __init__(self, path: Path | str, *, now: Callable[[], datetime] = _local_now) -> None:
        """Ouvre le compteur ; le fichier est créé au premier comptage.

        Args:
            path: Fichier du compteur.
            now: Horloge renvoyant l'heure locale avec fuseau (tests).
        """
        self.path = Path(path)
        self._now = now

    def _read(self) -> tuple[date, int]:
        """Lit le compteur ; un fichier illisible est mis en quarantaine (`.invalid`).

        Returns:
            Le jour et le nombre de comptages en attente (0 si aucun fichier).
        """
        today = self._now().date()
        if not self.path.exists():
            return today, 0
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            day = date.fromisoformat(data["date"])
            count = data["count"]
        except (ValueError, TypeError, KeyError) as exc:
            _LOG.warning("Compteur %s illisible, mis en quarantaine : %s", self.path.name, exc)
            self.path.replace(self.path.with_name(self.path.name + ".invalid"))
            return today, 0
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            return self._invalid_count(today)
        return day, count

    def _invalid_count(self, today: date) -> tuple[date, int]:
        """Met en quarantaine un fichier dont le compte est invalide.

        Args:
            today: Jour courant.

        Returns:
            Le jour courant et un compte nul.
        """
        _LOG.warning("Compteur %s : compte invalide, mis en quarantaine", self.path.name)
        self.path.replace(self.path.with_name(self.path.name + ".invalid"))
        return today, 0

    def _write(self, count: int) -> None:
        """Écrit le compteur du jour de façon atomique ; le supprime s'il est nul.

        Args:
            count: Comptages en attente.
        """
        if count == 0:
            self.path.unlink(missing_ok=True)
            return
        tmp = self.path.with_name(f".{self.path.name}.tmp")
        with tmp.open("w", encoding="utf-8") as stream:
            json.dump({"date": self._now().date().isoformat(), "count": count}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        tmp.replace(self.path)

    def pending(self) -> int:
        """Nombre de comptages du jour en attente ; ceux d'un jour précédent sont abandonnés.

        Returns:
            Le nombre de comptages à rattraper.
        """
        day, count = self._read()
        if day != self._now().date():
            if count:
                _LOG.warning("Compteur : %d comptage(s) du %s abandonné(s)", count, day)
            self._write(0)
            return 0
        return count

    def add(self, count: int = 1) -> None:
        """Mémorise des comptages en échec.

        Args:
            count: Nombre de plateaux à ajouter.
        """
        self._write(self.pending() + count)


class DailyTrayCounter(_TrayCounterCore):
    """Compteur de `trayCount` en attente, rattrapé de façon asynchrone."""

    async def flush(self, send: Callable[[], Awaitable[None]]) -> int:
        """Rattrape les comptages du jour, un appel par plateau, jusqu'au premier échec.

        Args:
            send: Un appel `trayCount` (ex. `camera.tray_count`).

        Returns:
            Le nombre de comptages envoyés.
        """
        remaining = self.pending()
        sent = 0
        while remaining:
            try:
                await send()
            except WelleatError as exc:
                _LOG.info("Compteur : rattrapage interrompu (%s)", exc)
                break
            remaining -= 1
            sent += 1
            self._write(remaining)
        return sent


class SyncDailyTrayCounter(_TrayCounterCore):
    """Compteur de `trayCount` en attente, rattrapé de façon synchrone."""

    def flush(self, send: Callable[[], None]) -> int:
        """Rattrape les comptages du jour, un appel par plateau, jusqu'au premier échec.

        Args:
            send: Un appel `trayCount` (ex. `camera.tray_count`).

        Returns:
            Le nombre de comptages envoyés.
        """
        remaining = self.pending()
        sent = 0
        while remaining:
            try:
                send()
            except WelleatError as exc:
                _LOG.info("Compteur : rattrapage interrompu (%s)", exc)
                break
            remaining -= 1
            sent += 1
            self._write(remaining)
        return sent
