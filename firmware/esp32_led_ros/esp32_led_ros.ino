/**
 * ESP32-CAM-MB — LED control via MQTT, with OTA updates
 *
 * Connects to WiFi and subscribes to a MAC-based MQTT topic:
 *   devices/<mac>/led/command
 *
 * Payload: "true" or "1" → LED on, "false" or "0" → LED off
 *
 * Publishes a retained device announcement on connect so the
 * dashboard auto-discovers the topic.
 *
 * After first USB flash, use `make ota` for subsequent updates.
 *
 * Required libraries (Tools → Manage Libraries):
 *   - PubSubClient by Nick O'Leary
 *
 * Board: AI Thinker ESP32-CAM
 * Port:  /dev/cu.usbserial-* (USB)
 */

#include <WiFi.h>
#include <ArduinoOTA.h>
#include <PubSubClient.h>
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"

#ifndef WIFI_SSID
#define WIFI_SSID "your_wifi_ssid"
#endif
#ifndef WIFI_PASS
#define WIFI_PASS "your_wifi_password"
#endif
#ifndef MQTT_IP
#define MQTT_IP "broker.hivemq.com"  // public cloud broker — no setup needed
#endif

const int MQTT_PORT = 1883;
const int LED_PIN   = 33;  // red LED on ESP32-CAM-MB (active low)

String topicCmd;  // devices/<mac>/led/command
String topicAnn;  // devices/<mac>

WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);

void onMessage(char* topic, byte* payload, unsigned int length) {
  String msg;
  for (unsigned int i = 0; i < length; i++) msg += (char)payload[i];

  if (strcmp(topic, topicCmd.c_str()) == 0) {
    bool on = (msg == "true" || msg == "1");
    digitalWrite(LED_PIN, on ? LOW : HIGH);  // LOW = on
    Serial.println(on ? "LED on" : "LED off");
  }
}

unsigned long lastReconnectMs = 0;
const unsigned long RECONNECT_INTERVAL = 5000;

void setup() {
  WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);  // disable brownout detector
  Serial.begin(115200);
  delay(2000);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, HIGH);  // off by default

  WiFi.begin(WIFI_SSID, WIFI_PASS);
  WiFi.setTxPower(WIFI_POWER_8_5dBm);  // reduce after begin, not before
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi connected: " + WiFi.localIP().toString());

  // Build unique topic prefix from MAC address (e.g. "d4e9f4a2a044")
  String mac = WiFi.macAddress();
  mac.toLowerCase();
  mac.replace(":", "");
  topicCmd = "devices/" + mac + "/led/command";
  topicAnn = "devices/" + mac;
  Serial.println("Topic: " + topicCmd);

  ArduinoOTA.setHostname("esp32-led");
  ArduinoOTA.onStart([]() {
    mqttClient.disconnect();  // free up WiFi bandwidth for OTA
    Serial.println("OTA start");
  });
  ArduinoOTA.onEnd([]()   { Serial.println("OTA done");  });
  ArduinoOTA.onError([](ota_error_t e) { Serial.printf("OTA error [%u]\n", e); });
  ArduinoOTA.begin();
  Serial.println("OTA ready — `make ota ESP32_IP=" + WiFi.localIP().toString() + "`");

  mqttClient.setServer(MQTT_IP, MQTT_PORT);
  mqttClient.setCallback(onMessage);
}

void loop() {
  ArduinoOTA.handle();  // must run every loop, even when MQTT is disconnected

  if (!mqttClient.connected()) {
    unsigned long now = millis();
    if (now - lastReconnectMs >= RECONNECT_INTERVAL) {
      lastReconnectMs = now;
      Serial.print("Connecting to MQTT...");
      String clientId = "esp32-" + topicAnn.substring(8);  // esp32-<mac>
      if (mqttClient.connect(clientId.c_str())) {
        Serial.println(" connected");
        String announcement = "{\"topics\":[\"" + topicCmd + "\"]}";
        mqttClient.publish(topicAnn.c_str(), announcement.c_str(), true);
        mqttClient.subscribe(topicCmd.c_str());
      } else {
        Serial.print(" failed, rc=");
        Serial.println(mqttClient.state());
      }
    }
  } else {
    mqttClient.loop();
  }
}
