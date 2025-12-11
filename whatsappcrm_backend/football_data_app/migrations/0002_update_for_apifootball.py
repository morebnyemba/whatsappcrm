# Generated migration for APIFootball integration

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('football_data_app', '0001_initial'),
    ]

    operations = [
        # Update Configuration model
        migrations.AlterField(
            model_name='configuration',
            name='provider_name',
            field=models.CharField(
                choices=[('APIFootball', 'APIFootball.com'), ('The Odds API', 'The Odds API')],
                default='APIFootball',
                help_text='Football data API provider',
                max_length=50
            ),
        ),
        migrations.AlterField(
            model_name='configuration',
            name='email',
            field=models.EmailField(help_text='Contact email for this API configuration', max_length=254),
        ),
        migrations.AlterField(
            model_name='configuration',
            name='api_key',
            field=models.CharField(help_text='API key for authentication', max_length=100),
        ),
        migrations.AddField(
            model_name='configuration',
            name='is_active',
            field=models.BooleanField(default=True, help_text='Whether this configuration is currently active'),
        ),
        migrations.AddField(
            model_name='configuration',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, null=True),
        ),
        migrations.AddField(
            model_name='configuration',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, null=True),
        ),
        
        # Update League model with APIFootball fields
        migrations.AddField(
            model_name='league',
            name='country_id',
            field=models.CharField(blank=True, help_text='Country ID from APIFootball.', max_length=50, null=True),
        ),
        migrations.AddField(
            model_name='league',
            name='country_name',
            field=models.CharField(blank=True, help_text='Country name from APIFootball.', max_length=100, null=True),
        ),
        migrations.AddField(
            model_name='league',
            name='league_season',
            field=models.CharField(blank=True, help_text="Current season (e.g., '2023/2024').", max_length=50, null=True),
        ),
        migrations.AlterField(
            model_name='league',
            name='api_id',
            field=models.CharField(
                help_text="The unique key for the league from the API (e.g., 'soccer_epl' or league_id from APIFootball).",
                max_length=100,
                unique=True
            ),
        ),
        
        # Update Team model
        migrations.AddField(
            model_name='team',
            name='badge_url',
            field=models.URLField(blank=True, help_text='Alternative badge/logo URL from APIFootball.', max_length=512, null=True),
        ),
        
        # Update Configuration meta ordering
        migrations.AlterModelOptions(
            name='configuration',
            options={'ordering': ['-is_active', '-created_at'], 'verbose_name': 'Configuration', 'verbose_name_plural': 'Configurations'},
        ),
    ]
