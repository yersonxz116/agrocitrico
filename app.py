import base64
import hashlib
import io
import os
import re
import secrets
import uuid
from datetime import date, datetime, timedelta
from threading import Lock
from urllib.parse import quote_plus

from dotenv import load_dotenv

load_dotenv()

import pyotp
import qrcode
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_pem_private_key,
)
from flask import (
    Flask,
    Response,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.security import check_password_hash, generate_password_hash

try:
    from gpt4all import GPT4All
except ImportError:
    GPT4All = None

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "agrocitrico-dev-secret-key")
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024


def build_mysql_uri():
    user = os.environ.get("MYSQL_USER", "root")
    password = os.environ.get("MYSQL_PASSWORD", "")
    host = os.environ.get("MYSQL_HOST", "localhost")
    port = os.environ.get("MYSQL_PORT", "3306")
    database = os.environ.get("MYSQL_DATABASE", "agrocitrico")
    socket = os.environ.get("MYSQL_SOCKET")

    auth = quote_plus(user)
    if password:
        auth = f"{auth}:{quote_plus(password)}"

    query = f"?unix_socket={quote_plus(socket)}" if socket else ""
    return f"mysql+pymysql://{auth}@{host}:{port}/{quote_plus(database)}{query}"


if not app.config["SQLALCHEMY_DATABASE_URI"]:
    app.config["SQLALCHEMY_DATABASE_URI"] = build_mysql_uri()

db = SQLAlchemy(app)
migrate = Migrate(app, db)

MODEL_NAME = "Meta-Llama-3-8B-Instruct.Q4_0.gguf"
_model = None
_model_lock = Lock()
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
MFA_ISSUER_NAME = "AgroCitrico"

GUEST_ENDPOINTS = {"login", "register", "login_pem", "forgot_password", "reset_password"}
MFA_ENDPOINTS = {"mfa_verify", "mfa_backup"}
SETUP_ENDPOINTS = {
    "mfa_setup",
    "mfa_setup_verify",
    "mfa_setup_complete",
    "mfa_download_pem",
    "mfa_setup_finish",
}
PROTECTED_ENDPOINTS = {
    "dashboard", "actividades", "actividad_nueva", "actividad_eliminar",
    "cosechas", "cosecha_nueva", "cosecha_eliminar", "actualizar_meta",
    "dispositivos", "dispositivo_registrar", "dispositivo_eliminar", "dispositivo_toggle",
    "admin_dashboard", "admin_user_toggle", "admin_user_role", "admin_mfa_reset", "admin_device_toggle"
}

_setup_store = {}

# ── Fernet encryption ─────────────────────────────────────────────────────────

_fernet = None


def get_fernet():
    global _fernet
    if _fernet is None:
        key = os.environ.get("FERNET_KEY")
        if not key:
            key = Fernet.generate_key().decode()
            os.environ["FERNET_KEY"] = key
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


def encrypt_value(plaintext):
    token = get_fernet().encrypt(plaintext.encode()).decode()
    return f"enc::{token}"


def decrypt_value(stored):
    if not stored or not stored.startswith("enc::"):
        return stored
    token = stored[5:]
    return get_fernet().decrypt(token.encode()).decode()


# ── Backup codes ──────────────────────────────────────────────────────────────


def generate_backup_codes(count=10):
    codes = []
    for _ in range(count):
        part1 = secrets.token_hex(3).upper()
        part2 = secrets.token_hex(3).upper()
        codes.append(f"{part1}-{part2}")
    return codes


def hash_backup_code(code):
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(code.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return f"{salt.hex()}:{derived.hex()}"


def check_backup_code(code, stored_hash):
    try:
        salt_hex, hash_hex = stored_hash.split(":")
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        derived = hashlib.scrypt(code.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
        return secrets.compare_digest(derived, expected)
    except (ValueError, Exception):
        return False


# ── Models ────────────────────────────────────────────────────────────────────


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    fullname = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    mfa_enabled = db.Column(db.Boolean, nullable=False, default=False)
    totp_secret = db.Column(db.String(255), nullable=True)
    pem_fingerprint = db.Column(db.String(64), nullable=True)
    pem_public_key = db.Column(db.Text, nullable=True)
    meta_semanal = db.Column(db.Numeric(10, 2), nullable=False, default=58.0)
    reset_token = db.Column(db.String(100), nullable=True)
    reset_token_expiry = db.Column(db.DateTime, nullable=True)
    role = db.Column(db.String(20), nullable=False, default="user")
    activo = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now(),
        onupdate=db.func.now(),
    )

    backup_codes = db.relationship("BackupCode", backref="user", lazy="dynamic")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == "admin"

    def get_totp_secret(self):
        return decrypt_value(self.totp_secret) if self.totp_secret else None

    def set_totp_secret(self, secret):
        self.totp_secret = encrypt_value(secret)


class BackupCode(db.Model):
    __tablename__ = "backup_codes"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    code_hash = db.Column(db.String(255), nullable=False)
    used = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())


TIPOS_ACTIVIDAD = ["Riego", "Fertilización", "Fumigación", "Poda", "Otra"]


class Actividad(db.Model):
    __tablename__ = "actividades"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    tipo = db.Column(db.String(50), nullable=False)
    fecha_realizada = db.Column(db.Date, nullable=False)
    intervalo_dias = db.Column(db.Integer, nullable=False, default=1)
    proxima_fecha = db.Column(db.Date, nullable=False)
    notas = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    user = db.relationship("User", backref=db.backref("actividades", lazy="dynamic"))


class Cosecha(db.Model):
    __tablename__ = "cosechas"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    fecha = db.Column(db.Date, nullable=False)
    cantidad_kg = db.Column(db.Numeric(10, 2), nullable=False)
    notas = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    user = db.relationship("User", backref=db.backref("cosechas", lazy="dynamic"))


class Dispositivo(db.Model):
    __tablename__ = "dispositivos"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    nombre = db.Column(db.String(120), nullable=False)
    token = db.Column(db.String(64), nullable=False, unique=True, index=True)
    activo = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    user = db.relationship("User", backref=db.backref("dispositivos", lazy="dynamic"))
    lecturas = db.relationship("LecturaSensor", backref="dispositivo", lazy="dynamic")


class LecturaSensor(db.Model):
    __tablename__ = "lecturas_sensor"

    id = db.Column(db.Integer, primary_key=True)
    dispositivo_id = db.Column(db.Integer, db.ForeignKey("dispositivos.id"), nullable=True, index=True)
    temperatura = db.Column(db.Float, nullable=True)
    humedad_aire = db.Column(db.Float, nullable=True)
    humedad_suelo = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())


# ── Helpers ───────────────────────────────────────────────────────────────────


def get_model():
    global _model
    if GPT4All is None:
        raise RuntimeError("La dependencia gpt4all no esta instalada.")
    if _model is None:
        _model = GPT4All(MODEL_NAME)
    return _model


def is_valid_email(value):
    return bool(EMAIL_RE.match(value.strip()))


def send_reset_email(email, reset_link):
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        print(f"[DEVELOPMENT ONLY] RESEND_API_KEY no configurada. Enlace de restablecimiento para {email}: {reset_link}")
        return True

    from_email = os.environ.get("RESEND_FROM_EMAIL", "onboarding@resend.dev")
    url = "https://api.resend.com/emails"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "from": f"AgroCitrico <{from_email}>",
        "to": email,
        "subject": "Restablecer contrasena - AgroCitrico",
        "html": f"""
        <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto; padding: 30px; border: 1px solid #E0E0E0; border-radius: 12px; background-color: #FFFFFF;">
            <div style="text-align: center; margin-bottom: 30px;">
                <h2 style="color: #2E7D32; margin: 0; font-size: 24px; font-weight: 700;">AgroCitrico</h2>
                <p style="color: #666; margin: 5px 0 0 0; font-size: 14px;">Gestion agricola digital</p>
            </div>
            
            <p style="font-size: 16px; color: #1E1E1E; line-height: 1.6;">Hola,</p>
            <p style="font-size: 16px; color: #1E1E1E; line-height: 1.6;">Recibimos una solicitud para restablecer la contrasena de tu cuenta en AgroCitrico.</p>
            <p style="font-size: 16px; color: #1E1E1E; line-height: 1.6;">Haz clic en el boton de abajo para establecer una nueva contrasena. Por seguridad, este enlace expirara en 1 hora:</p>
            
            <div style="margin: 35px 0; text-align: center;">
                <a href="{reset_link}" style="background-color: #388E3C; color: #FFFFFF; padding: 14px 28px; text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 16px; display: inline-block;">Restablecer contrasena</a>
            </div>
            
            <p style="font-size: 14px; color: #666; line-height: 1.6;">Si el boton no funciona, puedes copiar y pegar el siguiente enlace en tu navegador:</p>
            <p style="font-size: 13px; color: #388E3C; word-break: break-all; line-height: 1.6;"><a href="{reset_link}" style="color: #388E3C;">{reset_link}</a></p>
            
            <p style="font-size: 14px; color: #666; line-height: 1.6; margin-top: 25px;">Si no solicitaste este cambio, puedes ignorar este correo sin problemas; tu contrasena actual seguira siendo segura.</p>
            
            <hr style="border: none; border-top: 1px solid #E5E5E5; margin: 30px 0;">
            <p style="font-size: 12px; color: #888; text-align: center; margin: 0;">Este es un correo automatico, por favor no respondas a este mensaje.</p>
        </div>
        """
    }

    try:
        import requests
        res = requests.post(url, json=payload, headers=headers, timeout=10)
        if res.status_code in (200, 201):
            print(f"Correo enviado exitosamente a {email}: {res.json()}")
            return True
        else:
            print(f"Error al enviar correo (Resend): {res.status_code} - {res.text}")
            return False
    except Exception as e:
        try:
            import urllib.request
            import json
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                res_body = response.read().decode("utf-8")
                print(f"Correo enviado exitosamente a {email} (urllib): {res_body}")
                return True
        except Exception as ex:
            print(f"Error al enviar correo: {e} | Fallback error: {ex}")
            return False


# ── Middleware ────────────────────────────────────────────────────────────────


@app.before_request
def auth_middleware():
    endpoint = request.endpoint

    if endpoint == "static":
        return

    if endpoint in GUEST_ENDPOINTS:
        if session.get("user_id") and not session.get("mfa_pending") and not session.get("mfa_setup_required"):
            return redirect(url_for("dashboard"))
        return

    if session.get("mfa_pending"):
        if endpoint in MFA_ENDPOINTS:
            return
        return redirect(url_for("mfa_verify"))

    if session.get("mfa_setup_required"):
        if endpoint in SETUP_ENDPOINTS or endpoint == "logout":
            return
        return redirect(url_for("mfa_setup"))

    if endpoint in PROTECTED_ENDPOINTS:
        user_id = session.get("user_id")
        if not user_id:
            return redirect(url_for("login"))

        user = db.session.get(User, user_id)
        if user is None:
            session.clear()
            return redirect(url_for("login"))

        g.current_user = user


# ── Public routes ─────────────────────────────────────────────────────────────


@app.route("/")
def index():
    return render_template("index.html")


# ── Auth routes ───────────────────────────────────────────────────────────────


@app.route("/login", methods=["GET", "POST"])
def login():
    errors = {}
    form = {"email": ""}

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        form["email"] = email

        if not is_valid_email(email):
            errors["email"] = "Ingresa un correo electronico valido"
        if not password.strip():
            errors["password"] = "La contrasena no puede estar vacia"

        if not errors:
            try:
                user = User.query.filter_by(email=email).first()
            except SQLAlchemyError:
                errors["email"] = "No se pudo consultar la base de datos"
            else:
                if user is None or not user.check_password(password):
                    errors["email"] = "Correo o contrasena incorrectos"
                    errors["password"] = "Correo o contrasena incorrectos"
                elif not user.activo:
                    errors["email"] = "Tu cuenta ha sido desactivada por el administrador"
                else:
                    session.clear()
                    if user.mfa_enabled:
                        session["mfa_pending"] = True
                        session["mfa_user_id"] = user.id
                        return redirect(url_for("mfa_verify"))
                    else:
                        session["user_id"] = user.id
                        session["user_name"] = user.fullname
                        return redirect(url_for("dashboard"))

    return render_template("login.html", errors=errors, form=form)


@app.route("/register", methods=["GET", "POST"])
def register():
    errors = {}
    form = {"fullname": "", "email": ""}

    if request.method == "POST":
        fullname = request.form.get("fullname", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        password_confirm = request.form.get("password_confirm", "")
        form.update({"fullname": fullname, "email": email})

        if not fullname:
            errors["fullname"] = "Ingresa tu nombre completo"
        if not is_valid_email(email):
            errors["email"] = "Ingresa un correo electronico valido"
        if len(password) < 8:
            errors["password"] = "La contrasena debe tener al menos 8 caracteres"
        if password_confirm != password or not password_confirm:
            errors["password_confirm"] = "Las contrasenas no coinciden"

        if not errors:
            user = User(fullname=fullname, email=email)
            user.set_password(password)
            db.session.add(user)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                errors["email"] = "Este correo ya esta registrado"
            except SQLAlchemyError:
                db.session.rollback()
                errors["email"] = "No se pudo guardar el usuario en la base de datos"
            else:
                session.clear()
                session["mfa_setup_required"] = True
                session["user_id"] = user.id
                session["user_name"] = user.fullname
                return redirect(url_for("mfa_setup"))

    return render_template("register.html", errors=errors, form=form)


@app.route("/login/pem", methods=["GET", "POST"])
def login_pem():
    errors = {}
    form = {"email": ""}

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        pem_file = request.files.get("pem_file")
        form["email"] = email

        if not is_valid_email(email):
            errors["email"] = "Ingresa un correo electronico valido"
        if not pem_file or not pem_file.filename:
            errors["pem_file"] = "Selecciona tu archivo .pem"

        if not errors:
            user = User.query.filter_by(email=email).first()
            if not user or not user.pem_fingerprint:
                errors["email"] = "Credenciales invalidas"
            elif not user.activo:
                errors["email"] = "Tu cuenta ha sido desactivada por el administrador"
            else:
                try:
                    pem_data = pem_file.read()
                    private_key = load_pem_private_key(pem_data, password=None)
                    public_key = private_key.public_key()
                    pub_der = public_key.public_bytes(
                        Encoding.DER, PublicFormat.SubjectPublicKeyInfo
                    )
                    fingerprint = hashlib.sha256(pub_der).hexdigest()

                    if fingerprint == user.pem_fingerprint:
                        session.clear()
                        session["user_id"] = user.id
                        session["user_name"] = user.fullname
                        return redirect(url_for("dashboard"))
                    else:
                        errors["pem_file"] = "La llave no corresponde a esta cuenta"
                except Exception:
                    errors["pem_file"] = "Archivo PEM invalido"

    return render_template("login_pem.html", errors=errors, form=form)


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    errors = {}
    success_message = None
    form = {"email": ""}

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        form["email"] = email

        if not is_valid_email(email):
            errors["email"] = "Ingresa un correo electronico valido"

        if not errors:
            user = User.query.filter_by(email=email).first()
            if user:
                token = secrets.token_urlsafe(32)
                user.reset_token = token
                user.reset_token_expiry = datetime.now() + timedelta(hours=1)
                db.session.commit()

                reset_link = f"{request.host_url[:-1]}{url_for('reset_password', token=token)}"
                send_reset_email(user.email, reset_link)

            # Para mayor seguridad, siempre mostramos mensaje de exito
            success_message = "Si el correo esta registrado, recibiras un enlace para restablecer tu contrasena en unos minutos."

    return render_template("forgot_password.html", errors=errors, form=form, success_message=success_message)


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    errors = {}
    success_message = None
    invalid_token = False

    user = User.query.filter(User.reset_token == token, User.reset_token_expiry > datetime.now()).first()
    if not user:
        invalid_token = True
    else:
        if request.method == "POST":
            password = request.form.get("password", "")
            password_confirm = request.form.get("password_confirm", "")

            if len(password) < 8:
                errors["password"] = "La contrasena debe tener al menos 8 caracteres"
            if password_confirm != password or not password_confirm:
                errors["password_confirm"] = "Las contrasenas no coinciden"

            if not errors:
                user.set_password(password)
                user.reset_token = None
                user.reset_token_expiry = None
                db.session.commit()
                success_message = "Tu contrasena ha sido restablecida con exito. Ya puedes iniciar sesion."

    return render_template(
        "reset_password.html",
        errors=errors,
        token=token,
        invalid_token=invalid_token,
        success_message=success_message
    )


# ── MFA verification routes ───────────────────────────────────────────────────


@app.route("/mfa/verify", methods=["GET", "POST"])
def mfa_verify():
    if not session.get("mfa_pending"):
        return redirect(url_for("login"))

    errors = {}
    if request.method == "POST":
        code = request.form.get("code", "").strip()
        user = db.session.get(User, session["mfa_user_id"])

        if not user:
            session.clear()
            return redirect(url_for("login"))

        totp = pyotp.TOTP(user.get_totp_secret())
        if totp.verify(code, valid_window=1):
            session.pop("mfa_pending", None)
            session.pop("mfa_user_id", None)
            session["user_id"] = user.id
            session["user_name"] = user.fullname
            return redirect(url_for("dashboard"))
        else:
            errors["code"] = "Codigo incorrecto. Intenta de nuevo."

    return render_template("mfa_verify.html", errors=errors)


@app.route("/mfa/backup", methods=["GET", "POST"])
def mfa_backup():
    if not session.get("mfa_pending"):
        return redirect(url_for("login"))

    errors = {}
    if request.method == "POST":
        code = request.form.get("backup_code", "").strip().upper()
        user = db.session.get(User, session["mfa_user_id"])

        if not user:
            session.clear()
            return redirect(url_for("login"))

        matched = False
        for bc in user.backup_codes.filter_by(used=False).all():
            if check_backup_code(code, bc.code_hash):
                bc.used = True
                db.session.commit()
                matched = True
                break

        if matched:
            session.pop("mfa_pending", None)
            session.pop("mfa_user_id", None)
            session["user_id"] = user.id
            session["user_name"] = user.fullname
            return redirect(url_for("dashboard"))
        else:
            errors["backup_code"] = "Codigo de respaldo invalido o ya utilizado."

    return render_template("mfa_backup.html", errors=errors)


# ── MFA setup routes ──────────────────────────────────────────────────────────


@app.route("/mfa/setup")
def mfa_setup():
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    user = db.session.get(User, user_id)
    if user.mfa_enabled:
        return redirect(url_for("dashboard"))

    if "temp_totp_secret" not in session:
        session["temp_totp_secret"] = pyotp.random_base32()

    secret = session["temp_totp_secret"]
    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(name=user.email, issuer_name=MFA_ISSUER_NAME)

    qr = qrcode.make(provisioning_uri)
    buffer = io.BytesIO()
    qr.save(buffer, format="PNG")
    qr_base64 = base64.b64encode(buffer.getvalue()).decode()

    error = request.args.get("error")
    errors = {}
    if error == "invalid_code":
        errors["code"] = "Codigo incorrecto. Verifica tu aplicacion."

    return render_template(
        "mfa_setup.html", qr_data=qr_base64, secret=secret, errors=errors
    )


@app.route("/mfa/setup/verify", methods=["POST"])
def mfa_setup_verify():
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    user = db.session.get(User, user_id)
    secret = session.get("temp_totp_secret")
    code = request.form.get("code", "").strip()

    if not secret:
        return redirect(url_for("mfa_setup"))

    totp = pyotp.TOTP(secret)
    if not totp.verify(code, valid_window=1):
        return redirect(url_for("mfa_setup", error="invalid_code"))

    user.set_totp_secret(secret)
    user.mfa_enabled = True

    backup_codes_plain = generate_backup_codes(10)
    for code_plain in backup_codes_plain:
        bc = BackupCode(user_id=user.id, code_hash=hash_backup_code(code_plain))
        db.session.add(bc)

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()

    pub_pem = public_key.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()
    pub_der = public_key.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    fingerprint = hashlib.sha256(pub_der).hexdigest()

    user.pem_public_key = encrypt_value(pub_pem)
    user.pem_fingerprint = fingerprint

    priv_pem = private_key.private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
    ).decode()

    db.session.commit()

    session.pop("temp_totp_secret", None)

    store_id = str(uuid.uuid4())
    _setup_store[store_id] = {
        "backup_codes": backup_codes_plain,
        "pem_private": priv_pem,
    }
    session["setup_store_id"] = store_id

    return redirect(url_for("mfa_setup_complete"))


@app.route("/mfa/setup/complete")
def mfa_setup_complete():
    store_id = session.get("setup_store_id")
    if not store_id or store_id not in _setup_store:
        return redirect(url_for("dashboard"))

    data = _setup_store[store_id]
    return render_template(
        "mfa_setup_complete.html",
        backup_codes=data["backup_codes"],
        pem_data=data["pem_private"],
    )


@app.route("/mfa/setup/download-pem")
def mfa_download_pem():
    store_id = session.get("setup_store_id")
    if not store_id or store_id not in _setup_store:
        return redirect(url_for("dashboard"))

    pem_data = _setup_store[store_id]["pem_private"]
    return Response(
        pem_data,
        mimetype="application/x-pem-file",
        headers={"Content-Disposition": "attachment; filename=agrocitrico_key.pem"},
    )


@app.route("/mfa/setup/finish", methods=["POST"])
def mfa_setup_finish():
    store_id = session.pop("setup_store_id", None)
    if store_id and store_id in _setup_store:
        del _setup_store[store_id]

    session.pop("mfa_setup_required", None)
    return redirect(url_for("dashboard"))


# ── Protected routes ──────────────────────────────────────────────────────────


@app.route("/dashboard")
def dashboard():
    user = g.current_user
    hoy = date.today()
    manana = hoy + timedelta(days=1)

    # Actividades de hoy y mañana
    alertas_hoy = Actividad.query.filter_by(user_id=user.id).filter(
        Actividad.proxima_fecha == hoy
    ).order_by(Actividad.tipo).all()

    alertas_manana = Actividad.query.filter_by(user_id=user.id).filter(
        Actividad.proxima_fecha == manana
    ).order_by(Actividad.tipo).all()

    alertas_proximas = Actividad.query.filter_by(user_id=user.id).filter(
        Actividad.proxima_fecha > manana,
        Actividad.proxima_fecha <= hoy + timedelta(days=7)
    ).order_by(Actividad.proxima_fecha).all()

    # Stats reales
    total_actividades = Actividad.query.filter_by(user_id=user.id).count()
    total_cosechas = Cosecha.query.filter_by(user_id=user.id).count()
    ultima_cosecha = Cosecha.query.filter_by(user_id=user.id).order_by(Cosecha.fecha.desc()).first()
    total_alertas = len(alertas_hoy) + len(alertas_manana)

    # Cosecha de la semana actual (de lunes a hoy)
    lunes_semana = hoy - timedelta(days=hoy.weekday())
    cosechas_semana = Cosecha.query.filter(
        Cosecha.user_id == user.id,
        Cosecha.fecha >= lunes_semana,
        Cosecha.fecha <= hoy
    ).all()
    cosecha_semana_kg = sum(float(c.cantidad_kg) for c in cosechas_semana)
    meta_semanal = float(user.meta_semanal)
    porcentaje_cosecha = int((cosecha_semana_kg / meta_semanal) * 100) if meta_semanal > 0 else 0

    disp_ids = [d.id for d in Dispositivo.query.filter_by(user_id=user.id).all()]
    if disp_ids:
        ultima_lectura = LecturaSensor.query.filter(
            LecturaSensor.dispositivo_id.in_(disp_ids)
        ).order_by(LecturaSensor.created_at.desc()).first()
    else:
        ultima_lectura = None

    if ultima_lectura:
        temp = ultima_lectura.temperatura
        hum_aire = ultima_lectura.humedad_aire
        hum_suelo = ultima_lectura.humedad_suelo
        sensors = [
            {
                "name": "Temperatura",
                "value": f"{temp:.1f} °C" if temp is not None else "Sin dato",
                "trend": "Alta" if temp and temp > 35 else "Rango adecuado" if temp and temp >= 20 else "Baja" if temp is not None else "",
            },
            {
                "name": "Humedad ambiental",
                "value": f"{hum_aire:.0f}%" if hum_aire is not None else "Sin dato",
                "trend": "Alta" if hum_aire and hum_aire > 80 else "Normal" if hum_aire and hum_aire >= 40 else "Baja" if hum_aire is not None else "",
            },
            {
                "name": "Humedad del suelo",
                "value": f"{hum_suelo:.0f}%" if hum_suelo is not None else "Sin dato",
                "trend": "Riego urgente" if hum_suelo is not None and hum_suelo < 30 else "Sin riego urgente" if hum_suelo is not None else "",
            },
        ]
    else:
        sensors = [
            {"name": "Temperatura",       "value": "Sin dato", "trend": "Esperando sensor"},
            {"name": "Humedad ambiental", "value": "Sin dato", "trend": "Esperando sensor"},
            {"name": "Humedad del suelo", "value": "Sin dato", "trend": "Esperando sensor"},
        ]

    return render_template(
        "dashboard.html",
        user=user,
        hoy=hoy,
        manana=manana,
        alertas_hoy=alertas_hoy,
        alertas_manana=alertas_manana,
        alertas_proximas=alertas_proximas,
        total_actividades=total_actividades,
        total_cosechas=total_cosechas,
        ultima_cosecha=ultima_cosecha,
        total_alertas=total_alertas,
        sensors=sensors,
        cosecha_semana_kg=cosecha_semana_kg,
        meta_semanal=meta_semanal,
        porcentaje_cosecha=porcentaje_cosecha,
    )


@app.post("/dashboard/actualizar-meta")
def actualizar_meta():
    user = g.current_user
    meta_str = request.form.get("meta_semanal", "").strip()
    try:
        nueva_meta = float(meta_str)
        if nueva_meta <= 0:
            raise ValueError
        user.meta_semanal = nueva_meta
        db.session.commit()
    except ValueError:
        pass
    return redirect(url_for("dashboard"))


# ── Actividades ───────────────────────────────────────────────────────────────

@app.route("/actividades")
def actividades():
    from datetime import date, timedelta
    user = g.current_user
    hoy = date.today()
    lista = Actividad.query.filter_by(user_id=user.id).order_by(Actividad.proxima_fecha).all()
    return render_template("actividades.html", user=user, actividades=lista, hoy=hoy, tipos=TIPOS_ACTIVIDAD)


@app.route("/actividades/nueva", methods=["GET", "POST"])
def actividad_nueva():
    from datetime import date, timedelta
    user = g.current_user
    error = None

    if request.method == "POST":
        tipo = request.form.get("tipo", "").strip()
        fecha_str = request.form.get("fecha_realizada", "").strip()
        intervalo_str = request.form.get("intervalo_dias", "1").strip()
        notas = request.form.get("notas", "").strip()

        if not tipo or tipo not in TIPOS_ACTIVIDAD:
            error = "Selecciona un tipo de actividad válido."
        elif not fecha_str:
            error = "La fecha realizada es obligatoria."
        else:
            try:
                fecha = date.fromisoformat(fecha_str)
                intervalo = int(intervalo_str)
                if intervalo < 1:
                    raise ValueError
                proxima = fecha + timedelta(days=intervalo)
                act = Actividad(
                    user_id=user.id,
                    tipo=tipo,
                    fecha_realizada=fecha,
                    intervalo_dias=intervalo,
                    proxima_fecha=proxima,
                    notas=notas or None,
                )
                db.session.add(act)
                db.session.commit()
                return redirect(url_for("actividades"))
            except ValueError:
                error = "Fecha o intervalo inválido. El intervalo debe ser un número mayor a 0."

    return render_template("actividad_form.html", user=user, error=error, tipos=TIPOS_ACTIVIDAD, hoy=date.today().isoformat())


@app.route("/actividades/<int:act_id>/eliminar", methods=["POST"])
def actividad_eliminar(act_id):
    user = g.current_user
    act = Actividad.query.filter_by(id=act_id, user_id=user.id).first_or_404()
    db.session.delete(act)
    db.session.commit()
    return redirect(url_for("actividades"))


# ── Cosechas ──────────────────────────────────────────────────────────────────

@app.route("/cosechas")
def cosechas():
    from datetime import date
    user = g.current_user
    lista = Cosecha.query.filter_by(user_id=user.id).order_by(Cosecha.fecha.desc()).all()
    total_kg = sum(float(c.cantidad_kg) for c in lista)
    return render_template("cosechas.html", user=user, cosechas=lista, total_kg=total_kg, hoy=date.today())


@app.route("/cosechas/nueva", methods=["GET", "POST"])
def cosecha_nueva():
    from datetime import date
    user = g.current_user
    error = None

    if request.method == "POST":
        fecha_str = request.form.get("fecha", "").strip()
        cantidad_str = request.form.get("cantidad_kg", "").strip()
        notas = request.form.get("notas", "").strip()

        if not fecha_str:
            error = "La fecha de cosecha es obligatoria."
        elif not cantidad_str:
            error = "La cantidad recolectada es obligatoria."
        else:
            try:
                fecha = date.fromisoformat(fecha_str)
                cantidad = float(cantidad_str)
                if cantidad <= 0:
                    raise ValueError
                cos = Cosecha(
                    user_id=user.id,
                    fecha=fecha,
                    cantidad_kg=cantidad,
                    notas=notas or None,
                )
                db.session.add(cos)
                db.session.commit()
                return redirect(url_for("cosechas"))
            except ValueError:
                error = "Cantidad inválida. Debe ser un número mayor a 0."

    return render_template("cosecha_form.html", user=user, error=error, hoy=date.today().isoformat())


@app.route("/cosechas/<int:cos_id>/eliminar", methods=["POST"])
def cosecha_eliminar(cos_id):
    user = g.current_user
    cos = Cosecha.query.filter_by(id=cos_id, user_id=user.id).first_or_404()
    db.session.delete(cos)
    db.session.commit()
    return redirect(url_for("cosechas"))


# ── Dispositivos IoT ─────────────────────────────────────────────────────────


@app.route("/dispositivos")
def dispositivos():
    user = g.current_user
    lista = Dispositivo.query.filter_by(user_id=user.id).order_by(Dispositivo.created_at.desc()).all()
    return render_template("dispositivos.html", user=user, dispositivos=lista)


@app.route("/dispositivos/registrar", methods=["POST"])
def dispositivo_registrar():
    user = g.current_user
    nombre = request.form.get("nombre", "").strip()

    if not nombre:
        return redirect(url_for("dispositivos"))

    token = secrets.token_hex(32)
    disp = Dispositivo(user_id=user.id, nombre=nombre, token=token)
    db.session.add(disp)
    db.session.commit()

    return redirect(url_for("dispositivos"))


@app.route("/dispositivos/<int:disp_id>/eliminar", methods=["POST"])
def dispositivo_eliminar(disp_id):
    user = g.current_user
    disp = Dispositivo.query.filter_by(id=disp_id, user_id=user.id).first_or_404()
    LecturaSensor.query.filter_by(dispositivo_id=disp.id).delete()
    db.session.delete(disp)
    db.session.commit()
    return redirect(url_for("dispositivos"))


@app.route("/dispositivos/<int:disp_id>/toggle", methods=["POST"])
def dispositivo_toggle(disp_id):
    user = g.current_user
    disp = Dispositivo.query.filter_by(id=disp_id, user_id=user.id).first_or_404()
    disp.activo = not disp.activo
    db.session.commit()
    return redirect(url_for("dispositivos"))


# ── API Sensores IoT ─────────────────────────────────────────────────────────


@app.post("/api/sensores")
def api_sensores():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return jsonify({"error": "No autorizado"}), 401

    token = auth[7:]
    disp = Dispositivo.query.filter_by(token=token, activo=True).first()
    if not disp:
        return jsonify({"error": "Token inválido o dispositivo inactivo"}), 401

    data = request.get_json(silent=True) or {}
    temperatura = data.get("temperatura")
    humedad_aire = data.get("humedad_aire")
    humedad_suelo = data.get("humedad_suelo")

    if temperatura is None and humedad_aire is None and humedad_suelo is None:
        return jsonify({"error": "No se recibieron datos"}), 400

    lectura = LecturaSensor(
        dispositivo_id=disp.id,
        temperatura=temperatura,
        humedad_aire=humedad_aire,
        humedad_suelo=humedad_suelo,
    )
    db.session.add(lectura)
    db.session.commit()

    return jsonify({"ok": True, "id": lectura.id}), 201


@app.get("/api/sensores/ultimo")
def api_sensores_ultimo():
    if not session.get("user_id"):
        return jsonify({"error": "No autorizado"}), 401

    user_id = session["user_id"]
    disp_ids = [d.id for d in Dispositivo.query.filter_by(user_id=user_id).all()]

    if not disp_ids:
        return jsonify({
            "temperatura": None,
            "humedad_aire": None,
            "humedad_suelo": None,
            "trends": {
                "temperatura": "Sin dispositivos",
                "humedad_aire": "Sin dispositivos",
                "humedad_suelo": "Sin dispositivos"
            }
        })

    lectura = LecturaSensor.query.filter(
        LecturaSensor.dispositivo_id.in_(disp_ids)
    ).order_by(LecturaSensor.created_at.desc()).first()

    if not lectura:
        return jsonify({
            "temperatura": None,
            "humedad_aire": None,
            "humedad_suelo": None,
            "trends": {
                "temperatura": "Esperando sensor",
                "humedad_aire": "Esperando sensor",
                "humedad_suelo": "Esperando sensor"
            }
        })

    temp = lectura.temperatura
    hum_aire = lectura.humedad_aire
    hum_suelo = lectura.humedad_suelo

    trend_temp = "Alta" if temp and temp > 35 else "Rango adecuado" if temp and temp >= 20 else "Baja" if temp is not None else ""
    trend_hum_aire = "Alta" if hum_aire and hum_aire > 80 else "Normal" if hum_aire and hum_aire >= 40 else "Baja" if hum_aire is not None else ""
    trend_hum_suelo = "Riego urgente" if hum_suelo is not None and hum_suelo < 30 else "Sin riego urgente" if hum_suelo is not None else ""

    return jsonify({
        "temperatura": temp,
        "humedad_aire": hum_aire,
        "humedad_suelo": hum_suelo,
        "trends": {
            "temperatura": trend_temp,
            "humedad_aire": trend_hum_aire,
            "humedad_suelo": trend_hum_suelo
        }
    })


@app.route("/admin")
def admin_dashboard():
    if not g.current_user.is_admin:
        return redirect(url_for("dashboard"))

    users = User.query.order_by(User.created_at.desc()).all()
    devices = Dispositivo.query.order_by(Dispositivo.created_at.desc()).all()
    activities = Actividad.query.order_by(Actividad.created_at.desc()).all()
    harvests = Cosecha.query.order_by(Cosecha.created_at.desc()).all()

    total_users_count = len(users)
    total_devices_count = len(devices)
    total_activities_count = len(activities)
    total_harvests_count = len(harvests)

    return render_template(
        "admin_dashboard.html",
        user=g.current_user,
        users=users,
        devices=devices,
        activities=activities[:10],  # show top 10 recent
        harvests=harvests[:10],      # show top 10 recent
        total_users_count=total_users_count,
        total_devices_count=total_devices_count,
        total_activities_count=total_activities_count,
        total_harvests_count=total_harvests_count
    )


@app.post("/admin/usuarios/<int:target_user_id>/toggle")
def admin_user_toggle(target_user_id):
    if not g.current_user.is_admin:
        return redirect(url_for("dashboard"))

    if target_user_id == g.current_user.id:
        return redirect(url_for("admin_dashboard"))

    user = User.query.filter_by(id=target_user_id).first_or_404()
    user.activo = not user.activo
    db.session.commit()
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/usuarios/<int:target_user_id>/role")
def admin_user_role(target_user_id):
    if not g.current_user.is_admin:
        return redirect(url_for("dashboard"))

    if target_user_id == g.current_user.id:
        return redirect(url_for("admin_dashboard"))

    user = User.query.filter_by(id=target_user_id).first_or_404()
    new_role = request.form.get("role", "user").strip().lower()
    if new_role in ("admin", "user"):
        user.role = new_role
        db.session.commit()
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/usuarios/<int:target_user_id>/mfa-reset")
def admin_mfa_reset(target_user_id):
    if not g.current_user.is_admin:
        return redirect(url_for("dashboard"))

    user = User.query.filter_by(id=target_user_id).first_or_404()
    user.mfa_enabled = False
    user.totp_secret = None
    user.pem_fingerprint = None
    user.pem_public_key = None
    BackupCode.query.filter_by(user_id=user.id).delete()
    db.session.commit()
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/dispositivos/<int:disp_id>/toggle")
def admin_device_toggle(disp_id):
    if not g.current_user.is_admin:
        return redirect(url_for("dashboard"))

    disp = Dispositivo.query.filter_by(id=disp_id).first_or_404()
    disp.activo = not disp.activo
    db.session.commit()
    return redirect(url_for("admin_dashboard"))


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/ia")
def ia():
    return render_template("ia.html")


@app.post("/ia/chat")
def ia_chat():
    data = request.get_json(silent=True) or {}
    prompt = data.get("message", "").strip()

    if not prompt:
        return jsonify({"error": "El mensaje no puede estar vacio."}), 400

    try:
        with _model_lock:
            model = get_model()
            with model.chat_session():
                reply = model.generate(prompt, max_tokens=1024)
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 503
    except Exception as exc:
        return jsonify({"error": f"No se pudo generar la respuesta: {exc}"}), 500

    return jsonify({"reply": reply})


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")
