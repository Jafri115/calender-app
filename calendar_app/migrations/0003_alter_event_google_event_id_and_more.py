# Generated by Django 5.2.3 on 2025-06-18 18:03

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('calendar_app', '0002_task'),
    ]

    operations = [
        migrations.AlterField(
            model_name='event',
            name='google_event_id',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AlterField(
            model_name='googlecalendartoken',
            name='refresh_token',
            field=models.TextField(blank=True, null=True),
        ),
    ]
