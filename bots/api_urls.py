from django.urls import path
from . import api_views
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

urlpatterns = [
    path('sessions', api_views.SessionCreateView.as_view(), name='session-create'),
    path('sessions/<str:object_id>', api_views.SessionDetailView.as_view(), name='session-detail'),
    path('sessions/<str:object_id>/end', api_views.EndSessionView.as_view(), name='session-end'),
    path('sessions/<str:object_id>/transcript', api_views.TranscriptView.as_view(), name='session-transcript'),
    # API docs routes
    path('schema/', SpectacularAPIView.as_view(), name='schema'),
    path('schema/swagger-ui/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('schema/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
    # catch any other paths and return a 404 json response
    path('<path:any>', api_views.NotFoundView.as_view()),
]
