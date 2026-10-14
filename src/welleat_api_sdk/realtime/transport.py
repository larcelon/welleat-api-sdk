"""Transports Socket.IO : interfaces typées et adaptateurs `python-socketio`.

Les sockets du SDK ne dépendent que de `AsyncTransport` / `SyncTransport` ;
les adaptateurs traduisent les exceptions de la bibliothèque en
`RealtimeConnectionError`. La reconnexion de `python-socketio` est désactivée :
toute la politique est portée par le SDK (`ReconnectPolicy`).
"""

from collections.abc import Awaitable, Mapping
from typing import Protocol

import socketio  # type: ignore[import-untyped]  # python-socketio ne publie pas de py.typed

from welleat_api_sdk.errors import RealtimeConnectionError
from welleat_api_sdk.request import JsonValue

_TRANSPORTS = ["websocket"]


class AsyncHandler(Protocol):
    """Gestionnaire asynchrone d'événement : reçoit les arguments bruts de l'événement."""

    def __call__(self, *args: object) -> Awaitable[None]:
        """Traite l'événement.

        Args:
            *args: Arguments de l'événement (charge utile, motif de déconnexion...).
        """
        ...


class SyncHandler(Protocol):
    """Gestionnaire synchrone d'événement : reçoit les arguments bruts de l'événement."""

    def __call__(self, *args: object) -> None:
        """Traite l'événement.

        Args:
            *args: Arguments de l'événement (charge utile, motif de déconnexion...).
        """
        ...


class AsyncTransport(Protocol):
    """Connexion Socket.IO asynchrone vue par les sockets du SDK."""

    @property
    def connected(self) -> bool:
        """Indique si la connexion est établie."""
        ...

    def on(self, event: str, handler: AsyncHandler) -> None:
        """Enregistre l'unique gestionnaire d'un événement (y compris `connect`, `disconnect`).

        Args:
            event: Nom de l'événement.
            handler: Gestionnaire appelé à chaque réception.
        """
        ...

    async def connect(self, url: str, headers: Mapping[str, str], auth: Mapping[str, str]) -> None:
        """Ouvre la connexion WebSocket.

        Args:
            url: URL du serveur.
            headers: En-têtes HTTP de la poignée de main.
            auth: Données d'authentification Socket.IO.

        Raises:
            RealtimeConnectionError: Connexion refusée ou échouée.
        """
        ...

    async def emit(self, event: str, data: JsonValue) -> None:
        """Émet un événement.

        Args:
            event: Nom de l'événement.
            data: Charge utile JSON.

        Raises:
            RealtimeConnectionError: Connexion absente.
        """
        ...

    async def wait(self) -> None:
        """Attend la fin de la connexion."""
        ...

    async def disconnect(self) -> None:
        """Ferme la connexion."""
        ...


class SyncTransport(Protocol):
    """Connexion Socket.IO synchrone ; gestionnaires appelés depuis un thread de fond."""

    @property
    def connected(self) -> bool:
        """Indique si la connexion est établie."""
        ...

    def on(self, event: str, handler: SyncHandler) -> None:
        """Enregistre l'unique gestionnaire d'un événement (y compris `connect`, `disconnect`).

        Args:
            event: Nom de l'événement.
            handler: Gestionnaire appelé à chaque réception.
        """
        ...

    def connect(self, url: str, headers: Mapping[str, str], auth: Mapping[str, str]) -> None:
        """Ouvre la connexion WebSocket.

        Args:
            url: URL du serveur.
            headers: En-têtes HTTP de la poignée de main.
            auth: Données d'authentification Socket.IO.

        Raises:
            RealtimeConnectionError: Connexion refusée ou échouée.
        """
        ...

    def emit(self, event: str, data: JsonValue) -> None:
        """Émet un événement.

        Args:
            event: Nom de l'événement.
            data: Charge utile JSON.

        Raises:
            RealtimeConnectionError: Connexion absente.
        """
        ...

    def wait(self) -> None:
        """Attend la fin de la connexion."""
        ...

    def disconnect(self) -> None:
        """Ferme la connexion."""
        ...


# Sous-ensembles de `socketio.AsyncClient` / `socketio.Client` utilisés par les adaptateurs,
# avec les signatures de python-socketio 5.x (la bibliothèque n'est pas annotée).


class _SioAsyncClient(Protocol):
    connected: bool

    def on(self, event: str, handler: AsyncHandler) -> object: ...

    async def connect(
        self,
        url: str,
        headers: dict[str, str],
        auth: dict[str, str],
        transports: list[str],
        wait_timeout: float,
    ) -> None: ...

    async def emit(self, event: str, data: JsonValue) -> None: ...

    async def wait(self) -> None: ...

    async def disconnect(self) -> None: ...


class _SioClient(Protocol):
    connected: bool

    def on(self, event: str, handler: SyncHandler) -> object: ...

    def connect(
        self,
        url: str,
        headers: dict[str, str],
        auth: dict[str, str],
        transports: list[str],
        wait_timeout: float,
    ) -> None: ...

    def emit(self, event: str, data: JsonValue) -> None: ...

    def wait(self) -> None: ...

    def disconnect(self) -> None: ...


def connect_error_reason(data: object) -> str:
    """Extrait le motif d'un événement `connect_error`.

    Args:
        data: Données de l'événement (objet `{message}` ou chaîne).

    Returns:
        Le motif lisible.
    """
    if isinstance(data, dict):
        message = data.get("message")
        if isinstance(message, str):
            return message
    return str(data)


class SocketIOAsyncTransport:
    """`AsyncTransport` fondé sur `socketio.AsyncClient` (WebSocket seul, sans reconnexion)."""

    def __init__(self, connect_timeout: float) -> None:
        """Crée le client Socket.IO.

        Args:
            connect_timeout: Délai d'établissement de la connexion, en secondes.
        """
        client: _SioAsyncClient = socketio.AsyncClient(
            reconnection=False, handle_sigint=False, request_timeout=connect_timeout
        )
        self._sio = client
        self._timeout = connect_timeout
        self._last_error: str | None = None
        self._sio.on("connect_error", self._record_error)

    async def _record_error(self, *args: object) -> None:
        """Mémorise le motif du dernier refus de connexion.

        Args:
            *args: Données de l'événement `connect_error`.
        """
        self._last_error = connect_error_reason(args[0] if args else None)

    def _failure_reason(self, exc: Exception) -> str:
        """Choisit le motif d'un échec de connexion.

        Args:
            exc: Exception levée par `python-socketio`.

        Returns:
            Le motif transmis par `connect_error`, sinon celui de l'exception.
        """
        return self._last_error or str(exc)

    @property
    def connected(self) -> bool:
        """Indique si la connexion est établie."""
        return self._sio.connected

    def on(self, event: str, handler: AsyncHandler) -> None:
        """Enregistre le gestionnaire d'un événement.

        Args:
            event: Nom de l'événement.
            handler: Gestionnaire appelé à chaque réception.
        """
        self._sio.on(event, handler)

    async def connect(self, url: str, headers: Mapping[str, str], auth: Mapping[str, str]) -> None:
        """Ouvre la connexion WebSocket.

        Args:
            url: URL du serveur.
            headers: En-têtes HTTP de la poignée de main.
            auth: Données d'authentification Socket.IO.

        Raises:
            RealtimeConnectionError: Connexion refusée ou échouée.
        """
        self._last_error = None
        try:
            await self._sio.connect(
                url,
                headers=dict(headers),
                auth=dict(auth),
                transports=_TRANSPORTS,
                wait_timeout=self._timeout,
            )
        except socketio.exceptions.ConnectionError as exc:
            raise RealtimeConnectionError(self._failure_reason(exc)) from exc

    async def emit(self, event: str, data: JsonValue) -> None:
        """Émet un événement.

        Args:
            event: Nom de l'événement.
            data: Charge utile JSON.

        Raises:
            RealtimeConnectionError: Connexion absente (namespace non connecté).
        """
        try:
            await self._sio.emit(event, data)
        except socketio.exceptions.SocketIOError as exc:
            raise RealtimeConnectionError(f"{event} : {exc}") from exc

    async def wait(self) -> None:
        """Attend la fin de la connexion."""
        await self._sio.wait()

    async def disconnect(self) -> None:
        """Ferme la connexion."""
        await self._sio.disconnect()


class SocketIOSyncTransport:
    """`SyncTransport` fondé sur `socketio.Client` (WebSocket seul, sans reconnexion)."""

    def __init__(self, connect_timeout: float) -> None:
        """Crée le client Socket.IO.

        Args:
            connect_timeout: Délai d'établissement de la connexion, en secondes.
        """
        client: _SioClient = socketio.Client(
            reconnection=False, handle_sigint=False, request_timeout=connect_timeout
        )
        self._sio = client
        self._timeout = connect_timeout
        self._last_error: str | None = None
        self._sio.on("connect_error", self._record_error)

    def _record_error(self, *args: object) -> None:
        """Mémorise le motif du dernier refus de connexion.

        Args:
            *args: Données de l'événement `connect_error`.
        """
        self._last_error = connect_error_reason(args[0] if args else None)

    def _failure_reason(self, exc: Exception) -> str:
        """Choisit le motif d'un échec de connexion.

        Args:
            exc: Exception levée par `python-socketio`.

        Returns:
            Le motif transmis par `connect_error`, sinon celui de l'exception.
        """
        return self._last_error or str(exc)

    @property
    def connected(self) -> bool:
        """Indique si la connexion est établie."""
        return self._sio.connected

    def on(self, event: str, handler: SyncHandler) -> None:
        """Enregistre le gestionnaire d'un événement.

        Args:
            event: Nom de l'événement.
            handler: Gestionnaire appelé à chaque réception.
        """
        self._sio.on(event, handler)

    def connect(self, url: str, headers: Mapping[str, str], auth: Mapping[str, str]) -> None:
        """Ouvre la connexion WebSocket.

        Args:
            url: URL du serveur.
            headers: En-têtes HTTP de la poignée de main.
            auth: Données d'authentification Socket.IO.

        Raises:
            RealtimeConnectionError: Connexion refusée ou échouée.
        """
        self._last_error = None
        try:
            self._sio.connect(
                url,
                headers=dict(headers),
                auth=dict(auth),
                transports=_TRANSPORTS,
                wait_timeout=self._timeout,
            )
        except socketio.exceptions.ConnectionError as exc:
            raise RealtimeConnectionError(self._failure_reason(exc)) from exc

    def emit(self, event: str, data: JsonValue) -> None:
        """Émet un événement.

        Args:
            event: Nom de l'événement.
            data: Charge utile JSON.

        Raises:
            RealtimeConnectionError: Connexion absente (namespace non connecté).
        """
        try:
            self._sio.emit(event, data)
        except socketio.exceptions.SocketIOError as exc:
            raise RealtimeConnectionError(f"{event} : {exc}") from exc

    def wait(self) -> None:
        """Attend la fin de la connexion."""
        self._sio.wait()

    def disconnect(self) -> None:
        """Ferme la connexion."""
        self._sio.disconnect()
