"""Configuration des clients : environnement, base d'URL et délais d'attente."""

from dataclasses import dataclass
from enum import StrEnum


class Environment(StrEnum):
    """Environnement de l'API Welleat."""

    PRODUCTION = "https://welleat-api.welleat.fr/api"
    DEVELOPMENT = "https://welleat-api-dev.welleat.fr/api"


@dataclass(frozen=True, slots=True)
class Timeouts:
    """Délais d'attente d'un appel, en secondes.

    Attributes:
        connect: Délai d'établissement de la connexion.
        read: Délai de lecture (et d'écriture) de la réponse.
    """

    connect: float = 3.0
    read: float = 7.0


@dataclass(frozen=True, slots=True)
class ClientConfig:
    """Configuration commune à tous les clients.

    Le SDK ne lit jamais l'environnement du processus ni de fichier `.env` :
    tout est fourni explicitement par l'appelant.

    Attributes:
        environment: Environnement ciblé, qui fournit la base d'URL.
        base_url: Base d'URL (incluant `/api`) remplaçant celle de `environment`.
        timeouts: Délais par défaut, surchargeables par appel.
        user_agent: Valeur de l'en-tête `User-Agent`.
    """

    environment: Environment = Environment.PRODUCTION
    base_url: str | None = None
    timeouts: Timeouts = Timeouts()
    user_agent: str = "welleat-api-sdk/0.1"

    @property
    def api_base_url(self) -> str:
        """Base d'URL REST unique, sans barre oblique finale."""
        return (self.base_url or self.environment.value).rstrip("/")
