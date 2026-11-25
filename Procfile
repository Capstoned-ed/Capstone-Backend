web: gunicorn _core.wsgi:application --workers 3 --threads 2 --worker-class gthread --worker-tmp-dir /dev/shm --bind 0.0.0.0:$PORT

