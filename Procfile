web: bash -c '/opt/bin/entrypoint.sh && python manage.py migrate && python manage.py collectstatic --noinput && gunicorn attendee.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 4 --timeout 120'
worker: bash -c '/opt/bin/entrypoint.sh && celery -A attendee worker -l INFO'
scheduler: bash -c '/opt/bin/entrypoint.sh && python manage.py run_scheduler'