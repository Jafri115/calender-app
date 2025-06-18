from django.urls import path
from . import views

app_name = 'calendar'

# ...
urlpatterns = [
    path('', views.calendar_view, name='calendar_view'),
    
    # Add this new URL for the JSON data
    path('api/week-data/', views.week_data, name='api_week_data'),

    # ... keep all your other URLs for tasks, events, and auth
    path('auth/google/', views.google_auth, name='google_auth'),
    path('oauth/callback/', views.google_oauth_callback, name='oauth_callback'),
    path('create-event/', views.create_event, name='create_event'),
    path('sync/', views.sync_events, name='sync_events'),
    path('task/create/', views.create_task, name='create_task'),
    path('task/<int:task_id>/', views.task_detail, name='task_detail'),
    path('task/<int:task_id>/edit/', views.edit_task, name='edit_task'),
    path('task/<int:task_id>/delete/', views.delete_task, name='delete_task'),
    path('task/<int:task_id>/complete/', views.complete_task_on_date, name='complete_task_on_date'),
    path('task/<int:task_id>/sync/', views.sync_task_to_google, name='sync_task_to_google'),

]