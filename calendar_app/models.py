from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta, datetime, date, time # Ensure date and time are imported

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
        ('once', 'One Time'),
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        # ('monthly', 'Monthly'), # Kept original choices, you can add monthly back if needed
    ]
    
    PRIORITY_CHOICES = [
        ('Low', 'Low'),
        ('Medium', 'Medium'),
        ('High', 'High'),
    ]
    
    WEEKDAY_CHOICES = [
        (0, 'Monday'),
        (1, 'Tuesday'),
        (2, 'Wednesday'),
        (3, 'Thursday'),
        (4, 'Friday'),
        (5, 'Saturday'),
        (6, 'Sunday'), # Matches JS getDay() and Python weekday() for consistency if Sunday is 0
    ]

    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES, default='once', null=True)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='Medium', blank=True, null=True)
    
    # Timing fields for ALL tasks
    start_date = models.DateField(null=True, blank=True, help_text="Date for one-time task or start date for recurring task")
    time_of_day = models.TimeField(blank=True, null=True, help_text="Start time of the task")
    end_time_of_day = models.TimeField(blank=True, null=True, help_text="End time of the task (optional)")
    
    weekday = models.IntegerField(choices=WEEKDAY_CHOICES, null=True, blank=True, help_text="Day of week for weekly tasks (0=Monday, 6=Sunday)")
    
    # due_date = models.DateTimeField(null=True, blank=True, help_text="For one-time tasks (deprecated, use start_date and time_of_day)")
    
    recurring_end_date = models.DateField(null=True, blank=True, help_text="When recurring task series ends (optional)") # Renamed from end_date for clarity
    
    color = models.CharField(max_length=7, default="#2d5a3d", blank=True, null=True, help_text="Hex color code for the task (e.g., #FF5733)")

    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    def get_occurrences(self, view_start_date, view_end_date):
        # print(f"DEBUG: Task '{self.title}' get_occurrences for period: {view_start_date} to {view_end_date}")
        occurrences = []

        if not self.start_date or not self.time_of_day:
            # print(f"DEBUG: Task '{self.title}' missing start_date or time_of_day. Skipping.")
            return occurrences

        task_start_datetime_for_logic = datetime.combine(self.start_date, self.time_of_day)

        if self.frequency == 'once':
            if view_start_date <= self.start_date <= view_end_date:
                occurrence_dt = timezone.make_aware(datetime.combine(self.start_date, self.time_of_day))
                occurrences.append({
                    'date': self.start_date,
                    'datetime': occurrence_dt,
                    'task': self, # self provides access to all task fields including end_time_of_day and color
                    'hour': occurrence_dt.hour
                })
            # print(f"DEBUG: Task '{self.title}' (once) occurrences: {len(occurrences)}")
            return occurrences

        # For recurring tasks
        current_date = max(view_start_date, self.start_date)
        # Determine the effective end date for the loop
        loop_end_date = view_end_date
        if self.recurring_end_date:
            loop_end_date = min(view_end_date, self.recurring_end_date)
        
        # print(f"DEBUG: Task '{self.title}' ({self.frequency}) looping from {current_date} to {loop_end_date}")

        if self.frequency == 'daily':
            while current_date <= loop_end_date:
                if current_date >= self.start_date: # Ensure we don't go before task's own start_date
                    occurrence_dt = timezone.make_aware(datetime.combine(current_date, self.time_of_day))
                    occurrences.append({
                        'date': current_date,
                        'datetime': occurrence_dt,
                        'task': self,
                        'hour': self.time_of_day.hour
                    })
                current_date += timedelta(days=1)
        
        elif self.frequency == 'weekly':
            if self.weekday is None:
                # print(f"DEBUG: Task '{self.title}' (weekly) missing weekday. Skipping.")
                return occurrences

            # Align current_date to the first occurrence on or after self.start_date matching the weekday
            temp_date = self.start_date
            days_to_target_weekday = (self.weekday - temp_date.weekday() + 7) % 7
            first_occurrence_date = temp_date + timedelta(days=days_to_target_weekday)

            current_occurrence_date = first_occurrence_date
            
            # Start iteration from the later of view_start_date or first_occurrence_date, but adjusted to the correct weekday
            if current_occurrence_date < view_start_date:
                weeks_to_add = (view_start_date - current_occurrence_date).days // 7
                if (view_start_date - current_occurrence_date).days % 7 > 0 : # if not perfectly aligned
                     weeks_to_add +=1 # ensure we start on or after view_start_date
                current_occurrence_date += timedelta(weeks=weeks_to_add)


            while current_occurrence_date <= loop_end_date:
                if current_occurrence_date >= self.start_date: # Double check
                    occurrence_dt = timezone.make_aware(datetime.combine(current_occurrence_date, self.time_of_day))
                    occurrences.append({
                        'date': current_occurrence_date,
                        'datetime': occurrence_dt,
                        'task': self,
                        'hour': self.time_of_day.hour
                    })
                current_occurrence_date += timedelta(weeks=1)
        
        # print(f"DEBUG: Task '{self.title}' ({self.frequency}) final occurrences: {len(occurrences)}")
        return occurrences

    def sync_to_google_calendar(self, user, days_to_sync=30):
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
                end_time = start_time + timedelta(minutes=30) # Default duration
                if self.end_time_of_day:
                    # Calculate precise end time if available
                    # Ensure date component is correct if end_time_of_day is next day (e.g. 11 PM to 1 AM)
                    combined_end_datetime = datetime.combine(task_datetime.date(), self.end_time_of_day)
                    if self.end_time_of_day < self.time_of_day: # crosses midnight
                        combined_end_datetime += timedelta(days=1)
                    end_time = timezone.make_aware(combined_end_datetime, task_datetime.tzinfo)


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

    def __str__(self):
        return self.title or "Untitled Task"


class TaskCompletion(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    completion_date = models.DateField()
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['task', 'user', 'completion_date']

    def __str__(self):
        return f"{self.task.title} completed on {self.completion_date}"