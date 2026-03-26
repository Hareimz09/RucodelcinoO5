from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('constructor', '0002_recoveryrequest'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='TryOnGeneration',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('category', models.CharField(choices=[('hat', 'Шапка'), ('jewelry', 'Украшение')], max_length=20)),
                ('summary', models.TextField(blank=True)),
                ('selections', models.JSONField(blank=True, default=dict)),
                ('provider', models.CharField(default='server-fallback', max_length=50)),
                ('used_ai', models.BooleanField(default=False)),
                ('warnings_text', models.TextField(blank=True)),
                ('user_image', models.ImageField(upload_to='tryons/originals/%Y/%m/')),
                ('accessory_image', models.ImageField(upload_to='tryons/accessories/%Y/%m/')),
                ('result_image', models.ImageField(upload_to='tryons/results/%Y/%m/')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tryon_generations', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ('-created_at',),
            },
        ),
    ]
