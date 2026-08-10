from __future__ import annotations

import warnings
from io import BytesIO
from pathlib import Path
from typing import TypedDict

from werkzeug.datastructures import FileStorage

from .settings import ROOT_DIR, get_settings

try:
    from PIL import Image, ImageOps
except ImportError:  # pragma: no cover - optional dependency
    Image = None
    ImageOps = None


STATIC_DIR = ROOT_DIR / "app" / "web" / "static"
PLACE_UPLOAD_DIR = STATIC_DIR / "uploads" / "places"
SITE_UPLOAD_DIR = STATIC_DIR / "uploads" / "site"

DEFAULT_PLACE_ASSET = "img/places/default-destination.svg"
DEFAULT_SITE_LOGO = "img/logo-touch-vietnam.svg"
DEFAULT_HERO_IMAGE = "img/hero/vietnam-discovery.svg"

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
ALLOWED_SOURCE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
DIRECT_UPLOAD_EXTENSIONS = {".jpg", ".jpeg", ".png"}
OUTPUT_FORMATS = {"jpg", "png"}


class AssetInfo(TypedDict):
    path: str
    has_custom: bool
    format: str | None


def image_conversion_available() -> bool:
    return Image is not None and ImageOps is not None


def _ensure_media_dirs() -> None:
    PLACE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    SITE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _normalize_output_format(value: str | None) -> str:
    normalized = (value or "png").strip().lower()
    if normalized == "jpeg":
        normalized = "jpg"
    if normalized not in OUTPUT_FORMATS:
        return "png"
    return normalized


def _read_upload_bytes(file: FileStorage) -> bytes:
    file.stream.seek(0)
    data = file.stream.read()
    file.stream.seek(0)
    if not data:
        raise ValueError("Tệp hình ảnh đang rỗng.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("Tệp hình ảnh vượt quá giới hạn 8MB.")
    return data


def _static_relative_path(path: Path) -> str:
    return path.relative_to(STATIC_DIR).as_posix()


def _asset_candidates(base_dir: Path, key: str) -> list[Path]:
    return [
        base_dir / f"{key}.png",
        base_dir / f"{key}.jpg",
    ]


def _find_existing_asset(base_dir: Path, key: str) -> Path | None:
    for candidate in _asset_candidates(base_dir, key):
        if candidate.exists():
            return candidate
    return None


def _built_in_place_asset(place_id: str) -> str:
    for ext in ("jpg", "jpeg", "png", "svg"):
        candidate = STATIC_DIR / "img" / "places" / f"{place_id}.{ext}"
        if candidate.exists():
            return _static_relative_path(candidate)
    return DEFAULT_PLACE_ASSET


def get_place_image_asset(place_id: str) -> str:
    custom = _find_existing_asset(PLACE_UPLOAD_DIR, place_id)
    if custom is not None:
        return _static_relative_path(custom)
    return _built_in_place_asset(place_id)


def get_place_image_info(place_id: str) -> AssetInfo:
    custom = _find_existing_asset(PLACE_UPLOAD_DIR, place_id)
    if custom is not None:
        return {
            "path": _static_relative_path(custom),
            "has_custom": True,
            "format": custom.suffix.lstrip(".").lower(),
        }
    built_in = _built_in_place_asset(place_id)
    suffix = Path(built_in).suffix.lstrip(".").lower() or None
    return {"path": built_in, "has_custom": False, "format": suffix}


def get_site_media_assets() -> dict[str, AssetInfo]:
    _ensure_media_dirs()
    logo = _find_existing_asset(SITE_UPLOAD_DIR, "site-logo")
    hero = _find_existing_asset(SITE_UPLOAD_DIR, "home-hero")
    return {
        "logo": {
            "path": _static_relative_path(logo) if logo else DEFAULT_SITE_LOGO,
            "has_custom": logo is not None,
            "format": logo.suffix.lstrip(".").lower()
            if logo
            else Path(DEFAULT_SITE_LOGO).suffix.lstrip(".").lower(),
        },
        "hero": {
            "path": _static_relative_path(hero) if hero else DEFAULT_HERO_IMAGE,
            "has_custom": hero is not None,
            "format": hero.suffix.lstrip(".").lower()
            if hero
            else Path(DEFAULT_HERO_IMAGE).suffix.lstrip(".").lower(),
        },
    }


def _delete_candidate_assets(base_dir: Path, key: str) -> None:
    for candidate in _asset_candidates(base_dir, key):
        if candidate.exists():
            candidate.unlink()


def _save_with_pillow(data: bytes, target_path: Path, output_format: str) -> None:
    if Image is None or ImageOps is None:  # pragma: no cover - guarded by caller
        raise ValueError("Hệ thống chưa sẵn sàng chuyển đổi định dạng hình ảnh.")
    max_pixels = get_settings().max_image_pixels
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source_image:
                width, height = source_image.size
                if width <= 0 or height <= 0 or width * height > max_pixels:
                    raise ValueError(f"Ảnh vượt quá giới hạn xử lý {max_pixels:,} pixel.")
                source_image.load()
                image = ImageOps.exif_transpose(source_image)
                if output_format == "jpg":
                    if image.mode not in {"RGB", "L"}:
                        base = Image.new("RGB", image.size, (255, 255, 255))
                        rgba_image = image.convert("RGBA")
                        base.paste(rgba_image, mask=rgba_image.split()[-1])
                        image = base
                    else:
                        image = image.convert("RGB")
                    image.save(target_path, format="JPEG", quality=92, optimize=True)
                else:
                    if image.mode not in {"RGB", "RGBA"}:
                        image = image.convert("RGBA")
                    image.save(target_path, format="PNG", optimize=True)
    except ValueError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning, OSError) as exc:
        raise ValueError("Tệp tải lên không phải ảnh hợp lệ hoặc vượt giới hạn an toàn.") from exc


def _save_direct_image(data: bytes, target_path: Path) -> None:
    target_path.write_bytes(data)


def _save_uploaded_image(
    *,
    file: FileStorage,
    key: str,
    target_dir: Path,
    output_format: str | None,
) -> str:
    _ensure_media_dirs()
    filename = (file.filename or "").strip()
    if not filename:
        raise ValueError("Vui lòng chọn tệp hình ảnh.")

    source_extension = Path(filename).suffix.lower()
    if source_extension not in ALLOWED_SOURCE_EXTENSIONS:
        raise ValueError("Chỉ hỗ trợ ảnh JPG, JPEG, PNG, WEBP, BMP hoặc GIF.")

    data = _read_upload_bytes(file)
    normalized_format = _normalize_output_format(output_format)
    target_path = target_dir / f"{key}.{normalized_format}"

    if image_conversion_available():
        _save_with_pillow(data, target_path, normalized_format)
    else:
        if source_extension not in DIRECT_UPLOAD_EXTENSIONS:
            raise ValueError("Cần cài Pillow để chuyển tệp này về JPG hoặc PNG.")
        direct_source_format = "jpg" if source_extension in {".jpg", ".jpeg"} else "png"
        if direct_source_format != normalized_format:
            raise ValueError("Cần cài Pillow để chuyển đổi giữa JPG và PNG.")
        _save_direct_image(data, target_path)

    for candidate in _asset_candidates(target_dir, key):
        if candidate != target_path and candidate.exists():
            candidate.unlink()

    return _static_relative_path(target_path)


def save_uploaded_place_image(
    *,
    place_id: str,
    file: FileStorage,
    output_format: str | None,
) -> str:
    return _save_uploaded_image(
        file=file,
        key=place_id,
        target_dir=PLACE_UPLOAD_DIR,
        output_format=output_format,
    )


def remove_uploaded_place_image(place_id: str) -> bool:
    _ensure_media_dirs()
    existing = _find_existing_asset(PLACE_UPLOAD_DIR, place_id)
    if existing is None:
        return False
    _delete_candidate_assets(PLACE_UPLOAD_DIR, place_id)
    return True


def save_uploaded_site_image(
    *,
    asset_key: str,
    file: FileStorage,
    output_format: str | None,
) -> str:
    return _save_uploaded_image(
        file=file,
        key=asset_key,
        target_dir=SITE_UPLOAD_DIR,
        output_format=output_format,
    )


def remove_uploaded_site_image(asset_key: str) -> bool:
    _ensure_media_dirs()
    existing = _find_existing_asset(SITE_UPLOAD_DIR, asset_key)
    if existing is None:
        return False
    _delete_candidate_assets(SITE_UPLOAD_DIR, asset_key)
    return True
