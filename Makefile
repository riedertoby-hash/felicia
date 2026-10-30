# Local development. Needs a running PostgreSQL (user/db/password: felicia).
export DJANGO_DEBUG ?= 1
export PWNED_PASSWORDS_CHECK ?= 0

install:
	python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt

setup:
	.venv/bin/python manage.py migrate
	.venv/bin/python manage.py setup_marketplace --admin-email admin@example.ch --admin-password 'Tomaten-Feld-2026!'
	.venv/bin/python manage.py seed_demo

jobs:
	.venv/bin/python manage.py run_billing
	.venv/bin/python manage.py send_order_digests

run:
	.venv/bin/python manage.py runserver

test:
	.venv/bin/pytest

lint:
	.venv/bin/ruff check . && .venv/bin/ruff format --check .
