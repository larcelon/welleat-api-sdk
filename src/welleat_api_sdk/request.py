"""Description pure d'un appel REST, indépendante du transport."""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from welleat_api_sdk.auth import AuthMode
from welleat_api_sdk.config import Timeouts
from welleat_api_sdk.errors import ResponseFormatError

#: Valeur JSON quelconque, telle que produite par `json.loads`.
type JsonValue = str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None

OK_STATUSES = frozenset({200, 201})


@dataclass(frozen=True, slots=True)
class Reply:
    """Réponse HTTP reçue, réduite à ce que les parseurs consomment.

    Attributes:
        status: Statut HTTP.
        text: Corps en texte brut.
    """

    status: int
    text: str

    def json(self) -> object:
        """Décode le corps JSON.

        Returns:
            La valeur JSON décodée.

        Raises:
            ResponseFormatError: Si le corps n'est pas du JSON valide.
        """
        try:
            value: object = json.loads(self.text)
        except ValueError as exc:
            raise ResponseFormatError(f"corps non JSON : {self.text[:200]!r}") from exc
        return value


def ignore_reply(_reply: Reply) -> None:
    """Parseur des endpoints dont seule la réussite du statut compte."""


@dataclass(frozen=True, slots=True)
class Request[T]:
    """Un appel REST complet : où, comment s'authentifier, quoi accepter.

    Attributes:
        method: Verbe HTTP.
        path: Chemin relatif à la base d'URL ; `{identity}` est remplacé par
            l'identifiant (encodé) de l'appareil.
        parse: Transforme une réponse acceptée en résultat typé.
        auth: Mode d'authentification de l'endpoint.
        body: Corps JSON, sans les champs d'authentification.
        headers: En-têtes propres à l'appel.
        success: Statuts HTTP considérés comme un succès.
        timeouts: Délais propres à l'appel ; sinon ceux de la configuration.
    """

    method: str
    path: str
    parse: Callable[[Reply], T]
    auth: AuthMode = AuthMode.NONE
    body: Mapping[str, JsonValue] | None = None
    headers: Mapping[str, str] = field(default_factory=dict)
    success: frozenset[int] = OK_STATUSES
    timeouts: Timeouts | None = None
