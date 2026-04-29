#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <ESP8266mDNS.h>
#include <SoftwareSerial.h>

#include "secrets.h"

#ifndef BRIDGE_HOSTNAME
#define BRIDGE_HOSTNAME "treadmill-bridge"
#endif

#ifndef BRIDGE_PORT
#define BRIDGE_PORT 8023
#endif
#ifndef LINK_BAUD
#define LINK_BAUD 9600
#endif
#ifndef LINK_RX_PIN
#define LINK_RX_PIN 14
#endif
#ifndef LINK_TX_PIN
#define LINK_TX_PIN 12
#endif

static SoftwareSerial link(LINK_RX_PIN, LINK_TX_PIN);
static WiFiServer server(BRIDGE_PORT);
static WiFiClient client;

static void connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.persistent(false);
  WiFi.setAutoReconnect(true);
  WiFi.setSleepMode(WIFI_NONE_SLEEP);  // stay awake — answer ARP/pings
  WiFi.hostname(BRIDGE_HOSTNAME);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("[wifi] connecting");
  while (WiFi.status() != WL_CONNECTED) {
    delay(250);
    Serial.print('.');
  }
  Serial.printf("\n[wifi] IP:      %s\n", WiFi.localIP().toString().c_str());
  Serial.printf("[wifi] mask:    %s\n", WiFi.subnetMask().toString().c_str());
  Serial.printf("[wifi] gw:      %s\n", WiFi.gatewayIP().toString().c_str());
  Serial.printf("[wifi] dns:     %s\n", WiFi.dnsIP().toString().c_str());
  Serial.printf("[wifi] mac:     %s\n", WiFi.macAddress().c_str());
  Serial.printf("[wifi] rssi:    %d dBm\n", WiFi.RSSI());
  Serial.printf("[wifi] channel: %d\n", WiFi.channel());
  Serial.printf("[wifi] bssid:   %s\n", WiFi.BSSIDstr().c_str());

}

void setup() {
  Serial.begin(115200);
  delay(50);
  Serial.println("\n[boot] treadmill bridge");

  link.begin(LINK_BAUD);

  connectWifi();
  server.begin();
  server.setNoDelay(true);
  Serial.printf("[tcp] listening on :%d\n", BRIDGE_PORT);

  if (MDNS.begin(BRIDGE_HOSTNAME)) {
    MDNS.addService("csafe-bridge", "tcp", BRIDGE_PORT);
    Serial.printf("[mdns] %s.local\n", BRIDGE_HOSTNAME);
  } else {
    Serial.println("[mdns] failed");
  }
}

void loop() {
  MDNS.update();

  static uint32_t lastBeat = 0;
  if (millis() - lastBeat > 5000) {
    lastBeat = millis();
    Serial.printf("[beat] up=%lus  wifi=%d  rssi=%d  clients=%d\n",
                  millis() / 1000, WiFi.status(), WiFi.RSSI(),
                  client && client.connected() ? 1 : 0);
  }

  // Accept / replace client.
  if (server.hasClient()) {
    if (!client || !client.connected()) {
      if (client) client.stop();
      client = server.available();
      client.setNoDelay(true);
      Serial.printf("[tcp] client %s connected\n",
                    client.remoteIP().toString().c_str());
    } else {
      // Already have a client; reject new one.
      WiFiClient drop = server.available();
      drop.stop();
    }
  }

  if (client && client.connected()) {
    // TCP -> serial
    while (client.available()) {
      uint8_t b = client.read();
      link.write(b);
    }
    // serial -> TCP
    while (link.available()) {
      uint8_t b = link.read();
      client.write(b);
    }
  } else {
    // No client: drain serial so its buffer doesn't sit stale.
    while (link.available()) link.read();
    if (client && !client.connected()) {
      Serial.println("[tcp] client disconnected");
      client.stop();
    }
  }

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[wifi] reconnecting");
    connectWifi();
  }
}
