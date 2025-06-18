from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from datetime import datetime
from django.utils import timezone
from datetime import timedelta
class GoogleCalendarToken(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    access_token = models.TextField()
    refresh_token = models.TextField(blank=True, null=True)
    token_expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Token for {self.user.username}"

class Event(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    google_event_id = models.CharField(max_length=255, blank=True, null=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    location = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['start_time']

    def __str__(self):
        return f"{self.title} - {self.start_time}"

class Task(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    title = models.CharField(max_length=200, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    FREQUENCY_CHOICES = [
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
    ]
    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
    ]
    
    FREQUENCY_CHOICES = [
        ('once', 'One Time'),
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
    ]
    
    WEEKDAY_CHOICES = [
        (0, 'Monday'),
        (1, 'Tuesday'),
        (2, 'Wednesday'),
        (3, 'Thursday'),
        (4, 'Friday'),
        (5, 'Saturday'),
        (6, 'Sunday'),
    ]
    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES, null=True)
    time_of_day = models.TimeField(blank=True, null=True)
    weekday = models.IntegerField(choices=WEEKDAY_CHOICES, null=True, blank=True, help_text="Day of week for weekly tasks")
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)
    start_date = models.DateField(null=True, blank=True, help_text="When recurring task starts")
    end_date = models.DateField(null=True, blank=True, help_text="When recurring task ends (optional)")
    
    def get_occurrences(self, start_date, end_date):
        print(f"DEBUG: Called get_occurrences for task '{self.title}' from {start_date} to {end_date}")

        occurrences = []

        if self.frequency == 'once':
                if self.start_date:
                    if start_date <= self.start_date <= end_date:
                        if self.time_of_day:
                            task_datetime = timezone.make_aware(datetime.combine(self.start_date, self.time_of_day))
                        else:
                            task_datetime = timezone.make_aware(datetime.combine(self.start_date, datetime.min.time()))
                        print(f"DEBUG: Adding one-time task occurrence on {self.start_date}")
                        occurrences.append({
                            'date': self.start_date,
                            'datetime': task_datetime,
                            'task': self,
                            'hour': task_datetime.hour
                        })
                else:
                    print("DEBUG: One-time task missing start_date")

                print(f"DEBUG: Occurrences found: {occurrences}")
                return occurrences

        elif self.frequency == 'daily':
            if not self.start_date:
                print("DEBUG: Daily task missing start_date, returning empty occurrences")
                return occurrences
            if not self.time_of_day:
                print("DEBUG: Daily task missing time_of_day, returning empty occurrences")
                return occurrences

            current_date = max(start_date, self.start_date)
            end_limit = min(end_date, self.end_date) if self.end_date else end_date

            print(f"DEBUG: Iterating daily from {current_date} to {end_limit}")
            while current_date <= end_limit:
                task_datetime = timezone.make_aware(datetime.combine(current_date, self.time_of_day))
                occurrences.append({
                    'date': current_date,
                    'datetime': task_datetime,
                    'task': self,
                    'hour': self.time_of_day.hour
                })
                current_date += timedelta(days=1)

            print(f"DEBUG: Occurrences found: {occurrences}")
            return occurrences

        elif self.frequency == 'weekly':
            if not self.start_date:
                print("DEBUG: Weekly task missing start_date, returning empty occurrences")
                return occurrences
            if not self.time_of_day:
                print("DEBUG: Weekly task missing time_of_day, returning empty occurrences")
                return occurrences
            if self.weekday is None:
                print("DEBUG: Weekly task missing weekday, returning empty occurrences")
                return occurrences

            current_date = self.start_date

            # Align to the correct weekday
            days_ahead = self.weekday - current_date.weekday()
            if days_ahead < 0:
                days_ahead += 7
            current_date += timedelta(days=days_ahead)

            # Start at max of current_date and start_date param
            current_date = max(current_date, start_date)
            end_limit = min(end_date, self.end_date) if self.end_date else end_date

            print(f"DEBUG: Iterating weekly from {current_date} to {end_limit} on weekday {self.weekday}")
            while current_date <= end_limit:
                task_datetime = timezone.make_aware(datetime.combine(current_date, self.time_of_day))
                occurrences.append({
                    'date': current_date,
                    'datetime': task_datetime,
                    'task': self,
                    'hour': self.time_of_day.hour
                })
                current_date += timedelta(weeks=1)

            print(f"DEBUG: Occurrences found: {occurrences}")
            return occurrences

        else:
            print(f"DEBUG: Unknown frequency '{self.frequency}', returning empty list")
            return occurrences

    def sync_to_google_calendar(self, user, days_to_sync=30):
        """
        Creates Google Calendar events for the task's occurrences over the next X days.
        """
        from .google_calendar import GoogleCalendarService

        if not self.time_of_day:
            return 0, "Task must have a time of day to be synced."

        try:
            calendar_service = GoogleCalendarService(user)
        except Exception as e:
            return 0, f"Could not connect to Google Calendar: {e}"

        today = timezone.now().date()
        end_date_for_sync = today + timedelta(days=days_to_sync)

        occurrences = self.get_occurrences(today, end_date_for_sync)

        synced_count = 0
        for occ in occurrences:
            task_datetime = occ['datetime']
            unique_marker = f"[Synced Task ID: {self.id}, Date: {task_datetime.date()}]"

            try:
                start_time = task_datetime
                end_time = start_time + timedelta(minutes=30)

                calendar_service.create_event(
                    title=f"✅ {self.title}",
                    start_time=start_time,
                    end_time=end_time,
                    description=f"{self.description}\n\n{unique_marker}",
                    location=''
                )
                synced_count += 1
            except Exception as e:
                print(f"Failed to sync task '{self.title}' on {task_datetime.date()}: {e}")

        return synced_count, f"Successfully synced {synced_count} occurrences."

class TaskCompletion(models.Model):
    """Track completion of recurring tasks on specific dates"""
    task = models.ForeignKey(Task, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    completion_date = models.DateField()
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['task', 'user', 'completion_date']

    def __str__(self):
        return f"{self.task.title} completed on {self.completion_date}"
