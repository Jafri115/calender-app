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


@login_required
def week_data(request):
    """
    Provides all calendar data (tasks, events) for a given week as JSON.
    """
    start_date_str = request.GET.get('start_date')
    week_str = request.GET.get('week')

    try:
        if start_date_str:
            # New param: start_date=YYYY-MM-DD
            week_start = date.fromisoformat(start_date_str)
        elif week_str:
            # Old param: week=YYYY-W##
            year, week_num = map(int, week_str.split('-W'))
            week_start = datetime.fromisocalendar(year, week_num, 1).date()
        else:
            # Default to current week
            today = date.today()
            week_start = today - timedelta(days=today.weekday())  # Monday
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Invalid date format.'}, status=400)

    week_end = week_start + timedelta(days=6)

    # --- Get Task Occurrences ---
    tasks = Task.objects.filter(user=request.user)
    task_occurrences = []
    for task in tasks:
        occurrences = task.get_occurrences(week_start, week_end)
        for occ in occurrences:
            task_occurrences.append({
                'id': task.id,
                'title': task.title,
                'type': 'task',
                'description': task.description,
                'start_time': occ['datetime'].isoformat(),
                'category': 'dhuhr'  # Example placeholder
            })

    # --- Get Events ---
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
            'category': 'event'  # Example placeholder
        })

    return JsonResponse({
        'start_date': week_start.isoformat(),
        'end_date': week_end.isoformat(),
        'items': task_occurrences + event_list
    })


def get_week_dates(week_str=None):
    """Get the dates for a given week, starting from Monday."""
    if week_str:
        try:
            year, week_num = map(int, week_str.split('-W'))
            first_day = datetime.strptime(f'{year}-W{week_num-1}-1', '%Y-W%W-%w').date()
        except (ValueError, TypeError):
            today = date.today()
            first_day = today - timedelta(days=today.weekday())
    else:
        today = date.today()
        first_day = today - timedelta(days=today.weekday())
    
    return [first_day + timedelta(days=i) for i in range(7)], first_day

def get_time_slots():
    """Generate hourly time slots."""
    return [{'hour': hour, 'display': time(hour=hour).strftime('%I:%M %p')} for hour in range(24)]

@login_required
@login_required
def calendar_view(request):
    """
    This view now only needs to render the main HTML shell.
    The calendar data will be fetched by JavaScript.
    """
    return render(request, 'calendar_app/calendar.html')

@login_required
def create_task(request):
    """Create a new recurring or one-time task."""
    if request.method == 'POST':
        form_data = request.POST
        
        frequency = form_data.get('frequency', 'once')

        task = Task(
            user=request.user, 
            title=form_data.get('title'), 
            description=form_data.get('description',''), 
            frequency=frequency
        )
        
        if frequency == 'once':
            due_date_str = form_data.get('due_date')
            if due_date_str:
                dt = datetime.fromisoformat(due_date_str)
                task.start_date = dt.date()
                task.start_time = dt.time()
        else:  # Daily or Weekly
            if form_data.get('time_of_day'):
                task.time_of_day = time.fromisoformat(form_data.get('time_of_day'))
            if form_data.get('start_date'):
                task.start_date = date.fromisoformat(form_data.get('start_date'))
            else:
                task.start_date = date.today()
            
            if form_data.get('end_date'):
                task.end_date = date.fromisoformat(form_data.get('end_date'))
            
            if frequency == 'weekly' and form_data.get('weekday'):
                task.weekday = int(form_data.get('weekday'))

        task.save()
        messages.success(request, f'Task "{task.title}" created successfully!')
        return redirect('calendar:calendar_view')

    # GET request logic remains the same
    initial_data = {}
    datetime_str = request.GET.get('datetime')
    if datetime_str:
        try:
            initial_data['due_date'] = datetime.fromisoformat(datetime_str)
        except (ValueError, TypeError):
            pass

    context = {
        'frequencies': Task.FREQUENCY_CHOICES,
        'weekdays': Task.WEEKDAY_CHOICES,
        'initial_data': initial_data
    }
    return render(request, 'calendar_app/create_task.html', context)

@login_required
@require_http_methods(["POST"])
def sync_task_to_google(request, task_id):
    """
    View to trigger the syncing of a task's occurrences to Google Calendar.
    """
    task = get_object_or_404(Task, id=task_id, user=request.user)
    
    # You could get the number of days from the request body if you want
    days_to_sync = 30 # Sync for the next 30 days by default
    
    count, message = task.sync_to_google_calendar(request.user, days_to_sync=days_to_sync)
    
    if count > 0:
        messages.success(request, message)
    else:
        messages.warning(request, message)
        
    return redirect('calendar:calendar_view') # Or redirect back to a task detail page
@login_required
def edit_task(request, task_id):
    """Edit an existing task."""
    task = get_object_or_404(Task, id=task_id, user=request.user)
    if request.method == 'POST':
        # This logic is similar to create_task, just updating fields.
        # For brevity, I'll assume you can adapt the `create_task` logic here.
        # You would update task.title, task.frequency, etc., from request.POST
        # and then call task.save().
        task.title = request.POST.get('title')
        task.description = request.POST.get('description', '')
        task.frequency = request.POST.get('frequency')
        
        if task.frequency == 'once':
            task.due_date = datetime.fromisoformat(request.POST.get('due_date')) if request.POST.get('due_date') else None
            task.time_of_day, task.weekday, task.start_date, task.end_date = None, None, None, None
        else:
            task.time_of_day = time.fromisoformat(request.POST.get('time_of_day')) if request.POST.get('time_of_day') else None
            task.start_date = date.fromisoformat(request.POST.get('start_date')) if request.POST.get('start_date') else date.today()
            task.end_date = date.fromisoformat(request.POST.get('end_date')) if request.POST.get('end_date') else None
            task.weekday = request.POST.get('weekday') if task.frequency == 'weekly' else None
            task.due_date = None

        task.save()
        messages.success(request, f'Task "{task.title}" updated successfully!')
        return redirect('calendar:calendar_view')

    context = {
        'task': task,
        'frequencies': Task.FREQUENCY_CHOICES,
        'weekdays': Task.WEEKDAY_CHOICES,
    }
    return render(request, 'calendar_app/edit_task.html', context)

@login_required
@require_http_methods(["POST"])
@csrf_exempt
def complete_task_on_date(request, task_id):
    """Mark a recurring task as completed for a specific date."""
    task = get_object_or_404(Task, id=task_id, user=request.user)
    try:
        data = json.loads(request.body)
        completion_date_str = data.get('date')
        completion_date = datetime.strptime(completion_date_str, '%Y-%m-%d').date()
        
        # Check if it should be completed or un-completed
        completion_obj, created = TaskCompletion.objects.get_or_create(
            task=task,
            user=request.user,
            completion_date=completion_date
        )

        if created:
            return JsonResponse({'success': True, 'status': 'completed'})
        else:
            # If it already exists, delete it (toggle functionality)
            completion_obj.delete()
            return JsonResponse({'success': True, 'status': 'pending'})

    except (json.JSONDecodeError, ValueError, KeyError):
        return JsonResponse({'success': False, 'error': 'Invalid request'}, status=400)

@login_required
def delete_task(request, task_id):
    """Delete a task."""
    task = get_object_or_404(Task, id=task_id, user=request.user)
    if request.method == 'POST':
        task_title = task.title
        task.delete()
        messages.success(request, f'Task "{task_title}" has been deleted.')
        return redirect('calendar:calendar_view')
    return render(request, 'calendar_app/delete_task_confirm.html', {'task': task})

@login_required
def task_detail(request, task_id):
    """Get task details for modal display."""
    task = get_object_or_404(Task, id=task_id, user=request.user)
    data = {
        'id': task.id,
        'title': task.title,
        'description': task.description,
        'frequency': task.get_frequency_display(),
        'time_of_day': task.time_of_day.strftime('%I:%M %p') if task.time_of_day else 'N/A',
        'weekday': task.get_weekday_display() if task.weekday is not None else 'N/A',
        'start_date': task.start_date.strftime('%b %d, %Y') if task.start_date else 'N/A',
        'end_date': task.end_date.strftime('%b %d, %Y') if task.end_date else 'Ongoing',
    }
    return JsonResponse(data)
    
# Keep your other views like google_auth, create_event, etc. as they are.
# For brevity, I'm omitting them but they should remain in your file.
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
    # Using client secrets from settings.py
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
        scopes=['https://www.googleapis.com/auth/calendar']
    )
    flow.redirect_uri = request.build_absolute_uri(redirect('calendar:oauth_callback').url)
    authorization_url, state = flow.authorization_url(access_type='offline', include_granted_scopes='true')
    request.session['google_auth_state'] = state
    return redirect(authorization_url)

@login_required
def google_oauth_callback(request):
    """Handle Google OAuth callback"""
    # This view seems to be using an older model structure for GoogleCalendarToken.
    # I'll keep it as is, but it might need updates based on your exact model fields.
    state = request.session.pop('google_auth_state', '')
    client_config = {
        "web": {
            "client_id": settings.GOOGLE_OAUTH2_CLIENT_ID,
            "client_secret": settings.GOOGLE_OAUTH2_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    flow = Flow.from_client_config(client_config, scopes=['https://www.googleapis.com/auth/calendar'], state=state)
    flow.redirect_uri = request.build_absolute_uri(redirect('calendar:oauth_callback').url)
    flow.fetch_token(authorization_response=request.build_absolute_uri())
    
    credentials = flow.credentials
    expires_at = timezone.now() + timedelta(seconds=credentials.expires_in)

    GoogleCalendarToken.objects.update_or_create(
        user=request.user,
        defaults={
            'access_token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_expires_at': expires_at,
        }
    )
    messages.success(request, 'Google Calendar connected successfully!')
    return redirect('calendar:calendar_view')

@login_required
def create_event(request):
    if request.method == 'POST':
        try:
            calendar_service = GoogleCalendarService(request.user)
            start_dt = datetime.fromisoformat(request.POST.get('start_time'))
            end_dt = datetime.fromisoformat(request.POST.get('end_time'))
            
            calendar_service.create_event(
                title=request.POST.get('title'),
                start_time=start_dt,
                end_time=end_dt,
                description=request.POST.get('description', ''),
                location=request.POST.get('location', '')
            )
            messages.success(request, f"Event '{request.POST.get('title')}' created successfully.")
            return redirect('calendar:calendar_view')
        except Exception as e:
            messages.error(request, f"Could not create event: {e}")
            return redirect('calendar:create_event')
            
    return render(request, 'calendar_app/create_event.html')