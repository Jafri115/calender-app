from django.utils import timezone
from datetime import datetime, timedelta
import pytz

def parse_google_datetime(dt_str):
    """Parse Google Calendar datetime string to Django timezone-aware datetime"""
    if 'T' not in dt_str:
        # All-day event
        dt_str += 'T00:00:00'
    
    # Remove Z and add timezone info
    if dt_str.endswith('Z'):
        dt_str = dt_str[:-1] + '+00:00'
    
    return datetime.fromisoformat(dt_str)

def format_datetime_for_google(dt):
    """Format Django datetime for Google Calendar API"""
    if dt.tzinfo is None:
        dt = timezone.make_aware(dt)
    return dt.isoformat()

def get_week_range(date=None):
    """Get start and end of week for given date"""
    if date is None:
        date = timezone.now().date()
    
    start_of_week = date - timedelta(days=date.weekday())
    end_of_week = start_of_week + timedelta(days=6)
    
    return start_of_week, end_of_week

def get_month_range(date=None):
    """Get start and end of month for given date"""
    if date is None:
        date = timezone.now().date()
    
    start_of_month = date.replace(day=1)
    if date.month == 12:
        end_of_month = date.replace(year=date.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        end_of_month = date.replace(month=date.month + 1, day=1) - timedelta(days=1)
    
    return start_of_month, end_of_month