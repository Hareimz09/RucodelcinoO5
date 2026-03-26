from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('constructor', '0004_chatmessage_external_reference_url_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='extragenerationpurchase',
            name='admin_comment',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='extragenerationpurchase',
            name='approved_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='extragenerationpurchase',
            name='approved_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='approved_extra_generation_purchases', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='extragenerationpurchase',
            name='receipt_image',
            field=models.ImageField(blank=True, upload_to='tryons/receipts/%Y/%m/'),
        ),
        migrations.AddField(
            model_name='extragenerationpurchase',
            name='receipt_uploaded_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='extragenerationpurchase',
            name='status',
            field=models.CharField(choices=[('pending', 'Ожидает оплаты'), ('review', 'Чек отправлен'), ('paid', 'Одобрено'), ('cancelled', 'Отклонено')], default='pending', max_length=20),
        ),
    ]
