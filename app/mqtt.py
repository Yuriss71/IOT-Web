import asyncio
import json
import time
from .config import BROKER_URL, BROKER_TOPIC, parse_mqtt_url
from .db import apply_change
from .ws import broadcast

import aiomqtt as mqtt
Client = mqtt.Client

async def mqtt_consumer():
    cfg = parse_mqtt_url(BROKER_URL)
    while True:
        try:
            async with Client(cfg["host"], cfg["port"]) as client:
                await client.subscribe(BROKER_TOPIC)
                async with client.messages() as messages:
                    async for message in messages:
                        topic = message.topic
                        ts = int(time.time())
                        parts = topic.split("/")
                        if len(parts) < 4 or parts[-1] != "count":
                            continue
                        pin = parts[-2]

                        try:
                            payload = json.loads(message.payload.decode("utf-8"))
                        except Exception:
                            continue

                        try:
                            change = int(payload.get("change", 0))
                        except Exception:
                            continue
                        if change not in (-1, 1):
                            continue

                        new_count = apply_change(pin=pin, change=change, ts=ts)

                        await broadcast(
                            {
                                "topic": topic,
                                "pin": pin,
                                "change": change,
                                "new_count": new_count,
                                "ts": ts,
                            }
                        )
        except Exception:
            await asyncio.sleep(3)
