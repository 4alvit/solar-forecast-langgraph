"""Bounded MQTT delivery; broker PUBACK is distinct from controller acceptance."""

import json
import os
import threading

import paho.mqtt.client as mqtt


def deliver(broker, port, topic, payload, *, retain=False, ack_topic=None, timeout=8):
    done = threading.Event()
    result = {}
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if os.getenv("MQTT_USERNAME"):
        client.username_pw_set(os.environ["MQTT_USERNAME"], os.getenv("MQTT_PASSWORD"))

    def publish():
        client.publish(topic, json.dumps(payload, allow_nan=False), qos=1, retain=retain)

    def connected(_client, _userdata, _flags, reason, _properties):
        if reason.is_failure:
            result["error"] = "connection_rejected"
            done.set()
        elif ack_topic:
            client.subscribe(ack_topic, qos=1)
        else:
            publish()

    def subscribed(_client, _userdata, _mid, reasons, _properties):
        if any(reason.is_failure for reason in reasons):
            result["error"] = "subscription_rejected"
            done.set()
        else:
            publish()

    def published(_client, _userdata, _mid, reason, _properties):
        if reason.is_failure:
            result["error"] = "publish_rejected"
            done.set()
        elif not ack_topic:
            result["status"] = "delivered"
            done.set()

    def received(_client, _userdata, message):
        if message.topic != ack_topic or message.retain or len(message.payload) > 4096:
            return
        try:
            response = json.loads(message.payload)
            if response.get("request_id") == payload["request_id"] and response.get("status") in {
                "accepted",
                "suppressed",
                "duplicate",
                "rejected",
                "unavailable",
            }:
                result.update(response)
                done.set()
        except (ValueError, AttributeError):
            pass

    client.on_connect = connected
    client.on_subscribe = subscribed
    client.on_publish = published
    client.on_message = received
    client.connect_async(broker, port, keepalive=20)
    client.loop_start()
    try:
        if not done.wait(timeout):
            raise TimeoutError("MQTT controller acknowledgement" if ack_topic else "MQTT PUBACK")
        if "error" in result:
            raise RuntimeError(result["error"])
        return result
    finally:
        client.disconnect()
        client.loop_stop()
