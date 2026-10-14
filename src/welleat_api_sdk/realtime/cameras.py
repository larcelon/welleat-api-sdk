"""`CameraSocket` et `SyncCameraSocket` : canal temps réel d'une caméra.

Authentification : `auth={cameraId, api_key}` puis, à chaque connexion,
l'événement `authenticate` avec les mêmes champs. Plusieurs processus peuvent
ouvrir chacun leur socket avec les mêmes identifiants (capture et envoi).
"""

from collections.abc import Awaitable, Callable

from welleat_api_sdk.auth import CameraCredentials
from welleat_api_sdk.realtime.client import RealtimeSocket, ReconnectPolicy, SyncRealtimeSocket
from welleat_api_sdk.realtime.events import CameraEvent, ManualCaptureRequest

_CAMERA_POLICY = ReconnectPolicy(retry_interval=5.0)
_CAPTURED = "captured"


def _camera_auth(credentials: CameraCredentials) -> dict[str, str]:
    """Construit les données d'authentification d'une caméra.

    Args:
        credentials: Identifiants de la caméra.

    Returns:
        `cameraId` et `api_key`.
    """
    return {"cameraId": credentials.camera_id, "api_key": credentials.api_key}


class CameraSocket(RealtimeSocket[CameraCredentials]):
    """Canal temps réel asynchrone d'une caméra.

    Par défaut, `run` réessaie sans fin toutes les 5 s : une perte de lien
    doit faire basculer l'appelant en mode local, jamais l'arrêter.
    """

    default_policy = _CAMERA_POLICY

    def _auth(self) -> dict[str, str]:
        """Renvoie `cameraId` et `api_key`.

        Returns:
            Les données `auth` de la connexion.
        """
        return _camera_auth(self.credentials)

    async def _after_connect(self) -> None:
        """Émet `authenticate`, attendu par le serveur en plus de `auth`."""
        await self.emit(CameraEvent.AUTHENTICATE, self._auth())

    def on_manual_capture(self, handler: Callable[[ManualCaptureRequest], Awaitable[None]]) -> None:
        """Ajoute un gestionnaire des demandes de capture manuelle « chef ».

        Args:
            handler: Coroutine recevant la demande décodée.
        """
        self._subscribe(CameraEvent.MANUAL_CAPTURE, ManualCaptureRequest.from_payload, handler)

    def on_camera_connect(self, handler: Callable[[object], Awaitable[None]]) -> None:
        """Ajoute un gestionnaire du message libre `camera-connect`.

        Args:
            handler: Coroutine recevant le message brut.
        """
        self.on_event(CameraEvent.CAMERA_CONNECT, handler)

    def on_frame_ack(self, handler: Callable[[object], Awaitable[None]]) -> None:
        """Ajoute un gestionnaire des accusés d'image `frame_ack` envoyés par le serveur.

        Args:
            handler: Coroutine recevant le message brut.
        """
        self.on_event(CameraEvent.FRAME_ACK, handler)

    async def send_frame_ack(self, status: str = _CAPTURED) -> None:
        """Signale une capture au serveur (`frame_ack`).

        Args:
            status: Statut de la capture.
        """
        await self.emit(
            CameraEvent.FRAME_ACK, {"cameraId": self.credentials.camera_id, "status": status}
        )


class SyncCameraSocket(SyncRealtimeSocket[CameraCredentials]):
    """Canal temps réel synchrone d'une caméra ; mêmes méthodes que `CameraSocket`."""

    default_policy = _CAMERA_POLICY

    def _auth(self) -> dict[str, str]:
        """Renvoie `cameraId` et `api_key`.

        Returns:
            Les données `auth` de la connexion.
        """
        return _camera_auth(self.credentials)

    def _after_connect(self) -> None:
        """Émet `authenticate`, attendu par le serveur en plus de `auth`."""
        self.emit(CameraEvent.AUTHENTICATE, self._auth())

    def on_manual_capture(self, handler: Callable[[ManualCaptureRequest], None]) -> None:
        """Ajoute un gestionnaire des demandes de capture manuelle « chef ».

        Args:
            handler: Fonction recevant la demande décodée.
        """
        self._subscribe(CameraEvent.MANUAL_CAPTURE, ManualCaptureRequest.from_payload, handler)

    def on_camera_connect(self, handler: Callable[[object], None]) -> None:
        """Ajoute un gestionnaire du message libre `camera-connect`.

        Args:
            handler: Fonction recevant le message brut.
        """
        self.on_event(CameraEvent.CAMERA_CONNECT, handler)

    def on_frame_ack(self, handler: Callable[[object], None]) -> None:
        """Ajoute un gestionnaire des accusés d'image `frame_ack` envoyés par le serveur.

        Args:
            handler: Fonction recevant le message brut.
        """
        self.on_event(CameraEvent.FRAME_ACK, handler)

    def send_frame_ack(self, status: str = _CAPTURED) -> None:
        """Signale une capture au serveur (`frame_ack`).

        Args:
            status: Statut de la capture.
        """
        self.emit(CameraEvent.FRAME_ACK, {"cameraId": self.credentials.camera_id, "status": status})
