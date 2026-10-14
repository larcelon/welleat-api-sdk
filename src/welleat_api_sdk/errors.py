"""Exceptions levées par le SDK.

Le client lève, il ne réessaie jamais : la replanification (outbox) est à la
charge de l'appelant, qui peut se baser sur `RetryableError`.
"""

import json


class WelleatError(Exception):
    """Racine de toutes les erreurs du SDK."""


class NotEnrolledError(WelleatError):
    """Un appel authentifié a été tenté sans identifiants d'appareil."""


class RetryableError(WelleatError):
    """Erreur transitoire : l'appel peut être rejoué plus tard."""


class NetworkError(RetryableError):
    """Échec de transport (connexion, délai dépassé, réponse tronquée)."""


class ApiError(WelleatError):
    """Statut HTTP non accepté par l'endpoint, ou réponse métier invalide.

    Attributes:
        status: Statut HTTP reçu.
        body: Corps de la réponse en texte brut.
        error_message: Message `error` d'un corps `{ "error": "<message>" }`, seule
            forme d'erreur renvoyée par le back-end ; `None` pour tout autre corps.
    """

    def __init__(self, status: int, body: str, message: str | None = None) -> None:
        """Initialise l'erreur.

        Args:
            status: Statut HTTP reçu.
            body: Corps de la réponse en texte brut.
            message: Message explicatif ; par défaut, le statut suivi de
                `error_message` s'il existe, sinon du corps brut.
        """
        self.status = status
        self.body = body
        self.error_message = _error_message(body)
        super().__init__(message or f"HTTP {status} : {self.error_message or body}")


def _error_message(body: str) -> str | None:
    """Extrait le champ `error` d'un corps JSON `{ "error": "<message>" }`.

    Args:
        body: Corps de la réponse en texte brut.

    Returns:
        Le message non vide, ou `None` si le corps n'a pas cette forme.
    """
    try:
        data: object = json.loads(body)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    error = data.get("error")
    return error if isinstance(error, str) and error else None


class ServerError(ApiError, RetryableError):
    """Réponse 5xx, 408 ou 429 : l'appel peut être rejoué plus tard."""


class ResponseFormatError(WelleatError):
    """La réponse du serveur n'a pas la forme attendue."""
