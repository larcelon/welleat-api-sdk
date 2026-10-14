"""`GatewaySocket` et `SyncGatewaySocket` : canal temps réel d'une gateway (« station »).

Authentification : `auth={station_id, api_key}` (clés snake_case, différentes
de l'API REST), sans événement `authenticate`. Le canal porte les balances
(`SCALE_*`, `station-heartbeat`) et les prises (`PLUG_*`).
"""

from collections.abc import Awaitable, Callable
from functools import partial

from welleat_api_sdk.auth import GatewayCredentials
from welleat_api_sdk.realtime.client import RealtimeSocket, ReconnectPolicy, SyncRealtimeSocket
from welleat_api_sdk.realtime.events import (
    PlugCommand,
    ScaleCommand,
    ScaleCommandFailure,
    ScaleCommandSuccess,
    ScaleCommandType,
    ScaleConnectionState,
    ScaleWeightUpdate,
    StationEvent,
    StationHeartbeat,
    WeightAck,
    WeightRejection,
)

_GATEWAY_POLICY = ReconnectPolicy(connect_timeout=20.0, retry_interval=10.0, failure_threshold=6)


def _station_auth(credentials: GatewayCredentials) -> dict[str, str]:
    """Construit les données d'authentification d'une station.

    Args:
        credentials: Identifiants de la station.

    Returns:
        `station_id` et `api_key`.
    """
    return {"station_id": credentials.api_station_id, "api_key": credentials.api_key}


class GatewaySocket(RealtimeSocket[GatewayCredentials]):
    """Canal temps réel asynchrone d'une gateway.

    Par défaut : connexion en 20 s au plus, 10 s entre deux essais, abandon
    (`on_give_up`) après 6 échecs consécutifs.
    """

    default_policy = _GATEWAY_POLICY

    def _auth(self) -> dict[str, str]:
        """Renvoie `station_id` et `api_key`.

        Returns:
            Les données `auth` de la connexion.
        """
        return _station_auth(self.credentials)

    def on_scale_command(self, handler: Callable[[ScaleCommand], Awaitable[None]]) -> None:
        """Ajoute un gestionnaire des commandes matérielles de balance (`SCALE_CMD_*`).

        Args:
            handler: Coroutine recevant la commande décodée.
        """
        for command in ScaleCommandType:
            self._subscribe(command, partial(ScaleCommand.from_payload, command), handler)

    def on_weight_ack(self, handler: Callable[[WeightAck], Awaitable[None]]) -> None:
        """Ajoute un gestionnaire des accusés de poids (`SCALE_CMD_SUCCESS` reçu).

        Args:
            handler: Coroutine recevant l'accusé décodé.
        """
        self._subscribe(StationEvent.SCALE_CMD_SUCCESS, WeightAck.from_payload, handler)

    def on_weight_rejection(self, handler: Callable[[WeightRejection], Awaitable[None]]) -> None:
        """Ajoute un gestionnaire des refus de poids (`SCALE_CMD_ERROR` reçu).

        Args:
            handler: Coroutine recevant le refus décodé.
        """
        self._subscribe(StationEvent.SCALE_CMD_ERROR, WeightRejection.from_payload, handler)

    def on_plug_refresh(self, handler: Callable[[object], Awaitable[None]]) -> None:
        """Ajoute un gestionnaire de `PLUG REFRESH DATA` (relire `plugList`).

        Args:
            handler: Coroutine recevant le message brut.
        """
        self.on_event(StationEvent.PLUG_REFRESH, handler)

    def on_plug_command(self, handler: Callable[[PlugCommand], Awaitable[None]]) -> None:
        """Ajoute un gestionnaire des commandes de prise (`PLUG_CMD_ON` / `PLUG_CMD_OFF`).

        Args:
            handler: Coroutine recevant la commande ; ignorée sans `apiPlugId`.
        """
        self._subscribe(StationEvent.PLUG_ON, partial(PlugCommand.from_payload, True), handler)
        self._subscribe(StationEvent.PLUG_OFF, partial(PlugCommand.from_payload, False), handler)

    async def send_weight_update(self, update: ScaleWeightUpdate) -> None:
        """Publie une trame de poids (`SCALE_STREAM_WEIGHT_UPDATE`).

        Args:
            update: Trame à publier.
        """
        await self.emit(StationEvent.SCALE_WEIGHT_UPDATE, update.to_json())

    async def send_connection_state(self, state: ScaleConnectionState) -> None:
        """Publie une transition d'état de balance (`SCALE_CONNECTION_STATE`).

        Args:
            state: Nouvel état.
        """
        await self.emit(StationEvent.SCALE_CONNECTION_STATE, state.to_json())

    async def send_heartbeat(self, heartbeat: StationHeartbeat) -> None:
        """Publie l'état périodique des balances (`station-heartbeat`).

        Args:
            heartbeat: État des balances.
        """
        await self.emit(StationEvent.HEARTBEAT, heartbeat.to_json())

    async def send_command_success(self, success: ScaleCommandSuccess) -> None:
        """Acquitte une commande matérielle (`SCALE_CMD_SUCCESS`).

        Args:
            success: Commande exécutée.
        """
        await self.emit(StationEvent.SCALE_CMD_SUCCESS, success.to_json())

    async def send_command_failure(self, failure: ScaleCommandFailure) -> None:
        """Signale l'échec d'une commande matérielle (`SCALE_CMD_ERROR`).

        Args:
            failure: Commande en échec et motif.
        """
        await self.emit(StationEvent.SCALE_CMD_ERROR, failure.to_json())


class SyncGatewaySocket(SyncRealtimeSocket[GatewayCredentials]):
    """Canal temps réel synchrone d'une gateway ; mêmes méthodes que `GatewaySocket`."""

    default_policy = _GATEWAY_POLICY

    def _auth(self) -> dict[str, str]:
        """Renvoie `station_id` et `api_key`.

        Returns:
            Les données `auth` de la connexion.
        """
        return _station_auth(self.credentials)

    def on_scale_command(self, handler: Callable[[ScaleCommand], None]) -> None:
        """Ajoute un gestionnaire des commandes matérielles de balance (`SCALE_CMD_*`).

        Args:
            handler: Fonction recevant la commande décodée.
        """
        for command in ScaleCommandType:
            self._subscribe(command, partial(ScaleCommand.from_payload, command), handler)

    def on_weight_ack(self, handler: Callable[[WeightAck], None]) -> None:
        """Ajoute un gestionnaire des accusés de poids (`SCALE_CMD_SUCCESS` reçu).

        Args:
            handler: Fonction recevant l'accusé décodé.
        """
        self._subscribe(StationEvent.SCALE_CMD_SUCCESS, WeightAck.from_payload, handler)

    def on_weight_rejection(self, handler: Callable[[WeightRejection], None]) -> None:
        """Ajoute un gestionnaire des refus de poids (`SCALE_CMD_ERROR` reçu).

        Args:
            handler: Fonction recevant le refus décodé.
        """
        self._subscribe(StationEvent.SCALE_CMD_ERROR, WeightRejection.from_payload, handler)

    def on_plug_refresh(self, handler: Callable[[object], None]) -> None:
        """Ajoute un gestionnaire de `PLUG REFRESH DATA` (relire `plugList`).

        Args:
            handler: Fonction recevant le message brut.
        """
        self.on_event(StationEvent.PLUG_REFRESH, handler)

    def on_plug_command(self, handler: Callable[[PlugCommand], None]) -> None:
        """Ajoute un gestionnaire des commandes de prise (`PLUG_CMD_ON` / `PLUG_CMD_OFF`).

        Args:
            handler: Fonction recevant la commande ; ignorée sans `apiPlugId`.
        """
        self._subscribe(StationEvent.PLUG_ON, partial(PlugCommand.from_payload, True), handler)
        self._subscribe(StationEvent.PLUG_OFF, partial(PlugCommand.from_payload, False), handler)

    def send_weight_update(self, update: ScaleWeightUpdate) -> None:
        """Publie une trame de poids (`SCALE_STREAM_WEIGHT_UPDATE`).

        Args:
            update: Trame à publier.
        """
        self.emit(StationEvent.SCALE_WEIGHT_UPDATE, update.to_json())

    def send_connection_state(self, state: ScaleConnectionState) -> None:
        """Publie une transition d'état de balance (`SCALE_CONNECTION_STATE`).

        Args:
            state: Nouvel état.
        """
        self.emit(StationEvent.SCALE_CONNECTION_STATE, state.to_json())

    def send_heartbeat(self, heartbeat: StationHeartbeat) -> None:
        """Publie l'état périodique des balances (`station-heartbeat`).

        Args:
            heartbeat: État des balances.
        """
        self.emit(StationEvent.HEARTBEAT, heartbeat.to_json())

    def send_command_success(self, success: ScaleCommandSuccess) -> None:
        """Acquitte une commande matérielle (`SCALE_CMD_SUCCESS`).

        Args:
            success: Commande exécutée.
        """
        self.emit(StationEvent.SCALE_CMD_SUCCESS, success.to_json())

    def send_command_failure(self, failure: ScaleCommandFailure) -> None:
        """Signale l'échec d'une commande matérielle (`SCALE_CMD_ERROR`).

        Args:
            failure: Commande en échec et motif.
        """
        self.emit(StationEvent.SCALE_CMD_ERROR, failure.to_json())
