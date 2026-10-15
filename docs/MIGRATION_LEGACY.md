# Migration du legacy caméra/gateway vers le SDK

Correspondance entre les appels Welleat du legacy (rétro-ingénierie, chaîne `welleat/camera-soft-legacy#1`)
et les méthodes de `welleat-api-sdk` v0.3.0. Les chemins sont relatifs à la base d'URL du client.

Légende des clients : caméra = `CameraClient` (async) / `SyncCameraClient` ; station =
`GatewayClient` (async) / `SyncGatewayClient`. Une méthode listée existe à l'identique dans les deux variantes.
La colonne « Test » indique le test de contrat dans `tests/test_clients.py` (sync) ; l'async partage les
mêmes constructeurs de requêtes (`camera_requests.py`, `gateway_requests.py`).

## REST caméra

| Appel legacy | Auth | Méthode SDK (sync / async) | Test |
| --- | --- | --- | --- |
| `POST cameras/connectCamera/` (sans corps → `{cameraId, api_key}`) | en-têtes `api-key`, `api-secret`, `X-Device-Mac`, `hostname` | `connect_camera(secrets, device)` → `CameraCredentials` | oui |
| `POST cameras/sendFrame` (`{image, image_name, detections}`, 200/201) | `cameraId` + `api_key` dans le corps | `send_frame(frame, multicam=None)` | oui |
| `POST cameras/sendControlFrames` (`TabletId`, `images[]`) | `cameraId` + `api_key` dans le corps | `send_control_frames(payload)` | oui |
| `POST cameras/trayCount/{id}` (sans corps ; succès = 200/201 **et** `Count save`) | `api-key` | `tray_count(multicam=None)` | oui |
| `POST cameras/Reports/{id}` (`{lastImageDate, imageCount[, ServiceSlotId]}`) | `api-key` | `report(payload)` | oui |
| `POST cameras/temptracking/{id}` (`{temperature[, softVersion]}`) | `api-key` | `temp_tracking(temperature, soft_version=None)` | oui |
| `PUT cameras/StateUpdate/{id}` (`{state: 0\|1\|2}`) | `api-key` | `state_update(state: CameraState \| bool)` | oui |
| `POST cameras/SpeedPerfs/{id}` (`{speedPerf}`) | `api-key` | `speed_perf(bytes_per_second)` | oui |
| `GET cameras/ServiceSlots/{id}` | `api-key` | `service_slots()` → `list[ServiceSlot]` | oui |
| `GET cameras/fetchLastChefImage/{id}` (`{timestamp}`) | aucune | `last_chef_image()` → `datetime \| None` (tout échec → `None`) | oui |

`state_update` : `CameraState.CHEF` → 2, `SEGMENT` → 1, `OFF` → 0 ; `True` → 1 et `False` → 0 (compatibilité).
Toute autre valeur (`3`, `"1"`, `None`, `1.0`) lève `TypeError` sans construire de requête.

## REST station

| Appel legacy | Auth | Méthode SDK (sync / async) | Test |
| --- | --- | --- | --- |
| `POST stations/addNewStation` | en-têtes d'enrôlement (comme `connectCamera`) | `add_new_station(secrets, device)` → `GatewayCredentials` | oui |
| `POST stations/tempTracking/{s}` (`{tempTracking}`, 201) | `api-key` | `temp_tracking(cpu_temperature)` | non (voir « Manques ») |
| `POST stations/addNewScale/{s}` (`{ipAddress, macAddress}`) | `api-key` | `add_scale(scale)` → identifiant (`scaleId` \| `id` \| `_id` ou texte brut) | oui |
| `POST stations/sendWeights/{s}` | `api-key` seul | `send_weights(readings, speed_perf=None)` | **non** (voir « Manques ») |
| `POST stations/addNewSensor/{s}` (`{hardwareId}` → `{apiSensorId}`) | `api-key` | `add_sensor(hardware_id)` | oui |
| `POST stations/sendTemperatures/{s}` | `api-key` seul | `send_temperatures(readings, cpu_temperature=None, speed_perf=None)` | oui |
| `POST stations/sensorStatsTracking/{s}` | `api-key` | `sensor_stats(stats)` ; `SensorStat.battery_level` / `wifi_signal_dbm` : `int \| None` | oui |
| `GET stations/ignored/{s}` (`{ignored_hardware_ids}`) | `api-key` | `ignored_sensors()` → `list[str]` | oui |
| `GET dataAccess/sensors/taskList/{sensor}` | `api-key` | `task_list(api_sensor_id)` | oui |
| `GET stations/plugList/{s}` | `api-key` | `plug_list()` → `list[PlugConfig]` | oui |
| `PUT stations/plugStatus/{s}` | `api-key` en-tête **et** `api_key` corps | `plug_status(api_plug_id, status)` | oui |
| `PUT stations/plugConsumption/{s}` | `api-key` en-tête **et** `api_key` corps | `plug_consumption(api_plug_id, power, energy, current)` | oui |

`SensorReading(…, battery_level=0, wifi_signal_dbm=0)` envoie bien `batteryLevel: 0` / `wifiSignalDbm: 0`
(le legacy perdait ces valeurs ; non reproduit, couvert par un test de non-régression).

## Socket.IO

Classes dans `welleat_api_sdk.realtime` (extra `realtime`), testées dans `tests/test_realtime.py`.

| Événement legacy | Sens | Classe / méthode SDK |
| --- | --- | --- |
| `authenticate` | client→serveur | `CameraSocket` : émis automatiquement à la connexion |
| `camera-connect` | serveur→client | `CameraSocket.on_camera_connect` |
| `frame_ack` | serveur→client / client→serveur (`{status: "captured"}`) | `CameraSocket.on_frame_ack` / `send_frame_ack` |
| `manual-camera-images-asking` | serveur→client | `CameraSocket.on_manual_capture` |
| `SCALE_STREAM_WEIGHT_UPDATE` | client→serveur | `GatewaySocket.send_weight_update` |
| `SCALE_CONNECTION_STATE` | client→serveur | `GatewaySocket.send_connection_state` |
| `station-heartbeat` | client→serveur | `GatewaySocket.send_heartbeat` |
| `SCALE_CMD_*` (commandes) | serveur→client | `GatewaySocket.on_scale_command` |
| `SCALE_CMD_SUCCESS` / `SCALE_CMD_ERROR` | client→serveur | `send_command_success` / `send_command_failure` |
| `SCALE_CMD_SUCCESS` / `SCALE_CMD_ERROR` (accusés de poids) | serveur→client | `on_weight_ack` / `on_weight_rejection` |
| `PLUG REFRESH DATA` (avec espaces) | serveur→client | `GatewaySocket.on_plug_refresh` |
| `PLUG_CMD_ON` / `PLUG_CMD_OFF` | serveur→client | `GatewaySocket.on_plug_command` |

Les variantes synchrones portent les mêmes noms (`SyncCameraSocket`, `SyncGatewaySocket`).

## Différences volontaires

- **Une seule base d'URL** par client (`ClientConfig`), chemins relatifs ; fin du mélange base avec/sans `/api`.
- **Authentification masquée par client** : l'appelant ne choisit plus entre `api-key` en en-tête, `api_key`
  dans le corps ou les deux ; chaque requête porte son mode.
- **Erreurs typées au lieu de logs** : `ApiError`, `ServerError`, `NetworkError`, `NotEnrolledError`,
  `ResponseFormatError`... ; aucune erreur n'est avalée silencieusement (sauf `last_chef_image`, qui conserve la
  sémantique « pas d'image récente »).
- **Pas de lecture d'environnement** : identifiants, secrets d'enrôlement et base d'URL sont passés par
  l'application ; le SDK ne lit ni `.env` ni variables d'environnement.
- **Valeurs `0` conservées** dans `sendTemperatures` (bug du legacy non reproduit).

## Écarté (hors périmètre de cette migration)

Bornes RFID/NFC (`attachTray`, `tray-removed`), export quotidien, serveur monitor interne, watchdog, Tasmota,
secrets. Aucun changement de protocole ni de chemin.

## Manques constatés

- `stations/tempTracking/{s}` (`temp_tracking` côté station) : aucun test de contrat dédié trouvé dans `tests/`.
- `stations/sendWeights/{s}` (`send_weights`) : aucun test de contrat ; l'appel n'est de toute façon jamais
  utilisé par le legacy.
