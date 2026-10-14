"""SDK Python de l'API Welleat.

`WelleatClient` / `SyncWelleatClient` sont les clients génériques ;
`CameraClient` et `GatewayClient` (et leurs variantes `Sync*`) les spécialisent.
"""

from welleat_api_sdk.auth import (
    AuthMode,
    CameraCredentials,
    Credentials,
    EnrollmentSecrets,
    GatewayCredentials,
)
from welleat_api_sdk.cameras import CameraClient, SyncCameraClient
from welleat_api_sdk.client import SyncWelleatClient, WelleatClient
from welleat_api_sdk.config import ClientConfig, Environment, Timeouts
from welleat_api_sdk.errors import (
    ApiError,
    NetworkError,
    NotEnrolledError,
    RealtimeConnectionError,
    ResponseFormatError,
    RetryableError,
    ServerError,
    WelleatError,
)
from welleat_api_sdk.gateways import GatewayClient, SyncGatewayClient
from welleat_api_sdk.request import Reply, Request

__all__ = [
    "ApiError",
    "AuthMode",
    "CameraClient",
    "CameraCredentials",
    "ClientConfig",
    "Credentials",
    "EnrollmentSecrets",
    "Environment",
    "GatewayClient",
    "GatewayCredentials",
    "NetworkError",
    "NotEnrolledError",
    "RealtimeConnectionError",
    "Reply",
    "Request",
    "ResponseFormatError",
    "RetryableError",
    "ServerError",
    "SyncCameraClient",
    "SyncGatewayClient",
    "SyncWelleatClient",
    "Timeouts",
    "WelleatClient",
    "WelleatError",
]
