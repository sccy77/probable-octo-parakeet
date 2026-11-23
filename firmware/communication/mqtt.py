from umqtt.simple import MQTTClient
 import utime
 class MQTTUploader:
     def __init__(self, client_id, server, port, user, password):
         self.client_id = client_id
         self.server = server
         self.port = port
         self.user = user
         self.password = password
         self.client = None
     def connect(self):
         try:
             self.client = MQTTClient(self.client_id, self.server, self.port, self.user, self.password)
             self.client.connect()
             print("MQTT连接成功")
         except Exception as e:
             print("MQTT连接失败：", e)
     def publish(self, topic, payload):
         if self.client:
             self.client.publish(topic, payload)
             print("上报数据：", payload)