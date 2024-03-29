# Generated by Django 3.2.18 on 2024-01-16 20:36

import django.core.validators
from django.db import migrations, models
import users.validators


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0002_auto_20240110_0856'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='email',
            field=models.EmailField(help_text='Адрес электронной почты', max_length=100, unique=True, validators=[django.core.validators.EmailValidator, users.validators.validate_email_min_length], verbose_name='Адрес электронной почты'),
        ),
    ]
