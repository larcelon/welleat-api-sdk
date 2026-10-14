"""`CameraClient` et `SyncCameraClient` : spécialisations du client générique pour les caméras."""

from datetime import datetime

from welleat_api_sdk import camera_requests as req
from welleat_api_sdk.auth import CameraCredentials, EnrollmentSecrets
from welleat_api_sdk.client import SyncWelleatClient, WelleatClient
from welleat_api_sdk.models import (
    ChefFramePayload,
    DeviceInfo,
    FramePayload,
    MultiCamOptions,
    ReportPayload,
    ServiceSlot,
)


class CameraClient(WelleatClient[CameraCredentials]):
    """Client asynchrone de l'API caméra (`/cameras/...`).

    Toutes les méthodes lèvent une `WelleatError` en cas d'échec ; aucune ne
    réessaie. Hors `connect_camera`, elles exigent des `credentials`.
    """

    async def connect_camera(
        self, secrets: EnrollmentSecrets, device: DeviceInfo
    ) -> CameraCredentials:
        """Enrôle la caméra ; l'appelant stocke les identifiants renvoyés.

        Args:
            secrets: Clé et secret globaux d'enrôlement.
            device: Identité matérielle de la caméra.

        Returns:
            Les identifiants de la caméra.
        """
        return await self.request(req.connect_camera(secrets, device))

    async def send_frame(
        self, frame: FramePayload, multicam: MultiCamOptions | None = None
    ) -> None:
        """Envoie une image normale.

        Args:
            frame: Image et détections.
            multicam: Options MultiCam (idempotence, 409 accepté).
        """
        await self.request(req.send_frame(frame, multicam))

    async def send_control_frames(self, payload: ChefFramePayload) -> None:
        """Envoie des images « chef ».

        Args:
            payload: Tablette demandeuse et images.
        """
        await self.request(req.send_control_frames(payload))

    async def tray_count(self, multicam: MultiCamOptions | None = None) -> None:
        """Incrémente le comptage de plateaux de 1.

        Args:
            multicam: Options MultiCam (idempotence, 409 accepté).
        """
        await self.request(req.tray_count(multicam))

    async def report(self, payload: ReportPayload) -> None:
        """Envoie un rapport d'activité.

        Args:
            payload: Contenu du rapport.
        """
        await self.request(req.report(payload))

    async def temp_tracking(self, temperature: float, soft_version: str | None = None) -> None:
        """Envoie la température de la caméra.

        Args:
            temperature: Température en °C.
            soft_version: Version logicielle, optionnelle.
        """
        await self.request(req.temp_tracking(temperature, soft_version))

    async def state_update(self, active: bool) -> None:
        """Signale si la caméra est dans un créneau de service.

        Args:
            active: `True` dans un créneau.
        """
        await self.request(req.state_update(active))

    async def speed_perf(self, bytes_per_second: int) -> None:
        """Envoie le débit réseau mesuré.

        Args:
            bytes_per_second: Débit en octets par seconde.
        """
        await self.request(req.speed_perf(bytes_per_second))

    async def service_slots(self) -> list[ServiceSlot]:
        """Récupère les créneaux de service.

        Returns:
            Les créneaux, éventuellement vides.
        """
        return await self.request(req.service_slots())

    async def last_chef_image(self) -> datetime | None:
        """Date de la dernière image « chef » (endpoint non authentifié).

        Returns:
            La date UTC, ou `None` s'il n'y a pas d'image récente.
        """
        return await self.request(req.last_chef_image())


class SyncCameraClient(SyncWelleatClient[CameraCredentials]):
    """Client synchrone de l'API caméra ; mêmes méthodes que `CameraClient`."""

    def connect_camera(self, secrets: EnrollmentSecrets, device: DeviceInfo) -> CameraCredentials:
        """Enrôle la caméra ; voir `CameraClient.connect_camera`.

        Args:
            secrets: Clé et secret globaux d'enrôlement.
            device: Identité matérielle de la caméra.

        Returns:
            Les identifiants de la caméra.
        """
        return self.request(req.connect_camera(secrets, device))

    def send_frame(self, frame: FramePayload, multicam: MultiCamOptions | None = None) -> None:
        """Envoie une image normale ; voir `CameraClient.send_frame`.

        Args:
            frame: Image et détections.
            multicam: Options MultiCam (idempotence, 409 accepté).
        """
        self.request(req.send_frame(frame, multicam))

    def send_control_frames(self, payload: ChefFramePayload) -> None:
        """Envoie des images « chef » ; voir `CameraClient.send_control_frames`.

        Args:
            payload: Tablette demandeuse et images.
        """
        self.request(req.send_control_frames(payload))

    def tray_count(self, multicam: MultiCamOptions | None = None) -> None:
        """Incrémente le comptage de plateaux ; voir `CameraClient.tray_count`.

        Args:
            multicam: Options MultiCam (idempotence, 409 accepté).
        """
        self.request(req.tray_count(multicam))

    def report(self, payload: ReportPayload) -> None:
        """Envoie un rapport d'activité ; voir `CameraClient.report`.

        Args:
            payload: Contenu du rapport.
        """
        self.request(req.report(payload))

    def temp_tracking(self, temperature: float, soft_version: str | None = None) -> None:
        """Envoie la température ; voir `CameraClient.temp_tracking`.

        Args:
            temperature: Température en °C.
            soft_version: Version logicielle, optionnelle.
        """
        self.request(req.temp_tracking(temperature, soft_version))

    def state_update(self, active: bool) -> None:
        """Signale le créneau de service ; voir `CameraClient.state_update`.

        Args:
            active: `True` dans un créneau.
        """
        self.request(req.state_update(active))

    def speed_perf(self, bytes_per_second: int) -> None:
        """Envoie le débit mesuré ; voir `CameraClient.speed_perf`.

        Args:
            bytes_per_second: Débit en octets par seconde.
        """
        self.request(req.speed_perf(bytes_per_second))

    def service_slots(self) -> list[ServiceSlot]:
        """Récupère les créneaux de service ; voir `CameraClient.service_slots`.

        Returns:
            Les créneaux, éventuellement vides.
        """
        return self.request(req.service_slots())

    def last_chef_image(self) -> datetime | None:
        """Date de la dernière image « chef » ; voir `CameraClient.last_chef_image`.

        Returns:
            La date UTC, ou `None` s'il n'y a pas d'image récente.
        """
        return self.request(req.last_chef_image())
