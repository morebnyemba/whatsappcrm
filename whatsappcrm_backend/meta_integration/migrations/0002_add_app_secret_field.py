# Generated manually for adding app_secret field

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('meta_integration', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='metaappconfig',
            name='app_secret',
            field=models.CharField(blank=True, help_text='The App Secret from the Meta App Dashboard, used for verifying webhook signature. Recommended for security.', max_length=255, null=True),
        ),
    ]
