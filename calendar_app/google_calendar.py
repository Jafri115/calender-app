import os
import json
from datetime import datetime, timedelta
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from django.conf import settings
from django.utils import timezone
from .models import GoogleCalendarToken, Event

class GoogleCalendarService:
    def __init__(self, user):
        self.user = user
        self.service = None
        self._setup_service()

    def _setup_service(self):
        """Initialize Google Calendar service with user credentials"""
        try:
            token_obj = GoogleCalendarToken.objects.get(user=self.user)
            creds = Credentials(
                token=token_obj.access_token,
                refresh_token=token_obj.refresh_token,
                token_uri='https://oauth2.googleapis.com/token',
                client_id=settings.GOOGLE_OAUTH2_CLIENT_ID,
                client_secret=settings.GOOGLE_OAUTH2_CLIENT_SECRET
            )
            
            # Refresh token if expired
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                # Update stored token
                token_obj.access_token = creds.token
                token_obj.token_expires_at = timezone.now() + timedelta(seconds=creds.expiry)
                token_obj.save()
            
            self.service = build('calendar', 'v3', credentials=creds)
        except GoogleCalendarToken.DoesNotExist:
            raise Exception("User not authenticated with Google Calendar")

    def get_events(self, start_date=None, end_date=None):
        """Fetch events from Google Calendar"""
        if not start_date:
            start_date = timezone.now()
        if not end_date:
            end_date = start_date + timedelta(days=30)

        events_result = self.service.events().list(
            calendarId='primary',
            timeMin=start_date.isoformat(),
            timeMax=end_date.isoformat(),
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        return self._sync_events_to_db(events)

    def _sync_events_to_db(self, google_events):
        """Sync Google Calendar events to local database"""
        synced_events = []
        
        for event in google_events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            end = event['end'].get('dateTime', event['end'].get('date'))
            
            # Handle all-day events
            if 'T' not in start:
                start += 'T00:00:00'
                end += 'T23:59:59'
            
            start_dt = timezone.datetime.fromisoformat(start.replace('Z', '+00:00'))
            end_dt = timezone.datetime.fromisoformat(end.replace('Z', '+00:00'))
            
            event_obj, created = Event.objects.update_or_create(
                google_event_id=event['id'],
                defaults={
                    'user': self.user,
                    'title': event.get('summary', 'No Title'),
                    'description': event.get('description', ''),
                    'start_time': start_dt,
                    'end_time': end_dt,
                    'location': event.get('location', ''),
                }
            )
            synced_events.append(event_obj)
        
        return synced_events

    def create_event(self, title, start_time, end_time, description='', location=''):
        """Create event in Google Calendar"""
        event = {
            'summary': title,
            'location': location,
            'description': description,
            'start': {
                'dateTime': start_time.isoformat(),
                'timeZone': 'UTC',
            },
            'end': {
                'dateTime': end_time.isoformat(),
                'timeZone': 'UTC',
            },
        }

        created_event = self.service.events().insert(
            calendarId='primary', 
            body=event
        ).execute()
        
        # Save to local database
        Event.objects.create(
            user=self.user,
            google_event_id=created_event['id'],
            title=title,
            description=description,
            start_time=start_time,
            end_time=end_time,
            location=location
        )
        
        return created_event

    def update_event(self, event_id, **kwargs):
        """Update event in Google Calendar"""
        event = self.service.events().get(
            calendarId='primary', 
            eventId=event_id
        ).execute()
        
        # Update fields
        if 'title' in kwargs:
            event['summary'] = kwargs['title']
        if 'description' in kwargs:
            event['description'] = kwargs['description']
        if 'location' in kwargs:
            event['location'] = kwargs['location']
        if 'start_time' in kwargs:
            event['start']['dateTime'] = kwargs['start_time'].isoformat()
        if 'end_time' in kwargs:
            event['end']['dateTime'] = kwargs['end_time'].isoformat()

        updated_event = self.service.events().update(
            calendarId='primary',
            eventId=event_id,
            body=event
        ).execute()
        
        # Update local database
        try:
            local_event = Event.objects.get(google_event_id=event_id)
            for key, value in kwargs.items():
                setattr(local_event, key, value)
            local_event.save()
        except Event.DoesNotExist:
            pass
        
        return updated_event

    def delete_event(self, event_id):
        """Delete event from Google Calendar"""
        self.service.events().delete(
            calendarId='primary',
            eventId=event_id
        ).execute()
        
        # Delete from local database
        try:
            Event.objects.filter(google_event_id=event_id).delete()
        except Event.DoesNotExist:
            pass