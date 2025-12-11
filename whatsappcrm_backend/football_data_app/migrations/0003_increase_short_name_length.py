# Generated migration to increase short_name field length

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('football_data_app', '0002_update_for_apifootball'),
    ]

    operations = [
        migrations.AlterField(
            model_name='league',
            name='short_name',
            field=models.CharField(blank=True, help_text='Short name or title for the league from API (e.g., EPL).', max_length=200, null=True),
        ),
    ]
