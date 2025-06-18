from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from calendar_app.models import GoogleCalendarToken
from calendar_app.google_calendar import GoogleCalendarService

class Command(BaseCommand):
    help = 'Sync all users calendars with Google Calendar'

    def add_arguments(self, parser):
        parser.add_argument(
            '--user-id',
            type=int,
            help='Sync calendar for specific user ID only'
        )

    def handle(self, *args, **options):
        if options['user_id']:
            users = User.objects.filter(id=options['user_id'])
        else:
            # Get all users who have Google Calendar tokens
            user_ids = GoogleCalendarToken.objects.values_list('user_id', flat=True)
            users = User.objects.filter(id__in=user_ids)

        synced_count = 0
        error_count = 0

        for user in users:
            try:
                self.stdout.write(f'Syncing calendar for user: {user.username}')
                calendar_service = GoogleCalendarService(user)
                events = calendar_service.get_events()
                synced_count += len(events)
                self.stdout.write(
                    self.style.SUCCESS(f'✓ Synced {len(events)} events for {user.username}')
                )
            except Exception as e:
                error_count += 1
                self.stdout.write(
                    self.style.ERROR(f'✗ Failed to sync for {user.username}: {str(e)}')
                )

        self.stdout.write(
            self.style.SUCCESS(
                f'\nSync completed: {synced_count} events synced, {error_count} errors'
            )
        )