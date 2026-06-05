# AgroCítrico

AgroCítrico es una plataforma web académica para la gestión agrícola de cultivos de limón. Permite mostrar información del proyecto, registrar usuarios, iniciar sesión con autenticación multifactor, acceder a un dashboard protegido y consultar un asistente de IA local con GPT4All.

## Funcionalidades actuales

- Homepage informativa con secciones de objetivos, tecnologías, sensores y contexto del proyecto.
- Registro de usuarios con validación del lado cliente y servidor.
- Login con contraseñas protegidas mediante hash.
- **Autenticación multifactor (MFA):**
  - TOTP (Google Authenticator, Authy) como segundo factor obligatorio.
  - Archivo PEM (RSA 2048-bit) como método de login alternativo sin contraseña.
  - 10 códigos de respaldo de un solo uso (formato `XXXXXX-XXXXXX`), hasheados con scrypt.
  - Configuración MFA obligatoria en el primer inicio de sesión.
- **Encriptación en reposo:** Campos sensibles encriptados con Fernet (AES-128-CBC). Prefijo `enc::` identifica valores encriptados en la base de datos.
- Middleware de sesión:
  - Usuarios sin sesión no pueden acceder a `/dashboard`.
  - Usuarios logueados no pueden volver a `/login` ni `/register`.
  - Estado MFA pendiente restringe acceso hasta verificar código.
- Dashboard privado con resumen de labores, alertas, sensores IoT y cosecha.
- Asistente IA en `/ia` conectado a GPT4All.
- Migraciones de base de datos con Flask-Migrate/Alembic.

## Stack tecnológico

| Capa | Tecnología |
|---|---|
| Backend | Python 3, Flask, Flask-SQLAlchemy, Flask-Migrate |
| Base de datos | MySQL, PyMySQL |
| Seguridad | pyotp (TOTP), cryptography (Fernet + RSA), scrypt |
| Frontend | HTML5, Jinja2, CSS3, JavaScript |
| IA local | GPT4All con `Meta-Llama-3-8B-Instruct.Q4_0.gguf` |

## Estructura del proyecto

```text
agrocitrico-diplomado/
├── app.py                         # App principal, rutas, modelos y middleware
├── requirements.txt               # Dependencias Python
├── .env                           # Variables de entorno (NO subir al repo)
├── migrations/                    # Configuración y versiones de Flask-Migrate
│   └── versions/
│       ├── d1ba8446358a_create_users_table.py
│       └── a2f8c3e91b04_add_mfa_fields.py
├── templates/
│   ├── index.html                 # Homepage
│   ├── login.html                 # Inicio de sesión
│   ├── login_pem.html             # Login con archivo PEM
│   ├── register.html              # Registro de usuarios
│   ├── mfa_setup.html             # Configuración MFA (QR + TOTP)
│   ├── mfa_setup_complete.html    # Backup codes + descarga PEM
│   ├── mfa_verify.html            # Verificación código TOTP
│   ├── mfa_backup.html            # Ingreso código de respaldo
│   ├── dashboard.html             # Panel privado
│   └── ia.html                    # Asistente IA
└── static/
    ├── index.css
    ├── index.js
    ├── css/                       # Estilos por pantalla
    │   └── auth.css               # Estilos auth + MFA
    ├── js/                        # Scripts por pantalla
    │   ├── login.js
    │   ├── register.js
    │   └── mfa.js                 # Interactividad MFA
    └── img/                       # Logo e imágenes del proyecto
```

## Configuración en otro equipo

1. Clonar el repositorio:

```bash
git clone <URL_DEL_REPOSITORIO>
cd agrocitrico-diplomado
```

2. Crear y activar el entorno virtual:

```bash
python3 -m venv venv
source venv/bin/activate
```

En Windows:

```bash
python -m venv venv
venv\Scripts\activate
```

3. Instalar dependencias:

```bash
pip install -r requirements.txt
```

4. Crear la base de datos MySQL vacía:

```sql
CREATE DATABASE agrocitrico CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

5. Crear archivo `.env` en la raíz del proyecto:

```bash
# Generar la clave Fernet (ejecutar en terminal):
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Copiar la clave generada y crear el archivo `.env`:

```env
FERNET_KEY=tu_clave_fernet_generada_aqui
MYSQL_USER=root
MYSQL_PASSWORD=tu_password
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_DATABASE=agrocitrico
SECRET_KEY=cambia-esta-clave-en-produccion
```

La variable `FERNET_KEY` es obligatoria para la encriptación de campos sensibles (secretos TOTP, llaves públicas PEM).

También puedes usar una URL completa para MySQL:

```env
DATABASE_URL=mysql+pymysql://usuario:password@localhost:3306/agrocitrico
```

## Migraciones de base de datos

Aplicar las migraciones existentes:

```bash
flask db upgrade
```

Esto ejecuta dos migraciones:

1. `d1ba8446358a` — Crea tabla `users` (nombre, correo, password_hash, timestamps).
2. `a2f8c3e91b04` — Agrega campos MFA a `users` (mfa_enabled, totp_secret, pem_fingerprint, pem_public_key) y crea tabla `backup_codes`.

Ver la revisión actual aplicada:

```bash
flask db current
```

Crear una nueva migración después de cambiar modelos:

```bash
flask db migrate -m "descripcion del cambio"
flask db upgrade
```

## Ejecutar el proyecto

Con el entorno virtual activo:

```bash
python app.py
```

Abrir en el navegador:

```text
http://localhost:5000
```

Si el puerto 5000 está ocupado:

```bash
flask run --host 127.0.0.1 --port 5001
```

## Rutas principales

| Ruta | Acceso | Descripción |
|---|---|---|
| `/` | Público | Homepage |
| `/register` | Solo visitantes | Registro |
| `/login` | Solo visitantes | Inicio de sesión |
| `/login/pem` | Solo visitantes | Login con archivo PEM (sin contraseña) |
| `/mfa/setup` | Post-login (MFA no configurado) | Wizard: QR + verificar TOTP |
| `/mfa/setup/verify` | POST | Validar primer código TOTP |
| `/mfa/setup/complete` | Post-setup | Mostrar backup codes + descargar PEM |
| `/mfa/setup/download-pem` | GET | Descarga del archivo .pem |
| `/mfa/setup/finish` | POST | Finalizar configuración MFA |
| `/mfa/verify` | Post-login (MFA activo) | Ingresar código TOTP |
| `/mfa/backup` | Post-login (MFA activo) | Usar código de respaldo |
| `/dashboard` | Solo usuarios autenticados | Dashboard privado |
| `/ia` | Público actualmente | Asistente IA |
| `/ia/chat` | POST | Endpoint del modelo GPT4All |
| `/logout` | POST | Cierre de sesión |

## Asistente IA

El asistente usa:

```python
GPT4All("Meta-Llama-3-8B-Instruct.Q4_0.gguf")
```

La primera consulta puede tardar porque GPT4All descarga o carga un modelo de varios GB. No subas archivos `.gguf` al repositorio; están excluidos por `.gitignore`.

## Configuración de Sensores IoT (DHT11 y YL-69)

El sistema IoT lee variables críticas del cultivo de limón utilizando un microcontrolador ESP32 y las envía al servidor local. A continuación se detallan las conexiones y configuraciones:

### 1. Sensor de Humedad y Temperatura del Aire (DHT11)
*   **Descripción**: Mide la temperatura ambiente y el porcentaje de humedad en el aire.
*   **Conexiones**:
    *   **VCC**: 3.3V (o 5V) en el ESP32.
    *   **GND**: GND en el ESP32.
    *   **DATA**: Pin GPIO 4 en el ESP32 (definido como `DHTPIN` en el código).
*   **Librerías requeridas**:
    *   *DHT sensor library* de Adafruit (instalar desde el Gestor de Librerías del Arduino IDE).
    *   *Adafruit Unified Sensor* (dependencia de Adafruit requerida).

### 2. Higrómetro de Suelo (YL-69)
*   **Descripción**: Mide la humedad presente en la tierra del cultivo (limonar). Consta de una sonda de dos puntas metálicas que se entierra en el suelo y un módulo comparador.
*   **Conexiones**:
    *   **VCC**: 3.3V en el ESP32.
    *   **GND**: GND en el ESP32.
    *   **AO (Salida Analógica)**: Pin GPIO 34 en el ESP32 (entrada analógica ADC1).
*   **Mapeo de Valores (Calibración)**:
    *   El ESP32 posee un conversor analógico-digital (ADC) de 12 bits, dando lecturas de 0 a 4095.
    *   A mayor humedad, menor resistencia eléctrica, reduciendo la lectura del ADC.
    *   El mapeo se calcula en el código con la función:
        ```cpp
        float porcentajeSuelo = map(lecturaSueloRaw, 4095, 2000, 0, 100);
        ```
        Donde `4095` es el valor con el sensor al aire libre (humedad 0%) y `2000` representa el suelo sumergido en agua/saturado (humedad 100%). Se pueden ajustar estos límites según las características físicas de tu suelo.

### 3. Carga y Configuración en el ESP32
1. Abre el archivo [esp32_sensores.ino](file:///C:/Users/KOLD/Documents/2026/diplomado/agrocitrico/agrocitrico-diplomado/esp32_sensores.ino) en el Arduino IDE.
2. Configura tu placa en el menú de herramientas (ej. **ESP32 Dev Module**).
3. Asegúrate de configurar la red Wi-Fi (`ssid` y `password`) con las credenciales de tu router local.
4. Ajusta la dirección IP en `serverUrl` (ej. `http://192.168.101.10:5000/api/sensores`) con la IP interna asignada a tu PC por tu router local.
5. Sube el código y abre el monitor serial (115200 baudios) para verificar que conecte a la red e inicie a reportar lecturas.

## Comandos útiles

```bash
venv/bin/python -m py_compile app.py
venv/bin/flask routes
venv/bin/flask db current
```

## Flujo de autenticación MFA

```text
Registro (/register)
    │
    ▼
Login (/login) ─── contraseña correcta
    │
    ├── MFA NO configurado (primer login)
    │       ▼
    │   /mfa/setup ── Escanear QR con Google Authenticator
    │       ▼
    │   /mfa/setup/verify ── Ingresar primer código TOTP
    │       ▼
    │   /mfa/setup/complete ── Ver 10 backup codes + descargar .pem
    │       ▼
    │   /mfa/setup/finish ── Confirmar y acceder al dashboard
    │
    └── MFA YA configurado
            ▼
        /mfa/verify ── Ingresar código TOTP de 6 dígitos
            │
            ├── Código correcto ── ▶ /dashboard
            └── Sin acceso al autenticador ── /mfa/backup (código de respaldo)

Login con PEM (/login/pem)
    │
    ▼
Email + archivo .pem ── verificación de fingerprint ── ▶ /dashboard
(Sin contraseña ni TOTP)
```

## Seguridad implementada

| Mecanismo | Detalle |
|---|---|
| Contraseñas | Hash con Werkzeug (PBKDF2-SHA256) |
| TOTP | Secreto de 32 caracteres, rotación cada 30s, ventana de tolerancia ±1 |
| Encriptación en reposo | Fernet (AES-128-CBC + HMAC). Prefijo `enc::` en BD |
| Archivo PEM | RSA 2048-bit. Fingerprint SHA-256 del public key almacenado |
| Códigos de respaldo | 10 códigos `XXXXXX-XXXXXX`, hasheados con scrypt (n=16384, r=8, p=1) |
| Sesión | Flags `mfa_pending` y `mfa_setup_required` controlan el flujo |

## Notas de seguridad

- No subas `.env`, contraseñas, dumps de base de datos ni modelos locales.
- Cambia `SECRET_KEY` en producción.
- Usa `debug=True` solo en desarrollo local.
- Las contraseñas se guardan como hash, no en texto plano.
- `FERNET_KEY` debe mantenerse segura; si se pierde, los campos encriptados no se pueden recuperar.
- El archivo `.pem` es equivalente a una contraseña — quien lo tenga puede acceder a la cuenta.
- Los códigos de respaldo no se pueden recuperar después del setup; solo se muestran una vez.

## Estado del proyecto

Proyecto académico en desarrollo activo como parte de un Diplomado.
