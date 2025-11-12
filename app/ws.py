from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import json
from .db import is_pin_owned_by_user
from .auth import verify_token

router = APIRouter()
clients = set()
subscriptions = {}
owners = {}

async def broadcast(msg: dict):
    if not clients:
        return
    
    pin = msg.get("pin")
    if not pin:
        return
    
    data = json.dumps(msg)
    dead = []
    for ws in list(clients):
        try:
            pins = subscriptions.get(ws, set())
            if pin in pins:
                await ws.send_text(data)
        except Exception:
            dead.append(ws)

    for ws in dead:
        try:
            clients.remove(ws)
            subscriptions.pop(ws, None)
        except KeyError:
            pass


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    token = websocket.cookies.get("token")
    if not token:
        await websocket.close(code=1008)
        return
    
    try:
        payload = verify_token(token)
        user_id = int(payload.get("sub", 0))
    except Exception:
        await websocket.close(code=1008)
        return
    
    if not user_id:
        await websocket.close(code=1008)
        return
    
    await websocket.accept()
    clients.add(websocket)
    subscriptions[websocket] = set()
    owners[websocket] = user_id
    
    try:
        while True:
            try:
                text = await websocket.receive_text()
                if text.strip().lower() == "ping":
                    continue
                pins = None
                try:
                    data = json.loads(text)
                    if isinstance(data, dict) and isinstance(data.get("pins"), list):
                        pins = [str(p).strip() for p in data.get("pins") if str(p).strip()]
                except Exception:
                    tokens = [t.strip() for t in text.split(",") if t.strip()]
                    if tokens:
                        pins = tokens

                if pins is not None:
                    allowed = set()
                    for pin in pins:
                        if is_pin_owned_by_user(owners[websocket], pin):
                            allowed.add(pin)
                    subscriptions[websocket] = allowed

                    await websocket.send_text(json.dumps({"type": "subscribed", "pins": sorted(list(allowed))}))
            except WebSocketDisconnect:
                break
    finally:
        if websocket in clients:
            clients.remove(websocket)

        subscriptions.pop(websocket, None)
        owners.pop(websocket, None)
