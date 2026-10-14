"""Clients génériques (async et sync) : exécutent une `Request` et interprètent la réponse.

Ces classes ne connaissent aucun endpoint. `CameraClient` et `GatewayClient`
(et leurs pendants `Sync*`) les spécialisent par héritage.
"""

from types import TracebackType
from typing import TYPE_CHECKING, Self
from urllib.parse import quote

import httpx

from welleat_api_sdk.auth import AuthMode, Credentials
from welleat_api_sdk.config import ClientConfig, Timeouts
from welleat_api_sdk.errors import ApiError, NetworkError, NotEnrolledError, ServerError
from welleat_api_sdk.request import Reply, Request

if TYPE_CHECKING:
    from welleat_api_sdk.request import JsonValue

_RETRYABLE_STATUSES = frozenset({408, 429})
_SERVER_ERROR_FLOOR = 500


def _prepare[T](
    config: ClientConfig, credentials: Credentials | None, request: Request[T]
) -> httpx.Request:
    """Construit la requête httpx : URL, authentification, en-têtes, corps.

    Args:
        config: Configuration du client.
        credentials: Identifiants de l'appareil, `None` avant enrôlement.
        request: Appel à exécuter.

    Returns:
        La requête httpx prête à être envoyée.

    Raises:
        NotEnrolledError: Si l'endpoint exige une authentification sans identifiants.
    """
    headers = {"User-Agent": config.user_agent, **request.headers}
    body: dict[str, JsonValue] | None = None if request.body is None else dict(request.body)
    path = request.path
    if request.auth is not AuthMode.NONE or "{identity}" in path:
        if credentials is None:
            raise NotEnrolledError(f"{request.path} exige des identifiants d'appareil")
        path = path.replace("{identity}", quote(credentials.identifier, safe=""))
        match request.auth:
            case AuthMode.KEY_HEADER | AuthMode.KEY_HEADER_AND_BODY:
                headers["api-key"] = credentials.api_key
            case AuthMode.IDENTITY_HEADER:
                headers.update(credentials.identity_headers())
            case AuthMode.NONE | AuthMode.BODY:
                pass
        if request.auth in (AuthMode.BODY, AuthMode.KEY_HEADER_AND_BODY):
            body = {**(body or {}), **credentials.body_fields()}
    timeouts = request.timeouts or config.timeouts
    return httpx.Request(
        request.method,
        f"{config.api_base_url}/{path.lstrip('/')}",
        headers=headers,
        json=body,
        extensions={"timeout": _httpx_timeout(timeouts).as_dict()},
    )


def _httpx_timeout(timeouts: Timeouts) -> httpx.Timeout:
    """Convertit les délais du SDK en délais httpx.

    Returns:
        Délais équivalents au format httpx.
    """
    return httpx.Timeout(
        connect=timeouts.connect,
        read=timeouts.read,
        write=timeouts.read,
        pool=timeouts.connect,
    )


def _interpret[T](request: Request[T], response: httpx.Response) -> T:
    """Vérifie le statut puis parse la réponse.

    Args:
        request: Appel exécuté.
        response: Réponse httpx reçue.

    Returns:
        Le résultat parsé.

    Raises:
        ServerError: Statut 5xx, 408 ou 429 (rejouable).
        ApiError: Tout autre statut non accepté par l'endpoint.
    """
    reply = Reply(status=response.status_code, text=response.text)
    if reply.status in request.success:
        return request.parse(reply)
    if reply.status >= _SERVER_ERROR_FLOOR or reply.status in _RETRYABLE_STATUSES:
        raise ServerError(reply.status, reply.text)
    raise ApiError(reply.status, reply.text)


class SyncWelleatClient[C: Credentials]:
    """Client générique synchrone.

    Attributes:
        config: Configuration du client.
        credentials: Identifiants de l'appareil ; `None` avant enrôlement,
            à renseigner ensuite avec ceux renvoyés par l'enrôlement.
    """

    def __init__(
        self,
        config: ClientConfig | None = None,
        credentials: C | None = None,
        *,
        http: httpx.Client | None = None,
    ) -> None:
        """Initialise le client.

        Args:
            config: Configuration ; production par défaut.
            credentials: Identifiants de l'appareil, si déjà enrôlé.
            http: Client httpx à réutiliser (tests, proxy) ; il n'est alors pas fermé par `close`.
        """
        self.config = config or ClientConfig()
        self.credentials = credentials
        self._owns_http = http is None
        self._http = http or httpx.Client()

    def request[T](self, request: Request[T]) -> T:
        """Exécute un appel.

        Args:
            request: Appel à exécuter.

        Returns:
            Le résultat parsé par `request.parse`.

        Raises:
            NetworkError: Échec de transport.
        """
        prepared = _prepare(self.config, self.credentials, request)
        try:
            response = self._http.send(prepared)
        except httpx.HTTPError as exc:
            raise NetworkError(str(exc)) from exc
        return _interpret(request, response)

    def close(self) -> None:
        """Ferme le client httpx s'il appartient à ce client."""
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> Self:
        """Entre dans le contexte.

        Returns:
            Le client lui-même.
        """
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Ferme le client."""
        self.close()


class WelleatClient[C: Credentials]:
    """Client générique asynchrone.

    Attributes:
        config: Configuration du client.
        credentials: Identifiants de l'appareil ; `None` avant enrôlement,
            à renseigner ensuite avec ceux renvoyés par l'enrôlement.
    """

    def __init__(
        self,
        config: ClientConfig | None = None,
        credentials: C | None = None,
        *,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        """Initialise le client.

        Args:
            config: Configuration ; production par défaut.
            credentials: Identifiants de l'appareil, si déjà enrôlé.
            http: Client httpx à réutiliser (tests, proxy) ; il n'est alors pas fermé par `aclose`.
        """
        self.config = config or ClientConfig()
        self.credentials = credentials
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient()

    async def request[T](self, request: Request[T]) -> T:
        """Exécute un appel.

        Args:
            request: Appel à exécuter.

        Returns:
            Le résultat parsé par `request.parse`.

        Raises:
            NetworkError: Échec de transport.
        """
        prepared = _prepare(self.config, self.credentials, request)
        try:
            response = await self._http.send(prepared)
        except httpx.HTTPError as exc:
            raise NetworkError(str(exc)) from exc
        return _interpret(request, response)

    async def aclose(self) -> None:
        """Ferme le client httpx s'il appartient à ce client."""
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> Self:
        """Entre dans le contexte.

        Returns:
            Le client lui-même.
        """
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Ferme le client."""
        await self.aclose()
