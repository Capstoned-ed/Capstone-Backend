#!/usr/bin/env bash
# Exit immediately if a command exits with a non-zero status
set -o errexit

echo "==> Installing Python dependencies..."
pip install -r requirements.txt

echo "==> Collecting static files..."
python manage.py collectstatic --no-input

echo "==> Applying database migrations..."
python manage.py migrate --no-input

echo "==> Seeding default admin account..."
python manage.py seed_admin

echo "==> Build complete!"

