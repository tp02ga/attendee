web: /opt/bin/entrypoint.sh bash -c 'python manage.py migrate && python manage.py collectstatic --noinput && gunicorn attendee.wsgi:application --bind 0.0.0.0:$PORT --workers 4 --timeout 120'
worker: /opt/bin/entrypoint.sh celery -A attendee worker -l INFO
scheduler: /opt/bin/entrypoint.sh python manage.py run_scheduler