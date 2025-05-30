# Generated by Django 5.1.7 on 2025-05-18 00:33

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('conversations', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='CustomerProfile',
            fields=[
                ('contact', models.OneToOneField(help_text='The contact this profile belongs to.', on_delete=django.db.models.deletion.CASCADE, primary_key=True, related_name='customer_profile', serialize=False, to='conversations.contact')),
                ('email', models.EmailField(blank=True, help_text="Customer's email address, if collected.", max_length=254, null=True)),
                ('preferences', models.JSONField(blank=True, default=dict, help_text='Customer preferences collected over time (e.g., language, interests).')),
                ('custom_attributes', models.JSONField(blank=True, default=dict, help_text='Arbitrary custom attributes collected for this customer.')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True, help_text='Last time this profile record was updated.')),
                ('last_updated_from_conversation', models.DateTimeField(blank=True, help_text='Last time data was explicitly updated from a conversation/flow.', null=True)),
            ],
            options={
                'verbose_name': 'Customer Profile',
                'verbose_name_plural': 'Customer Profiles',
                'ordering': ['-updated_at'],
            },
        ),
    ]
