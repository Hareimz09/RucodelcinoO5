from __future__ import annotations

import json
import os
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from typing import Any
from uuid import uuid4

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login as auth_login, logout as auth_logout
from django.contrib.auth import password_validation
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.validators import URLValidator, validate_email
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.db.models import Sum
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST
from PIL import Image, ImageOps

from constructor.models import ChatMessage, ExtraGenerationPurchase, RecoveryRequest, TryOnGeneration
from constructor.services.ai_tryon import TryOnError, encode_png_data_url, parse_data_url, perform_tryon


HAT_OPTIONS = {
    "hat_colors": ("Чёрный", "Белый", "Красный", "Бежевый"),
    "yarn_types": ("Мохеровая", "Шерстяная", "Хлопковая", "Плюшевая"),
    "hat_models": ("Бини", "Ушанка", "Берет", "Снуд"),
}

JEWELRY_OPTIONS = {
    "bases": ("Проволока", "Леска", "Тросик", "Спандекс"),
    "lengths": ("10 см", "15 см", "20 см", "25 см"),
    "fittings": ("Штифты", "Маскировочная бусина", "Карабины", "Швензы"),
}



def render_page(request: HttpRequest, template_name: str, context: dict[str, Any] | None = None) -> HttpResponse:
    """Render a template with an optional context dictionary."""

    return render(request, template_name, context)


@ensure_csrf_cookie
def home(request: HttpRequest) -> HttpResponse:
    return render_page(request, "constructor/mainpages/home.html")


@ensure_csrf_cookie
def hats_constructor(request: HttpRequest) -> HttpResponse:
    context = {
        **HAT_OPTIONS,
        **_build_tryon_page_context(request),
    }
    return render_page(request, "constructor/mainpages/hats.html", context)


@ensure_csrf_cookie
def jewelry_constructor(request: HttpRequest) -> HttpResponse:
    context = {
        **JEWELRY_OPTIONS,
        **_build_tryon_page_context(request),
    }
    return render_page(request, "constructor/mainpages/jewelry.html", context)


def contact(request: HttpRequest) -> HttpResponse:
    return render_page(request, "constructor/secondarypages/contact.html")


def registration(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("account")

    next_url = request.GET.get("next") or request.POST.get("next") or reverse("account")
    errors: list[str] = []
    form_data = {
        "name": request.POST.get("name", "").strip(),
        "email": request.POST.get("email", "").strip().lower(),
        "agree": request.POST.get("agree") == "on",
    }

    if request.method == "POST":
        password1 = request.POST.get("password1", "")
        password2 = request.POST.get("password2", "")
        agree = form_data["agree"]

        if not form_data["name"]:
            errors.append("Введите имя.")

        try:
            validate_email(form_data["email"])
        except ValidationError:
            errors.append("Введите корректный email.")

        if get_user_model().objects.filter(email__iexact=form_data["email"]).exists():
            errors.append("Пользователь с таким email уже зарегистрирован.")

        if password1 != password2:
            errors.append("Пароли должны совпадать.")

        try:
            password_validation.validate_password(password1)
        except ValidationError as validation_error:
            errors.extend(validation_error.messages)

        if not agree:
            errors.append("Необходимо согласиться с условиями.")

        if not errors:
            user = get_user_model().objects.create_user(
                username=form_data["email"],
                email=form_data["email"],
                first_name=form_data["name"],
            )
            user.set_password(password1)
            user.save()
            auth_login(request, user)
            _configure_session_persistence(request, persist=True)
            return redirect(next_url)

    return render_page(
        request,
        "constructor/secondarypages/registration.html",
        {"errors": errors, "form_data": form_data, "next": next_url},
    )



def login(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("account")

    next_url = request.GET.get("next") or request.POST.get("next") or reverse("account")
    errors: list[str] = []
    form_data = {
        "email": request.POST.get("email", "").strip().lower(),
        "remember": request.POST.get("remember") == "on",
    }

    if request.method == "POST":
        password = request.POST.get("password", "")

        if not form_data["email"] or not password:
            errors.append("Введите email и пароль.")
        else:
            user = authenticate(request, username=form_data["email"], password=password)
            if user is None:
                errors.append("Неверный email или пароль.")
            else:
                auth_login(request, user)
                _configure_session_persistence(request, persist=form_data["remember"])
                return redirect(next_url)

    return render_page(
        request,
        "constructor/secondarypages/login.html",
        {"errors": errors, "form_data": form_data, "next": next_url},
    )



def forgot_password(request: HttpRequest) -> HttpResponse:
    errors: list[str] = []
    success = False

    form_data = {
        "email": request.POST.get("email", "").strip().lower(),
        "name": request.POST.get("name", "").strip(),
        "details": request.POST.get("details", "").strip(),
    }

    if request.method == "POST":
        try:
            validate_email(form_data["email"])
        except ValidationError:
            errors.append("Введите корректный email, который вы указывали при регистрации.")

        user = (
            get_user_model()
            .objects.filter(email__iexact=form_data["email"])
            .first()
            if not errors
            else None
        )

        if user is None and not errors:
            errors.append("Пользователь с таким email не найден.")

        if not form_data["details"]:
            errors.append("Опишите ситуацию, чтобы администратор мог помочь.")

        if not errors and user:
            RecoveryRequest.objects.create(
                user=user,
                name=form_data["name"],
                email=form_data["email"],
                details=form_data["details"],
            )
            success = True
            form_data["details"] = ""

    return render_page(
        request,
        "constructor/secondarypages/forgot_password.html",
        {
            "errors": errors,
            "form_data": form_data,
            "success": success,
            "MASTER_EMAIL": settings.MASTER_EMAIL,
        },
    )



def about05(request: HttpRequest) -> HttpResponse:
    return render_page(request, "constructor/secondarypages/about05.html")



def aboutstore(request: HttpRequest) -> HttpResponse:
    return render_page(request, "constructor/secondarypages/aboutstore.html")



def _get_user_initials(full_name: str, email: str) -> str:
    if full_name:
        parts = full_name.split()
        if len(parts) >= 2:
            return f"{parts[0][0]}{parts[1][0]}".upper()
        return full_name[:2].upper()

    prefix = email.split("@", maxsplit=1)[0]
    return prefix[:2].upper() if prefix else "?"



def _is_master_user(user: Any) -> bool:
    return bool(
        getattr(user, "is_authenticated", False)
        and user.email
        and user.email.lower() == settings.MASTER_EMAIL.lower()
    )



def _month_range(now=None):
    now = now or timezone.localtime()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end



def _get_monthly_limit() -> int:
    return max(int(getattr(settings, "TRYON_MONTHLY_LIMIT", 7)), 0)



def _get_extra_generation_price_rub() -> int:
    return max(int(getattr(settings, "TRYON_EXTRA_GENERATION_PRICE_RUB", 25)), 1)



def _get_generation_count_for_user(user) -> int:
    if not getattr(user, "is_authenticated", False):
        return 0
    start, end = _month_range()
    return TryOnGeneration.objects.filter(user=user, created_at__gte=start, created_at__lt=end).count()



def _get_paid_extra_generations(user) -> int:
    if not getattr(user, "is_authenticated", False):
        return 0
    paid_total = ExtraGenerationPurchase.objects.filter(
        user=user,
        status=ExtraGenerationPurchase.STATUS_PAID,
    ).aggregate(total=Sum("quantity"))["total"]
    return int(paid_total or 0)



def _get_used_extra_generations(user) -> int:
    if not getattr(user, "is_authenticated", False):
        return 0
    return TryOnGeneration.objects.filter(user=user, consumed_extra_credit=True).count()



def _get_available_extra_generations(user) -> int:
    return max(_get_paid_extra_generations(user) - _get_used_extra_generations(user), 0)



def _get_tryon_quota(user) -> dict[str, int]:
    monthly_limit = _get_monthly_limit()
    monthly_used = _get_generation_count_for_user(user) if getattr(user, "is_authenticated", False) else 0
    monthly_remaining = max(monthly_limit - monthly_used, 0)
    extra_available = _get_available_extra_generations(user) if getattr(user, "is_authenticated", False) else 0
    total_remaining = monthly_remaining + extra_available
    return {
        "monthly_limit": monthly_limit,
        "monthly_used": monthly_used,
        "monthly_remaining": monthly_remaining,
        "extra_available": extra_available,
        "total_remaining": total_remaining,
        "extra_price_rub": _get_extra_generation_price_rub(),
    }



def _generation_will_consume_extra_credit(user) -> bool:
    quota = _get_tryon_quota(user)
    return quota["monthly_used"] >= quota["monthly_limit"]



AI_IMAGE_COST_USD = Decimal("0.29")


def _build_tryon_page_context(request: HttpRequest) -> dict[str, Any]:
    quota = _get_tryon_quota(request.user)
    is_master = _is_master_user(request.user)
    can_generate = bool(getattr(request.user, "is_authenticated", False)) and not is_master

    disabled_reason = ""
    if is_master:
        disabled_reason = "Для администратора AI-примерка отключена. В личном кабинете доступна статистика по пользователям."
    elif not getattr(request.user, "is_authenticated", False):
        disabled_reason = "AI-примерка доступна только зарегистрированным пользователям."

    return {
        "ai_tryon_enabled": bool(getattr(settings, "OPENAI_API_KEY", "") or os.getenv("OPENAI_API_KEY")),
        "tryon_requires_auth": True,
        "tryon_monthly_limit": quota["monthly_limit"],
        "tryon_monthly_remaining": quota["monthly_remaining"],
        "tryon_extra_remaining": quota["extra_available"],
        "tryon_remaining": quota["total_remaining"],
        "tryon_extra_price_rub": quota["extra_price_rub"],
        "tryon_login_url": f"{reverse('login')}?next={request.path}",
        "tryon_purchase_url": reverse("extra_generations"),
        "tryon_can_generate": can_generate,
        "tryon_disabled_reason": disabled_reason,
        "tryon_is_master_user": is_master,
    }


def _resolve_generation_reference(user, raw_generation_id: str | None) -> TryOnGeneration | None:
    generation_id = str(raw_generation_id or "").strip()
    if not generation_id:
        return None
    return TryOnGeneration.objects.filter(user=user, id=generation_id).first()


def _clean_reference_url(raw_url: str | None) -> str:
    url = str(raw_url or "").strip()
    if not url:
        return ""
    URLValidator()(url)
    return url


def _create_chat_message(
    *,
    target_user,
    sender: str,
    message_text: str,
    linked_generation: TryOnGeneration | None,
    external_reference_url: str,
) -> ChatMessage:
    final_text = message_text.strip()
    if not final_text and (linked_generation or external_reference_url):
        final_text = "Прикрепил(а) работу для обсуждения."

    return ChatMessage.objects.create(
        user=target_user,
        sender=sender,
        text=final_text,
        linked_generation=linked_generation,
        external_reference_url=external_reference_url,
    )


def _get_master_generation_queryset():
    return TryOnGeneration.objects.exclude(user__email__iexact=settings.MASTER_EMAIL).filter(used_ai=True)


def _build_master_stats() -> dict[str, Any]:
    now = timezone.localtime()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = day_start - timedelta(days=day_start.weekday())
    month_start = day_start.replace(day=1)
    year_start = day_start.replace(month=1, day=1)

    periods = (
        ("day", "За день", day_start),
        ("week", "За неделю", week_start),
        ("month", "За месяц", month_start),
        ("year", "За год", year_start),
    )

    queryset = _get_master_generation_queryset()
    stats_cards: list[dict[str, Any]] = []

    for key, label, period_start in periods:
        count = queryset.filter(created_at__gte=period_start).count()
        cost_usd = (AI_IMAGE_COST_USD * count).quantize(Decimal("0.01"))
        stats_cards.append(
            {
                "key": key,
                "label": label,
                "count": count,
                "cost_usd": f"{cost_usd:.2f}",
            }
        )

    User = get_user_model()
    return {
        "cards": stats_cards,
        "clients_total": User.objects.exclude(email__iexact=settings.MASTER_EMAIL).count(),
        "pending_receipts_count": ExtraGenerationPurchase.objects.exclude(user__email__iexact=settings.MASTER_EMAIL).filter(
            status=ExtraGenerationPurchase.STATUS_REVIEW
        ).count(),
        "recent_receipts": ExtraGenerationPurchase.objects.exclude(user__email__iexact=settings.MASTER_EMAIL).select_related(
            "user",
            "approved_by",
        )[:8],
    }


def _create_extra_purchase(*, user, quantity: int, payment_note: str, receipt_image) -> ExtraGenerationPurchase:
    purchase = ExtraGenerationPurchase(
        user=user,
        quantity=quantity,
        unit_price_rub=_get_extra_generation_price_rub(),
        payment_note=payment_note,
    )
    if receipt_image:
        purchase.receipt_image = receipt_image
        purchase.status = ExtraGenerationPurchase.STATUS_REVIEW
    purchase.save()
    return purchase


def _submit_purchase_receipt(*, purchase: ExtraGenerationPurchase, payment_note: str, receipt_image) -> ExtraGenerationPurchase:
    if payment_note:
        purchase.payment_note = payment_note
    if receipt_image:
        purchase.receipt_image = receipt_image
        purchase.status = ExtraGenerationPurchase.STATUS_REVIEW
    purchase.save()
    return purchase


def _set_purchase_status(*, purchase: ExtraGenerationPurchase, status: str, approved_by=None, admin_comment: str = "") -> ExtraGenerationPurchase:
    purchase.status = status
    purchase.admin_comment = admin_comment.strip()
    purchase.approved_by = approved_by if status == ExtraGenerationPurchase.STATUS_PAID else None
    purchase.approved_at = timezone.now() if status == ExtraGenerationPurchase.STATUS_PAID else None
    purchase.save()
    return purchase


def _parse_purchase_quantity(raw_value: str | None) -> int:
    try:
        quantity = int(str(raw_value or "1").strip())
    except (TypeError, ValueError):
        raise ValidationError("Укажите корректное количество генераций.")

    if quantity < 1:
        raise ValidationError("Количество генераций должно быть больше нуля.")
    if quantity > 100:
        raise ValidationError("За один заказ можно оформить не более 100 генераций.")
    return quantity


def _build_purchase_page_context(user, *, form_data: dict[str, Any] | None = None) -> dict[str, Any]:
    quota = _get_tryon_quota(user)
    unit_price = quota["extra_price_rub"]
    if form_data:
        try:
            quantity_value = max(min(int(form_data.get("quantity") or 1), 100), 1)
        except (TypeError, ValueError):
            quantity_value = 1
        payment_note = str(form_data.get("payment_note") or "")
    else:
        quantity_value = 1
        payment_note = ""
    presets = [1, 3, 5, 10]
    purchases = ExtraGenerationPurchase.objects.filter(user=user).select_related("approved_by").order_by("-created_at")

    return {
        "extra_generation_price_rub": unit_price,
        "extra_generations_available": quota["extra_available"],
        "monthly_limit": quota["monthly_limit"],
        "monthly_remaining": quota["monthly_remaining"],
        "total_generations_remaining": quota["total_remaining"],
        "purchases": purchases,
        "purchase_presets": [
            {
                "quantity": preset,
                "total_price_rub": preset * unit_price,
            }
            for preset in presets
        ],
        "purchase_form": {
            "quantity": quantity_value,
            "payment_note": payment_note,
        },
        "purchase_total_price_rub": quantity_value * unit_price,
    }


@login_required(login_url="login")
def extra_generations(request: HttpRequest) -> HttpResponse:
    user = request.user
    if _is_master_user(user):
        return redirect("account")

    form_data = {
        "quantity": request.POST.get("quantity", request.GET.get("quantity", "1")).strip() or "1",
        "payment_note": request.POST.get("payment_note", "").strip(),
    }

    if request.method == "POST":
        form_type = request.POST.get("form")

        if form_type == "buy_extra_generation":
            try:
                quantity = _parse_purchase_quantity(form_data["quantity"])
            except ValidationError as validation_error:
                messages.error(request, validation_error.messages[0])
            else:
                receipt_image = request.FILES.get("receipt_image")
                purchase = _create_extra_purchase(
                    user=user,
                    quantity=quantity,
                    payment_note=form_data["payment_note"],
                    receipt_image=receipt_image,
                )
                if receipt_image:
                    messages.success(
                        request,
                        f"Заказ на {purchase.quantity} генерац{'ию' if purchase.quantity == 1 else 'ии' if 2 <= purchase.quantity <= 4 else 'ий'} создан. Чек отправлен на проверку. Сумма: {purchase.total_price_rub} ₽.",
                    )
                else:
                    messages.success(
                        request,
                        f"Заказ на {purchase.quantity} генерац{'ию' if purchase.quantity == 1 else 'ии' if 2 <= purchase.quantity <= 4 else 'ий'} создан. Сумма: {purchase.total_price_rub} ₽. После оплаты загрузите чек в карточку заказа.",
                    )
                return redirect("extra_generations")

        elif form_type == "upload_purchase_receipt":
            purchase_id = request.POST.get("purchase_id", "").strip()
            purchase = ExtraGenerationPurchase.objects.filter(
                user=user,
                id=purchase_id,
            ).exclude(status__in=[ExtraGenerationPurchase.STATUS_PAID, ExtraGenerationPurchase.STATUS_CANCELLED]).first()
            receipt_image = request.FILES.get("receipt_image")

            if purchase is None:
                messages.error(request, "Заказ для загрузки чека не найден.")
            elif not receipt_image:
                messages.error(request, "Прикрепите изображение чека.")
            else:
                _submit_purchase_receipt(
                    purchase=purchase,
                    payment_note=request.POST.get("payment_note", "").strip(),
                    receipt_image=receipt_image,
                )
                messages.success(request, "Чек отправлен администратору. После проверки кредиты появятся автоматически.")
                return redirect("extra_generations")

    return render_page(
        request,
        "constructor/secondarypages/extra_generations.html",
        _build_purchase_page_context(user, form_data=form_data),
    )


@login_required(login_url="login")
def account(request: HttpRequest) -> HttpResponse:
    user = request.user
    display_name = user.get_full_name() or user.first_name or user.email or "Ваш профиль"
    is_master = _is_master_user(user)

    works = TryOnGeneration.objects.filter(user=user).order_by("-created_at")
    chat_messages = ChatMessage.objects.filter(user=user).select_related("user", "linked_generation").order_by("created_at")
    purchases = ExtraGenerationPurchase.objects.filter(user=user).order_by("-created_at")[:3]

    message_error: str | None = None
    chat_form = {
        "message": "",
        "linked_generation_id": request.GET.get("work", "").strip(),
        "external_reference_url": "",
    }
    if request.method == "POST":
        form_type = request.POST.get("form")

        if form_type == "chat":
            chat_form = {
                "message": request.POST.get("message", "").strip(),
                "linked_generation_id": request.POST.get("linked_generation_id", "").strip(),
                "external_reference_url": request.POST.get("external_reference_url", "").strip(),
            }
            linked_generation = _resolve_generation_reference(user, chat_form["linked_generation_id"])
            if chat_form["linked_generation_id"] and linked_generation is None:
                message_error = "Прикреплённая работа не найдена в вашем профиле."
            else:
                try:
                    external_reference_url = _clean_reference_url(chat_form["external_reference_url"])
                except ValidationError:
                    message_error = "Ссылка на работу должна быть корректным URL."
                else:
                    if not chat_form["message"] and linked_generation is None and not external_reference_url:
                        message_error = "Введите сообщение или прикрепите работу/ссылку."
                    else:
                        _create_chat_message(
                            target_user=user,
                            sender=ChatMessage.SENDER_MASTER if is_master else ChatMessage.SENDER_USER,
                            message_text=chat_form["message"],
                            linked_generation=linked_generation,
                            external_reference_url=external_reference_url,
                        )
                        return redirect("account")


    quota = _get_tryon_quota(user)
    master_stats = _build_master_stats() if is_master else None

    return render_page(
        request,
        "constructor/secondarypages/account.html",
        {
            "user_display_name": display_name,
            "user_email": user.email,
            "user_initials": _get_user_initials(display_name, user.email or ""),
            "chat_messages": chat_messages,
            "chat_message_count": chat_messages.count(),
            "is_master_user": is_master,
            "message_error": message_error,
            "chat_form": chat_form,
            "works": works,
            "works_count": works.count(),
            "chat_reference_works": works[:20],
            "monthly_limit": quota["monthly_limit"],
            "monthly_used": quota["monthly_used"],
            "monthly_remaining": quota["monthly_remaining"],
            "extra_generations_available": quota["extra_available"],
            "total_generations_remaining": quota["total_remaining"],
            "extra_generation_price_rub": quota["extra_price_rub"],
            "purchases": purchases,
            "master_stats": master_stats,
        },
    )


def privacy(request: HttpRequest) -> HttpResponse:
    return render_page(request, "constructor/secondarypages/privacy.html")


@ensure_csrf_cookie
@user_passes_test(_is_master_user, login_url="login")
def master_chat(request: HttpRequest) -> HttpResponse:
    User = get_user_model()
    clients = User.objects.exclude(email__iexact=settings.MASTER_EMAIL).order_by("first_name", "email")

    selected_user_id = request.POST.get("user_id") or request.GET.get("user_id")
    selected_user = clients.filter(id=selected_user_id).first() if selected_user_id else None
    if not selected_user:
        selected_user = clients.first()

    message_error: str | None = None
    purchase_notice_code = request.GET.get("purchase_notice", "").strip()
    purchase_notice_map = {
        "approved": "Чек подтверждён, дополнительный кредит начислен пользователю.",
        "cancelled": "Заказ отклонён.",
    }
    purchase_notice: str | None = purchase_notice_map.get(purchase_notice_code)
    chat_form = {
        "message": "",
        "linked_generation_id": "",
        "external_reference_url": "",
    }

    if request.method == "POST" and selected_user:
        form_type = request.POST.get("form", "chat")

        if form_type == "chat":
            chat_form = {
                "message": request.POST.get("message", "").strip(),
                "linked_generation_id": request.POST.get("linked_generation_id", "").strip(),
                "external_reference_url": request.POST.get("external_reference_url", "").strip(),
            }
            linked_generation = _resolve_generation_reference(selected_user, chat_form["linked_generation_id"])
            if chat_form["linked_generation_id"] and linked_generation is None:
                message_error = "Выбранная работа клиента не найдена."
            else:
                try:
                    external_reference_url = _clean_reference_url(chat_form["external_reference_url"])
                except ValidationError:
                    message_error = "Ссылка на работу должна быть корректным URL."
                else:
                    if not chat_form["message"] and linked_generation is None and not external_reference_url:
                        message_error = "Введите сообщение или прикрепите работу/ссылку."
                    else:
                        _create_chat_message(
                            target_user=selected_user,
                            sender=ChatMessage.SENDER_MASTER,
                            message_text=chat_form["message"],
                            linked_generation=linked_generation,
                            external_reference_url=external_reference_url,
                        )
                        redirect_url = f"{reverse('master_chat')}?user_id={selected_user.id}"
                        return redirect(redirect_url)

        elif form_type in {"approve_purchase", "cancel_purchase"}:
            purchase_id = request.POST.get("purchase_id", "").strip()
            admin_comment = request.POST.get("admin_comment", "").strip()
            purchase = ExtraGenerationPurchase.objects.filter(user=selected_user, id=purchase_id).first()
            if purchase is None:
                purchase_notice = "Заказ клиента не найден."
            else:
                new_status = (
                    ExtraGenerationPurchase.STATUS_PAID
                    if form_type == "approve_purchase"
                    else ExtraGenerationPurchase.STATUS_CANCELLED
                )
                _set_purchase_status(
                    purchase=purchase,
                    status=new_status,
                    approved_by=request.user if new_status == ExtraGenerationPurchase.STATUS_PAID else None,
                    admin_comment=admin_comment,
                )
                notice_code = "approved" if new_status == ExtraGenerationPurchase.STATUS_PAID else "cancelled"
                return redirect(f"{reverse('master_chat')}?user_id={selected_user.id}&purchase_notice={notice_code}#purchase-management")

    chat_messages = (
        ChatMessage.objects.filter(user=selected_user)
        .select_related("user", "linked_generation")
        .order_by("created_at")
        if selected_user
        else []
    )

    clients_data = [
        {
            "user": client,
            "last_message": ChatMessage.objects.filter(user=client).order_by("-created_at").first(),
            "pending_receipts": ExtraGenerationPurchase.objects.filter(
                user=client,
                status=ExtraGenerationPurchase.STATUS_REVIEW,
            ).count(),
        }
        for client in clients
    ]
    selected_user_works = (
        TryOnGeneration.objects.filter(user=selected_user).order_by("-created_at")[:20]
        if selected_user
        else []
    )
    selected_user_purchases = (
        ExtraGenerationPurchase.objects.filter(user=selected_user)
        .select_related("approved_by")
        .order_by("-created_at")
        if selected_user
        else []
    )

    return render_page(
        request,
        "constructor/secondarypages/master_chat.html",
        {
            "clients": clients_data,
            "clients_count": clients.count(),
            "selected_user": selected_user,
            "selected_user_works": selected_user_works,
            "selected_user_purchases": selected_user_purchases,
            "chat_messages": chat_messages,
            "message_error": message_error,
            "purchase_notice": purchase_notice,
            "chat_form": chat_form,
            "master_stats": _build_master_stats(),
        },
    )


@user_passes_test(_is_master_user, login_url="login")
def master_recovery_requests(request: HttpRequest) -> HttpResponse:
    recovery_requests = RecoveryRequest.objects.select_related("user").order_by("-created_at")

    return render_page(
        request,
        "constructor/secondarypages/master_recovery_requests.html",
        {
            "requests": recovery_requests,
            "requests_count": recovery_requests.count(),
        },
    )


@require_POST
def tryon_api(request: HttpRequest) -> JsonResponse:
    if not request.user.is_authenticated:
        return JsonResponse(
            {
                "ok": False,
                "error": "AI-примерка доступна только зарегистрированным пользователям.",
                "login_url": f"{reverse('login')}?next={request.META.get('HTTP_REFERER') or reverse('account')}",
            },
            status=401,
        )

    if _is_master_user(request.user):
        return JsonResponse(
            {
                "ok": False,
                "error": "Для администратора AI-примерка отключена. Используйте панель статистики в кабинете.",
            },
            status=403,
        )

    quota_before = _get_tryon_quota(request.user)
    if quota_before["total_remaining"] <= 0:
        return JsonResponse(
            {
                "ok": False,
                "error": (
                    "Ежемесячный лимит исчерпан и дополнительных оплаченных генераций пока нет. "
                    f"Можно купить доп. генерации на отдельной странице: 1 шт. за {quota_before['extra_price_rub']} ₽."
                ),
                "remaining_generations": 0,
                "purchase_url": reverse("extra_generations"),
                "quota": quota_before,
            },
            status=403,
        )

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "Тело запроса должно быть JSON."}, status=400)

    category = str(payload.get("category", "")).strip().lower()
    summary = str(payload.get("summary", "")).strip()
    selections = payload.get("selections") if isinstance(payload.get("selections"), dict) else {}

    try:
        user_image_data_url = str(payload.get("user_image", ""))
        accessory_image_data_url = str(payload.get("accessory_image", ""))
        user_image_bytes = parse_data_url(user_image_data_url)
        accessory_image_bytes = parse_data_url(accessory_image_data_url)
        result = perform_tryon(
            category=category,
            user_image_bytes=user_image_bytes,
            accessory_image_bytes=accessory_image_bytes,
            summary=summary,
            selections=selections,
        )
    except TryOnError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    except Exception as exc:
        return JsonResponse({"ok": False, "error": f"Внутренняя ошибка try-on: {exc}"}, status=500)

    generation = TryOnGeneration(
        user=request.user,
        category=category,
        summary=summary,
        selections=selections,
        provider=result.provider,
        used_ai=result.used_ai,
        warnings_text="\n".join(result.warnings),
        consumed_extra_credit=_generation_will_consume_extra_credit(request.user),
    )
    user_content = _make_uploaded_image_content(user_image_bytes, prefix=f"{category}-user")
    accessory_content = _make_uploaded_image_content(accessory_image_bytes, prefix=f"{category}-accessory")
    result_content = _make_uploaded_image_content(result.image_bytes, prefix=f"{category}-result")
    generation.user_image.save(user_content.name, user_content, save=False)
    generation.accessory_image.save(accessory_content.name, accessory_content, save=False)
    generation.result_image.save(result_content.name, result_content, save=False)
    generation.save()

    quota_after = _get_tryon_quota(request.user)

    return JsonResponse(
        {
            "ok": True,
            "result_image": encode_png_data_url(result.image_bytes),
            "provider": result.provider,
            "used_ai": result.used_ai,
            "warnings": result.warnings,
            "remaining_generations": quota_after["total_remaining"],
            "quota": quota_after,
            "generation": {
                "id": generation.id,
                "category": generation.category,
                "category_label": generation.category_label,
                "created_at": timezone.localtime(generation.created_at).strftime("%d.%m.%Y %H:%M"),
                "result_image_url": generation.result_image.url,
                "user_image_url": generation.user_image.url,
                "consumed_extra_credit": generation.consumed_extra_credit,
            },
        }
    )


def _make_uploaded_image_content(image_bytes: bytes, *, prefix: str) -> ContentFile:
    image = Image.open(BytesIO(image_bytes))
    image = ImageOps.exif_transpose(image).convert("RGBA")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return ContentFile(buffer.getvalue(), name=f"{prefix}-{uuid4().hex}.png")



def logout(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        auth_logout(request)
        return redirect("home")

    return redirect("account")



def _configure_session_persistence(request: HttpRequest, persist: bool) -> None:
    default_age = getattr(settings, "SESSION_COOKIE_AGE", 60 * 60 * 24 * 14)
    remember_age = getattr(settings, "REMEMBER_ME_AGE", 60 * 60 * 24 * 30)

    expiry = remember_age if persist else default_age
    request.session.set_expiry(expiry)
