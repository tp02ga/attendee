from django.urls import path

from . import calendars_api_views

urlpatterns = [
    path("calendars", calendars_api_views.CalendarCreateView.as_view(), name="calendar-create"),
]
