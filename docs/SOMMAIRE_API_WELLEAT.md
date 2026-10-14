---
title: Sommaire des contrats et interfaces — API Welleat
tags: [welleat, api, sdk, contrats, rewrite]
---

# Sommaire des contrats API Welleat (état actuel du code)

Objectif : servir de base de spécification pour un **SDK Python** partagé par le rework. Ce document ne décrit que ce qui est **implémenté aujourd'hui** ; les réponses serveur non lues par le code sont marquées *« non observé »* (le SDK devra les valider contre le back-end).

Complète [[documentation/libwelleat-api|libwelleat-api]] (catalogue d'URLs) en ajoutant les **corps de requête, réponses, codes d'erreur, politiques de retry et canaux Socket.IO**.

> Les secrets d'enrôlement globaux sont codés en dur dans plusieurs fichiers (`first_install.sh`, `WEB_FIRST_INSTALL.py`, `balance_antenna.py`, `bt_temp_relay.py`, `ajouter_au_fichier_env.py`). Ils ne sont **volontairement pas reproduits ici**. Le SDK doit les recevoir par configuration.

## 1. Vue d'ensemble

| Acteur | Identité | Transport |
| --- | --- | --- |
| Caméra (Jetson) | `CAMERA_ID` + `API_KEY` (`.env`) | HTTP REST + Socket.IO |
| Station / gateway (Raspberry) | `apiStationId` + `api_key` (`balance_config.json`, `bt_config.json`) | HTTP REST + Socket.IO |
| Enrôlement (les deux) | clé + secret **globaux** + MAC | HTTP REST |

### Environnements et bases d'URL

| Env | Base REST | Base Socket.IO |
| --- | --- | --- |
| production | `https://welleat-api.welleat.fr/api` | `https://welleat-api.welleat.fr` |
| développement | `https://welleat-api-dev.welleat.fr/api` | `https://welleat-api-dev.welleat.fr` |

- Caméra : `SERVER_URL` = `…/api/cameras` (utilisé par monitoring et timelines) ; `vanilla_send_delete.py` code `https://welleat-api.welleat.fr` en dur.
- Gateway : `BASE_API_URL` (`.env`), défaut **dev**. L'URL Socket.IO est dérivée par `base_url.replace("/api", "")`.
- ⚠️ Piège actuel : certains appels ajoutent `/cameras/` ou `/stations/` à une base qui contient déjà `/api`, d'autres non. Le SDK doit avoir **une seule base** et des chemins relatifs.

## 2. Authentification et en-têtes

| Contexte | En-têtes / champs |
| --- | --- |
| Enrôlement caméra | `api-key`, `api-secret` (globaux), `X-Device-Mac`, `hostname` ; **pas de corps** |
| Enrôlement station | mêmes en-têtes, vers `addNewStation` |
| Caméra – monitoring, rapports, comptage | `api-key: <API_KEY caméra>` (+ `Content-Type: application/json` si corps) |
| Caméra – images (`sendFrame`, `sendControlFrames`) | `cameraId` + `api_key` **dans le corps JSON** |
| Station – la plupart des appels | `api-key: <clé station>` ; souvent aussi `apiStationId: <id>` en en-tête |
| Station – `sendWeights`, `sendTemperatures` | `api-key` seul (pas de `apiStationId`) |
| Station – `plugStatus`, `plugConsumption` | `api-key` en en-tête **et** `api_key` dans le corps |
| Socket.IO caméra | `auth={cameraId, api_key}` à la connexion **+** émission `authenticate {cameraId, api_key}` sur `connect` |
| Socket.IO station | `auth={station_id, api_key}` (pas d'événement `authenticate`) |
| `fetchLastChefImage` | aucune authentification |

Reconnexion Socket.IO : `reconnection=True`, `transports=["websocket"]`, `reconnection_attempts=5` côté caméra (`vanilla_send_delete`), illimitée côté gateway (boucle manuelle 10–15 s). `User-Agent: CameraClient/1.0` côté caméra.

## 3. Contrats REST — caméra

Timeouts caméra (envoi images) : total 10 s, connect 3 s, lecture 7 s. Monitoring : 10 s. Timelines : `(3.05, 15.0)`. LED : 5 s.

### 3.1 `POST {base}/cameras/connectCamera/` — enrôlement
- Requête : en-têtes uniquement (voir §2). Timeout 10 s.
- Réponse 200 : `{ "cameraId": str, "api_key": str }`.
- Erreur : `first_install.sh` n'analyse que la présence des deux champs ; `WEB_FIRST_INSTALL.py` retourne `HTTP {status} : {texte}`.
- Effet de bord attendu côté appelant : écrire `CAMERA_ID`, `API_KEY` dans `.env`.
- MAC : format `AA:BB:CC:DD:EE:FF`, validé par `register_camera.sh` (`^([0-9A-F]{2}:){5}…`), route par défaut puis première interface physique.

### 3.2 `POST {base}/cameras/sendFrame` — image normale
```jsonc
{
  "cameraId": "<id>",
  "api_key":  "<clé>",
  "image":       "data:image/jpeg;base64,<…>",   // 640×480 recadrée, anonymisée
  "image_name":  "frame_YYYYMMDD_HHMMSS_ffffff.jpg",
  "detections": [ { "label": "tray", "confidence": 0.9, "bbox": [x1,y1,x2,y2], "track_id": 3 } ]
}
```
- Succès : **200 ou 201** uniquement (hors MultiCam). Autre statut → retry (§5).
- `detections[].label` valeurs observées : `tray` (+ autres classes du modèle, `data.yaml`). `track_id` présent surtout sur `tray`. `bbox` en pixels de l'image **envoyée** (recalculée après recadrage).
- Pré-conditions locales (non API) : `privacy.status`/`privacy_verified` obligatoires, sinon rien n'est envoyé.
- Variantes :
  - **Borne/RFID** (`borne_…`, `rfid_…`) : `cameraId`/`api_key` passent en **en-têtes** et le corps ajoute `tray_id` (UID NFC ou `"-1"`). Endpoints `…/cameras/sendFrame` ou `…/cameras/attachTray` (RFID). Base `API_BASE_URL` (défaut `https://api-local.mdev.fr/api`).
  - **MultiCam coordinateur** : corps étendu avec `sourceCameraId`, `rigId`, `global_tray_id`, `quality_score`, `quality_low`, `image_name` normalisé ; en-têtes `Idempotency-Key` et `X-Welleat-Global-Tray-Id` = `global_id`. **409 = succès** (doublon).

### 3.3 `POST {base}/cameras/sendControlFrames` — image « chef »
```jsonc
{
  "cameraId": "<id>", "api_key": "<clé>",
  "TabletId": 12,                          // int si convertible, sinon str ; peut être null
  "images": [ { "image": "data:image/jpeg;base64,…", "image_name": "…jpg", "detections": [ … ] } ]
}
```
- En-têtes : `Content-Type: application/json`, `Accept: application/json`. Succès 200/201.
- `TabletId` provient de l'événement Socket.IO `manual-camera-images-asking` (§6) via `last_tablet_id.txt`.

### 3.4 `POST {base}/cameras/trayCount/{cameraId}` — incrément de comptage
- En-tête `api-key`. **Aucun corps.** Un appel = +1 plateau.
- Succès = statut 200/201 **ET** corps contenant le texte `Count save` (réponse non-JSON).
- Échec → compteur persistant `pending_counts_file` ; rattrapage toutes les 60 s **uniquement le jour même** (purge si la date a changé).
- MultiCam : ajoute `Idempotency-Key` + `X-Welleat-Global-Tray-Id` ; 409 accepté.

### 3.5 `POST {base}/cameras/Reports/{cameraId}` — rapport d'activité
```json
{ "lastImageDate": "<contenu de last_sent_time.txt ou null>", "imageCount": 42, "ServiceSlotId": 12 }
```
- `ServiceSlotId` uniquement envoyé par `monitor_raspberry.py` (valeur calculée depuis `TIMELINE_SEGMENT_n`, `0` si hors créneau). L'envoi post-image (`vanilla_send_delete`) omet ce champ.
- Succès 200/201 ; erreurs seulement journalisées, **aucun retry**.

### 3.6 Monitoring (`monitor_raspberry.py`, boucle 150 s)

| Endpoint | Méthode | Corps | Succès |
| --- | --- | --- | --- |
| `/cameras/temptracking/{id}` | POST | `{ "temperature": float (1 déc.), "softVersion"?: "<APP_VERSION>" }` | 200/201 |
| `/cameras/StateUpdate/{id}` | **PUT** | `{ "state": <0\|1> }` (1 si l'heure courante est dans un `TIMELINE_SEGMENT_1..5`) | 200/201/204 |
| `/cameras/SpeedPerfs/{id}` | POST | `{ "speedPerf": int }` (octets/s, mesuré toutes les 3600 s via `speedtest.tele2.net/1MB.zip`) | 200/201 |

Casse à conserver : `temptracking` (minuscules) côté caméra.

### 3.7 `GET {base}/cameras/ServiceSlots/{cameraId}` — timelines
- `cameraId` encodé URL (`quote(..., safe="")`). En-tête `api-key`. Base = `SERVER_URL` (défaut `https://welleat-api.welleat.fr/api/cameras/`).
- Réponse : objet **ou** liste d'objets :
  ```json
  { "ServiceSlotId": 12, "schedules": ["11:00", "15:00"] }
  ```
  - `ServiceSlotId` : `int` (ou chaîne décimale) ; `bool` rejeté. `schedules` : liste de `str`.
  - Le client joint `schedules` en `"11:00,15:00"` → variable `TIMELINE_SEGMENT_<id>`.
- Erreurs : corps `{ "error": "<message>" }` lu si JSON ; vide/liste vide → exception, `.env` non modifié.

### 3.8 `GET {base}/cameras/fetchLastChefImage/{cameraId}`
- Sans authentification, timeout 5 s. Réponse 200 : `{ "timestamp": <epoch secondes, nombre> }`. Tout autre cas → traité comme « pas d'image récente ».

### 3.9 Borne de commande (hors périmètre caméra standard, API distincte)
- `POST {API_BASE_URL}/checkout/terminals/{TERMINAL_UUID}/tray-removed`, en-tête `terminal-api-key`, corps `{ "trayId": "<str>" }`, succès 200/201/204.
- ⚠️ Un `TERMINAL_UUID`/`TERMINAL_API_KEY` par défaut est codé en dur dans `borne_sort_send_delete.py` : à externaliser.

### 3.10 Export quotidien (`daily_export_uploader.py`) — non actif
- URLs **vides** dans le code (`CONTROL_COUNTING_EXPORT_API_URL`, `SORT_CONTROL_EXPORT_API_URL`, `API_KEY`) : contrat à définir avec le back.
- Forme prévue : `multipart/form-data` — champ `metadata` (JSON) + champ `video` (`video/mp4`, comptage) **ou** `archive` (`application/zip`, sélection). En-têtes `cameraId`, `Idempotency-Key` (= SHA-256 de `export_id` = `<kind>:<camera_id>:<dossier>`), `User-Agent: welleat-daily-export-uploader/1`, `api-key` si renseignée. Succès : tout 2xx. Timeout 300 s.

## 4. Contrats REST — station / gateway

Préfixe `{base}/stations/…` (`base` incluant `/api`).

### 4.1 Enrôlement et télémétrie station

| Endpoint | Méthode | Corps | Réponse |
| --- | --- | --- | --- |
| `/stations/addNewStation` | POST | aucun (en-têtes globaux + `X-Device-Mac` + `hostname`) | 200/201 `{ "apiStationId": str, "api_key": str }` → persisté en JSON local |
| `/stations/tempTracking/{station}` | POST | `{ "tempTracking": float }` (temp. CPU) | **201** attendu (log d'erreur sinon) |

### 4.2 Balances

| Endpoint | Méthode | Corps | Réponse |
| --- | --- | --- | --- |
| `/stations/addNewScale/{station}` | POST | `{ "ipAddress": "<ip>", "macAddress": "<MAC ou null>" }` | JSON avec `scaleId` \| `id` \| `_id`, **ou** texte brut = l'identifiant. Idempotent : renvoyer un id connu = IP mise à jour |
| `/stations/sendWeights/{station}` | POST | `{ "datas": [ { "scaleId", "value": kg, "date": str } ], "speedPerf"?: int }` | 200/201 (code présent mais décrit comme inutilisé : le flux nominal passe par Socket.IO) |

`speedPerf` : au plus 1 fois/heure, lu depuis un fichier de vitesse centralisé (validité 7200 s).
Identifiant balance : MAC si disponible (jamais `00:00:00:00:00:00`, ignoré), sinon IP.

### 4.3 Capteurs de température (BLE)

| Endpoint | Méthode | Corps | Réponse |
| --- | --- | --- | --- |
| `/stations/addNewSensor/{station}` | POST | `{ "hardwareId": "<nom BLE>" }` | 200/201 `{ "apiSensorId": str }` |
| `/stations/sendTemperatures/{station}` | POST | voir ci-dessous | 200/201 = succès, ligne retirée de la file SQLite |
| `/stations/sensorStatsTracking/{station}` | POST | `{ "datas": [ { "apiSensorId", "batteryLevel", "wifiSignalDbm", "isConnected": true } ] }` | non lue (erreurs avalées) |
| `/stations/ignored/{station}` | GET | — | `{ "ignored_hardware_ids": [str] }` |
| `/dataAccess/sensors/taskList/{apiSensorId}` | GET | — | JSON non typé *(non observé)* — attention : **hors `/stations`** |

Corps `sendTemperatures` :
```jsonc
{
  "datas": [ { "apiSensorId": "…", "value": 4.2, "date": "2026-10-14T10:00:00Z",
               "batteryLevel"?: 87, "wifiSignalDbm"?: -61 } ],
  "tempTracking"?: 51.2,     // temp. CPU station
  "speedPerf"?: 123456       // au plus 1 fois par SPEED_TEST_INTERVAL
}
```
- `date` = `timestamp_end` agrégé, ISO-8601 UTC suffixé `Z`. `value` = `avg_temperature`. File persistante SQLite (`upload_queue`) : envoi FIFO, timeout 15 s.

### 4.4 Prises connectées (Tasmota)

| Endpoint | Méthode | Corps | Notes |
| --- | --- | --- | --- |
| `/stations/plugList/{station}` | GET | — | Réponse : liste de `{ "apiPlugId", "ipAddress", "name", "stationPlug": bool, "PlugProgrammings": [ { "turnOn": "HH:MM:SS", "turnOff": "HH:MM:SS", "days": [1..7] } ] }`. `days` : 1 = lundi … 7 = dimanche. Seul `PlugProgrammings[0]` est utilisé |
| `/stations/plugStatus/{station}` | **PUT** | `{ "apiPlugId", "status": bool, "api_key" }` | timeout 5 s, statut non vérifié |
| `/stations/plugConsumption/{station}` | **PUT** | `{ "apiPlugId", "power", "energy", "current", "api_key" }` | timeout 5 s, statut non vérifié |

Les en-têtes de ces trois appels : `Content-Type: application/json`, `api-key`.

### 4.5 Watchdog interne (hors API Welleat)
`bt_antenna/protection_client.py` poste `{ "station_id", "active_sensors": {hw_id: apiSensorId|null}, "hostname" }` vers des serveurs internes (`100.86.97.52–54:8000`). À ne **pas** inclure dans le SDK Welleat.

## 5. Politiques de fiabilité à reprendre dans le SDK

| Mécanisme | Valeur actuelle | Source |
| --- | --- | --- |
| Outbox images (fichier JSON atomique) | `schema_version: 2`, champs `payload`, `retries`, `next_attempt_at`, `first_failed_at`, `last_error`, `last_status`, `privacy_verified` | `vanilla_send_delete.py` |
| Délai de retry | 1200 s (20 min) | `outbox_policy.py` |
| Péremption | 7 jours → suppression | `PENDING_MAX_RETRY_AGE_SECONDS` |
| Priorité | 10 envois « frais » pour 1 retry | `FRESH_DELIVERIES_BEFORE_RETRY` |
| Blackout jours précédents | 10:30–15:00 (les trames anciennes attendent) | `outbox_policy.py` |
| Statuts de succès | 200, 201 (+ 409 en MultiCam) ; **tout autre statut = replanification** | |
| Quarantaine | JSON invalide → `.invalid` ; non certifié privacy → `.privacy_blocked` | |
| `trayCount` | file de compteurs du jour uniquement | `_add_pending_tray_count` |
| `Reports`, `monitoring`, plugs | pas de retry | |
| Idempotence | `Idempotency-Key` (MultiCam, exports) ; **absente** en mono-caméra | |

## 6. Socket.IO

### 6.1 Caméra (capture et envoi)

| Sens | Événement | Charge utile | Rôle |
| --- | --- | --- | --- |
| serveur→client | `connect` | — | déclenche `authenticate` |
| client→serveur | `authenticate` | `{ cameraId, api_key }` | auth applicative en plus de `auth=` |
| serveur→client | `camera-connect` | message libre | simplement journalisé |
| serveur→client | `frame_ack` | message libre | journalisé |
| serveur→client | `manual-camera-images-asking` | `{ "TabletId" \| "tablet_id": … , … }` | demande de capture manuelle « chef » ; payload mis en file locale et `TabletId` persisté (`stats/last_tablet_id.txt`) |
| client→serveur | `frame_ack` | `{ cameraId, status: "captured" }` | émis par le capteur après capture |

Perte de connexion = **mode local autonome** (jamais d'arrêt du process).

### 6.2 Station — balances

Connexion : `auth={station_id, api_key}`, `transports=["websocket"]`.

| Sens | Événement | Charge utile |
| --- | --- | --- |
| client→serveur | `SCALE_STREAM_WEIGHT_UPDATE` | `{ scaleId, raw_data }` (trame brute, ex. `AW 1.234 T 0.1`) ; émis si poids changé (>0,001) ou 15 s écoulées |
| client→serveur | `SCALE_CONNECTION_STATE` | `{ scaleId, state: 0\|1 }` (uniquement sur transition, uniquement rôle `debarrassage`) |
| client→serveur | `station-heartbeat` | `{ scales: [ { scaleUuid, connected, streamActive, lastWeightGrams } ], timestamp }` toutes les 5 s |
| client→serveur | `SCALE_CMD_SUCCESS` | `{ scaleId, original_command, timestamp }` |
| client→serveur | `SCALE_CMD_ERROR` | `{ scaleId, original_command, error_code, message }` |
| serveur→client | `SCALE_CMD_START_STREAM`, `SCALE_CMD_STOP_STREAM`, `SCALE_CMD_REBOOT`, `SCALE_CMD_CALIBRATE_ZERO`, `SCALE_CMD_TARE_SET` | commandes (retry 1,5 s côté balance) |
| serveur→client | `SCALE_CMD_SUCCESS` / `SCALE_CMD_ERROR` (retour backend) | accusés de réception du poids (rejeu/blocage de publication) |

Poids : `raw_data` contient `AW<brut>` et `T<tare>` ; le poids net = brut − tare (kg, arrondi 3 déc.).

### 6.3 Station — prises (gateway centrale)

| Sens | Événement | Charge utile |
| --- | --- | --- |
| serveur→client | `PLUG REFRESH DATA` (avec **espaces**) | libre → déclenche `GET plugList` |
| serveur→client | `PLUG_CMD_ON` / `PLUG_CMD_OFF` | `{ apiPlugId }` → commande Tasmota puis `PUT plugStatus` |

Incohérence de nommage à noter (`PLUG REFRESH DATA` vs `PLUG_CMD_*`) : le SDK doit exposer l'événement exact.

## 7. Modèles de données à typer dans le SDK

| Modèle | Champs |
| --- | --- |
| `Detection` | `label: str`, `confidence: float`, `bbox: [float×4]`, `track_id?: int\|str` |
| `CameraCredentials` | `camera_id`, `api_key` |
| `StationCredentials` | `api_station_id`, `api_key` |
| `FramePayload` | `image` (data-URI JPEG), `image_name`, `detections[]`, `tray_id?` |
| `ChefFramePayload` | `tablet_id`, `images[]` |
| `ReportPayload` | `last_image_date?`, `image_count`, `service_slot_id?` |
| `ServiceSlot` | `service_slot_id: int`, `schedules: list[str]` |
| `PlugConfig` | `api_plug_id`, `ip_address`, `name`, `station_plug`, `programmings[]` |
| `SensorReading` | `api_sensor_id`, `value`, `date` (ISO UTC `Z`), `battery_level?`, `wifi_signal_dbm?` |
| `WeightReading` | `scale_id`, `value`, `date` |
| `ManualCaptureRequest` | `tablet_id` (clé `TabletId` ou `tablet_id`) |

## 8. Incohérences et risques à traiter dans le SDK

1. **Authentification hétérogène** : `api-key` en en-tête, `api_key` dans le corps, ou les deux ; `cameraId` en en-tête (borne) ou en corps. Le SDK devrait masquer cela par client (`CameraClient`, `StationClient`) sans changer ce que le back accepte.
2. **Casse des chemins** : `temptracking` (caméra) vs `tempTracking` (station), `Reports`, `StateUpdate`, `SpeedPerfs`, `ServiceSlots` en PascalCase. À conserver strictement.
3. **Verbes** : `StateUpdate`, `plugStatus`, `plugConsumption` en **PUT** ; le reste en POST/GET.
4. **Succès de `trayCount`** dépend d'un texte (`Count save`), pas d'un schéma JSON.
5. **`/dataAccess/sensors/taskList`** est le seul endpoint hors `/cameras` et `/stations`.
6. **Formats d'identifiant** : `ServiceSlotId` int, `TabletId` int ou str, `scaleId` parfois texte brut.
7. **Aucune idempotence** en mono-caméra : un retry après timeout peut dupliquer une image ou un comptage.
8. **Secrets** : clé/secret globaux et `TERMINAL_API_KEY` en clair dans le dépôt ; `API_KEY_TEMP`/`API_SECRET` écrits dans le `.env`.
9. **Défauts divergents** : base dev pour la gateway, prod en dur pour la caméra ; `rfid`/`borne` visent `api-local.mdev.fr`.
10. **Réponses non typées côté code** : seuls `connectCamera`, `addNewStation`, `addNewSensor`, `ServiceSlots`, `plugList`, `ignored`, `fetchLastChefImage` sont lues ; le reste n'est vérifié que sur le statut.

## 9. Périmètre proposé du SDK

```
welleat_sdk/
├── config.py          # Environment(prod|dev), base_url, timeouts
├── auth.py            # Credentials, en-têtes (api-key / corps / Socket.IO auth)
├── errors.py          # ApiError(status, body), NotEnrolled, RetryableError
├── models.py          # §7
├── cameras.py         # CameraClient : connect_camera, send_frame, send_control_frames,
│                      #   tray_count, report, temp_tracking, state_update, speed_perf,
│                      #   service_slots, last_chef_image
├── stations.py        # StationClient : add_new_station, add_scale, add_sensor,
│                      #   send_temperatures, sensor_stats, ignored_sensors, task_list,
│                      #   temp_tracking, plug_list, plug_status, plug_consumption
├── realtime.py        # CameraSocket / StationSocket (Socket.IO sync + async)
└── outbox.py          # file durable + politique de retry (voir §5), optionnelle
```

Points de conception issus de l'existant :
- Clients **async (aiohttp)** pour l'envoi d'images et les balances, **sync (requests)** pour monitoring/timelines/plugs : prévoir les deux, ou un cœur async avec façade sync.
- Garder l'outbox hors du client HTTP pur (le client lève, l'outbox replanifie).
- Exposer la détection de succès par endpoint (statuts acceptés, 409 idempotent, texte `Count save`).
- Paramétrer MultiCam (`Idempotency-Key`, `X-Welleat-Global-Tray-Id`, champs `sourceCameraId`/`rigId`/`global_tray_id`) comme options de `send_frame`/`tray_count`.

## 10. Hors périmètre Welleat (ne pas mettre dans le SDK)

GitHub (releases, LFS, contents), Tailscale, `speedtest.tele2.net`, `google.com/generate_204`, serveur monitor interne `100.71.41.74:5000` (`/api/alert`, `/api/alerts_batch`, `/api/metrics`, `/api/upload_training`, `/api/ping`, `/api/device/role`), watchdog `100.86.97.5x:8000`, APIs locales (`/api/multicam/*`, `/api/wifi/*`, `/api/nfc/tray`, `/retake_trigger`, badgeuse), commandes Tasmota (`http://<ip>/cm?cmnd=…`), protocole balances TCP.
