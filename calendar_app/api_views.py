from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views import View
from .google_calendar import GoogleCalendarService
from .models import Event
import json

@method_decorator(login_required, name='dispatch')
class EventsAPIView(View):
    def get(self, request):
        """Get events for the current user"""
        events = Event.objects.filter(user=request.user).order_by('start_time')
        events_data = []
        
        for event in events:
            events_data.append({
                'id': event.id,
                'google_event_id': event.google_event_id,
                'title': event.title,
                'description': event.description,
                'start_time': event.start_time.isoformat(),
                'end_time': event.end_time.isoformat(),
                'location': event.location,
            })
        
        return JsonResponse({'events': events_data})

    @csrf_exempt
    def post(self, request):
        """Create a new event"""
        try:
            data = json.loads(request.body)
            calendar_service = GoogleCalendarService(request.user)
            
            event = calendar_service.create_event(
                title=data['title'],
                start_time=datetime.fromisoformat(data['start_time']),
                end_time=datetime.fromisoformat(data['end_time']),
                description=data.get('description', ''),
                location=data.get('location', '')
            )
            
            return JsonResponse({
                'success': True,
                'event_id': event['id']
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=400)

# Additional API URL patterns
from django.urls import path
from . import api_views

api_urlpatterns = [
    path('api/events/', api_views.EventsAPIView.as_view(), name='api_events'),
]

# Add to main urls.py:
# path('calendar/api/', include('calendar_app.api_urls')),
                