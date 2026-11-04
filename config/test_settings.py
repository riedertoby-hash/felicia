import os

os.environ.setdefault("DJANGO_DEBUG", "1")
os.environ.setdefault("PWNED_PASSWORDS_CHECK", "0")

from .settings import *  # noqa: E402, F403
