# welleat-api-sdk

SDK Python de l'API Welleat, issu de la rétro-ingénierie de `camera-soft`
(voir `SOMMAIRE_API_WELLEAT.md`).

```python
from welleat_api_sdk import CameraClient, CameraCredentials, ClientConfig, Environment

async with CameraClient(
    ClientConfig(Environment.DEVELOPMENT), CameraCredentials("id", "clé")
) as cam:
    await cam.tray_count()
```

## Architecture

| Module | Rôle |
| --- | --- |
| `config` | `Environment`, `Timeouts`, `ClientConfig` (une seule base d'URL `…/api`) |
| `auth` | `Credentials` (Protocol), `CameraCredentials`, `GatewayCredentials`, `EnrollmentSecrets`, `AuthMode` |
| `request` | `Request[T]` : description pure d'un appel (chemin, auth, statuts acceptés, parseur) |
| `client` | `WelleatClient` (async) et `SyncWelleatClient` : exécutent une `Request` |
| `camera_requests`, `gateway_requests` | constructeurs de `Request`, un par endpoint |
| `cameras`, `gateways` | `CameraClient`, `GatewayClient` et variantes `Sync*` |
| `models`, `errors` | dataclasses frozen avec parsing validé ; hiérarchie `WelleatError` |
| `outbox` | `Outbox` / `SyncOutbox` (file durable des envois en échec, format camera-soft `schema_version: 2`), `OutboxPolicy`, `DailyTrayCounter` |

## Outbox

```python
from welleat_api_sdk.models import FramePayload
from welleat_api_sdk.outbox import SyncOutbox

outbox = SyncOutbox("/var/lib/welleat/outbox")  # retry 20 min, péremption 7 j, blackout 10:30-15:00


def send(payload: dict) -> None:
    cam.send_frame(FramePayload.from_json(payload))


outbox.deliver(frame.to_json(), send)  # en file si échec ; 1 rejeu tous les 10 succès
outbox.retry_due(send)  # périodes creuses
```

## Principes

- Le client lève, ne réessaie jamais (`RetryableError` signale les erreurs rejouables) ; l'outbox optionnelle (`outbox`) replanifie.
- Aucun secret ni fichier lu/écrit : l'enrôlement renvoie les credentials, l'appelant les stocke.
- Les chemins conservent la casse du back-end (`temptracking`, `Reports`, `StateUpdate`...).

## Hors périmètre de cette base

Socket.IO (`realtime`), bornes/RFID (`api-local.mdev.fr`), export quotidien (contrat non défini).
