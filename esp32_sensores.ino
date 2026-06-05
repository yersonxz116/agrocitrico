#include <WiFi.h>
#include <HTTPClient.h>
#include "DHT.h"

// ── WiFi ─────────────────────────────────────────────────────────────────────
const char* ssid = "RAMIREZ";
const char* password = "burkina3699";

// ── Servidor Flask ───────────────────────────────────────────────────────────
const char* serverUrl = "http://192.168.101.10:5000/api/sensores";
// Token unico generado al registrar este dispositivo en la plataforma
const char* sensorToken = "80b4981f08724936f6e1a9a9160bf7da486b116cbaa607fefd9df4b8138e8680";

// ── DHT11 ────────────────────────────────────────────────────────────────────
#define DHTPIN 4
#define DHTTYPE DHT11
DHT dht(DHTPIN, DHTTYPE);

// ── YL-69 ────────────────────────────────────────────────────────────────────
const int pinHumedadSuelo = 34;

// Intervalo de envío (30 segundos)
const unsigned long intervaloEnvio = 30000;
unsigned long ultimoEnvio = 0;

void setup() {
  Serial.begin(115200);
  Serial.println("Iniciando sistema IoT AgroCítrico...");

  dht.begin();
  pinMode(pinHumedadSuelo, INPUT);

  // Conectar WiFi
  WiFi.begin(ssid, password);
  Serial.print("Conectando a WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  Serial.print("Conectado! IP: ");
  Serial.println(WiFi.localIP());
}

void loop() {
  unsigned long ahora = millis();

  if (ahora - ultimoEnvio >= intervaloEnvio) {
    ultimoEnvio = ahora;

    // Leer sensores
    float humedadAire = dht.readHumidity();
    float temperatura = dht.readTemperature();

    int lecturaSueloRaw = analogRead(pinHumedadSuelo);
    float porcentajeSuelo = map(lecturaSueloRaw, 4095, 2000, 0, 100);
    if (porcentajeSuelo < 0) porcentajeSuelo = 0;
    if (porcentajeSuelo > 100) porcentajeSuelo = 100;

    // Verificar lecturas válidas
    if (isnan(humedadAire) || isnan(temperatura)) {
      Serial.println("Error leyendo DHT11");
      return;
    }

    Serial.printf("Temp: %.1f°C | Hum aire: %.0f%% | Hum suelo: %.0f%%\n",
                  temperatura, humedadAire, porcentajeSuelo);

    // Enviar a Flask
    if (WiFi.status() == WL_CONNECTED) {
      WiFiClient client;
      HTTPClient http;
      http.begin(client, serverUrl);
      http.addHeader("Content-Type", "application/json");
      http.addHeader("Authorization", String("Bearer ") + sensorToken);

      String json = "{\"temperatura\":" + String(temperatura, 1)
                  + ",\"humedad_aire\":" + String(humedadAire, 0)
                  + ",\"humedad_suelo\":" + String(porcentajeSuelo, 0) + "}";

      int httpCode = http.POST(json);

      if (httpCode == 201) {
        Serial.println("Datos enviados correctamente");
      } else {
        Serial.printf("Error al enviar: HTTP %d\n", httpCode);
        Serial.println(http.getString());
      }

      http.end();
    } else {
      Serial.println("WiFi desconectado, reintentando...");
      WiFi.reconnect();
    }
  }
}
