"""Politique de rejeu de l'outbox (valeurs de `outbox_policy.py` de camera-soft).

Fonctions pures : l'heure courante est toujours passée en argument, avec son
fuseau, qui sert aussi de référence pour le jour et le créneau de blackout.
"""

from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta

from welleat_api_sdk.errors import ApiError, WelleatError
from welleat_api_sdk.outbox.store import OutboxEntry


@dataclass(frozen=True, slots=True)
class OutboxPolicy:
    """Délais, péremption, priorité et blackout de l'outbox.

    Attributes:
        retry_delay: Attente entre deux tentatives d'une même entrée.
        max_age: Âge (depuis le premier échec) au-delà duquel l'entrée est supprimée.
        fresh_before_retry: Envois frais réussis avant de rejouer une entrée.
        blackout_start: Début du créneau où les entrées des jours précédents attendent.
        blackout_end: Fin (exclue) de ce créneau.
    """

    retry_delay: timedelta = timedelta(seconds=1200)
    max_age: timedelta = timedelta(days=7)
    fresh_before_retry: int = 10
    blackout_start: time = time(10, 30)
    blackout_end: time = time(15, 0)

    def is_expired(self, entry: OutboxEntry, now: datetime) -> bool:
        """Indique si l'entrée est périmée.

        Args:
            entry: Entrée à examiner.
            now: Heure courante.

        Returns:
            `True` si le premier échec date de plus de `max_age`.
        """
        return entry.first_failed_at is not None and now - entry.first_failed_at > self.max_age

    def in_blackout(self, entry: OutboxEntry, now: datetime) -> bool:
        """Indique si l'entrée doit attendre la fin du blackout.

        Pendant le créneau (heure locale de `now`), seules les entrées d'un jour
        précédent attendent : celles du jour passent.

        Args:
            entry: Entrée à examiner.
            now: Heure courante.

        Returns:
            `True` si l'entrée date d'un jour précédent et que `now` est dans le créneau.
        """
        if entry.first_failed_at is None:
            return False
        older = entry.first_failed_at.astimezone(now.tzinfo).date() < now.date()
        return older and self.blackout_start <= now.time() < self.blackout_end

    def is_due(self, entry: OutboxEntry, now: datetime) -> bool:
        """Indique si l'entrée peut être rejouée maintenant.

        Args:
            entry: Entrée à examiner.
            now: Heure courante.

        Returns:
            `True` si sa tentative est échue et qu'elle n'est pas en blackout.
        """
        ready = entry.next_attempt_at is None or entry.next_attempt_at <= now
        return ready and not self.in_blackout(entry, now)

    def reschedule(self, entry: OutboxEntry, now: datetime, error: WelleatError) -> OutboxEntry:
        """Enregistre un échec et replanifie l'entrée.

        Args:
            entry: Entrée en échec.
            now: Heure courante.
            error: Erreur levée par l'envoi.

        Returns:
            L'entrée mise à jour.
        """
        return replace(
            entry,
            retries=entry.retries + 1,
            next_attempt_at=now + self.retry_delay,
            first_failed_at=entry.first_failed_at or now,
            last_error=str(error),
            last_status=error.status if isinstance(error, ApiError) else None,
        )
