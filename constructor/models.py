from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class ChatMessage(models.Model):
    """Сообщение в чате между клиентом и мастером."""

    SENDER_USER = "user"
    SENDER_MASTER = "master"

    SENDER_CHOICES = (
        (SENDER_USER, "Пользователь"),
        (SENDER_MASTER, "Мастер"),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_messages",
    )
    sender = models.CharField(max_length=10, choices=SENDER_CHOICES)
    text = models.TextField(blank=True)
    linked_generation = models.ForeignKey(
        "TryOnGeneration",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chat_messages",
    )
    external_reference_url = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at",)

    def __str__(self) -> str:  # pragma: no cover - представление для админки
        sender_name = dict(self.SENDER_CHOICES).get(self.sender, self.sender)
        if self.linked_generation_id:
            return f"{sender_name}: работа #{self.linked_generation_id}"
        return f"{sender_name}: {self.text[:30]}"

    @property
    def has_reference(self) -> bool:
        return bool(self.linked_generation_id or self.external_reference_url)


class RecoveryRequest(models.Model):
    """Анкета на восстановление доступа, отправленная пользователем."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="recovery_requests",
    )
    name = models.CharField(max_length=255, blank=True)
    email = models.EmailField()
    details = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:  # pragma: no cover - представление для админки
        return f"{self.email}: {self.details[:30]}"


class TryOnGeneration(models.Model):
    """Сохранённый результат AI-примерки пользователя."""

    CATEGORY_HAT = "hat"
    CATEGORY_JEWELRY = "jewelry"
    CATEGORY_CHOICES = (
        (CATEGORY_HAT, "Шапка"),
        (CATEGORY_JEWELRY, "Украшение"),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tryon_generations",
    )
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    summary = models.TextField(blank=True)
    selections = models.JSONField(default=dict, blank=True)
    provider = models.CharField(max_length=50, default="server-fallback")
    used_ai = models.BooleanField(default=False)
    warnings_text = models.TextField(blank=True)
    consumed_extra_credit = models.BooleanField(default=False)
    user_image = models.ImageField(upload_to="tryons/originals/%Y/%m/")
    accessory_image = models.ImageField(upload_to="tryons/accessories/%Y/%m/")
    result_image = models.ImageField(upload_to="tryons/results/%Y/%m/")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:  # pragma: no cover - представление для админки
        category_name = dict(self.CATEGORY_CHOICES).get(self.category, self.category)
        return f"{self.user} • {category_name} • {self.created_at:%d.%m.%Y %H:%M}"

    @property
    def category_label(self) -> str:
        return dict(self.CATEGORY_CHOICES).get(self.category, self.category)

    @property
    def warnings(self) -> list[str]:
        return [item.strip() for item in self.warnings_text.split("\n") if item.strip()]


class ExtraGenerationPurchase(models.Model):
    """Покупка дополнительных генераций сверх ежемесячного лимита."""

    STATUS_PENDING = "pending"
    STATUS_REVIEW = "review"
    STATUS_PAID = "paid"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = (
        (STATUS_PENDING, "Ожидает оплаты"),
        (STATUS_REVIEW, "Чек отправлен"),
        (STATUS_PAID, "Одобрено"),
        (STATUS_CANCELLED, "Отклонено"),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="extra_generation_purchases",
    )
    quantity = models.PositiveIntegerField(default=1)
    unit_price_rub = models.PositiveIntegerField(default=25)
    total_price_rub = models.PositiveIntegerField(default=25)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    payment_note = models.CharField(max_length=255, blank=True)
    receipt_image = models.ImageField(upload_to="tryons/receipts/%Y/%m/", blank=True)
    receipt_uploaded_at = models.DateTimeField(null=True, blank=True)
    admin_comment = models.CharField(max_length=255, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_extra_generation_purchases",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:  # pragma: no cover - представление для админки
        return f"{self.user} • {self.quantity} × {self.unit_price_rub} ₽ • {self.get_status_display()}"

    @property
    def status_label(self) -> str:
        return dict(self.STATUS_CHOICES).get(self.status, self.status)

    @property
    def has_receipt(self) -> bool:
        return bool(self.receipt_image)

    def save(self, *args, **kwargs):
        self.quantity = max(int(self.quantity or 1), 1)
        self.unit_price_rub = max(int(self.unit_price_rub or 25), 1)
        self.total_price_rub = self.quantity * self.unit_price_rub

        if self.receipt_image and self.receipt_uploaded_at is None:
            self.receipt_uploaded_at = timezone.now()
        elif not self.receipt_image:
            self.receipt_uploaded_at = None

        if self.status == self.STATUS_PENDING and self.receipt_image:
            self.status = self.STATUS_REVIEW

        if self.status == self.STATUS_PAID:
            if self.paid_at is None:
                self.paid_at = timezone.now()
            if self.approved_at is None:
                self.approved_at = timezone.now()
        else:
            self.paid_at = None
            if self.status != self.STATUS_REVIEW:
                self.approved_at = None
                self.approved_by = None

        super().save(*args, **kwargs)
