from django.db import migrations, models
from django.utils import timezone

def set_initial_status(apps, schema_editor):
    FootballFixture = apps.get_model('football_data_app', 'FootballFixture')
    for fixture in FootballFixture.objects.all():
        if fixture.completed:
            fixture.status = 'COMPLETED'
        elif fixture.commence_time <= timezone.now():
            fixture.status = 'STARTED'
        else:
            fixture.status = 'PENDING'
        fixture.save()

class Migration(migrations.Migration):

    dependencies = [
        ('football_data_app', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='footballfixture',
            name='status',
            field=models.CharField(
                choices=[
                    ('PENDING', 'Pending'),
                    ('STARTED', 'Started'),
                    ('COMPLETED', 'Completed'),
                    ('CANCELLED', 'Cancelled'),
                ],
                db_index=True,
                default='PENDING',
                max_length=20
            ),
        ),
        migrations.RunPython(set_initial_status),
        migrations.RemoveField(
            model_name='footballfixture',
            name='completed',
        ),
    ] 