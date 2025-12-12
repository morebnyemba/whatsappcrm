# Generated manually for adding message field to WebhookEventLog

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('conversations', '0001_initial'),
        ('meta_integration', '0002_add_app_secret_field'),
    ]

    operations = [
        migrations.AddField(
            model_name='webhookeventlog',
            name='message',
            field=models.ForeignKey(
                blank=True,
                help_text='Link to the Message object if this webhook event is related to a message.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to='conversations.Message'
            ),
        ),
    ]
