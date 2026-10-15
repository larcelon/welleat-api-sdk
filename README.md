# welleat-api-sdk

SDK Python de l'API Welleat, issu de la rétro-ingénierie de `camera-soft`
(voir `SOMMAIRE_API_WELLEAT.md`).

## Installation

Le SDK n'est pas publié sur PyPI : on l'installe depuis ce dépôt Git, épinglé sur un tag.

```bash
uv add "welleat-api-sdk @ git+https://github.com/larcelon/welleat-api-sdk.git" --tag v0.3.0
# avec le canal temps réel (Socket.IO) :
uv add "welleat-api-sdk[realtime] @ git+https://github.com/larcelon/welleat-api-sdk.git" --tag v0.3.0
```

ce qui écrit dans le `pyproject.toml` du projet :

```toml
[project]
dependencies = ["welleat-api-sdk[realtime]"]

[tool.uv.sources]
welleat-api-sdk = { git = "https://github.com/larcelon/welleat-api-sdk.git", tag = "v0.3.0" }
```

- Sans uv : `"welleat-api-sdk[realtime] @ git+https://github.com/larcelon/welleat-api-sdk.git@v0.3.0"`
  dans `dependencies`.
- Dépôt privé : `git+ssh://git@github.com/larcelon/welleat-api-sdk.git` avec une clé de
  déploiement ; ne jamais écrire de jeton dans le `pyproject.toml`.
- Développement simultané : `welleat-api-sdk = { path = "../welleat-api-sdk", editable = true }`.

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
| `realtime` | canal Socket.IO (extra `realtime`) : `CameraSocket`, `GatewaySocket` et variantes `Sync*`, `ReconnectPolicy`, événements typés |


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

## Temps réel (Socket.IO)

Nécessite l'extra `realtime` (voir Installation).

```python
from welleat_api_sdk import ClientConfig, GatewayCredentials
from welleat_api_sdk.realtime import GatewaySocket, ScaleCommand

socket = GatewaySocket(GatewayCredentials("station", "clé"), ClientConfig())


async def on_command(command: ScaleCommand) -> None: ...


async def restart_service() -> None: ...


socket.on_scale_command(on_command)
socket.on_give_up(restart_service)  # 6 échecs consécutifs par défaut
await socket.run()  # reconnecte selon la ReconnectPolicy jusqu'à stop()
```

Le SDK décode les charges utiles (objet ou chaîne JSON), distingue accusés de poids et retours de
commande, et reconnecte ; le suivi de livraison des poids et le redémarrage du service restent à
l'appelant, via les hooks `on_connect`, `on_disconnect`, `on_connect_error` et `on_give_up`.

## Principes

- Le client lève, ne réessaie jamais (`RetryableError` signale les erreurs rejouables) ; l'outbox optionnelle (`outbox`) replanifie.
- `ApiError.error_message` expose le message d'un corps `{ "error": "…" }`, seule forme d'erreur du back-end ; `body` garde le texte brut.
- Aucun secret ni fichier lu/écrit : l'enrôlement renvoie les credentials, l'appelant les stocke.
- Les chemins conservent la casse du back-end (`temptracking`, `Reports`, `StateUpdate`...).

## Hors périmètre de cette base

Bornes/RFID (`api-local.mdev.fr`), export quotidien (contrat non défini).
