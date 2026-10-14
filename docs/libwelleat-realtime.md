---
title: libwelleat-realtime — Socket.IO et compléments pour le SDK Welleat
tags: [welleat, librairie, api, socketio, sdk]
---

# libwelleat-realtime — canal temps réel et compléments

Retour à l'[[00-index|index]]. Complète [[libwelleat-api]] et `SOMMAIRE_API_WELLEAT.md` (§6) avec les détails nécessaires à un module `realtime` du SDK. Uniquement l'état implémenté ; « non observé » = non lu par le code.

## Connexion Socket.IO

### Paramètres communs
- Base : URL REST sans `/api` (`base_url.replace("/api", "")`) ; caméra : `WEBSOCKET_SERVER` (défaut `https://welleat-api.welleat.fr/`) ou `http_base` en dur. Namespace par défaut `/`.
- Transport forcé `["websocket"]` (pas de long-polling).
- Bibliothèque : `python-socketio` (client sync `Client` pour capture caméra et gateway centrale ; `AsyncClient` pour `vanilla_send_delete` et `balance_antenna`).

### Caméra
| Élément | Valeur |
| --- | --- |
| `auth` | `{cameraId, api_key}` |
| En-tête | `User-Agent: CameraClient/1.0` |
| Sur `connect` | émet `authenticate {cameraId, api_key}` (en plus de `auth`) |
| Reconnexion | capture : `reconnection=True` + boucle manuelle (`connect`, `wait()`, attente **5 s** si échec) ; envoi : `reconnection=True`, `reconnection_attempts=5` |
| Perte de lien | jamais d'arrêt du process : mode local autonome (images conservées sur disque) |
| Hub capteur (`sensor_sort_send_delete`) | connexion cloud **optionnelle** : un échec n'est qu'un avertissement |
| Simulation | pas de connexion ; capture utilise un `MockSocket` |

Deux processus caméra se connectent **en parallèle** avec les mêmes identifiants (capture et envoi) : le SDK ne doit pas supposer une connexion unique par caméra.

### Station (gateway)
| Élément | Valeur |
| --- | --- |
| `auth` | `{station_id, api_key}` (clés snake_case, **différentes** de l'API REST `apiStationId`) |
| `authenticate` | non émis |
| Relais balances | `reconnection=False`, `handle_sigint=False` : toute la politique est applicative |
| Délai de connexion | `WS_CONNECT_TIMEOUT = 20 s` |
| Attente entre essais | `WS_RETRY_INTERVAL = 10 s` après une session terminée |
| Seuil d'échecs | `WS_CONNECTION_FAILURE_THRESHOLD = 6` échecs consécutifs → redémarrage du service |
| Gateway centrale | `reconnection=True`, boucle : station non enrôlée → attente 15 s ; échec → 10 s ; connecté → test toutes les 5 s |
| Événement `connect_error` | journalisé avec motif ; la clé n'est jamais loguée |

## Catalogue des événements

### Caméra
| Sens | Événement | Charge utile | Remarques |
| --- | --- | --- | --- |
| S→C | `connect` / `disconnect` | — | `connect` déclenche `authenticate` |
| S→C | `camera-connect` | libre | journalisé seulement |
| S→C | `frame_ack` | libre | journalisé seulement |
| S→C | `manual-camera-images-asking` | dict ; `TabletId` **ou** `tablet_id` | file locale (`queue.Full` → requête ignorée) ; `TabletId` écrit dans `stats/last_tablet_id.txt` seulement s'il est « truthy » |
| C→S | `authenticate` | `{cameraId, api_key}` | |
| C→S | `frame_ack` | `{cameraId, status: "captured"}` | après capture (même nom que l'événement entrant, sens opposé) |

### Station — balances
| Sens | Événement | Charge utile | Remarques |
| --- | --- | --- | --- |
| C→S | `SCALE_STREAM_WEIGHT_UPDATE` | `{scaleId, raw_data}` | si poids changé de > 0,001 kg ou 15 s écoulées ; seulement si connecté et publication autorisée |
| C→S | `SCALE_CONNECTION_STATE` | `{scaleId, state: 0\|1}` | uniquement sur **transition** (mémoire conservée entre reconnexions) ; `1` seulement si la balance transporte réellement des trames |
| C→S | `station-heartbeat` | `{scales: [{scaleUuid, connected, streamActive, lastWeightGrams}], timestamp}` | toutes les 5 s si activé et connecté ; erreurs avalées ; `lastWeightGrams = int(kg×1000)`, `0` si flux inactif ou balance rejetée ; `timestamp` en secondes |
| C→S | `SCALE_CMD_SUCCESS` | `{scaleId, original_command, timestamp}` | acquittement d'une commande |
| C→S | `SCALE_CMD_ERROR` | `{scaleId, original_command, error_code, message}` | `error_code` observés : `SCALE_CMD_ERROR` (échec après 3 essais), `SCALE_HARDWARE_FAILURE` (IP/balance introuvable) |
| S→C | `SCALE_CMD_START_STREAM`, `…_STOP_STREAM`, `…_REBOOT`, `…_CALIBRATE_ZERO`, `…_TARE_SET` | `{scaleId, ip?}` (objet ou JSON en chaîne ; absent → `{}`) | l'`ip` du message prime sur celle connue ; 3 essais, 1,5 s entre essais ; tout autre événement entrant est ignoré |
| S→C | `SCALE_CMD_SUCCESS` (accusé de poids) | `{scaleUuid \| scaleId, …}` **sans** `original_command` | confirme les poids ; **active le rôle `debarrassage`** et rétablit la publication |
| S→C | `SCALE_CMD_ERROR` (refus de poids) | `{error \| message: "Scale not registered to this station", scaleUuid \| scaleId}` **sans** `original_command` | suspend les poids de cette balance ; ignoré si aucun poids n'est en attente |

#### Ambiguïtés à porter dans le SDK
- `SCALE_CMD_SUCCESS` / `SCALE_CMD_ERROR` ont **deux sens** selon le sens et la présence de `original_command` : le SDK doit discriminer (`original_command` présent = commande matérielle, absent = accusé de poids).
- Identifiant de balance : `scaleId` (client→serveur) mais `scaleUuid` (heartbeat, accusés) ; les deux sont lus.
- Messages possibles sous forme de **chaîne JSON** ou d'objet.
- Le message de refus est comparé en texte, insensible à la casse (`casefold`) : constante `Scale not registered to this station`.

#### Suivi de livraison des poids (logique à répliquer si le SDK expose un publisher)
- Un envoi est « en attente » jusqu'à un accusé ; état par balance : `pending_sends`, `first_pending_at`.
- `WEIGHT_ACK_TIMEOUT = 30 s`, `WEIGHT_ACK_FAILURE_THRESHOLD = 3` envois sans accusé → reconnexion forcée du socket, au plus une fois par `WEIGHT_ACK_RECONNECT_COOLDOWN = 60 s`.
- Sur `connect`/`disconnect` : suivi réinitialisé, poids republiés, état de connexion de chaque balance réémis.

#### Format du poids
`raw_data` brut (ex. `AW 1.234 T 0.1`) ; regex `AW\s*([-+]?\d+\.?\d*)` et `T\s*([-+]?\d+\.?\d*)` après retrait des caractères non imprimables ; poids net = brut − tare (défaut 0), arrondi à 3 décimales ; sans `AW` → pas de poids.

### Station — prises (gateway centrale)
| Sens | Événement | Charge utile | Effet |
| --- | --- | --- | --- |
| S→C | `connect` | — | `GET plugList` (resynchronisation) |
| S→C | `PLUG REFRESH DATA` (avec espaces) | libre | `GET plugList` |
| S→C | `PLUG_CMD_ON` / `PLUG_CMD_OFF` | `{apiPlugId}` | commande Tasmota locale `Power On/Off` (timeout 3 s), état local mis à jour, puis `PUT plugStatus` ; `apiPlugId` absent ou inconnu en base locale → ignoré |

## Compléments REST non couverts par le premier jet

### Variantes borne / RFID / NFC (base `API_BASE_URL`, défaut `https://api-local.mdev.fr/api`)
| Endpoint | Auth | Corps | Succès |
| --- | --- | --- | --- |
| `POST {base}/cameras/sendFrame` (borne) | **en-têtes** `cameraId`, `api_key` | `{image, image_name, detections, tray_id}` (`tray_id` = UID NFC ≤ 5 s, sinon `"-1"`) | 200/201 |
| `POST {base}/cameras/attachTray` (RFID) | en-têtes `cameraId`, `api_key` | `{image, image_name, detections, tray_id: <UID RFID>}` | 200/201 ; sans UID → abandon local sans appel |
| `POST {base}/checkout/terminals/{uuid}/tray-removed` | en-tête `terminal-api-key` | `{trayId}` | 200/201/204 ; non envoyé si `trayId == "-1"` ou image jamais envoyée |

Reprises : rapports et comptage RFID réutilisent `Reports` et `trayCount` sur la même base. Échec RFID → fichier pending `{type: "SEND_RFID_FRAME", trayId, image}`. Ces variantes vivent sur **une autre base d'URL** et un **autre schéma d'authentification** (en-têtes) : le SDK devra permettre un `AuthMode.HEADER_IDENTITY` et une base surchargeable par appel.

### Points de contrat à confirmer avec le back
- Corps d'erreur : seul `{ "error": "<message>" }` est lu (timelines, refus de balance) ; aucun schéma d'erreur global.
- `Idempotency-Key` MultiCam = `global_id` ; export quotidien = SHA-256 de `export_id`.
- `GET /dataAccess/sensors/taskList/{apiSensorId}` : contrat et authentification non observés.
- Valeurs de `TabletId`, `ServiceSlotId`, `scaleId` : types mixtes int/str.
- `WEB_FIRST_INSTALL*.py` : sélection d'environnement `production`/`development` côté UI → mêmes deux bases d'URL.

## Implications pour le module `realtime` du SDK
- Deux clients : `CameraSocket` (auth `cameraId`+`authenticate`) et `GatewaySocket` (auth `station_id`, pas d'`authenticate`).
- Politique de reconnexion **injectable** (intervalle, seuil d'échecs, callback d'abandon) : les services actuels diffèrent (5 s / 10 s / 15 s, illimité ou 5 essais).
- Événements entrants typés par dataclasses (`ManualCaptureRequest`, `ScaleCommand`, `WeightAck`, `WeightRejection`, `PlugCommand`) avec décodage objet **ou** chaîne JSON ; nom d'événement exact conservé (`PLUG REFRESH DATA`).
- API async (`AsyncClient`) et façade sync (threads) comme pour le REST.
- Le SDK n'implémente ni le suivi de livraison des poids ni la politique « redémarrer le service » : il expose des hooks (`on_connect`, `on_disconnect`, `on_connect_error`).
