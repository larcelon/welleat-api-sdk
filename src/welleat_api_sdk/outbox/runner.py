"""`Outbox` et `SyncOutbox` : envoi avec mise en file des échecs et rejeu.

Comme dans camera-soft, l'outbox ne contient que des envois en échec. Un envoi
« frais » passe par `deliver` : en cas d'échec il est mis en file, et tous les
`fresh_before_retry` succès une entrée due est rejouée. `retry_due` vide la file
dans les périodes creuses. Tout échec `WelleatError` (statut non accepté compris)
replanifie l'entrée ; les autres exceptions, des défauts de l'appelant, remontent.

Ne soumettre que des charges certifiées « privacy » : l'outbox les marque comme
telles. Les fichiers sont lus et écrits de façon synchrone (petits fichiers locaux).
"""

import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from pathlib import Path

from welleat_api_sdk.errors import WelleatError
from welleat_api_sdk.outbox.policy import OutboxPolicy
from welleat_api_sdk.outbox.store import FileOutboxStore, OutboxEntry
from welleat_api_sdk.request import JsonValue

_LOG = logging.getLogger(__name__)

type JsonObject = dict[str, JsonValue]
"""Charge utile JSON d'une entrée."""

type AsyncSender = Callable[[JsonObject], Awaitable[None]]
"""Envoi asynchrone d'une charge utile ; lève une `WelleatError` en cas d'échec."""
type SyncSender = Callable[[JsonObject], None]
"""Envoi synchrone d'une charge utile ; lève une `WelleatError` en cas d'échec."""


def _local_now() -> datetime:
    """Heure locale courante, avec fuseau.

    Returns:
        L'heure courante.
    """
    return datetime.now().astimezone()


class _OutboxCore:
    """Partie commune aux outbox async et sync : stockage, horloge, sélection.

    Attributes:
        store: Stockage des entrées.
        policy: Politique de rejeu.
    """

    def __init__(
        self,
        directory: Path | str,
        policy: OutboxPolicy | None = None,
        *,
        now: Callable[[], datetime] = _local_now,
    ) -> None:
        """Ouvre l'outbox.

        Args:
            directory: Répertoire de l'outbox, propre à cet usage.
            policy: Politique de rejeu ; celle de camera-soft par défaut.
            now: Horloge renvoyant l'heure locale avec fuseau (tests).
        """
        self.store = FileOutboxStore(directory)
        self.policy = policy or OutboxPolicy()
        self._now = now
        self._fresh_sent = 0

    def enqueue(self, payload: Mapping[str, JsonValue], error: WelleatError) -> OutboxEntry:
        """Met en file un envoi qui vient d'échouer.

        Args:
            payload: Charge utile JSON à rejouer.
            error: Erreur de la première tentative.

        Returns:
            L'entrée créée.
        """
        entry = OutboxEntry(uuid.uuid4().hex, dict(payload))
        entry = self.policy.reschedule(entry, self._now(), error)
        self.store.save(entry)
        _LOG.info("Outbox : %s mis en file (%s)", entry.entry_id, error)
        return entry

    def pending(self) -> list[OutboxEntry]:
        """Liste les entrées en attente (les fichiers invalides sont mis en quarantaine).

        Returns:
            Les entrées, par identifiant croissant.
        """
        return self.store.load()

    def _due_entries(self, limit: int | None) -> list[OutboxEntry]:
        """Supprime les entrées périmées puis renvoie les entrées dues, les plus anciennes d'abord.

        Args:
            limit: Nombre maximal d'entrées ; `None` pour toutes.

        Returns:
            Les entrées à rejouer.
        """
        now = self._now()
        due: list[OutboxEntry] = []
        for entry in self.store.load():
            if self.policy.is_expired(entry, now):
                _LOG.warning("Outbox : %s périmé, supprimé", entry.entry_id)
                self.store.delete(entry.entry_id)
            elif self.policy.is_due(entry, now):
                due.append(entry)
        due.sort(key=lambda e: (e.first_failed_at or now, e.entry_id))
        return due if limit is None else due[:limit]

    def _record_failure(self, entry: OutboxEntry, error: WelleatError) -> None:
        """Replanifie une entrée dont le rejeu a échoué.

        Args:
            entry: Entrée rejouée.
            error: Erreur du rejeu.
        """
        self.store.save(self.policy.reschedule(entry, self._now(), error))

    def _retry_turn(self) -> bool:
        """Compte un envoi frais réussi ; indique si c'est le tour d'un rejeu.

        Returns:
            `True` tous les `fresh_before_retry` envois frais réussis.
        """
        self._fresh_sent += 1
        if self._fresh_sent < self.policy.fresh_before_retry:
            return False
        self._fresh_sent = 0
        return True


class Outbox(_OutboxCore):
    """Outbox asynchrone."""

    async def deliver(self, payload: Mapping[str, JsonValue], send: AsyncSender) -> bool:
        """Tente un envoi frais ; en cas d'échec, le met en file.

        Après `fresh_before_retry` envois frais réussis, une entrée due est rejouée.

        Args:
            payload: Charge utile JSON.
            send: Envoi de la charge utile.

        Returns:
            `True` si l'envoi frais a réussi, `False` s'il a été mis en file.
        """
        data = dict(payload)
        try:
            await send(data)
        except WelleatError as exc:
            self.enqueue(data, exc)
            return False
        if self._retry_turn():
            await self.retry_due(send, limit=1)
        return True

    async def retry_due(self, send: AsyncSender, limit: int | None = None) -> int:
        """Rejoue les entrées dues ; supprime les entrées périmées.

        Args:
            send: Envoi d'une charge utile.
            limit: Nombre maximal d'entrées à rejouer ; `None` pour toutes.

        Returns:
            Le nombre d'entrées envoyées avec succès.
        """
        delivered = 0
        for entry in self._due_entries(limit):
            try:
                await send(entry.payload)
            except WelleatError as exc:
                self._record_failure(entry, exc)
            else:
                self.store.delete(entry.entry_id)
                delivered += 1
        return delivered


class SyncOutbox(_OutboxCore):
    """Outbox synchrone ; mêmes méthodes que `Outbox`."""

    def deliver(self, payload: Mapping[str, JsonValue], send: SyncSender) -> bool:
        """Tente un envoi frais ; en cas d'échec, le met en file.

        Après `fresh_before_retry` envois frais réussis, une entrée due est rejouée.

        Args:
            payload: Charge utile JSON.
            send: Envoi de la charge utile.

        Returns:
            `True` si l'envoi frais a réussi, `False` s'il a été mis en file.
        """
        data = dict(payload)
        try:
            send(data)
        except WelleatError as exc:
            self.enqueue(data, exc)
            return False
        if self._retry_turn():
            self.retry_due(send, limit=1)
        return True

    def retry_due(self, send: SyncSender, limit: int | None = None) -> int:
        """Rejoue les entrées dues ; supprime les entrées périmées.

        Args:
            send: Envoi d'une charge utile.
            limit: Nombre maximal d'entrées à rejouer ; `None` pour toutes.

        Returns:
            Le nombre d'entrées envoyées avec succès.
        """
        delivered = 0
        for entry in self._due_entries(limit):
            try:
                send(entry.payload)
            except WelleatError as exc:
                self._record_failure(entry, exc)
            else:
                self.store.delete(entry.entry_id)
                delivered += 1
        return delivered
