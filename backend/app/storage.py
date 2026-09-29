import io
import warnings
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import get_settings


def save_image(upload: UploadFile) -> tuple[str, int, int]:
    settings = get_settings()
    raw = upload.file.read(settings.max_upload_bytes + 1)
    if len(raw) > settings.max_upload_bytes:
        raise HTTPException(413, "照片不能超过 5 MB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in {"JPEG", "PNG", "WEBP"}:
                    raise HTTPException(422, "请选择 JPEG、PNG 或 WebP 图片")
                if source.width * source.height > settings.max_image_pixels:
                    raise HTTPException(422, "图片分辨率过大，请压缩后上传")
                if min(source.size) < 64:
                    raise HTTPException(422, "照片太小，请重新拍摄")
                source.load()
                normalized = ImageOps.exif_transpose(source).convert("RGB")
                normalized.thumbnail((1280, 1280))
                # New image strips metadata, including GPS EXIF and source comments.
                clean = Image.new("RGB", normalized.size)
                clean.paste(normalized)
        key = f"{uuid4().hex}.jpg"
        settings.storage_dir.mkdir(parents=True, exist_ok=True)
        clean.save(settings.storage_dir / key, format="JPEG", quality=90)
        return key, clean.width, clean.height
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise HTTPException(422, "无法读取照片，请重新拍摄或选择图片") from exc


def remove_image(key: str) -> None:
    (get_settings().storage_dir / key).unlink(missing_ok=True)
