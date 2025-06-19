from django.urls import path
from . import views

app_name = 'calendar'

urlpatterns = [
    path('', views.calendar_view, name='calendar_view'),
    path('api/week-data/', views.week_data, name='api_week_data'),

    path('auth/google/', views.google_auth, name='google_auth'),
    path('oauth/callback/', views.google_oauth_callback, name='oauth_callback'),
    
    path('create-event/', views.create_event, name='create_event'), # For Google Calendar events
    path('sync-gcal-events/', views.sync_events, name='sync_gcal_events'), # Renamed for clarity

    path('task/create/', views.create_task, name='create_task'),
    # path('task/<int:task_id>/', views.task_detail, name='task_detail'), # Not currently used by modal
    path('task/<int:task_id>/edit/', views.edit_task, name='edit_task'),
    path('task/<int:task_id>/delete/', views.delete_task, name='delete_task'),
    path('task/<int:task_id>/complete/', views.complete_task_on_date, name='complete_task_on_date'),
    path('task/<int:task_id>/sync-to-gcal/', views.sync_task_to_google, name='sync_task_to_google'), # Renamed for clarity

    path('statistics/', views.task_statistics, name='task_statistics'),
    path('task/<int:pk>/description/', views.task_description_page, name='task_description_page'),
    path('event/<int:pk>/description/', views.event_description_page, name='event_description_page'),
]