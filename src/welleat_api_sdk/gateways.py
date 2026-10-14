"""`GatewayClient` et `SyncGatewayClient` : spécialisations du client générique pour les gateways.

Une gateway est une « station » côté API : chemins `/stations/...`, `apiStationId`.
"""

from collections.abc import Sequence

from welleat_api_sdk import gateway_requests as req
from welleat_api_sdk.auth import EnrollmentSecrets, GatewayCredentials
from welleat_api_sdk.client import SyncWelleatClient, WelleatClient
from welleat_api_sdk.models import (
    DeviceInfo,
    PlugConfig,
    ScaleRegistration,
    SensorReading,
    SensorStat,
    WeightReading,
)


class GatewayClient(WelleatClient[GatewayCredentials]):
    """Client asynchrone de l'API gateway (`/stations/...`).

    Toutes les méthodes lèvent une `WelleatError` en cas d'échec ; aucune ne
    réessaie. Hors `add_new_station`, elles exigent des `credentials`.
    """

    async def add_new_station(
        self, secrets: EnrollmentSecrets, device: DeviceInfo
    ) -> GatewayCredentials:
        """Enrôle la gateway ; l'appelant stocke les identifiants renvoyés.

        Args:
            secrets: Clé et secret globaux d'enrôlement.
            device: Identité matérielle de la gateway.

        Returns:
            Les identifiants de la station.
        """
        return await self.request(req.add_new_station(secrets, device))

    async def temp_tracking(self, cpu_temperature: float) -> None:
        """Envoie la température CPU.

        Args:
            cpu_temperature: Température en °C.
        """
        await self.request(req.temp_tracking(cpu_temperature))

    async def add_scale(self, scale: ScaleRegistration) -> str:
        """Enregistre une balance (idempotent).

        Args:
            scale: Adresses IP et MAC de la balance.

        Returns:
            L'identifiant de balance.
        """
        return await self.request(req.add_scale(scale))

    async def send_weights(
        self, readings: Sequence[WeightReading], speed_perf: int | None = None
    ) -> None:
        """Envoie des pesées.

        Args:
            readings: Pesées à envoyer.
            speed_perf: Débit mesuré en octets/s, optionnel.
        """
        await self.request(req.send_weights(readings, speed_perf))

    async def add_sensor(self, hardware_id: str) -> str:
        """Enregistre un capteur BLE.

        Args:
            hardware_id: Nom BLE du capteur.

        Returns:
            L'identifiant `apiSensorId`.
        """
        return await self.request(req.add_sensor(hardware_id))

    async def send_temperatures(
        self,
        readings: Sequence[SensorReading],
        cpu_temperature: float | None = None,
        speed_perf: int | None = None,
    ) -> None:
        """Envoie des mesures de capteurs.

        Args:
            readings: Mesures agrégées.
            cpu_temperature: Température CPU, optionnelle.
            speed_perf: Débit mesuré en octets/s, optionnel.
        """
        await self.request(req.send_temperatures(readings, cpu_temperature, speed_perf))

    async def sensor_stats(self, stats: Sequence[SensorStat]) -> None:
        """Envoie l'état des capteurs.

        Args:
            stats: États des capteurs.
        """
        await self.request(req.sensor_stats(stats))

    async def ignored_sensors(self) -> list[str]:
        """Liste les capteurs à ignorer.

        Returns:
            Les `hardwareId` ignorés.
        """
        return await self.request(req.ignored_sensors())

    async def task_list(self, api_sensor_id: str) -> object:
        """Tâches d'un capteur (contrat non observé, JSON non typé).

        Args:
            api_sensor_id: Identifiant de capteur.

        Returns:
            Le JSON décodé tel que reçu.
        """
        return await self.request(req.task_list(api_sensor_id))

    async def plug_list(self) -> list[PlugConfig]:
        """Liste les prises connectées.

        Returns:
            Les prises de la station.
        """
        return await self.request(req.plug_list())

    async def plug_status(self, api_plug_id: str, status: bool) -> None:
        """Remonte l'état d'une prise.

        Args:
            api_plug_id: Identifiant de prise.
            status: `True` si allumée.
        """
        await self.request(req.plug_status(api_plug_id, status))

    async def plug_consumption(
        self, api_plug_id: str, power: float, energy: float, current: float
    ) -> None:
        """Remonte la consommation d'une prise.

        Args:
            api_plug_id: Identifiant de prise.
            power: Puissance instantanée.
            energy: Énergie cumulée.
            current: Courant.
        """
        await self.request(req.plug_consumption(api_plug_id, power, energy, current))


class SyncGatewayClient(SyncWelleatClient[GatewayCredentials]):
    """Client synchrone de l'API gateway ; mêmes méthodes que `GatewayClient`."""

    def add_new_station(self, secrets: EnrollmentSecrets, device: DeviceInfo) -> GatewayCredentials:
        """Enrôle la gateway ; voir `GatewayClient.add_new_station`.

        Args:
            secrets: Clé et secret globaux d'enrôlement.
            device: Identité matérielle de la gateway.

        Returns:
            Les identifiants de la station.
        """
        return self.request(req.add_new_station(secrets, device))

    def temp_tracking(self, cpu_temperature: float) -> None:
        """Envoie la température CPU ; voir `GatewayClient.temp_tracking`.

        Args:
            cpu_temperature: Température en °C.
        """
        self.request(req.temp_tracking(cpu_temperature))

    def add_scale(self, scale: ScaleRegistration) -> str:
        """Enregistre une balance ; voir `GatewayClient.add_scale`.

        Args:
            scale: Adresses IP et MAC de la balance.

        Returns:
            L'identifiant de balance.
        """
        return self.request(req.add_scale(scale))

    def send_weights(
        self, readings: Sequence[WeightReading], speed_perf: int | None = None
    ) -> None:
        """Envoie des pesées ; voir `GatewayClient.send_weights`.

        Args:
            readings: Pesées à envoyer.
            speed_perf: Débit mesuré en octets/s, optionnel.
        """
        self.request(req.send_weights(readings, speed_perf))

    def add_sensor(self, hardware_id: str) -> str:
        """Enregistre un capteur BLE ; voir `GatewayClient.add_sensor`.

        Args:
            hardware_id: Nom BLE du capteur.

        Returns:
            L'identifiant `apiSensorId`.
        """
        return self.request(req.add_sensor(hardware_id))

    def send_temperatures(
        self,
        readings: Sequence[SensorReading],
        cpu_temperature: float | None = None,
        speed_perf: int | None = None,
    ) -> None:
        """Envoie des mesures de capteurs ; voir `GatewayClient.send_temperatures`.

        Args:
            readings: Mesures agrégées.
            cpu_temperature: Température CPU, optionnelle.
            speed_perf: Débit mesuré en octets/s, optionnel.
        """
        self.request(req.send_temperatures(readings, cpu_temperature, speed_perf))

    def sensor_stats(self, stats: Sequence[SensorStat]) -> None:
        """Envoie l'état des capteurs ; voir `GatewayClient.sensor_stats`.

        Args:
            stats: États des capteurs.
        """
        self.request(req.sensor_stats(stats))

    def ignored_sensors(self) -> list[str]:
        """Liste les capteurs à ignorer ; voir `GatewayClient.ignored_sensors`.

        Returns:
            Les `hardwareId` ignorés.
        """
        return self.request(req.ignored_sensors())

    def task_list(self, api_sensor_id: str) -> object:
        """Tâches d'un capteur ; voir `GatewayClient.task_list`.

        Args:
            api_sensor_id: Identifiant de capteur.

        Returns:
            Le JSON décodé tel que reçu.
        """
        return self.request(req.task_list(api_sensor_id))

    def plug_list(self) -> list[PlugConfig]:
        """Liste les prises connectées ; voir `GatewayClient.plug_list`.

        Returns:
            Les prises de la station.
        """
        return self.request(req.plug_list())

    def plug_status(self, api_plug_id: str, status: bool) -> None:
        """Remonte l'état d'une prise ; voir `GatewayClient.plug_status`.

        Args:
            api_plug_id: Identifiant de prise.
            status: `True` si allumée.
        """
        self.request(req.plug_status(api_plug_id, status))

    def plug_consumption(
        self, api_plug_id: str, power: float, energy: float, current: float
    ) -> None:
        """Remonte la consommation d'une prise ; voir `GatewayClient.plug_consumption`.

        Args:
            api_plug_id: Identifiant de prise.
            power: Puissance instantanée.
            energy: Énergie cumulée.
            current: Courant.
        """
        self.request(req.plug_consumption(api_plug_id, power, energy, current))
