# Register your models here.

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html

from .models import Organization, User


class UserInline(admin.TabularInline):
    model = User
    extra = 0
    fields = ('email', 'first_name', 'last_name', 'is_active', 'is_staff')
    readonly_fields = ('email', 'first_name', 'last_name', 'is_active', 'is_staff')
    can_delete = False
    

@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ('name', 'display_credits', 'is_webhooks_enabled', 'created_at', 'updated_at')
    list_filter = ('is_webhooks_enabled',)
    search_fields = ('name',)
    readonly_fields = ('name', 'centicredits', 'is_webhooks_enabled', 'created_at', 'updated_at', 'version')
    inlines = [UserInline]
    
    def display_credits(self, obj):
        return f"{obj.credits():.2f}"
    display_credits.short_description = "Credits"
    
    fieldsets = (
        ("Organization Information", {"fields": ("name", "centicredits", "is_webhooks_enabled")}),
        ("Metadata", {"fields": ("created_at", "updated_at", "version")}),
    )
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return True  # Allow viewing but fields will be read-only
    
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('email', 'first_name', 'last_name', 'organization', 'is_staff')
    list_filter = ('is_staff', 'is_superuser', 'is_active', 'organization')
    search_fields = ('email', 'first_name', 'last_name')
    ordering = ('email',)
    readonly_fields = ('email', 'first_name', 'last_name', 'is_active', 
                      'is_staff', 'is_superuser', 'groups', 'user_permissions', 
                      'organization', 'last_login', 'date_joined')
    
    fieldsets = (
        (None, {'fields': ('email',)}),
        ('Personal info', {'fields': ('first_name', 'last_name')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Organization', {'fields': ('organization',)}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    
    # Since all fields are read-only, we don't need add_fieldsets
    add_fieldsets = None
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return True  # Allow viewing but fields will be read-only
    
    def has_delete_permission(self, request, obj=None):
        return False
