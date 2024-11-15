from django.urls import path
from . import views

app_name = 'bots'

urlpatterns = [
    path('<str:object_id>', views.BotDashboardView.as_view(), name='bot-dashboard'),
    path('<str:object_id>/settings', views.BotSettingsView.as_view(), name='bot-settings'),
    path('<str:object_id>/logs', views.BotLogsView.as_view(), name='bot-logs'),
    path('<str:object_id>/keys', views.BotApiKeysView.as_view(), name='bot-api-keys'),
    path('<str:object_id>/keys/create/', views.CreateApiKeyView.as_view(), name='create-api-key'),
    path('<str:object_id>/keys/<str:key_object_id>/delete/', views.DeleteApiKeyView.as_view(), name='delete-api-key'),
    path('<str:object_id>/settings/credentials/', views.CreateBotCredentialsView.as_view(), name='create-bot-credentials'),
    # Don't put anything after this, it will redirect to the dashboard
    path('<str:object_id>/', views.RedirectToDashboardView.as_view(), name='bot-unrecognized'),
    path('<str:object_id>/<path:extra>', views.RedirectToDashboardView.as_view(), name='bot-unrecognized'),
]