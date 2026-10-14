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

## Principes

- Le client lève, ne réessaie jamais (`RetryableError` signale les erreurs rejouables) ; l'outbox est hors SDK.
- `ApiError.error_message` expose le message d'un corps `{ "error": "…" }`, seule forme d'erreur du back-end ; `body` garde le texte brut.
- Aucun secret ni fichier lu/écrit : l'enrôlement renvoie les credentials, l'appelant les stocke.
- Les chemins conservent la casse du back-end (`temptracking`, `Reports`, `StateUpdate`...).

## Hors périmètre de cette base

Socket.IO (`realtime`), outbox, bornes/RFID (`api-local.mdev.fr`), export quotidien (contrat non défini).
