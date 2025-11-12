import asyncio, json, time
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from asyncio_mqtt import Client, MqttError

app = FastAPI()

@app.get("/")
def home():
    return FileResponse("public/index.html")

clients = set()

#Config MQTT
BROKER = "test.mosquitto.org"
PORT = 1883
TOPIC = "test/demo/#"

async def mqtt_loop():
    while True:
        try:
            async with Client(BROKER, PORT) as client:
                await client.subscribe(TOPIC)
                async with client.unfiltered_messages() as messages:
                    async for msg in messages:
                        data = {
                            "topic": msg.topic,
                            "payload": msg.payload.decode("utf-8", "ignore"),
                            "ts": int(time.time()),
                        }
                        dead = []
                        for ws in list(clients):
                            try:
                                await ws.send_json(data)
                            except Exception:
                                dead.append(ws)
                        for ws in dead:
                            clients.discard(ws)
        except MqttError:
            await asyncio.sleep(2)

@app.on_event("startup")
async def startup():
    asyncio.create_task(mqtt_loop())
    
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    try:
        while True:
            await ws.receive_text()  
    except WebSocketDisconnect:
        clients.discard(ws)
