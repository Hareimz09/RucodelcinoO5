from __future__ import annotations

import base64
import io
import os
import tempfile
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageFilter, ImageOps

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    cv2 = None

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    np = None


class TryOnError(Exception):
    """Raised when the try-on request cannot be processed."""


@dataclass(slots=True)
class TryOnResult:
    image_bytes: bytes
    provider: str
    used_ai: bool
    warnings: list[str]


@dataclass(slots=True)
class Placement:
    x: int
    y: int
    width: int
    height: int


MAX_INPUT_SIDE = 1280
MIN_OUTPUT_SIZE = 512
FaceBox = tuple[int, int, int, int]


def perform_tryon(
    *,
    category: str,
    user_image_bytes: bytes,
    accessory_image_bytes: bytes,
    summary: str,
    selections: dict[str, Any] | None = None,
) -> TryOnResult:
    """Create a server-side try-on result."""

    if category not in {"hat", "jewelry"}:
        raise TryOnError("Неизвестная категория примерки.")

    user_photo = _load_user_photo(user_image_bytes)
    accessory = _load_accessory(accessory_image_bytes)

    placement, face_box, warnings = _estimate_placement(user_photo, accessory, category)
    composited, mask = _compose_accessory(
        user_photo,
        accessory,
        placement,
        category=category,
        face_box=face_box,
    )

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    provider = os.getenv("AI_TRYON_PROVIDER", "openai").strip().lower() or "openai"
    enable_ai = provider == "openai" and bool(api_key)

    if enable_ai:
        try:
            image_bytes = _refine_with_openai(
                base_image=composited,
                mask_image=mask,
                accessory_image=accessory,
                category=category,
                summary=summary,
                selections=selections or {},
                api_key=api_key,
            )
            return TryOnResult(
                image_bytes=image_bytes,
                provider="openai",
                used_ai=True,
                warnings=warnings,
            )
        except Exception as exc:  # pragma: no cover - network/runtime fallback
            warnings.append(f"AI-уточнение недоступно, использован серверный fallback: {exc}")

    output = io.BytesIO()
    composited.save(output, format="PNG")
    return TryOnResult(
        image_bytes=output.getvalue(),
        provider="server-fallback",
        used_ai=False,
        warnings=warnings,
    )



def _load_user_photo(image_bytes: bytes) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(image_bytes))
    except Exception as exc:
        raise TryOnError("Не удалось открыть фото пользователя.") from exc

    image = ImageOps.exif_transpose(image).convert("RGBA")
    return _downscale_image(image, MAX_INPUT_SIDE)



def _load_accessory(image_bytes: bytes) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    except Exception as exc:
        raise TryOnError("Не удалось открыть изображение изделия.") from exc

    image = ImageOps.exif_transpose(image)

    transparent = image.copy()
    pixels = transparent.load()
    width, height = transparent.size
    for y in range(height):
        for x in range(width):
            r, g, b, a = pixels[x, y]
            if a == 0:
                continue
            if r > 242 and g > 242 and b > 242:
                pixels[x, y] = (255, 255, 255, 0)

    bbox = transparent.getbbox()
    if bbox:
        transparent = transparent.crop(bbox)
    transparent = _downscale_image(transparent, 1024)

    if transparent.width < 10 or transparent.height < 10:
        raise TryOnError("Изображение изделия получилось пустым после обработки.")

    return transparent



def _downscale_image(image: Image.Image, max_side: int) -> Image.Image:
    width, height = image.size
    largest = max(width, height)
    if largest <= max_side:
        return image

    scale = max_side / float(largest)
    resized = image.resize(
        (max(int(width * scale), 1), max(int(height * scale), 1)),
        Image.Resampling.LANCZOS,
    )
    return resized



def _estimate_placement(
    user_photo: Image.Image,
    accessory: Image.Image,
    category: str,
) -> tuple[Placement, FaceBox | None, list[str]]:
    width, height = user_photo.size
    face_box = _detect_face_box(user_photo)
    warnings: list[str] = []

    if face_box is None:
        warnings.append("Лицо не найдено автоматически, использована приблизительная посадка.")
        if category == "hat":
            target_width = int(width * 0.42)
            target_height = int(target_width * accessory.height / max(accessory.width, 1))
            x = int((width - target_width) / 2)
            y = max(int(height * 0.03), 0)
            return Placement(x=x, y=y, width=target_width, height=target_height), None, warnings

        target_width = int(width * 0.36)
        target_height = int(target_width * accessory.height / max(accessory.width, 1))
        x = int((width - target_width) / 2)
        y = int(height * 0.52)
        return Placement(x=x, y=y, width=target_width, height=target_height), None, warnings

    face_x, face_y, face_w, face_h = face_box
    accessory_aspect = accessory.height / max(accessory.width, 1)

    if category == "hat":
        ideal_width = face_w * 1.15
        max_height = face_h * 0.74
        target_width = int(ideal_width)
        target_height = int(target_width * accessory_aspect)
        if target_height > max_height:
            target_height = int(max_height)
            target_width = int(target_height / max(accessory_aspect, 0.01))

        target_width = max(int(face_w * 1.02), min(target_width, int(face_w * 1.30)))
        target_height = int(target_width * accessory_aspect)

        bottom_anchor = int(face_y + face_h * 0.22)
        x = int(face_x + face_w / 2 - target_width / 2)
        y = int(bottom_anchor - target_height)
    else:
        target_width = int(face_w * 1.08)
        target_height = int(target_width * accessory_aspect)
        x = int(face_x + face_w / 2 - target_width / 2)
        y = int(face_y + face_h * 0.88)

    target_width = max(target_width, MIN_OUTPUT_SIZE // 4)
    target_height = max(target_height, MIN_OUTPUT_SIZE // 4)
    x = max(min(x, width - target_width), 0)
    y = max(min(y, height - target_height), 0)

    return Placement(x=x, y=y, width=target_width, height=target_height), face_box, warnings



def _detect_face_box(user_photo: Image.Image) -> FaceBox | None:
    if cv2 is None:
        return None

    try:
        rgb = user_photo.convert("RGB")
        bgr = cv2.cvtColor(__import__("numpy").array(rgb), cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        cascade_paths = [
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml",
            cv2.data.haarcascades + "haarcascade_frontalface_alt2.xml",
        ]
        faces = []
        for cascade_path in cascade_paths:
            classifier = cv2.CascadeClassifier(cascade_path)
            detected = classifier.detectMultiScale(
                gray,
                scaleFactor=1.08,
                minNeighbors=5,
                minSize=(80, 80),
            )
            if len(detected):
                faces.extend(detected)
    except Exception:
        return None

    if len(faces) == 0:
        return None

    faces_sorted = sorted(faces, key=lambda item: item[2] * item[3], reverse=True)
    x, y, w, h = faces_sorted[0]
    return int(x), int(y), int(w), int(h)



def _compose_accessory(
    user_photo: Image.Image,
    accessory: Image.Image,
    placement: Placement,
    *,
    category: str,
    face_box: FaceBox | None,
) -> tuple[Image.Image, Image.Image]:
    result = user_photo.copy()

    fitted = accessory.resize((placement.width, placement.height), Image.Resampling.LANCZOS)
    alpha = fitted.getchannel("A")

    composite_alpha = alpha.filter(ImageFilter.GaussianBlur(radius=max(1, placement.width // 180)))
    fitted.putalpha(composite_alpha)
    result.alpha_composite(fitted, dest=(placement.x, placement.y))

    edit_region = alpha
    if category == "hat" and face_box is not None:
        edit_region = _limit_hat_edit_region(alpha, placement, face_box)

    expand_size = _odd(max(5, placement.width // 90))
    edit_region = edit_region.filter(ImageFilter.MaxFilter(size=expand_size))
    edit_region = edit_region.filter(ImageFilter.GaussianBlur(radius=max(2, placement.width // 180)))

    transparent_hole = ImageOps.invert(edit_region)
    mask_alpha = Image.new("L", user_photo.size, 255)
    mask_alpha.paste(transparent_hole, (placement.x, placement.y))

    mask = Image.new("RGBA", user_photo.size, (255, 255, 255, 255))
    mask.putalpha(mask_alpha)
    return result, mask



def _limit_hat_edit_region(alpha: Image.Image, placement: Placement, face_box: FaceBox) -> Image.Image:
    if np is None:
        return alpha

    face_x, face_y, face_w, face_h = face_box
    _ = face_x, face_w  # reserved for future tuning

    cutoff = int((face_y - placement.y) + face_h * 0.18)
    band = max(8, face_h // 16)
    alpha_array = np.array(alpha, dtype=np.float32)
    height = alpha_array.shape[0]

    fade = np.ones((height, 1), dtype=np.float32)
    for row in range(height):
        if row <= cutoff - band:
            value = 1.0
        elif row >= cutoff + band:
            value = 0.0
        else:
            value = float(cutoff + band - row) / float(2 * band)
        fade[row, 0] = max(0.0, min(1.0, value))

    limited = (alpha_array * fade).clip(0, 255).astype("uint8")
    return Image.fromarray(limited, mode="L")



def _odd(value: int) -> int:
    return value if value % 2 == 1 else value + 1



def _refine_with_openai(
    *,
    base_image: Image.Image,
    mask_image: Image.Image,
    accessory_image: Image.Image,
    category: str,
    summary: str,
    selections: dict[str, Any],
    api_key: str,
) -> bytes:
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    prompt = _build_openai_prompt(
        category=category,
        summary=summary,
        selections=selections,
    )

    model = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1.5").strip() or "gpt-image-1.5"
    quality = os.getenv("OPENAI_IMAGE_QUALITY", "medium").strip() or "medium"
    input_fidelity = os.getenv("OPENAI_INPUT_FIDELITY", "high").strip() or "high"

    with tempfile.TemporaryDirectory() as temp_dir:
        base_path = os.path.join(temp_dir, "base.png")
        mask_path = os.path.join(temp_dir, "mask.png")
        accessory_path = os.path.join(temp_dir, "accessory.png")

        base_image.save(base_path, format="PNG")
        mask_image.save(mask_path, format="PNG")
        accessory_image.save(accessory_path, format="PNG")

        with open(base_path, "rb") as base_file, open(mask_path, "rb") as mask_file, open(accessory_path, "rb") as accessory_file:
            response = client.images.edit(
                model=model,
                image=[base_file, accessory_file],
                mask=mask_file,
                prompt=prompt,
                input_fidelity=input_fidelity,
                quality=quality,
                size="auto",
                output_format="png",
            )

    if not response.data or not response.data[0].b64_json:
        raise TryOnError("Провайдер AI не вернул изображение.")

    return base64.b64decode(response.data[0].b64_json)



def _build_openai_prompt(*, category: str, summary: str, selections: dict[str, Any]) -> str:
    prompt_parts = [
        "Image 1 is the original person photo with a rough server-side accessory placement.",
        "Image 2 is the clean product reference.",
        "Change only the transparent masked region in image 1.",
        "Keep everything outside the mask identical to image 1.",
        "Preserve the same person identity exactly: face shape, eyes, eyebrows, nose, lips, skin texture, age, expression, hair outside the masked region, body proportions, clothing, pose, framing, background, and lighting.",
        "Do not beautify, retouch, relight, reshape, change gender, or alter facial features. Do not change any visible facial pixel outside the accessory contact edge.",
        "Use image 2 only to match the accessory design, silhouette, color, material, and texture.",
        "Make the accessory look naturally worn with realistic contact shadows and occlusion.",
        "The final image must remain a faithful ecommerce try-on photo of the same person.",
    ]

    if category == "hat":
        prompt_parts.append(
            "The accessory is a hat. Keep the forehead, eyes, cheeks, nose, mouth, and jaw unchanged. Only refine the hat region and a very small contact edge with hair. The hat must sit above the eyebrows and must not cover the eyes."
        )
    else:
        prompt_parts.append(
            "The accessory is neck jewelry. Keep the entire face unchanged. Only refine the jewelry and the immediate contact shadows on neck and collarbone."
        )

    if summary:
        prompt_parts.append(f"Product summary: {summary}.")

    selection_lines = []
    for key, value in selections.items():
        if value in (None, "", [], {}):
            continue
        selection_lines.append(f"{key}: {value}")

    if selection_lines:
        prompt_parts.append(f"Selected options: {'; '.join(selection_lines)}.")

    return " ".join(prompt_parts)



def encode_png_data_url(image_bytes: bytes) -> str:
    return f"data:image/png;base64,{base64.b64encode(image_bytes).decode('utf-8')}"



def parse_data_url(data_url: str) -> bytes:
    if not data_url or "," not in data_url:
        raise TryOnError("Некорректный формат изображения.")
    _, encoded = data_url.split(",", 1)
    try:
        return base64.b64decode(encoded)
    except Exception as exc:
        raise TryOnError("Не удалось декодировать изображение.") from exc
