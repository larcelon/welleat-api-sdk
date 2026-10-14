"""Sockets génériques (async et sync) : connexion, reconnexion et répartition des événements.

Ces classes ne connaissent aucun événement métier. `CameraSocket` et
`GatewaySocket` (et leurs pendants `Sync*`) les spécialisent par héritage.

Une perte de connexion n'arrête jamais l'appelant : `run` reconnecte selon la
`ReconnectPolicy` et signale chaque étape par des hooks. Le SDK n'implémente ni
le suivi de livraison des poids ni le redémarrage du service : c'est le rôle
des hooks `on_connect`, `on_disconnect`, `on_connect_error` et `on_give_up`.
"""

import asyncio
import contextlib
import logging
import threading
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from types import TracebackType
from typing import ClassVar, Self

from welleat_api_sdk.config import ClientConfig
from welleat_api_sdk.errors import RealtimeConnectionError, ResponseFormatError
from welleat_api_sdk.realtime.transport import (
    AsyncHandler,
    AsyncTransport,
    SocketIOAsyncTransport,
    SocketIOSyncTransport,
    SyncHandler,
    SyncTransport,
)
from welleat_api_sdk.request import JsonValue

_LOG = logging.getLogger(__name__)

type AsyncCallback = Callable[[], Awaitable[None]]
"""Hook asynchrone sans argument."""

type SyncCallback = Callable[[], None]
"""Hook synchrone sans argument."""


@dataclass(frozen=True, slots=True)
class ReconnectPolicy:
    """Politique de connexion et de reconnexion de `run`.

    Attributes:
        connect_timeout: Délai d'établissement d'une connexion, en secondes.
        retry_interval: Attente après un échec ou une fin de session, en secondes.
        failure_threshold: Nombre d'échecs consécutifs avant abandon (hook
            `on_give_up` puis retour de `run`) ; `None` pour réessayer sans fin.
    """

    connect_timeout: float = 20.0
    retry_interval: float = 10.0
    failure_threshold: int | None = None

    def gives_up_after(self, failures: int) -> bool:
        """Indique si `run` abandonne après ce nombre d'échecs consécutifs.

        Args:
            failures: Échecs de connexion consécutifs.

        Returns:
            `True` si le seuil est atteint.
        """
        return self.failure_threshold is not None and failures >= self.failure_threshold


def _payload(args: tuple[object, ...]) -> object:
    """Renvoie la charge utile d'un événement : son premier argument, s'il existe.

    Args:
        args: Arguments bruts de l'événement.

    Returns:
        La charge utile, ou `None`.
    """
    return args[0] if args else None


def _decode_or_log[E](
    event: str, decode: Callable[[object], E | None], payload: object
) -> E | None:
    """Décode une charge utile ; une charge invalide est journalisée puis ignorée.

    Args:
        event: Nom de l'événement.
        decode: Décodeur ; renvoie `None` pour ignorer l'événement.
        payload: Charge utile reçue.

    Returns:
        L'événement décodé, ou `None` s'il est ignoré.
    """
    try:
        return decode(payload)
    except ResponseFormatError as exc:
        _LOG.warning("Événement %s ignoré : %s", event, exc)
        return None


class RealtimeSocket[C]:
    """Socket générique asynchrone (`socketio.AsyncClient`).

    Les gestionnaires enregistrés s'ajoutent les uns aux autres ; une exception
    levée par l'un d'eux est journalisée sans interrompre les suivants.

    Attributes:
        credentials: Identifiants de l'appareil.
        config: Configuration (URL du serveur, `User-Agent`).
        policy: Politique de connexion et de reconnexion.
    """

    default_policy: ClassVar[ReconnectPolicy] = ReconnectPolicy()
    """Politique utilisée quand l'appelant n'en fournit pas."""

    def __init__(
        self,
        credentials: C,
        config: ClientConfig | None = None,
        *,
        policy: ReconnectPolicy | None = None,
        transport: AsyncTransport | None = None,
    ) -> None:
        """Initialise le socket, sans se connecter.

        Args:
            credentials: Identifiants de l'appareil enrôlé.
            config: Configuration ; production par défaut.
            policy: Politique de reconnexion ; `default_policy` par défaut.
            transport: Transport à utiliser (tests) ; `python-socketio` par défaut.
        """
        self.credentials = credentials
        self.config = config or ClientConfig()
        self.policy = policy or self.default_policy
        self._transport = transport or SocketIOAsyncTransport(self.policy.connect_timeout)
        self._listeners: dict[str, list[AsyncHandler]] = {}
        self._connect_hooks: list[AsyncCallback] = []
        self._disconnect_hooks: list[AsyncCallback] = []
        self._error_hooks: list[Callable[[str], Awaitable[None]]] = []
        self._give_up_hooks: list[AsyncCallback] = []
        self._stopped = asyncio.Event()
        self._session_open = False
        self._transport.on("connect", self._handle_connect)
        self._transport.on("disconnect", self._handle_disconnect)

    def _auth(self) -> dict[str, str]:
        """Renvoie les données d'authentification Socket.IO.

        Returns:
            Les données `auth` de la connexion.

        Raises:
            NotImplementedError: Toujours ; à définir par les spécialisations.
        """
        raise NotImplementedError

    async def _after_connect(self) -> None:
        """Étape exécutée à chaque connexion, avant les hooks `on_connect`."""

    @property
    def connected(self) -> bool:
        """Indique si la connexion est établie."""
        return self._transport.connected

    def on_connect(self, hook: AsyncCallback) -> None:
        """Ajoute un hook appelé à chaque connexion (republication, resynchronisation...).

        Args:
            hook: Coroutine sans argument.
        """
        self._connect_hooks.append(hook)

    def on_disconnect(self, hook: AsyncCallback) -> None:
        """Ajoute un hook appelé à chaque perte de connexion (passage en mode local...).

        Args:
            hook: Coroutine sans argument.
        """
        self._disconnect_hooks.append(hook)

    def on_connect_error(self, hook: Callable[[str], Awaitable[None]]) -> None:
        """Ajoute un hook appelé à chaque échec de connexion ; le motif n'inclut jamais la clé.

        Args:
            hook: Coroutine recevant le motif de l'échec.
        """
        self._error_hooks.append(hook)

    def on_give_up(self, hook: AsyncCallback) -> None:
        """Ajoute un hook appelé quand `run` abandonne (seuil d'échecs atteint).

        Args:
            hook: Coroutine sans argument (ex. redémarrage du service).
        """
        self._give_up_hooks.append(hook)

    def on_event(self, event: str, handler: Callable[[object], Awaitable[None]]) -> None:
        """Ajoute un gestionnaire brut pour un événement quelconque.

        Args:
            event: Nom exact de l'événement.
            handler: Coroutine recevant la charge utile non décodée (`None` si absente).
        """

        async def listener(*args: object) -> None:
            await handler(_payload(args))

        self._listen(event, listener)

    def _subscribe[E](
        self,
        event: str,
        decode: Callable[[object], E | None],
        handler: Callable[[E], Awaitable[None]],
    ) -> None:
        """Ajoute un gestionnaire typé ; la charge utile est décodée avant l'appel.

        Args:
            event: Nom exact de l'événement.
            decode: Décodeur ; renvoie `None` pour ignorer l'événement.
            handler: Coroutine recevant l'événement décodé.
        """

        async def listener(*args: object) -> None:
            decoded = _decode_or_log(event, decode, _payload(args))
            if decoded is not None:
                await handler(decoded)

        self._listen(event, listener)

    def _listen(self, event: str, listener: AsyncHandler) -> None:
        """Ajoute un écouteur ; le premier d'un événement l'enregistre auprès du transport.

        Args:
            event: Nom exact de l'événement.
            listener: Écouteur recevant les arguments bruts de l'événement.
        """
        listeners = self._listeners.setdefault(event, [])
        if not listeners:
            self._transport.on(event, self._dispatcher(event))
        listeners.append(listener)

    def _dispatcher(self, event: str) -> AsyncHandler:
        """Crée le gestionnaire de transport d'un événement, qui appelle chaque écouteur.

        Args:
            event: Nom de l'événement.

        Returns:
            Le gestionnaire à enregistrer auprès du transport.
        """

        async def dispatch(*args: object) -> None:
            for listener in self._listeners[event]:
                try:
                    await listener(*args)
                except Exception:
                    _LOG.exception("Gestionnaire de %s en échec", event)

        return dispatch

    @staticmethod
    async def _notify(hooks: list[AsyncCallback], what: str) -> None:
        """Appelle des hooks sans argument ; une exception est journalisée.

        Args:
            hooks: Hooks à appeler.
            what: Nature des hooks, pour le journal.
        """
        for hook in hooks:
            try:
                await hook()
            except Exception:
                _LOG.exception("Hook %s en échec", what)

    async def _handle_connect(self, *_args: object) -> None:
        """Réagit à l'établissement de la connexion.

        Args:
            *_args: Arguments de l'événement, ignorés.
        """
        self._session_open = True
        try:
            await self._after_connect()
        except RealtimeConnectionError as exc:
            _LOG.warning("Initialisation de la connexion en échec : %s", exc)
        await self._notify(self._connect_hooks, "on_connect")

    async def _handle_disconnect(self, *_args: object) -> None:
        """Réagit à la fin de la connexion, une seule fois par session.

        `python-socketio` peut signaler deux fois la même déconnexion (fermeture
        par le serveur puis `stop` appelé depuis un hook).

        Args:
            *_args: Arguments de l'événement (motif), ignorés.
        """
        if not self._session_open:
            return
        self._session_open = False
        await self._notify(self._disconnect_hooks, "on_disconnect")

    async def emit(self, event: str, data: Mapping[str, JsonValue]) -> None:
        """Émet un événement brut ; lève `RealtimeConnectionError` si le socket est déconnecté.

        Args:
            event: Nom exact de l'événement.
            data: Charge utile JSON.
        """
        await self._transport.emit(event, dict(data))

    async def connect(self) -> None:
        """Tente une connexion, sans reconnexion.

        En cas de refus ou d'échec, les hooks `on_connect_error` sont appelés
        puis `RealtimeConnectionError` est levée.
        """
        headers = {"User-Agent": self.config.user_agent}
        try:
            await self._transport.connect(self.config.realtime_base_url, headers, self._auth())
        except RealtimeConnectionError as exc:
            _LOG.warning("Connexion temps réel en échec : %s", exc)
            for hook in self._error_hooks:
                try:
                    await hook(str(exc))
                except Exception:
                    _LOG.exception("Hook on_connect_error en échec")
            raise

    async def run(self) -> None:
        """Maintient la connexion jusqu'à `stop` ou jusqu'à l'abandon (`ReconnectPolicy`)."""
        self._stopped.clear()
        failures = 0
        while not self._stopped.is_set():
            try:
                await self.connect()
            except RealtimeConnectionError:
                failures += 1
                if self.policy.gives_up_after(failures):
                    await self._notify(self._give_up_hooks, "on_give_up")
                    return
            else:
                failures = 0
                await self._transport.wait()
            await self._pause()

    async def _pause(self) -> None:
        """Attend `retry_interval`, ou moins si `stop` est appelé entre-temps."""
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stopped.wait(), self.policy.retry_interval)

    async def stop(self) -> None:
        """Arrête `run` et ferme la connexion.

        Les émissions encore en file d'envoi peuvent être perdues.
        """
        self._stopped.set()
        if self._transport.connected:
            await self._transport.disconnect()

    async def __aenter__(self) -> Self:
        """Entre dans le contexte.

        Returns:
            Le socket lui-même.
        """
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Arrête le socket."""
        await self.stop()


class SyncRealtimeSocket[C]:
    """Socket générique synchrone (`socketio.Client`).

    Les gestionnaires sont appelés depuis le thread de fond de `python-socketio` ;
    ils s'ajoutent les uns aux autres et une exception est journalisée sans
    interrompre les suivants. `stop` peut être appelé depuis un autre thread.

    Attributes:
        credentials: Identifiants de l'appareil.
        config: Configuration (URL du serveur, `User-Agent`).
        policy: Politique de connexion et de reconnexion.
    """

    default_policy: ClassVar[ReconnectPolicy] = ReconnectPolicy()
    """Politique utilisée quand l'appelant n'en fournit pas."""

    def __init__(
        self,
        credentials: C,
        config: ClientConfig | None = None,
        *,
        policy: ReconnectPolicy | None = None,
        transport: SyncTransport | None = None,
    ) -> None:
        """Initialise le socket, sans se connecter.

        Args:
            credentials: Identifiants de l'appareil enrôlé.
            config: Configuration ; production par défaut.
            policy: Politique de reconnexion ; `default_policy` par défaut.
            transport: Transport à utiliser (tests) ; `python-socketio` par défaut.
        """
        self.credentials = credentials
        self.config = config or ClientConfig()
        self.policy = policy or self.default_policy
        self._transport = transport or SocketIOSyncTransport(self.policy.connect_timeout)
        self._listeners: dict[str, list[SyncHandler]] = {}
        self._connect_hooks: list[SyncCallback] = []
        self._disconnect_hooks: list[SyncCallback] = []
        self._error_hooks: list[Callable[[str], None]] = []
        self._give_up_hooks: list[SyncCallback] = []
        self._stopped = threading.Event()
        self._session_open = False
        self._transport.on("connect", self._handle_connect)
        self._transport.on("disconnect", self._handle_disconnect)

    def _auth(self) -> dict[str, str]:
        """Renvoie les données d'authentification Socket.IO.

        Returns:
            Les données `auth` de la connexion.

        Raises:
            NotImplementedError: Toujours ; à définir par les spécialisations.
        """
        raise NotImplementedError

    def _after_connect(self) -> None:
        """Étape exécutée à chaque connexion, avant les hooks `on_connect`."""

    @property
    def connected(self) -> bool:
        """Indique si la connexion est établie."""
        return self._transport.connected

    def on_connect(self, hook: SyncCallback) -> None:
        """Ajoute un hook appelé à chaque connexion ; voir `RealtimeSocket.on_connect`.

        Args:
            hook: Fonction sans argument.
        """
        self._connect_hooks.append(hook)

    def on_disconnect(self, hook: SyncCallback) -> None:
        """Ajoute un hook appelé à chaque perte de connexion.

        Args:
            hook: Fonction sans argument.
        """
        self._disconnect_hooks.append(hook)

    def on_connect_error(self, hook: Callable[[str], None]) -> None:
        """Ajoute un hook appelé à chaque échec de connexion ; le motif n'inclut jamais la clé.

        Args:
            hook: Fonction recevant le motif de l'échec.
        """
        self._error_hooks.append(hook)

    def on_give_up(self, hook: SyncCallback) -> None:
        """Ajoute un hook appelé quand `run` abandonne (seuil d'échecs atteint).

        Args:
            hook: Fonction sans argument (ex. redémarrage du service).
        """
        self._give_up_hooks.append(hook)

    def on_event(self, event: str, handler: Callable[[object], None]) -> None:
        """Ajoute un gestionnaire brut pour un événement quelconque.

        Args:
            event: Nom exact de l'événement.
            handler: Fonction recevant la charge utile non décodée (`None` si absente).
        """

        def listener(*args: object) -> None:
            handler(_payload(args))

        self._listen(event, listener)

    def _subscribe[E](
        self,
        event: str,
        decode: Callable[[object], E | None],
        handler: Callable[[E], None],
    ) -> None:
        """Ajoute un gestionnaire typé ; la charge utile est décodée avant l'appel.

        Args:
            event: Nom exact de l'événement.
            decode: Décodeur ; renvoie `None` pour ignorer l'événement.
            handler: Fonction recevant l'événement décodé.
        """

        def listener(*args: object) -> None:
            decoded = _decode_or_log(event, decode, _payload(args))
            if decoded is not None:
                handler(decoded)

        self._listen(event, listener)

    def _listen(self, event: str, listener: SyncHandler) -> None:
        """Ajoute un écouteur ; le premier d'un événement l'enregistre auprès du transport.

        Args:
            event: Nom exact de l'événement.
            listener: Écouteur recevant les arguments bruts de l'événement.
        """
        listeners = self._listeners.setdefault(event, [])
        if not listeners:
            self._transport.on(event, self._dispatcher(event))
        listeners.append(listener)

    def _dispatcher(self, event: str) -> SyncHandler:
        """Crée le gestionnaire de transport d'un événement, qui appelle chaque écouteur.

        Args:
            event: Nom de l'événement.

        Returns:
            Le gestionnaire à enregistrer auprès du transport.
        """

        def dispatch(*args: object) -> None:
            for listener in self._listeners[event]:
                try:
                    listener(*args)
                except Exception:
                    _LOG.exception("Gestionnaire de %s en échec", event)

        return dispatch

    @staticmethod
    def _notify(hooks: list[SyncCallback], what: str) -> None:
        """Appelle des hooks sans argument ; une exception est journalisée.

        Args:
            hooks: Hooks à appeler.
            what: Nature des hooks, pour le journal.
        """
        for hook in hooks:
            try:
                hook()
            except Exception:
                _LOG.exception("Hook %s en échec", what)

    def _handle_connect(self, *_args: object) -> None:
        """Réagit à l'établissement de la connexion.

        Args:
            *_args: Arguments de l'événement, ignorés.
        """
        self._session_open = True
        try:
            self._after_connect()
        except RealtimeConnectionError as exc:
            _LOG.warning("Initialisation de la connexion en échec : %s", exc)
        self._notify(self._connect_hooks, "on_connect")

    def _handle_disconnect(self, *_args: object) -> None:
        """Réagit à la fin de la connexion, une seule fois par session.

        `python-socketio` peut signaler deux fois la même déconnexion (fermeture
        par le serveur puis `stop` appelé depuis un hook).

        Args:
            *_args: Arguments de l'événement (motif), ignorés.
        """
        if not self._session_open:
            return
        self._session_open = False
        self._notify(self._disconnect_hooks, "on_disconnect")

    def emit(self, event: str, data: Mapping[str, JsonValue]) -> None:
        """Émet un événement brut ; lève `RealtimeConnectionError` si le socket est déconnecté.

        Args:
            event: Nom exact de l'événement.
            data: Charge utile JSON.
        """
        self._transport.emit(event, dict(data))

    def connect(self) -> None:
        """Tente une connexion, sans reconnexion.

        En cas de refus ou d'échec, les hooks `on_connect_error` sont appelés
        puis `RealtimeConnectionError` est levée.
        """
        headers = {"User-Agent": self.config.user_agent}
        try:
            self._transport.connect(self.config.realtime_base_url, headers, self._auth())
        except RealtimeConnectionError as exc:
            _LOG.warning("Connexion temps réel en échec : %s", exc)
            for hook in self._error_hooks:
                try:
                    hook(str(exc))
                except Exception:
                    _LOG.exception("Hook on_connect_error en échec")
            raise

    def run(self) -> None:
        """Maintient la connexion jusqu'à `stop` ou jusqu'à l'abandon (`ReconnectPolicy`)."""
        self._stopped.clear()
        failures = 0
        while not self._stopped.is_set():
            try:
                self.connect()
            except RealtimeConnectionError:
                failures += 1
                if self.policy.gives_up_after(failures):
                    self._notify(self._give_up_hooks, "on_give_up")
                    return
            else:
                failures = 0
                self._transport.wait()
            self._stopped.wait(self.policy.retry_interval)

    def stop(self) -> None:
        """Arrête `run` et ferme la connexion.

        Les émissions encore en file d'envoi peuvent être perdues.
        """
        self._stopped.set()
        if self._transport.connected:
            self._transport.disconnect()

    def __enter__(self) -> Self:
        """Entre dans le contexte.

        Returns:
            Le socket lui-même.
        """
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Arrête le socket."""
        self.stop()
