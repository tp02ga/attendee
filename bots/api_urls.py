from django.urls import path
from . import api_views

urlpatterns = [
    path('sessions', api_views.SessionCreateView.as_view(), name='session-create'),
    path('sessions/<str:object_id>', api_views.SessionDetailView.as_view(), name='session-detail'),
    path('sessions/<str:object_id>/leave', api_views.LeaveCallView.as_view(), name='session-leave'),
    path('sessions/<str:object_id>/transcript', api_views.TranscriptView.as_view(), name='session-transcript'),
    # catch any other paths and return a 404 json response
    path('<path:any>', api_views.NotFoundView.as_view()),
]
