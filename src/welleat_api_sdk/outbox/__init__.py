"""Outbox durable : mise en file des envois en échec et politique de rejeu.

Optionnelle et hors des clients HTTP : le client lève, l'outbox replanifie.
Le format de fichier (`schema_version: 2`) et la politique reprennent ceux de
camera-soft, pour reprendre les envois en attente sur les appareils déployés.
"""

from welleat_api_sdk.outbox.policy import OutboxPolicy
from welleat_api_sdk.outbox.runner import Outbox, SyncOutbox
from welleat_api_sdk.outbox.store import FileOutboxStore, OutboxEntry
from welleat_api_sdk.outbox.tray_counts import DailyTrayCounter, SyncDailyTrayCounter

__all__ = [
    "DailyTrayCounter",
    "FileOutboxStore",
    "Outbox",
    "OutboxEntry",
    "OutboxPolicy",
    "SyncDailyTrayCounter",
    "SyncOutbox",
]
