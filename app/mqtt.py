import asyncio
import json
import time
from .config import BROKER_URL, BROKER_TOPIC, parse_mqtt_url
from .db import apply_change
from .ws import broadcast

import aiomqtt as mqtt
Client = mqtt.Client

enabled_state = {} # TODO: IN DATABASE

async def mqtt_consumer():
    cfg = parse_mqtt_url(BROKER_URL)
    while True:
        try:
            async with Client(cfg["host"], cfg["port"]) as client:
                await client.subscribe(f"{BROKER_TOPIC}/+/+")
                print("MQTT connected to", BROKER_URL, "subscribed to", f"{BROKER_TOPIC}/+/+")

                async for message in client.messages:
                    topic = message.topic
                    ts = int(time.time())

                    topicString = topic.value
                    parts = topicString.split("/")
                    print("new message", topicString)
                    

                    if len(parts) < 4:
                        continue

                    pin =   parts[-2]
                    action = parts[-1]

                    try:
                        payload = json.loads(message.payload.decode("utf-8"))
                    except Exception:
                        continue


                    if action == "toggle":
                        enabled = bool(payload.get("enabled", True))
                        enabled_state[pin] = enabled
                        print(f"PIN {pin} -> {'ENABLED' if enabled else 'DISABLED'}")
                        continue

                    if action == "count":
                        if enabled_state.get(pin, True) is False:
                            continue

                        try:
                            change = int(payload.get("change", 0))
                        except Exception:
                            continue

                        if change not in (-1, 1):
                            continue

                        print(f"PIN {pin} -> CHANGE {change}")
                        new_count = apply_change(pin=pin, change=change, ts=ts)
                        await broadcast(
                            {
                                "topic": topic.value,
                                "pin": pin,
                                "change": change,
                                "new_count": new_count,
                                "ts": ts,
                            }
                        )
        except Exception as e:
            print("MQTT error:", e)
            await asyncio.sleep(3)
