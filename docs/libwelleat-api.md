---
title: libwelleat-api — URLs, en-têtes et identités d'API
tags: [welleat, librairie, api]
---

# libwelleat-api — accès à l'API Welleat

Retour à l'[[00-index|index]]. Utilisé par : tous les documents caméra et gateway.

## Environnements

| Nom | Base |
| --- | --- |
| production | `https://welleat-api.welleat.fr` (`/api/cameras/…`, `/api/stations/…`) |
| développement | `https://welleat-api-dev.welleat.fr` |

Dispersion de la configuration (aucune constante centrale) :

| Source | Valeur |
| --- | --- |
| `SERVER_URL` du `.env` (caméra) | `https://welleat-api.welleat.fr/api/cameras` (écrit par `ajouter_au_fichier_env.py`) — lu par `monitor_raspberry.py`, `auto_timelines.py` |
| `WEBSOCKET_SERVER` du `.env` | défaut `https://welleat-api.welleat.fr/` — capture |
| `VanillaSendDelete.http_base` | `https://welleat-api.welleat.fr` **codé en dur** |
| `status_leds.py` | `https://welleat-api.welleat.fr/api/cameras/fetchLastChefImage/{id}` codé en dur |
| `BASE_API_URL` du `.env` (gateway) | prod ou dev selon l'assistant ; défaut **dev** dans `gateway_centrale.py`, `balance_antenna.py`, `bt_temp_relay.py` |
| `WIFI_WATCHDOG_BACKEND_URL` | `https://welleat-api.welleat.fr/` (unité systemd) |
| `register_camera.sh` | `--production` / `--development`, base `…/api` |

## Authentification

| Étape | En-têtes / charge utile |
| --- | --- |
| Enrôlement caméra | `POST /api/cameras/connectCamera/` — `api-key`, `api-secret` (globaux), `X-Device-Mac`, `hostname` → `{cameraId, api_key}` |
| Enrôlement station | `POST /api/stations/addNewStation` — mêmes en-têtes globaux → `{apiStationId, api_key}` |
| Appels caméra | `api-key: <clé caméra>` (`temptracking`, `Reports`, `StateUpdate`, `SpeedPerfs`, `trayCount`, `ServiceSlots`), ou `api_key` + `cameraId` dans le corps (`sendFrame`, `sendControlFrames`) |
| Appels station | `api-key: <clé station>` (+ `apiStationId`) |
| Socket.IO | auth `{cameraId, api_key}` (caméra) ou `{station_id, api_key}` (station) ; événement `authenticate` supplémentaire côté caméra |

`scripts/register_camera.sh` est l'outil d'enrôlement manuel **sans secret dans le code** : clé et secret lus dans `WELLEAT_API_KEY` / `WELLEAT_API_SECRET` ou demandés (le secret en saisie masquée), MAC détectée (route par défaut puis première interface physique), option `--dry-run`.

## Catalogue des endpoints utilisés

| Domaine | Endpoint | Appelant |
| --- | --- | --- |
| Caméra | `POST /api/cameras/connectCamera/` | `first_install.sh`, `WEB_FIRST_INSTALL.py`, `register_camera.sh` |
| | `POST /api/cameras/sendFrame` | envoi normal, coordinateur MultiCam |
| | `POST /api/cameras/sendControlFrames` | trames « chef » |
| | `POST /api/cameras/trayCount/{id}` | compteur, coordinateur MultiCam |
| | `POST /api/cameras/Reports/{id}` | envoi (après succès), `monitor_raspberry` |
| | `POST /api/cameras/temptracking/{id}`, `PUT …/StateUpdate/{id}`, `POST …/SpeedPerfs/{id}` | `monitor_raspberry` |
| | `GET /api/cameras/ServiceSlots/{id}` | `auto_timelines` |
| | `GET /api/cameras/fetchLastChefImage/{id}` | `status_leds` |
| Station | `POST /api/stations/addNewStation` | relais balance, relais BT |
| | `POST …/addNewScale/{station}`, `…/sendWeights/{station}` (inutilisé), Socket.IO `SCALE_*`, `station-heartbeat` | relais balance |
| | `POST …/addNewSensor/{station}`, `…/sendTemperatures/{station}`, `GET …/ignored/{station}`, `GET /api/dataAccess/sensors/taskList/{sensor}` | relais BT |
| | `GET …/plugList/{station}`, `PUT …/plugStatus/{station}`, `PUT …/plugConsumption/{station}`, Socket.IO `PLUG_*` | gateway centrale |

Hors API Welleat : GitHub (`api.github.com`, `raw.githubusercontent.com`, `github.com/…/info/lfs/objects/batch`), `tailscale.com`, `install.zerotier.com`, `speedtest.tele2.net` (débit), `google.com/generate_204` (connectivité LED), serveurs internes `100.71.41.74:5000` (monitor), `100.86.97.52–54:8000` (watchdog sondes), broker Tailscale (`192.168.1.210` par défaut).

## Écarts à résoudre

- Aucune URL ni identité d'API n'est centralisée ; les valeurs de développement servent de défaut côté gateway.
- Secrets globaux d'enrôlement (clé + secret) embarqués dans cinq fichiers (voir [[00-index#Synthèse transverse — points structurants pour le rewrite]]).
- Corps d'authentification : `api_key` dans le JSON (images), dans les en-têtes (comptage, rapports), ou dans les deux (`plugStatus`).
