from django.contrib import admin
from django.utils.html import format_html

from .models import ChatMessage, ExtraGenerationPurchase, RecoveryRequest, TryOnGeneration


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("user", "sender", "linked_generation", "created_at", "short_text")
    list_filter = ("sender", "created_at")
    search_fields = ("user__email", "text", "external_reference_url", "linked_generation__summary")
    autocomplete_fields = ("user", "linked_generation")

    @staticmethod
    def short_text(obj):
        return (obj.text or "")[:60]


@admin.register(RecoveryRequest)
class RecoveryRequestAdmin(admin.ModelAdmin):
    list_display = ("email", "user", "created_at", "short_details")
    list_filter = ("created_at",)
    search_fields = ("email", "details", "user__email")
    autocomplete_fields = ("user",)

    @staticmethod
    def short_details(obj):
        return obj.details[:60]


@admin.register(TryOnGeneration)
class TryOnGenerationAdmin(admin.ModelAdmin):
    list_display = ("user", "category", "provider", "used_ai", "consumed_extra_credit", "created_at")
    list_filter = ("category", "provider", "used_ai", "consumed_extra_credit", "created_at")
    search_fields = ("user__email", "summary")
    autocomplete_fields = ("user",)

    def has_add_permission(self, request):
        return False


@admin.action(description="Одобрить выбранные покупки")
def mark_purchases_paid(modeladmin, request, queryset):
    for purchase in queryset.exclude(status=ExtraGenerationPurchase.STATUS_PAID):
        purchase.status = ExtraGenerationPurchase.STATUS_PAID
        purchase.approved_by = request.user if request.user.is_authenticated else None
        purchase.save()


@admin.action(description="Пометить выбранные покупки как ожидающие проверки")
def mark_purchases_review(modeladmin, request, queryset):
    for purchase in queryset.exclude(status=ExtraGenerationPurchase.STATUS_PAID):
        purchase.status = ExtraGenerationPurchase.STATUS_REVIEW if purchase.receipt_image else ExtraGenerationPurchase.STATUS_PENDING
        purchase.approved_by = None
        purchase.approved_at = None
        purchase.save()


@admin.register(ExtraGenerationPurchase)
class ExtraGenerationPurchaseAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "quantity",
        "unit_price_rub",
        "total_price_rub",
        "status",
        "receipt_badge",
        "created_at",
        "approved_at",
    )
    list_filter = ("status", "created_at", "approved_at", "receipt_uploaded_at")
    search_fields = ("user__email", "payment_note", "admin_comment")
    actions = (mark_purchases_paid, mark_purchases_review)
    autocomplete_fields = ("user", "approved_by")
    readonly_fields = ("total_price_rub", "receipt_preview")

    @staticmethod
    def receipt_badge(obj):
        return "есть" if obj.receipt_image else "—"

    @staticmethod
    def receipt_preview(obj):
        if not obj.receipt_image:
            return "Чек не загружен"
        return format_html('<img src="{}" style="max-width: 240px; border-radius: 12px; border: 1px solid #e2e8f0;" />', obj.receipt_image.url)
