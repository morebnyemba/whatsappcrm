# Generated by Django 5.1.7 on 2025-06-02 10:59

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('conversations', '0004_alter_message_direction'),
    ]

    operations = [
        migrations.AddField(
            model_name='contact',
            name='current_flow_state',
            field=models.JSONField(blank=True, default=dict, help_text='Stores the current state of the contact within a flow.'),
        ),
        migrations.AddField(
            model_name='contact',
            name='intervention_resolved_at',
            field=models.DateTimeField(blank=True, help_text='Timestamp of when human intervention was resolved.', null=True),
        ),
    ]
