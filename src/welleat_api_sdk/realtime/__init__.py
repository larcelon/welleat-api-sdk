"""Canal temps réel Socket.IO (WebSocket) de l'API Welleat.

Nécessite l'extra `realtime` (`pip install welleat-api-sdk[realtime]`).
`CameraSocket` / `GatewaySocket` (et leurs variantes `Sync*`) spécialisent les
sockets génériques `RealtimeSocket` / `SyncRealtimeSocket`.
"""

from welleat_api_sdk.realtime.cameras import CameraSocket, SyncCameraSocket
from welleat_api_sdk.realtime.client import RealtimeSocket, ReconnectPolicy, SyncRealtimeSocket
from welleat_api_sdk.realtime.events import (
    CameraEvent,
    DeviceId,
    ManualCaptureRequest,
    PlugCommand,
    ScaleCommand,
    ScaleCommandFailure,
    ScaleCommandSuccess,
    ScaleCommandType,
    ScaleConnectionState,
    ScaleErrorCode,
    ScaleHeartbeat,
    ScaleWeightUpdate,
    StationEvent,
    StationHeartbeat,
    WeightAck,
    WeightRejection,
    parse_scale_weight,
)
from welleat_api_sdk.realtime.gateways import GatewaySocket, SyncGatewaySocket

__all__ = [
    "CameraEvent",
    "CameraSocket",
    "DeviceId",
    "GatewaySocket",
    "ManualCaptureRequest",
    "PlugCommand",
    "RealtimeSocket",
    "ReconnectPolicy",
    "ScaleCommand",
    "ScaleCommandFailure",
    "ScaleCommandSuccess",
    "ScaleCommandType",
    "ScaleConnectionState",
    "ScaleErrorCode",
    "ScaleHeartbeat",
    "ScaleWeightUpdate",
    "StationEvent",
    "StationHeartbeat",
    "SyncCameraSocket",
    "SyncGatewaySocket",
    "SyncRealtimeSocket",
    "WeightAck",
    "WeightRejection",
    "parse_scale_weight",
]
