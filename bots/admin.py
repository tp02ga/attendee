import os
from django.contrib import admin
from django.utils.html import format_html
from django.db.models import Count, Case, When, IntegerField, F, Value, FloatField
from django.db.models.functions import Cast
from django.contrib.admin.views.main import ChangeList
from django.db.models.expressions import Window
from django.db.models.functions import RowNumber

from .models import Bot, BotEvent, Utterance, WebhookDeliveryAttempt, WebhookSubscription


# Create an inline for BotEvent to show on the Bot admin page
class BotEventInline(admin.TabularInline):
    model = BotEvent
    extra = 0
    readonly_fields = ("created_at", "event_type", "event_sub_type", "old_state", "new_state", "metadata")
    can_delete = False
    max_num = 0  # Don't allow adding new events through admin
    ordering = ("created_at",)  # Show most recent events first

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Bot)
class BotAdmin(admin.ModelAdmin):
    actions = None
    list_display = ("object_id", "name", "project", "state", "created_at", "updated_at", "view_logs_link")
    list_filter = ("state", "project")
    search_fields = ("object_id",)
    readonly_fields = ("object_id", "created_at", "updated_at", "state", "view_logs_link")
    inlines = [BotEventInline]  # Add the inline to the admin

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return True

    def view_logs_link(self, obj):
        pod_name = obj.k8s_pod_name()
        link_formatting_str = os.getenv("CLOUD_LOGS_LINK_FORMATTING_STR")
        if not link_formatting_str:
            return None
        try:
            url = link_formatting_str.format(pod_name=pod_name)
            return format_html('<a href="{}" target="_blank">View Logs</a>', url)
        except Exception:
            return None

    view_logs_link.short_description = "Cloud Logs"

    # Optional: if you want to organize the fields in the detail view
    fieldsets = (
        ("Basic Information", {"fields": ("object_id", "name", "project")}),
        ("Meeting Details", {"fields": ("meeting_url", "meeting_uuid")}),
        ("Status", {"fields": ("state", "view_logs_link")}),
        ("Settings", {"fields": ("settings",)}),
        ("Metadata", {"fields": ("created_at", "updated_at", "version")}),
    )


@admin.register(WebhookDeliveryAttempt)
class WebhookDeliveryAttemptAdmin(admin.ModelAdmin):
    list_display = ('webhook_subscription', 'webhook_trigger_type', 'status', 'attempt_count', 'created_at', 'last_attempt_at', 'succeeded_at')
    list_filter = ('status', 'webhook_trigger_type', 'webhook_subscription')
    search_fields = ('webhook_subscription__url', 'idempotency_key')
    readonly_fields = ('idempotency_key', 'payload', 'response_body_list')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return True

    def changelist_view(self, request, extra_context=None):
        # Get statistics
        stats = WebhookDeliveryAttempt.objects.aggregate(
            total=Count('id'),
            success=Count(Case(When(status=2, then=1))),  # 2 is SUCCESS
            failure=Count(Case(When(status=3, then=1))),  # 3 is FAILURE
            pending=Count(Case(When(status=1, then=1))),  # 1 is PENDING
        )
        
        total = stats['total'] or 0
        success = stats['success'] or 0
        failure = stats['failure'] or 0
        pending = stats['pending'] or 0
        
        # Calculate percentages
        success_pct = round((success / total) * 100, 2) if total > 0 else 0
        failure_pct = round((failure / total) * 100, 2) if total > 0 else 0
        pending_pct = round((pending / total) * 100, 2) if total > 0 else 0
        
        if not extra_context:
            extra_context = {}
            
        extra_context.update({
            'webhook_stats': {
                'total': total,
                'success': success,
                'failure': failure,
                'pending': pending,
                'success_pct': success_pct,
                'failure_pct': failure_pct,
                'pending_pct': pending_pct,
            }
        })
        
        return super().changelist_view(request, extra_context=extra_context)


@admin.register(WebhookSubscription)
class WebhookSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('url', 'project', 'is_active', 'created_at')
    list_filter = ('is_active', 'project')
    search_fields = ('url', 'project__name')
    readonly_fields = ('object_id',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return True