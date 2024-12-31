from .base import *

DEBUG = False
ALLOWED_HOSTS = []

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'attendee_test',
        'USER': 'attendee_development_user',
        'PASSWORD': 'attendee_development_user',
        'HOST': os.getenv('POSTGRES_HOST', 'localhost'),
        'PORT': '5432',
    }
}