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
if [ "$CLEAN_SEED" = "true" ]; then
  python manage.py seed_admin --clean
else
  python manage.py seed_admin
fi

echo "==> Build complete!"

