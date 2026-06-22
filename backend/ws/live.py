"""WebSocket server — real-time position updates and pipeline status.

Handles two types of broadcast:
  1. Position updates: satellite positions for globe rendering (every 5 seconds)
  2. Pipeline status: current ingestion/propagation/detection stage and progress

Message protocol:
  Server → Client:
    {"type": "positions", "data": [[norad_id, lat, lon, alt], ...]}
    {"type": "pipeline_status", "data": {"stage": "propagation", "progress_pct": 45.2}}
    {"type": "conjunction_alert", "data": {...}}
    {"type": "ping"}

  Client → Server:
    {"type": "pong"}
    {"type": "subscribe", "data": {"norad_ids": [25544, 44713]}}

Connection lifecycle:
  - Server sends ping every 30 seconds
  - Client responds with pong
  - If 3 consecutive pongs are missed, connection is dropped
  - Client should reconnect with exponential backoff (1s, 2s, 4s, 8s, max 30s)
"""
import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import WebSocket, WebSocketDisconnect

from core.engine import orbital_engine
from cache.position_cache import get_pipeline_status

logger = logging.getLogger("orbitpulse.ws.live")

# Connected clients
_clients: set[WebSocket] = set()

# Update interval for position broadcasts (seconds)
_POSITION_INTERVAL = 5
# Ping interval (seconds)
_PING_INTERVAL = 30


async def websocket_endpoint(websocket: WebSocket) -> None:
    """Main WebSocket handler for /ws/live.

    Manages the connection lifecycle: accept, broadcast, ping/pong, disconnect.
    Each connection starts a background task for position updates and
    a separate task for ping keepalive.
    """
    await websocket.accept()
    _clients.add(websocket)
    client_id = id(websocket)
    logger.info(f"WebSocket client {client_id} connected (total: {len(_clients)})")

    # Track subscribed NORAD IDs (None = all objects up to limit)
    subscribed_ids: list[int] | None = None

    try:
        # Start background tasks for this connection
        position_task = asyncio.create_task(
            _position_broadcast_loop(websocket, lambda: subscribed_ids)
        )
        ping_task = asyncio.create_task(_ping_loop(websocket))

        # Listen for client messages
        while True:
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(), timeout=120.0,
                )
                message = json.loads(data)
                msg_type = message.get("type")

                if msg_type == "pong":
                    continue
                elif msg_type == "subscribe":
                    ids = message.get("data", {}).get("norad_ids")
                    if isinstance(ids, list):
                        subscribed_ids = ids
                        logger.debug(f"Client {client_id} subscribed to {len(ids)} objects")
                else:
                    logger.debug(f"Unknown message type from client {client_id}: {msg_type}")

            except asyncio.TimeoutError:
                # No message received in 120s — connection may be stale
                break
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON from client {client_id}")
                continue

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error for client {client_id}: {e}")
    finally:
        _clients.discard(websocket)
        position_task.cancel()
        ping_task.cancel()
        logger.info(f"WebSocket client {client_id} disconnected (remaining: {len(_clients)})")


async def _position_broadcast_loop(
    websocket: WebSocket,
    get_subscribed_ids: callable,
) -> None:
    """Background loop that sends position updates every 5 seconds."""
    while True:
        try:
            await asyncio.sleep(_POSITION_INTERVAL)

            if not orbital_engine.is_propagated:
                # Send pipeline status instead of positions during startup
                status = await get_pipeline_status()
                if status:
                    await websocket.send_json({
                        "type": "pipeline_status",
                        "data": status,
                    })
                continue

            subscribed = get_subscribed_ids()
            positions = await orbital_engine.get_current_positions_batch(
                norad_ids=subscribed,
                limit=5000,
            )

            await websocket.send_json({
                "type": "positions",
                "data": positions,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "count": len(positions),
            })

        except (WebSocketDisconnect, RuntimeError):
            break
        except Exception as e:
            logger.error(f"Position broadcast error: {e}")
            await asyncio.sleep(1)


async def _ping_loop(websocket: WebSocket) -> None:
    """Background loop that sends ping messages every 30 seconds."""
    while True:
        try:
            await asyncio.sleep(_PING_INTERVAL)
            await websocket.send_json({"type": "ping"})
        except (WebSocketDisconnect, RuntimeError):
            break
        except Exception as e:
            logger.error(f"Ping error: {e}")
            break


async def broadcast_conjunction_alert(alert_data: dict) -> None:
    """Broadcast a new conjunction alert to all connected clients.

    Called by the detection pipeline when a new ACTION-tier conjunction
    is detected. Non-blocking — errors on individual clients are logged
    but don't prevent other clients from receiving the alert.
    """
    if not _clients:
        return

    message = json.dumps({
        "type": "conjunction_alert",
        "data": alert_data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    disconnected: set[WebSocket] = set()
    for client in _clients:
        try:
            await client.send_text(message)
        except Exception:
            disconnected.add(client)

    _clients -= disconnected
    if disconnected:
        logger.info(f"Removed {len(disconnected)} disconnected WebSocket client(s)")
