from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import Event, GoogleCalendarToken

@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ['title', 'user', 'start_time', 'end_time', 'location']
    list_filter = ['user', 'start_time', 'created_at']
    search_fields = ['title', 'description', 'location']
    readonly_fields = ['google_event_id', 'created_at', 'updated_at']
    
    fieldsets = (
        (None, {
            'fields': ('user', 'title', 'description')
        }),
        ('Schedule', {
            'fields': ('start_time', 'end_time', 'location')
        }),
        ('Google Calendar', {
            'fields': ('google_event_id',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

@admin.register(GoogleCalendarToken)
class GoogleCalendarTokenAdmin(admin.ModelAdmin):
    list_display = ['user', 'token_expires_at', 'created_at']
    readonly_fields = ['access_token', 'refresh_token', 'created_at', 'updated_at']
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if not request.user.is_superuser:
            qs = qs.filter(user=request.user)
        return qs
