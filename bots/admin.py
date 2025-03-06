from django.contrib import admin
from .models import Bot

@admin.register(Bot)
class BotAdmin(admin.ModelAdmin):
    actions = None
    list_display = ('object_id', 'name', 'project', 'state', 'created_at', 'updated_at')
    list_filter = ('state', 'project')
    search_fields = ('object_id',)
    readonly_fields = ('object_id', 'created_at', 'updated_at', 'state')
    
    def has_add_permission(self, request):
        return False
        
    def has_change_permission(self, request, obj=None):
        return False
        
    def has_delete_permission(self, request, obj=None):
        return True
    
    # Optional: if you want to organize the fields in the detail view
    fieldsets = (
        ('Basic Information', {
            'fields': ('object_id', 'name', 'project')
        }),
        ('Meeting Details', {
            'fields': ('meeting_url', 'meeting_uuid')
        }),
        ('Status', {
            'fields': ('state',)
        }),
        ('Settings', {
            'fields': ('settings',)
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at', 'version')
        }),
    )
