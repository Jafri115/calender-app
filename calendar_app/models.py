from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone # Still useful for other things, like created_at/updated_at
from datetime import timedelta, datetime, date, time

class GoogleCalendarToken(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    access_token = models.TextField()
    refresh_token = models.TextField(blank=True, null=True)
    token_expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Token for {self.user.username}"

class Event(models.Model): # Assuming GCal Events are still timezone-aware
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    google_event_id = models.CharField(max_length=255, blank=True, null=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    start_time = models.DateTimeField() # Store as aware (UTC typically by GCal)
    end_time = models.DateTimeField()   # Store as aware
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
    ]
    
    PRIORITY_CHOICES = [
        ('Low', 'Low'),
        ('Medium', 'Medium'),
        ('High', 'High'),
    ]
    
    WEEKDAY_CHOICES = [
        (0, 'Monday'), (1, 'Tuesday'), (2, 'Wednesday'),
        (3, 'Thursday'), (4, 'Friday'), (5, 'Saturday'), (6, 'Sunday'),
    ]

    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES, default='once', null=True)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='Medium', blank=True, null=True)
    
    start_date = models.DateField(null=True, blank=True, help_text="Date for one-time task or start date for recurring task")
    time_of_day = models.TimeField(blank=True, null=True, help_text="Start time of the task") # Stored as naive time
    end_time_of_day = models.TimeField(blank=True, null=True, help_text="End time of the task (optional)") # Stored as naive time
    
    weekday = models.IntegerField(choices=WEEKDAY_CHOICES, null=True, blank=True, help_text="Day of week for weekly tasks (0=Monday, 6=Sunday)")
    recurring_end_date = models.DateField(null=True, blank=True, help_text="When recurring task series ends (optional)")
    color = models.CharField(max_length=7, default="#AEC6CF", blank=True, null=True, help_text="Hex color code for the task (e.g., #FF5733)")

    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    def get_occurrences(self, view_start_date, view_end_date):
        occurrences = []
        if not self.start_date or not self.time_of_day:
            return occurrences

        if isinstance(view_start_date, datetime): view_start_date = view_start_date.date()
        if isinstance(view_end_date, datetime): view_end_date = view_end_date.date()
        
        if self.frequency == 'once':
            if self.start_date >= view_start_date and self.start_date <= view_end_date:
                occurrence_dt_naive = datetime.combine(self.start_date, self.time_of_day) # Keep naive
                occurrences.append({
                    'date': self.start_date,
                    'datetime': occurrence_dt_naive, # Store naive datetime
                    'task': self,
                    'hour': self.time_of_day.hour
                })
            return occurrences

        current_date_iter = max(view_start_date, self.start_date)
        loop_end_date = view_end_date
        if self.recurring_end_date:
            loop_end_date = min(view_end_date, self.recurring_end_date)
        
        if self.frequency == 'daily':
            while current_date_iter <= loop_end_date:
                if current_date_iter >= self.start_date: 
                    occurrence_dt_naive = datetime.combine(current_date_iter, self.time_of_day) # Keep naive
                    occurrences.append({
                        'date': current_date_iter,
                        'datetime': occurrence_dt_naive, # Store naive datetime
                        'task': self,
                        'hour': self.time_of_day.hour
                    })
                current_date_iter += timedelta(days=1)
        
        elif self.frequency == 'weekly':
            if self.weekday is None: return occurrences
            temp_date = self.start_date
            days_to_target_weekday = (self.weekday - temp_date.weekday() + 7) % 7
            first_occurrence_date = temp_date + timedelta(days=days_to_target_weekday)
            current_occurrence_date = first_occurrence_date
            if current_occurrence_date < view_start_date:
                weeks_to_add = (view_start_date - current_occurrence_date).days // 7
                if (view_start_date - current_occurrence_date).days % 7 > 0 : weeks_to_add +=1 
                current_occurrence_date += timedelta(weeks=weeks_to_add)
            while current_occurrence_date <= loop_end_date:
                if current_occurrence_date >= self.start_date: 
                    occurrence_dt_naive = datetime.combine(current_occurrence_date, self.time_of_day) # Keep naive
                    occurrences.append({
                        'date': current_occurrence_date,
                        'datetime': occurrence_dt_naive, # Store naive datetime
                        'task': self,
                        'hour': self.time_of_day.hour
                    })
                current_occurrence_date += timedelta(weeks=1)
        
        return occurrences

    def sync_to_google_calendar(self, user, days_to_sync=30):
        # Google Calendar API expects aware datetimes, usually UTC.
        # So, when syncing, we *will* make them aware.
        from .google_calendar import GoogleCalendarService 
        if not self.time_of_day:
            return 0, "Task must have a time of day to be synced."
        try:
            calendar_service = GoogleCalendarService(user)
        except Exception as e:
            return 0, f"Could not connect to Google Calendar: {e}"

        today_date = timezone.now().date() 
        end_date_for_sync = today_date + timedelta(days=days_to_sync)
        
        # Get occurrences as naive datetimes first
        occurrences_to_sync_naive = self.get_occurrences(today_date, end_date_for_sync)
        
        synced_count = 0
        for occ_naive in occurrences_to_sync_naive:
            task_datetime_naive = occ_naive['datetime'] # This is naive
            
            # Make it aware using current Django timezone for GCal.
            # GCal service should handle conversion to UTC if needed.
            task_datetime_aware = timezone.make_aware(task_datetime_naive) 

            unique_marker = f"[Synced Task ID: {self.id}, Date: {task_datetime_aware.date()}]"
            
            try:
                start_time_gcal = task_datetime_aware 
                end_time_gcal = start_time_gcal + timedelta(minutes=30) 
                
                if self.end_time_of_day:
                    end_datetime_naive_local = datetime.combine(task_datetime_naive.date(), self.end_time_of_day)
                    if self.end_time_of_day < self.time_of_day: 
                        end_datetime_naive_local += timedelta(days=1)
                    end_time_gcal = timezone.make_aware(end_datetime_naive_local, task_datetime_aware.tzinfo)

                calendar_service.create_event(
                    title=f"✅ {self.title}",
                    start_time=start_time_gcal, 
                    end_time=end_time_gcal,  
                    description=f"{self.description or ''}\n\n{unique_marker}",
                    location='' 
                )
                synced_count += 1
            except Exception as e:
                print(f"Failed to sync task occurrence '{self.title}' on {task_datetime_aware.date()} to Google Calendar: {e}")
        
        return synced_count, f"Successfully synced {synced_count} occurrences to Google Calendar."

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