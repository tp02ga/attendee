from django.urls import path
from . import bots_api_views

urlpatterns = [
    path('', bots_api_views.BotCreateView.as_view(), name='bot-create'),
    path('/<str:object_id>', bots_api_views.BotDetailView.as_view(), name='bot-detail'),
    path('/<str:object_id>/leave', bots_api_views.BotLeaveView.as_view(), name='bot-leave'),
    path('/<str:object_id>/transcript', bots_api_views.TranscriptView.as_view(), name='bot-transcript'),
]

# catch any other paths and return a 404 json response - must be last
urlpatterns += [path('<path:any>', bots_api_views.NotFoundView.as_view())]
