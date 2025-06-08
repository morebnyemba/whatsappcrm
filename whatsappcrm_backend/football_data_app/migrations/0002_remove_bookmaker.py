from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):

    dependencies = [
        ('football_data_app', '0001_initial'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='market',
            name='bookmaker',
        ),
        migrations.DeleteModel(
            name='Bookmaker',
        ),
        migrations.AlterField(
            model_name='market',
            name='fixture_display',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='markets', to='football_data_app.footballfixture'),
        ),
        migrations.AlterUniqueTogether(
            name='market',
            unique_together={('fixture_display', 'api_market_key')},
        ),
    ] 