from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.conf import settings
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from datetime import datetime, timedelta, date, time
from google_auth_oauthlib.flow import Flow
from .models import GoogleCalendarToken, Event, Task, TaskCompletion
from .google_calendar import GoogleCalendarService
import json
from django.db.models import Count, Q
import markdown 
from django.urls import reverse

DEFAULT_TASK_COLORS = [
    '#AEC6CF', 
    '#C8E6C9', 
    '#FFD8B1', 
    '#F8BBD0', 
    '#D1C4E9', 
    '#FFF9C4', 
    '#B2DFDB'  
]

@login_required
def week_data(request):
    start_date_str = request.GET.get('start_date')
    
    try:
        if start_date_str:
            week_start = date.fromisoformat(start_date_str)
        else:
            today = date.today()
            week_start = today - timedelta(days=today.weekday()) 
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Invalid date format.'}, status=400)

    week_end = week_start + timedelta(days=6)
    user_tasks = Task.objects.filter(user=request.user)
    task_occurrences = []

    completions_in_week = TaskCompletion.objects.filter(
        user=request.user,
        completion_date__gte=week_start,
        completion_date__lte=week_end
    ).values_list('task_id', 'completion_date')
    completed_set = {(item[0], item[1]) for item in completions_in_week}

    for task_obj in user_tasks:
        occurrences = task_obj.get_occurrences(week_start, week_end)
        for occ in occurrences:
            start_datetime = occ['datetime']
            end_datetime = None
            if task_obj.time_of_day:
                default_end_datetime = start_datetime + timedelta(minutes=30)
                if task_obj.end_time_of_day:
                    combined_end = datetime.combine(occ['date'], task_obj.end_time_of_day)
                    if task_obj.end_time_of_day < task_obj.time_of_day:
                        combined_end_datetime_obj = timezone.make_aware(combined_end, start_datetime.tzinfo) + timedelta(days=1)
                    else:
                        combined_end_datetime_obj = timezone.make_aware(combined_end, start_datetime.tzinfo)
                    
                    if combined_end_datetime_obj > start_datetime:
                        end_datetime = combined_end_datetime_obj
                    else:
                        end_datetime = default_end_datetime
                else:
                    end_datetime = default_end_datetime
            
            is_completed = (task_obj.id, occ['date']) in completed_set
            
            # --- MODIFIED: Assign default color if task has none ---
            task_color = task_obj.color
            if not task_color: # If no color is set for the task
                # Assign a default based on task ID to keep it consistent
                if DEFAULT_TASK_COLORS: # Ensure the list is not empty
                     task_color = DEFAULT_TASK_COLORS[task_obj.id % len(DEFAULT_TASK_COLORS)]
                else:
                    task_color = '#2d5a3d' # Fallback default if list is somehow empty

            task_occurrences.append({
                'id': task_obj.id,
                'occurrence_date': occ['date'].isoformat(),
                'title': task_obj.title,
                'type': 'task',
                'description': task_obj.description,
                'start_time': start_datetime.isoformat(),
                'end_time': end_datetime.isoformat() if end_datetime else None,
                'priority': task_obj.priority or 'Medium',
                'color': task_color, # Use the assigned or calculated default color
                'completed': is_completed,
            })
    
    events = Event.objects.filter(
        user=request.user,
        start_time__date__lte=week_end,
        end_time__date__gte=week_start
    )
    event_list = []
    for event in events:
        event_list.append({
            'id': event.id,
            'title': event.title,
            'description': event.description,
            'type': 'event',
            'start_time': event.start_time.isoformat(),
            'end_time': event.end_time.isoformat(),
            'priority': 'Medium',
            'color': '#6c757d', # Default event color
            'completed': False,
        })

    return JsonResponse({
        'start_date': week_start.isoformat(),
        'end_date': week_end.isoformat(),
        'items': task_occurrences + event_list
    })

@login_required
def calendar_view(request):
    today = timezone.now().date()
    # Basic summary data (can be expanded)
    todays_tasks_count = 0
    upcoming_tasks_count = 0

    user_tasks = Task.objects.filter(user=request.user)
    next_7_days_end = today + timedelta(days=7)

    for task in user_tasks:
        occurrences_today = task.get_occurrences(today, today)
        todays_tasks_count += len(occurrences_today)
        
        occurrences_next_7_days = task.get_occurrences(today + timedelta(days=1), next_7_days_end)
        upcoming_tasks_count += len(occurrences_next_7_days)

    context = {
        'todays_tasks_count': todays_tasks_count,
        'upcoming_tasks_count': upcoming_tasks_count,
    }
    return render(request, 'calendar_app/calendar.html', context)


@login_required
def create_task(request):
    if request.method == 'POST':
        form_data = request.POST
        
        task = Task(user=request.user)
        task.title = form_data.get('title')
        task.description = form_data.get('description','')
        task.frequency = form_data.get('frequency', 'once')
        task.priority = form_data.get('priority', 'Medium')
        task.color = form_data.get('color', '#2d5a3d')

        start_date_str = form_data.get('start_date')
        if start_date_str:
            task.start_date = date.fromisoformat(start_date_str)
        else: # Default to today if not provided, crucial for 'once' tasks if UI allows empty
            task.start_date = timezone.now().date()

        time_of_day_str = form_data.get('time_of_day')
        if time_of_day_str:
            task.time_of_day = time.fromisoformat(time_of_day_str)
        
        end_time_of_day_str = form_data.get('end_time_of_day')
        if end_time_of_day_str:
            task.end_time_of_day = time.fromisoformat(end_time_of_day_str)

        if task.frequency == 'weekly':
            task.weekday = int(form_data.get('weekday')) if form_data.get('weekday') else None
        
        recurring_end_date_str = form_data.get('recurring_end_date')
        if recurring_end_date_str:
            task.recurring_end_date = date.fromisoformat(recurring_end_date_str)

        task.save()
        messages.success(request, f'Task "{task.title}" created successfully!')
        return redirect('calendar:calendar_view')

    initial_data = {}
    datetime_param = request.GET.get('datetime') # Expected format 'YYYY-MM-DDTHH:MM'
    if datetime_param:
        try:
            dt_obj = datetime.fromisoformat(datetime_param)
            initial_data['start_date'] = dt_obj.date().isoformat()
            # Ensure time_of_day is in 'HH:MM' format string for the input value
            initial_data['time_of_day'] = dt_obj.time().strftime('%H:%M') 
        except ValueError:
            pass # Ignore if param is malformed

    context = {
        'frequencies': Task.FREQUENCY_CHOICES,
        'priorities': Task.PRIORITY_CHOICES,
        'weekdays': Task.WEEKDAY_CHOICES,
        'initial_data': initial_data
    }
    return render(request, 'calendar_app/create_task.html', context)
# calendar_app/views.py
# ... (imports) ...

@login_required
def task_description_page(request, pk):
    task = get_object_or_404(Task, pk=pk, user=request.user)
    html_description = markdown.markdown(task.description or "")
    
    # Get a potential return date (e.g., task's start date or a query param)
    # For simplicity, let's just make the back button go to the main calendar.
    # A more advanced way would be to pass the original calendar week's start_date.
    # referer = request.META.get('HTTP_REFERER') # Could use this but it's not always reliable
    
    context = {
        'item_title': task.title,
        'html_description': html_description,
        'item_type': 'Task',
        'back_url': reverse('calendar:calendar_view') # Simple back to main calendar
    }
    return render(request, 'calendar_app/full_description.html', context)

@login_required
def event_description_page(request, pk):
    event = get_object_or_404(Event, pk=pk, user=request.user)
    html_description = markdown.markdown(event.description or "")
    context = {
        'item_title': event.title,
        'html_description': html_description,
        'item_type': 'Event',
        'back_url': reverse('calendar:calendar_view') # Simple back to main calendar
    }
    return render(request, 'calendar_app/full_description.html', context)
@login_required
def edit_task(request, task_id):
    task = get_object_or_404(Task, id=task_id, user=request.user)
    if request.method == 'POST':
        form_data = request.POST
        task.title = form_data.get('title')
        task.description = form_data.get('description', '')
        task.frequency = form_data.get('frequency')
        task.priority = form_data.get('priority', 'Medium')
        task.color = form_data.get('color', '#2d5a3d')

        start_date_str = form_data.get('start_date')
        task.start_date = date.fromisoformat(start_date_str) if start_date_str else None
        
        time_of_day_str = form_data.get('time_of_day')
        task.time_of_day = time.fromisoformat(time_of_day_str) if time_of_day_str else None

        end_time_of_day_str = form_data.get('end_time_of_day')
        task.end_time_of_day = time.fromisoformat(end_time_of_day_str) if end_time_of_day_str else None

        if task.frequency == 'weekly':
            task.weekday = int(form_data.get('weekday')) if form_data.get('weekday') else None
        else:
            task.weekday = None 
        
        recurring_end_date_str = form_data.get('recurring_end_date')
        task.recurring_end_date = date.fromisoformat(recurring_end_date_str) if recurring_end_date_str else None
        
        task.save()
        messages.success(request, f'Task "{task.title}" updated successfully!')
        return redirect('calendar:calendar_view')

    context = {
        'task': task,
        'frequencies': Task.FREQUENCY_CHOICES,
        'priorities': Task.PRIORITY_CHOICES,
        'weekdays': Task.WEEKDAY_CHOICES,
    }
    return render(request, 'calendar_app/edit_task.html', context)

@login_required
@require_http_methods(["POST"])
@csrf_exempt # Ensure CSRF is handled appropriately if not using session auth for API parts
def complete_task_on_date(request, task_id):
    # This task_id is the main Task ID, not an occurrence ID
    task = get_object_or_404(Task, id=task_id, user=request.user)
    try:
        data = json.loads(request.body)
        completion_date_str = data.get('date') # This should be the specific date of the occurrence
        if not completion_date_str:
            return JsonResponse({'success': False, 'error': 'Date not provided'}, status=400)
            
        completion_date_obj = date.fromisoformat(completion_date_str)
        
        completion_obj, created = TaskCompletion.objects.get_or_create(
            task=task,
            user=request.user,
            completion_date=completion_date_obj
        )

        if created:
            return JsonResponse({'success': True, 'status': 'completed', 'task_id': task.id, 'date': completion_date_str})
        else:
            completion_obj.delete()
            return JsonResponse({'success': True, 'status': 'pending', 'task_id': task.id, 'date': completion_date_str})

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    except ValueError:
        return JsonResponse({'success': False, 'error': 'Invalid date format. Expected YYYY-MM-DD.'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def task_statistics(request):
    user = request.user
    total_completed_count = TaskCompletion.objects.filter(user=user).count()

    tasks_completion_counts = Task.objects.filter(user=user).annotate(
        # Use Q directly now, not models.Q
        num_completions=Count('taskcompletion', filter=Q(taskcompletion__user=user))
    ).order_by('-num_completions')

    # Example: completions in the last 7 days
    last_week_start = timezone.now().date() - timedelta(days=7)
    completions_last_week = TaskCompletion.objects.filter(
        user=user, 
        completion_date__gte=last_week_start
    ).count()

    context = {
        'total_completed_count': total_completed_count,
        'tasks_completion_counts': tasks_completion_counts,
        'completions_last_week': completions_last_week,
    }
    return render(request, 'calendar_app/task_statistics.html', context)

# ... (keep other views like google_auth, sync_events, delete_task, task_detail, etc.)
# Minor adjustment for task_detail if needed, but it seems it's not used by current modal
@login_required
def delete_task(request, task_id):
    task = get_object_or_404(Task, id=task_id, user=request.user)
    if request.method == 'POST': # Should be POST for delete
        task_title = task.title
        task.delete()
        messages.success(request, f'Task "{task_title}" has been deleted.')
        return redirect('calendar:calendar_view')
    # It's better to have a confirmation page or use a POST request from JS.
    # For now, let's assume it's linked from edit page and a GET for delete confirmation is ok.
    # If using POST from a button in a list:
    # task.delete()
    # messages.success(request, f'Task "{task_title}" deleted.')
    # return redirect('calendar:calendar_view')
    return render(request, 'calendar_app/delete_task_confirm.html', {'task': task}) # Make sure this template exists

@login_required
@require_http_methods(["POST"])
def sync_task_to_google(request, task_id):
    task = get_object_or_404(Task, id=task_id, user=request.user)
    days_to_sync = 30 
    count, message_text = task.sync_to_google_calendar(request.user, days_to_sync=days_to_sync)
    if count > 0:
        messages.success(request, message_text)
    else:
        messages.warning(request, message_text)
    return redirect('calendar:edit_task', task_id=task.id) # Redirect back to edit page


# ... (rest of the views: google_auth, google_oauth_callback, create_event, sync_events)
# Ensure they are present and correct based on previous state if not listed for modification here.
# For example:
@login_required
def sync_events(request):
    """Sync events from Google Calendar"""
    try:
        calendar_service = GoogleCalendarService(request.user)
        events = calendar_service.get_events()
        messages.success(request, f'Successfully synced {len(events)} events from Google Calendar!')
    except Exception as e:
        messages.error(request, f'Error syncing events: {str(e)}')
    return redirect('calendar:calendar_view')

def google_auth(request):
    """Initialize Google OAuth flow"""
    client_config = {
        "web": {
            "client_id": settings.GOOGLE_OAUTH2_CLIENT_ID,
            "client_secret": settings.GOOGLE_OAUTH2_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [request.build_absolute_uri(redirect('calendar:oauth_callback').url)]
        }
    }
    flow = Flow.from_client_config(
        client_config,
        scopes=['https://www.googleapis.com/auth/calendar'],
        # Make sure your redirect URI here matches what's in Google Cloud Console
        redirect_uri=request.build_absolute_uri(redirect('calendar:oauth_callback').url)
    )
    # flow.redirect_uri = request.build_absolute_uri(redirect('calendar:oauth_callback').url) # Duplicate
    authorization_url, state = flow.authorization_url(access_type='offline', include_granted_scopes='true', prompt='consent') # Added prompt='consent' for refresh token
    request.session['google_auth_state'] = state
    return redirect(authorization_url)

@login_required # Ensure user is logged in for callback
def google_oauth_callback(request):
    state = request.session.pop('google_auth_state', '')
    # Check if state matches to prevent CSRF
    if not state or state != request.GET.get('state'):
        messages.error(request, "State mismatch. OAuth2 flow could not be completed.")
        return redirect('calendar:calendar_view') # Or an error page

    client_config = {
        "web": {
            "client_id": settings.GOOGLE_OAUTH2_CLIENT_ID,
            "client_secret": settings.GOOGLE_OAUTH2_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    flow = Flow.from_client_config(
        client_config, 
        scopes=['https://www.googleapis.com/auth/calendar'], 
        state=state,
        redirect_uri=request.build_absolute_uri(redirect('calendar:oauth_callback').url)
    )
    
    # Use the full URL for `authorization_response`
    authorization_response = request.build_absolute_uri()
    flow.fetch_token(authorization_response=authorization_response)
    
    credentials = flow.credentials
    # expires_at: Google's library typically returns expiry as a datetime object or seconds.
    # Assuming credentials.expiry is a timezone-aware datetime object (UTC).
    # If it's seconds, you'll need timezone.now() + timedelta(seconds=credentials.expires_in)
    
    expires_at_datetime = timezone.now() + timedelta(seconds=credentials.expires_in) if credentials.expires_in else None


    GoogleCalendarToken.objects.update_or_create(
        user=request.user,
        defaults={
            'access_token': credentials.token,
            'refresh_token': credentials.refresh_token, # This is crucial
            'token_expires_at': expires_at_datetime,
        }
    )
    messages.success(request, 'Google Calendar connected successfully!')
    return redirect('calendar:calendar_view')

@login_required
def create_event(request): # This is for Google Calendar Events, not local tasks.
    # Assuming this creates events directly in Google Calendar and syncs back.
    # The existing EventForm in forms.py might be for this.
    # Let's assume the current simple POST handling is what was intended for direct creation.
    if request.method == 'POST':
        try:
            calendar_service = GoogleCalendarService(request.user)
            start_dt_str = request.POST.get('start_time')
            end_dt_str = request.POST.get('end_time')

            if not start_dt_str or not end_dt_str:
                messages.error(request, "Start time and end time are required.")
                return render(request, 'calendar_app/create_event.html') # Or redirect

            # Ensure parsing with timezone if not already part of string
            start_dt = timezone.make_aware(datetime.fromisoformat(start_dt_str)) if len(start_dt_str) == 16 else datetime.fromisoformat(start_dt_str)
            end_dt = timezone.make_aware(datetime.fromisoformat(end_dt_str)) if len(end_dt_str) == 16 else datetime.fromisoformat(end_dt_str)


            calendar_service.create_event(
                title=request.POST.get('title'),
                start_time=start_dt,
                end_time=end_dt,
                description=request.POST.get('description', ''),
                location=request.POST.get('location', '')
            )
            messages.success(request, f"Event '{request.POST.get('title')}' created and synced to Google Calendar.")
            return redirect('calendar:calendar_view')
        except Exception as e:
            messages.error(request, f"Could not create event: {e}")
            # Consider passing form back with errors if using Django forms
            return render(request, 'calendar_app/create_event.html') # Redirecting might lose POST data
            
    return render(request, 'calendar_app/create_event.html') # Assumes this template exists