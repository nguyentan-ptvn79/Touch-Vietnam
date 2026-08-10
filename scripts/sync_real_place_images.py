from __future__ import annotations

import json
import mimetypes
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.shared.sample_data import PLACES

ASSET_DIR = ROOT / "app" / "web" / "static" / "img" / "places"
ATTRIBUTION_PATH = ASSET_DIR / "attribution.json"
USER_AGENT = "TouchVN-StudentProject/1.1 (educational local demo; contact: admin@localhost)"
REQUEST_DELAY_SECONDS = 1.35
MAX_RETRIES = 4

TITLE_OVERRIDES = {
    "ha-noi-old-quarter": "Khu phố cổ Hà Nội",
    "cat-ba": "Quần đảo Cát Bà",
    "bac-ninh-dong-ho": "Làng tranh Đông Hồ",
    "tam-chuc": "Chùa Tam Chúc",
    "con-son-kiep-bac": "Khu di tích Côn Sơn - Kiếp Bạc",
    "tran-temple-nam-dinh": "Đền Trần Nam Định",
    "con-den": "Cồn Đen",
    "hung-temple": "Đền Hùng",
    "dong-van": "Cao nguyên đá Đồng Văn",
    "ban-gioc": "Thác Bản Giốc",
    "ba-be-lake": "Hồ Ba Bể",
    "atks-dinh-hoa": "An toàn khu Định Hóa",
    "tay-yen-tu": "Tây Yên Tử",
    "dien-bien-phu": "Điện Biên Phủ",
    "sam-son": "Sầm Sơn",
    "cua-lo": "Cửa Lò",
    "thien-cam": "Thiên Cầm",
    "phong-nha": "Phong Nha - Kẻ Bàng",
    "vinh-moc": "Địa đạo Vịnh Mốc",
    "ly-son": "Lý Sơn",
    "ky-co": "Kỳ Co",
    "ghenh-da-dia": "Gành Đá Đĩa",
    "ninh-chu": "Ninh Chữ",
    "mui-ne": "Mũi Né",
    "mang-den": "Măng Đen",
    "bien-ho-che": "Biển Hồ",
    "buon-don": "Buôn Đôn",
    "ta-dung": "Tà Đùng",
    "ba-den": "Núi Bà Đen",
    "dai-nam": "Khu du lịch Đại Nam",
    "buulong": "Khu du lịch Bửu Long",
    "vung-tau": "Vũng Tàu",
    "tan-lap": "Làng nổi Tân Lập",
    "cai-be": "Cái Bè",
    "con-phung": "Cồn Phụng",
    "ao-ba-om": "Ao Bà Om",
    "an-binh": "Cù lao An Bình",
    "tram-chim": "Vườn quốc gia Tràm Chim",
    "tra-su": "Rừng tràm Trà Sư",
    "lung-ngoc-hoang": "Lung Ngọc Hoàng",
    "nga-nam": "Ngã Năm",
    "bac-lieu-wind-farm": "Cánh đồng điện gió Bạc Liêu",
    "dat-mui": "Mũi Cà Mau",
}

EXCLUDED_FILE_RE = re.compile(
    r"(?i)(map|locator|relief|logo|flag|seal|icon|diagram|route|banner|"
    r"bản.?đồ|quốc.?kỳ|huy.?hiệu|location)"
)


def request_json(url: str) -> dict[str, Any] | None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Image metadata URL must be HTTP(S): {url}")
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT, "Api-User-Agent": USER_AGENT})
            with urlopen(req, timeout=45) as response:  # nosec B310
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            last_error = exc
            if exc.code == 404:
                return None
            if exc.code not in {429, 500, 502, 503, 504}:
                raise
        except URLError as exc:
            last_error = exc
        time.sleep((attempt + 1) * 4)
    if last_error:
        raise last_error
    return None


def download_file(url: str, target: Path) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Image download URL must be HTTP(S): {url}")
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=75) as response:  # nosec B310
                target.write_bytes(response.read())
            return
        except (HTTPError, URLError) as exc:
            last_error = exc
            time.sleep((attempt + 1) * 4)
    if last_error:
        raise last_error


def is_valid_image(path: Path, extension: str) -> bool:
    if path.stat().st_size < 12_000:
        return False
    header = path.read_bytes()[:12]
    if extension == "png":
        return header.startswith(b"\x89PNG")
    return header.startswith(b"\xff\xd8")


def extension_from_url(url: str, mime: str | None = None) -> str:
    if mime:
        guessed = mimetypes.guess_extension(mime.split(";", 1)[0].strip())
        if guessed in {".jpg", ".jpeg", ".png"}:
            return "jpg" if guessed in {".jpg", ".jpeg"} else "png"
    path = url.split("?", 1)[0].lower()
    if ".png" in path:
        return "png"
    return "jpg"


def candidate_from_summary(title: str) -> dict[str, Any] | None:
    summary_url = "https://vi.wikipedia.org/api/rest_v1/page/summary/" + quote(
        title.replace(" ", "_"),
        safe="",
    )
    payload = request_json(summary_url)
    if not payload:
        return None
    thumbnail = (payload.get("thumbnail") or {}).get("source")
    page = ((payload.get("content_urls") or {}).get("desktop") or {}).get("page")
    if not thumbnail or EXCLUDED_FILE_RE.search(thumbnail):
        return None
    if "/wikipedia/commons/" not in thumbnail and "/wikipedia/vi/" not in thumbnail:
        return None
    return {
        "source_title": payload.get("title") or title,
        "source_page": page,
        "image_url": thumbnail.replace("/330px-", "/1280px-").replace("/320px-", "/1280px-"),
        "license": "See source page",
        "license_url": page,
    }


def commons_search(search_term: str, province: str) -> dict[str, Any] | None:
    params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "generator": "search",
        "gsrnamespace": "6",
        "gsrsearch": f"{search_term} {province} Vietnam",
        "gsrlimit": "10",
        "prop": "imageinfo",
        "iiprop": "url|mime|extmetadata",
        "iiurlwidth": "1280",
    }
    url = "https://commons.wikimedia.org/w/api.php?" + urlencode(params)
    payload = request_json(url)
    pages = ((payload or {}).get("query") or {}).get("pages") or []
    for page in sorted(pages, key=lambda item: item.get("index", 999)):
        title = str(page.get("title") or "")
        if EXCLUDED_FILE_RE.search(title):
            continue
        imageinfo = (page.get("imageinfo") or [{}])[0]
        mime = str(imageinfo.get("mime") or "")
        if mime not in {"image/jpeg", "image/png"}:
            continue
        metadata = imageinfo.get("extmetadata") or {}
        return {
            "source_title": title,
            "source_page": imageinfo.get("descriptionurl"),
            "image_url": imageinfo.get("thumburl") or imageinfo.get("url"),
            "mime": mime,
            "author": (metadata.get("Artist") or {}).get("value"),
            "license": (metadata.get("LicenseShortName") or {}).get("value"),
            "license_url": (metadata.get("LicenseUrl") or {}).get("value"),
        }
    return None


def find_image(place) -> dict[str, Any] | None:
    search_term = TITLE_OVERRIDES.get(place.id, place.name)
    for title in dict.fromkeys([search_term, place.name, f"{place.name} {place.province}"]):
        candidate = candidate_from_summary(title)
        if candidate:
            return candidate
        time.sleep(REQUEST_DELAY_SECONDS)
    return commons_search(search_term, place.province)


def main() -> int:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    attributions: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    for index, place in enumerate(PLACES, start=1):
        print(f"[{index}/{len(PLACES)}] {place.name}", flush=True)
        try:
            candidate = find_image(place)
            if not candidate or not candidate.get("image_url"):
                raise RuntimeError("Không tìm thấy ảnh thật phù hợp.")

            extension = extension_from_url(str(candidate["image_url"]), candidate.get("mime"))
            target = ASSET_DIR / f"{place.id}.{extension}"
            temp = target.with_suffix(target.suffix + ".download")
            download_file(str(candidate["image_url"]), temp)
            if not is_valid_image(temp, extension):
                temp.unlink(missing_ok=True)
                raise RuntimeError("Ảnh tải về không hợp lệ hoặc quá nhỏ.")

            target.write_bytes(temp.read_bytes())
            temp.unlink(missing_ok=True)

            entry = {
                "place_id": place.id,
                "place_name": place.name,
                "province": place.province,
                "asset": f"img/places/{place.id}.{extension}",
                **candidate,
            }
            attributions.append(entry)
        except Exception as exc:
            failures.append({"place_id": place.id, "place_name": place.name, "error": str(exc)})
            print(f"  failed: {exc}", flush=True)
        time.sleep(REQUEST_DELAY_SECONDS)

    manifest = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_policy": "Real destination photos from Wikipedia/Wikimedia where available. See source_page/license fields for attribution.",
        "downloaded_count": len(attributions),
        "failed_count": len(failures),
        "places": attributions,
        "failures": failures,
    }
    ATTRIBUTION_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Downloaded: {len(attributions)} | Failed: {len(failures)}")
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
