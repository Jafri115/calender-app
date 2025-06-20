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
from django.db.models import Count, Q, Sum, F, ExpressionWrapper, DurationField
import markdown 
from django.urls import reverse

DEFAULT_TASK_COLORS = [
    '#AEC6CF', '#C8E6C9', '#FFD8B1', '#F8BBD0', 
    '#D1C4E9', '#FFF9C4', '#B2DFDB'  
]

# (Other view functions like week_data, create_task, edit_task, etc. would be here)
# ...

@login_required
def week_data(request):
    # FIX: Changed 'start_date' to 'date' to match the parameter sent by the frontend JavaScript.
    date_param_str = request.GET.get('date')
    
    try:
        if date_param_str:
            # The date from the parameter becomes the reference point for the week.
            ref_date = date.fromisoformat(date_param_str)
            week_start = ref_date - timedelta(days=ref_date.weekday())
        else:
            # If no date is provided, default to the current week.
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
            
            task_color = task_obj.color
            if not task_color:
                if DEFAULT_TASK_COLORS:
                     task_color = DEFAULT_TASK_COLORS[task_obj.id % len(DEFAULT_TASK_COLORS)]
                else:
                    task_color = '#2d5a3d'

            task_occurrences.append({
                'id': task_obj.id,
                'occurrence_date': occ['date'].isoformat(),
                'title': task_obj.title,
                'type': 'task',
                'description': task_obj.description,
                'start_time': start_datetime.isoformat(),
                'end_time': end_datetime.isoformat() if end_datetime else None,
                'priority': task_obj.priority or 'Medium',
                'color': task_color,
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
            'priority': 'Medium', # Events don't have priority in model, default
            'color': '#6c757d', # Default color for events
            'completed': False, # Events are not completable in the same way as tasks
        })

    return JsonResponse({
        'start_date': week_start.isoformat(),
        'end_date': week_end.isoformat(),
        'items': task_occurrences + event_list
    })

@login_required
def calendar_view(request):
    today = timezone.now().date()
    user_tasks = Task.objects.filter(user=request.user)

    upcoming_tasks_list = []
    sidebar_upcoming_end_date = today + timedelta(days=3) # Today + next 2 days
    
    upcoming_completions_dict = {}
    completions_for_upcoming = TaskCompletion.objects.filter(
        user=request.user,
        completion_date__gte=today,
        completion_date__lte=sidebar_upcoming_end_date
    )
    for comp in completions_for_upcoming:
        upcoming_completions_dict[(comp.task_id, comp.completion_date)] = True

    for task in user_tasks:
        sidebar_occurrences = task.get_occurrences(today, sidebar_upcoming_end_date)
        for occ in sidebar_occurrences:
            is_completed = (task.id, occ['date']) in upcoming_completions_dict
            if not is_completed: 
                task_color = task.color
                if not task_color: # Assign default if no color
                    if DEFAULT_TASK_COLORS:
                        task_color = DEFAULT_TASK_COLORS[task.id % len(DEFAULT_TASK_COLORS)]
                    else:
                        task_color = '#2d5a3d' # Fallback default
                
                upcoming_tasks_list.append({
                    'id': task.id,
                    'title': task.title,
                    'date': occ['date'],
                    'time_of_day': task.time_of_day, # For display formatting
                    'datetime': occ['datetime'], 
                    'color': task_color
                })

    upcoming_tasks_list.sort(key=lambda x: x['datetime'])

    context = {
        # 'todays_tasks_count': ..., # Can be calculated if needed for other parts
        # 'upcoming_tasks_count': ..., # Can be calculated if needed
        'sidebar_upcoming_tasks': upcoming_tasks_list[:5], 
    }
    return render(request, 'calendar_app/calendar.html', context)


def get_week_start_end(ref_date):
    # Assuming Monday is the start of the week (weekday() == 0)
    start_of_week = ref_date - timedelta(days=ref_date.weekday())
    end_of_week = start_of_week + timedelta(days=6)
    return start_of_week, end_of_week

@login_required
def task_statistics(request):
    user = request.user
    today = timezone.now().date()

    current_week_start, current_week_end = get_week_start_end(today)
    tasks = Task.objects.filter(user=user)
    
    current_week_completions_dates = {}
    completions_this_week_qs = TaskCompletion.objects.filter(
        user=user, 
        completion_date__gte=current_week_start,
        completion_date__lte=current_week_end
    )
    for comp in completions_this_week_qs:
        current_week_completions_dates[(comp.task_id, comp.completion_date)] = True

    total_duration_completed_this_week = timedelta(0)
    total_occurrences_this_week = 0
    completed_occurrences_this_week = 0

    daily_breakdown_data = {} 
    for i in range(7):
        day_in_week = current_week_start + timedelta(days=i)
        daily_breakdown_data[day_in_week] = {'total': 0, 'completed': 0, 'duration': timedelta(0)}

    practice_categories_data = {}

    for task in tasks:
        occurrences = task.get_occurrences(current_week_start, current_week_end)
        task_category_title = task.title 
        if task_category_title not in practice_categories_data:
            practice_categories_data[task_category_title] = {
                'total': 0, 'completed': 0, 'duration': timedelta(0), 
                'color': task.color or DEFAULT_TASK_COLORS[task.id % len(DEFAULT_TASK_COLORS)] if DEFAULT_TASK_COLORS else '#AEC6CF'
            }

        for occ in occurrences:
            occurrence_date = occ['date']
            total_occurrences_this_week += 1
            if occurrence_date in daily_breakdown_data:
                daily_breakdown_data[occurrence_date]['total'] += 1
            practice_categories_data[task_category_title]['total'] += 1
            
            is_completed = (task.id, occurrence_date) in current_week_completions_dates
            
            duration = timedelta(minutes=30) 
            if task.time_of_day and task.end_time_of_day:
                start_dt = datetime.combine(datetime.min, task.time_of_day) # Use datetime.min as a dummy date
                end_dt = datetime.combine(datetime.min, task.end_time_of_day)
                if end_dt > start_dt:
                    duration = end_dt - start_dt
                elif task.end_time_of_day < task.time_of_day : 
                     duration = (datetime.combine(datetime.min + timedelta(days=1), task.end_time_of_day) - start_dt)

            if is_completed:
                completed_occurrences_this_week += 1
                total_duration_completed_this_week += duration
                if occurrence_date in daily_breakdown_data:
                    daily_breakdown_data[occurrence_date]['completed'] += 1
                    daily_breakdown_data[occurrence_date]['duration'] += duration
                practice_categories_data[task_category_title]['completed'] += 1
                practice_categories_data[task_category_title]['duration'] += duration

    # Post-process to add hours and minutes
    for day_date_key in daily_breakdown_data:
        duration_obj = daily_breakdown_data[day_date_key]['duration']
        total_seconds = duration_obj.total_seconds()
        daily_breakdown_data[day_date_key]['hours'] = int(total_seconds // 3600)
        daily_breakdown_data[day_date_key]['minutes'] = int((total_seconds % 3600) // 60)

    for cat_key in practice_categories_data:
        duration_obj = practice_categories_data[cat_key]['duration']
        total_seconds = duration_obj.total_seconds()
        practice_categories_data[cat_key]['hours'] = int(total_seconds // 3600)
        practice_categories_data[cat_key]['minutes'] = int((total_seconds % 3600) // 60)

    completion_rate_current_week = (completed_occurrences_this_week / total_occurrences_this_week * 100) if total_occurrences_this_week > 0 else 0
    avg_daily_practice_time_this_week = (total_duration_completed_this_week / 7) if completed_occurrences_this_week > 0 else timedelta(0)
    
    avg_daily_total_seconds = avg_daily_practice_time_this_week.total_seconds()
    avg_daily_hours = int(avg_daily_total_seconds // 3600)
    avg_daily_minutes = int((avg_daily_total_seconds % 3600) // 60)

    last_week_start, last_week_end = get_week_start_end(today - timedelta(days=7))
    completed_occurrences_last_week = 0
    total_occurrences_last_week = 0
    for task in tasks:
        occurrences = task.get_occurrences(last_week_start, last_week_end)
        for occ in occurrences:
            total_occurrences_last_week +=1
            if TaskCompletion.objects.filter(user=user, task=task, completion_date=occ['date']).exists():
                completed_occurrences_last_week +=1
    
    completion_rate_last_week = (completed_occurrences_last_week / total_occurrences_last_week * 100) if total_occurrences_last_week > 0 else 0
    weekly_trend_vs_last = completion_rate_current_week - completion_rate_last_week

    four_week_trend_data = []
    for i in range(3, -1, -1): 
        week_ref_date = today - timedelta(weeks=i)
        w_start, w_end = get_week_start_end(week_ref_date)
        
        w_completed = 0
        w_total = 0
        for task_item in tasks:
            w_occurrences = task_item.get_occurrences(w_start, w_end)
            for occ_item in w_occurrences:
                w_total += 1
                if TaskCompletion.objects.filter(user=user, task=task_item, completion_date=occ_item['date']).exists():
                    w_completed +=1
        
        w_rate = (w_completed / w_total * 100) if w_total > 0 else 0
        four_week_trend_data.append({
            'week_label': w_start.strftime('%b %d'),
            'rate': round(w_rate, 1)
        })

    sorted_daily_breakdown = sorted(daily_breakdown_data.items())

    context = {
        'current_week_label': f"{current_week_start.strftime('%B %d')} - {current_week_end.strftime('%d, %Y')}",
        'completion_rate_current_week': round(completion_rate_current_week,1),
        'completed_this_week_count': completed_occurrences_this_week,
        'total_this_week_count': total_occurrences_this_week,
        'avg_daily_practice_time_hours': avg_daily_hours,
        'avg_daily_practice_time_minutes': avg_daily_minutes,
        'total_practices_this_week': total_occurrences_this_week,
        'weekly_trend_vs_last': round(weekly_trend_vs_last,1),
        
        'daily_breakdown': sorted_daily_breakdown,
        'practice_categories': practice_categories_data,
        'four_week_trend_labels': json.dumps([d['week_label'] for d in four_week_trend_data]),
        'four_week_trend_rates': json.dumps([d['rate'] for d in four_week_trend_data]),
    }
    return render(request, 'calendar_app/task_statistics.html', context)

@login_required
def create_task(request):
    if request.method == 'POST':
        form_data = request.POST
        
        task = Task(user=request.user)
        task.title = form_data.get('title')
        task.description = form_data.get('description','')
        task.frequency = form_data.get('frequency', 'once')
        task.priority = form_data.get('priority', 'Medium')
        task.color = form_data.get('color', '#AEC6CF') # Default from palette

        start_date_str = form_data.get('start_date')
        if start_date_str:
            task.start_date = date.fromisoformat(start_date_str)
        else: 
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
    datetime_param = request.GET.get('datetime') 
    if datetime_param:
        try:
            dt_obj = datetime.fromisoformat(datetime_param)
            initial_data['start_date'] = dt_obj.date().isoformat()
            initial_data['time_of_day'] = dt_obj.time().strftime('%H:%M') 
        except ValueError:
            pass 

    context = {
        'frequencies': Task.FREQUENCY_CHOICES,
        'priorities': Task.PRIORITY_CHOICES,
        'weekdays': Task.WEEKDAY_CHOICES,
        'initial_data': initial_data
    }
    return render(request, 'calendar_app/create_task.html', context)

@login_required
def edit_task(request, task_id):
    task = get_object_or_404(Task, id=task_id, user=request.user)
    if request.method == 'POST':
        form_data = request.POST
        task.title = form_data.get('title')
        task.description = form_data.get('description', '')
        task.frequency = form_data.get('frequency')
        task.priority = form_data.get('priority', 'Medium')
        task.color = form_data.get('color', '#AEC6CF')

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
@csrf_exempt 
def complete_task_on_date(request, task_id):
    task = get_object_or_404(Task, id=task_id, user=request.user)
    try:
        data = json.loads(request.body)
        completion_date_str = data.get('date') 
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
def delete_task(request, task_id):
    task = get_object_or_404(Task, id=task_id, user=request.user)
    if request.method == 'POST': 
        task_title = task.title
        task.delete()
        messages.success(request, f'Task "{task_title}" has been deleted.')
        return redirect('calendar:calendar_view')
    return render(request, 'calendar_app/delete_task_confirm.html', {'task': task})

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
    return redirect('calendar:edit_task', task_id=task.id)

@login_required
def task_description_page(request, pk):
    task = get_object_or_404(Task, pk=pk, user=request.user)
    raw_description = task.description or ""
    html_description = markdown.markdown(raw_description)
    has_content = bool(raw_description.strip()) 
    
    context = {
        'item_title': task.title,
        'html_description': html_description,
        'has_content': has_content,
        'item_type': 'Task',
        'back_url': reverse('calendar:calendar_view') 
    }
    return render(request, 'calendar_app/full_description.html', context)

@login_required
def event_description_page(request, pk):
    event = get_object_or_404(Event, pk=pk, user=request.user)
    raw_description = event.description or ""
    html_description = markdown.markdown(raw_description)
    has_content = bool(raw_description.strip())

    context = {
        'item_title': event.title,
        'html_description': html_description,
        'has_content': has_content,
        'item_type': 'Event',
        'back_url': reverse('calendar:calendar_view')
    }
    return render(request, 'calendar_app/full_description.html', context)

# --- Google Calendar OAuth and Event Sync Views ---
@login_required
def sync_events(request):
    try:
        calendar_service = GoogleCalendarService(request.user)
        events = calendar_service.get_events()
        messages.success(request, f'Successfully synced {len(events)} events from Google Calendar!')
    except Exception as e:
        messages.error(request, f'Error syncing events: {str(e)}')
    return redirect('calendar:calendar_view')

def google_auth(request):
    client_config = {
        "web": {
            "client_id": settings.GOOGLE_OAUTH2_CLIENT_ID,
            "client_secret": settings.GOOGLE_OAUTH2_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [request.build_absolute_uri(reverse('calendar:oauth_callback'))]
        }
    }
    flow = Flow.from_client_config(
        client_config,
        scopes=['https://www.googleapis.com/auth/calendar'],
        redirect_uri=request.build_absolute_uri(reverse('calendar:oauth_callback'))
    )
    authorization_url, state = flow.authorization_url(access_type='offline', include_granted_scopes='true', prompt='consent')
    request.session['google_auth_state'] = state
    return redirect(authorization_url)

@login_required 
def google_oauth_callback(request):
    state = request.session.pop('google_auth_state', '')
    if not state or state != request.GET.get('state'):
        messages.error(request, "State mismatch. OAuth2 flow could not be completed.")
        return redirect('calendar:calendar_view')

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
        redirect_uri=request.build_absolute_uri(reverse('calendar:oauth_callback'))
    )
    
    authorization_response = request.build_absolute_uri()
    flow.fetch_token(authorization_response=authorization_response)
    
    credentials = flow.credentials
    expires_at_datetime = timezone.now() + timedelta(seconds=credentials.expires_in) if credentials.expires_in else None

    GoogleCalendarToken.objects.update_or_create(
        user=request.user,
        defaults={
            'access_token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_expires_at': expires_at_datetime,
        }
    )
    messages.success(request, 'Google Calendar connected successfully!')
    return redirect('calendar:calendar_view')

@login_required
def create_event(request): 
    if request.method == 'POST':
        try:
            calendar_service = GoogleCalendarService(request.user)
            start_dt_str = request.POST.get('start_time')
            end_dt_str = request.POST.get('end_time')

            if not start_dt_str or not end_dt_str:
                messages.error(request, "Start time and end time are required.")
                return render(request, 'calendar_app/create_event.html') 

            # Attempt to parse datetime-local input, which doesn't include timezone
            # Make them timezone-aware using Django's current timezone
            start_dt_naive = datetime.fromisoformat(start_dt_str)
            end_dt_naive = datetime.fromisoformat(end_dt_str)
            
            start_dt = timezone.make_aware(start_dt_naive)
            end_dt = timezone.make_aware(end_dt_naive)

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
            return render(request, 'calendar_app/create_event.html') 
            
    return render(request, 'calendar_app/create_event.html')