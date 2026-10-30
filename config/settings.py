"""Felicia settings. All environment-specific values come from environment variables."""

import os
from pathlib import Path

from csp.constants import NONE, SELF
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name, default=None, required=False):
    value = os.environ.get(name, default)
    if required and not value:
        raise ImproperlyConfigured(f"Umgebungsvariable {name} fehlt.")
    return value


def env_bool(name, default=False):
    return str(env(name, str(default))).lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [v.strip() for v in env(name, default).split(",") if v.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)
SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-insecure-key" if DEBUG else None, required=True)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1" if DEBUG else "")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

# Keys for encrypted fields (IBAN etc.). Comma-separated; first key encrypts, all decrypt (rotation).
FIELD_ENCRYPTION_KEYS = env_list("FIELD_ENCRYPTION_KEYS")
if not FIELD_ENCRYPTION_KEYS:
    if DEBUG:
        FIELD_ENCRYPTION_KEYS = ["2LdNzt9Ks_9Y8hBzjbN8wl8W0r3uQTOZ8gbAgbYQqH0="]
    else:
        raise ImproperlyConfigured("Umgebungsvariable FIELD_ENCRYPTION_KEYS fehlt.")

DEFAULT_TENANT_SLUG = env("DEFAULT_TENANT_SLUG", "feldzutisch")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "django.contrib.postgres",
    "allauth",
    "allauth.account",
    "allauth.mfa",
    "allauth.usersessions",
    "csp",
    # Felicia modules
    "apps.core",
    "apps.accounts",
    "apps.audit",
    "apps.orgs",
    "apps.operator",
    "apps.suppliers",
    "apps.customers",
    "apps.catalog",
    "apps.shop",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "csp.middleware.CSPMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "allauth.usersessions.middleware.UserSessionsMiddleware",
    "apps.core.middleware.TenantMiddleware",
    "apps.orgs.middleware.OrganizationMiddleware",
    "apps.accounts.middleware.EnforceMfaMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.orgs.context_processors.organization",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "felicia"),
        "USER": env("POSTGRES_USER", "felicia"),
        "PASSWORD": env("POSTGRES_PASSWORD", "felicia" if DEBUG else None, required=not DEBUG),
        "HOST": env("POSTGRES_HOST", "localhost"),
        "PORT": env("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {"sslmode": env("POSTGRES_SSLMODE", "prefer")},
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    {"NAME": "apps.accounts.validators.PwnedPasswordValidator"},
]
PWNED_PASSWORDS_CHECK = env_bool("PWNED_PASSWORDS_CHECK", True)

# --- allauth -------------------------------------------------------------
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = True
ACCOUNT_CONFIRM_EMAIL_ON_GET = False
ACCOUNT_SESSION_REMEMBER = None
ACCOUNT_LOGOUT_ON_PASSWORD_CHANGE = False
ACCOUNT_PREVENT_ENUMERATION = True
ACCOUNT_ADAPTER = "apps.accounts.adapters.AccountAdapter"
ACCOUNT_FORMS = {"signup": "apps.accounts.forms.SignupForm"}
ACCOUNT_EMAIL_SUBJECT_PREFIX = ""
ACCOUNT_RATE_LIMITS = {
    "login_failed": "10/m/ip,5/5m/key",
    "signup": "20/m/ip",
    "reset_password": "20/m/ip,5/m/key",
    "confirm_email": "1/3m/key",
}
MFA_SUPPORTED_TYPES = ["totp", "webauthn", "recovery_codes"]
MFA_PASSKEY_LOGIN_ENABLED = True
MFA_WEBAUTHN_ALLOW_INSECURE_ORIGIN = DEBUG
MFA_TOTP_ISSUER = env("MFA_TOTP_ISSUER", "Felicia")
USERSESSIONS_TRACK_ACTIVITY = True
LOGIN_REDIRECT_URL = "/"
LOGIN_URL = "account_login"

# --- Sessions & cookies --------------------------------------------------
SESSION_COOKIE_AGE = 60 * 60 * 12
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

# --- Transport & headers -------------------------------------------------
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", not DEBUG)
SECURE_HSTS_SECONDS = 0 if DEBUG else 63072000
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SECURE_REDIRECT_EXEMPT = [r"^healthz$"]

CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": [SELF],
        "script-src": [SELF],
        "style-src": [SELF],
        "img-src": [SELF, "data:"],
        "font-src": [SELF],
        "connect-src": [SELF],
        "form-action": [SELF],
        "frame-ancestors": [NONE],
        "base-uri": [SELF],
        "object-src": [NONE],
    }
}

# --- I18N ----------------------------------------------------------------
LANGUAGE_CODE = "de-ch"
LANGUAGES = [("de-ch", "Deutsch")]
TIME_ZONE = "Europe/Zurich"
FORMAT_MODULE_PATH = ["config.formats"]
USE_I18N = True
USE_TZ = True

# --- Static & media ------------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(env("DJANGO_MEDIA_ROOT", str(BASE_DIR / "media")))
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        if DEBUG
        else "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

# --- E-Mail --------------------------------------------------------------
EMAIL_BACKEND = env("DJANGO_EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", "localhost")
EMAIL_PORT = int(env("EMAIL_PORT", "587"))
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "Felicia <noreply@localhost>")

# --- Logging -------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}

INVITATION_VALID_DAYS = 7
FORMS_URLFIELD_ASSUME_HTTPS = True
