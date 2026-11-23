from firmware.communication.mqtt import MQTTUploader
import json

CLIENT_ID = "quec_001"
SERVER = "你的mqtt服务器地址"
PORT = 1883
USER = ""
PASSWORD = ""
TOPIC = "device/data"

mqtt = MQTTUploader(CLIENT_ID, SERVER, PORT, USER, PASSWORD)
mqtt.connect()

data = {
    "temp": 24.5,
    "humi": 78.2,
    "dew_point": 21.3,
    "fan_pwm": 60,
    "risk_level": 2
}
msg = json.dumps(data)
mqtt.publish(TOPIC, msg)