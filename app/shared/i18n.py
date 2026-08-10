from __future__ import annotations

import unicodedata
from typing import Any

from .geography import normalize_province_name
from .models import Place, TicketOffer
from .translations import UI_TEXTS

DEFAULT_LANGUAGE = "vi"
LANGUAGE_OPTIONS = [
    {"code": "vi", "label": "Tiếng Việt", "short": "VI"},
    {"code": "en", "label": "English", "short": "EN"},
    {"code": "ko", "label": "한국어", "short": "KO"},
]
LANGUAGE_CODES = {item["code"] for item in LANGUAGE_OPTIONS}


REGION_LABELS_BY_LANG = {
    "north": {"vi": "Miền Bắc", "en": "Northern Vietnam", "ko": "베트남 북부"},
    "central": {"vi": "Miền Trung", "en": "Central Vietnam", "ko": "베트남 중부"},
    "south": {"vi": "Miền Nam", "en": "Southern Vietnam", "ko": "베트남 남부"},
}

CATEGORY_LABELS_BY_LANG = {
    "mountain": {"vi": "Núi", "en": "Mountains", "ko": "산악"},
    "island": {"vi": "Hải đảo", "en": "Islands", "ko": "섬"},
    "beach": {"vi": "Biển", "en": "Beaches", "ko": "해변"},
    "spiritual": {"vi": "Tâm linh", "en": "Spiritual", "ko": "영성"},
    "culture": {"vi": "Văn hóa", "en": "Culture", "ko": "문화"},
    "food": {"vi": "Ẩm thực", "en": "Food", "ko": "음식"},
    "history": {"vi": "Lịch sử", "en": "History", "ko": "역사"},
    "entertainment": {"vi": "Giải trí", "en": "Entertainment", "ko": "엔터테인먼트"},
}

SERVICE_NAMES_BY_LANG = {
    "hotel": {"vi": "Khách sạn gần bạn", "en": "Nearby hotel", "ko": "근처 호텔"},
    "resort": {"vi": "Resort gần bạn", "en": "Nearby resort", "ko": "근처 리조트"},
    "pharmacy": {"vi": "Tiệm thuốc gần bạn", "en": "Nearby pharmacy", "ko": "근처 약국"},
    "drugstore": {"vi": "Nhà thuốc địa phương", "en": "Local drugstore", "ko": "현지 약국"},
    "hospital": {"vi": "Bệnh viện đa khoa", "en": "General hospital", "ko": "종합병원"},
    "market": {"vi": "Chợ truyền thống", "en": "Traditional market", "ko": "전통시장"},
    "supermarket": {"vi": "Siêu thị mini", "en": "Mini supermarket", "ko": "미니 마트"},
    "convenience-store": {"vi": "Cửa hàng bách hóa", "en": "Convenience store", "ko": "편의점"},
    "night-market": {"vi": "Chợ đêm ẩm thực", "en": "Night food market", "ko": "야시장"},
    "tailor": {"vi": "Tiệm may đo nhanh", "en": "Quick tailor", "ko": "맞춤 재단점"},
    "theme-park": {"vi": "Khu vui chơi", "en": "Theme park", "ko": "테마파크"},
    "restaurant": {"vi": "Nhà hàng đặc sản", "en": "Specialty restaurant", "ko": "현지 맛집"},
    "first-aid": {"vi": "Trạm y tế", "en": "First-aid station", "ko": "응급 진료소"},
    "homestay": {"vi": "Homestay bản địa", "en": "Local homestay", "ko": "현지 홈스테이"},
    "cafe": {"vi": "Quán cà phê view đẹp", "en": "Scenic café", "ko": "전망 좋은 카페"},
}

LOCATION_TRANSLATIONS = {
    "An Giang": {"en": "An Giang", "ko": "안장"},
    "Bắc Ninh": {"en": "Bac Ninh", "ko": "박닌"},
    "Cao Bằng": {"en": "Cao Bang", "ko": "까오방"},
    "Cà Mau": {"en": "Ca Mau", "ko": "까마우"},
    "Hạ Long": {"en": "Ha Long", "ko": "하롱"},
    "Bà Nà Hills": {"en": "Ba Na Hills", "ko": "바나힐"},
    "Hà Nội": {"en": "Hanoi", "ko": "하노이"},
    "Hội An": {"en": "Hoi An", "ko": "호이안"},
    "Huế": {"en": "Hue", "ko": "후에"},
    "Đà Nẵng": {"en": "Da Nang", "ko": "다낭"},
    "Sa Pa": {"en": "Sapa", "ko": "사파"},
    "Phú Quốc": {"en": "Phu Quoc", "ko": "푸꾸옥"},
    "Cần Thơ": {"en": "Can Tho", "ko": "껀터"},
    "Điện Biên": {"en": "Dien Bien", "ko": "디엔비엔"},
    "Thành phố Hồ Chí Minh": {"en": "Ho Chi Minh City", "ko": "호찌민시"},
    "Đắk Lắk": {"en": "Dak Lak", "ko": "닥락"},
    "Đồng Nai": {"en": "Dong Nai", "ko": "동나이"},
    "Đồng Tháp": {"en": "Dong Thap", "ko": "동탑"},
    "Gia Lai": {"en": "Gia Lai", "ko": "잘라이"},
    "Hà Tĩnh": {"en": "Ha Tinh", "ko": "하띤"},
    "Hải Phòng": {"en": "Hai Phong", "ko": "하이퐁"},
    "Hưng Yên": {"en": "Hung Yen", "ko": "흥옌"},
    "Khánh Hòa": {"en": "Khanh Hoa", "ko": "카인호아"},
    "Lai Châu": {"en": "Lai Chau", "ko": "라이쩌우"},
    "Lâm Đồng": {"en": "Lam Dong", "ko": "럼동"},
    "Lạng Sơn": {"en": "Lang Son", "ko": "랑선"},
    "Quảng Ninh": {"en": "Quang Ninh", "ko": "꽝닌"},
    "Lào Cai": {"en": "Lao Cai", "ko": "라오까이"},
    "Nghệ An": {"en": "Nghe An", "ko": "응에안"},
    "Ninh Bình": {"en": "Ninh Binh", "ko": "닌빈"},
    "Phú Thọ": {"en": "Phu Tho", "ko": "푸토"},
    "Quảng Ngãi": {"en": "Quang Ngai", "ko": "꽝응아이"},
    "Quảng Trị": {"en": "Quang Tri", "ko": "꽝찌"},
    "Sơn La": {"en": "Son La", "ko": "선라"},
    "Thanh Hóa": {"en": "Thanh Hoa", "ko": "타인호아"},
    "Thái Nguyên": {"en": "Thai Nguyen", "ko": "타이응우옌"},
    "Tuyên Quang": {"en": "Tuyen Quang", "ko": "뚜옌꽝"},
    "Tây Ninh": {"en": "Tay Ninh", "ko": "떠이닌"},
    "Vĩnh Long": {"en": "Vinh Long", "ko": "빈롱"},
    "Thừa Thiên Huế": {"en": "Thua Thien Hue", "ko": "트어티엔후에"},
    "Quảng Nam": {"en": "Quang Nam", "ko": "꽝남"},
    "Kiên Giang": {"en": "Kien Giang", "ko": "끼엔장"},
    "Hoàng thành Thăng Long": {"en": "Thang Long Imperial Citadel", "ko": "탕롱 황성"},
    "Đại Nội Huế": {"en": "Hue Imperial Citadel", "ko": "후에 황궁"},
    "Địa đạo Củ Chi": {"en": "Cu Chi Tunnels", "ko": "꾸찌 터널"},
}

PLACE_TRANSLATIONS = {
    "ha-long-bay": {
        "en": {
            "name": "Ha Long Bay",
            "province": "Quang Ninh",
            "description": "A UNESCO World Heritage bay with limestone islands, caves, and cruise experiences.",
            "highlights": ["Overnight cruise", "Kayaking", "Surprise Cave"],
        },
        "ko": {
            "name": "하롱베이",
            "province": "꽝닌",
            "description": "석회암 섬과 동굴, 크루즈 체험으로 유명한 유네스코 세계자연유산입니다.",
            "highlights": ["선상 1박 크루즈", "카약 체험", "승솟 동굴"],
        },
    },
    "sapa": {
        "en": {
            "name": "Sapa",
            "province": "Lao Cai",
            "description": "A mountain town known for rice terraces, Fansipan peak, and ethnic culture.",
            "highlights": ["Fansipan Legend", "Cat Cat Village", "Rice terraces"],
        },
        "ko": {
            "name": "사파",
            "province": "라오까이",
            "description": "계단식 논, 판시판 정상, 소수민족 문화로 유명한 고산 마을입니다.",
            "highlights": ["판시판 레전드", "깟깟 마을", "계단식 논"],
        },
    },
    "trang-an": {
        "en": {
            "name": "Trang An",
            "province": "Ninh Binh",
            "description": "A scenic complex of rivers, caves, mountains, and spiritual landmarks.",
            "highlights": ["Trang An boat tour", "Bai Dinh Pagoda", "Mua Cave"],
        },
        "ko": {
            "name": "짱안",
            "province": "닌빈",
            "description": "강, 동굴, 산세와 사찰이 어우러진 대표적인 경승지입니다.",
            "highlights": ["짱안 보트 투어", "바이딘 사원", "무아 동굴"],
        },
    },
    "hue-imperial-city": {
        "en": {
            "name": "Hue Imperial City",
            "province": "Thua Thien Hue",
            "description": "A former royal capital rich in imperial heritage, cuisine, and Nguyen dynasty tombs.",
            "highlights": ["Imperial City", "Khai Dinh Tomb", "Thien Mu Pagoda"],
        },
        "ko": {
            "name": "후에 황성",
            "province": "트어티엔후에",
            "description": "황궁 유산, 왕실 음식, 응우옌 왕조 능묘가 어우러진 옛 수도입니다.",
            "highlights": ["황성", "카이딘 능", "티엔무 사원"],
        },
    },
    "hoi-an": {
        "en": {
            "name": "Hoi An Ancient Town",
            "province": "Quang Nam",
            "description": "A riverside ancient town famous for lanterns, tailoring, and local cuisine.",
            "highlights": ["Lantern streets", "Japanese Bridge", "Quick tailoring"],
        },
        "ko": {
            "name": "호이안 올드타운",
            "province": "꽝남",
            "description": "등불 거리, 맞춤 의상, 현지 음식으로 사랑받는 강변 고도시입니다.",
            "highlights": ["등불 거리", "일본교", "맞춤 의상"],
        },
    },
    "ba-na-hills": {
        "en": {
            "name": "Ba Na Hills",
            "province": "Da Nang",
            "description": "A mountain resort complex with the Golden Bridge, cable car, and cool climate.",
            "highlights": ["Golden Bridge", "French Village", "Fantasy Park"],
        },
        "ko": {
            "name": "바나힐",
            "province": "다낭",
            "description": "골든 브리지, 케이블카, 시원한 기후를 갖춘 산악 리조트형 관광지입니다.",
            "highlights": ["골든 브리지", "프렌치 빌리지", "판타지 파크"],
        },
    },
    "phu-quoc": {
        "en": {
            "name": "Phu Quoc",
            "province": "Kien Giang",
            "description": "A tropical island known for turquoise beaches, coral reefs, night markets, and luxury resorts.",
            "highlights": ["Bai Sao", "Sunset Town", "Hon Thom"],
        },
        "ko": {
            "name": "푸꾸옥",
            "province": "끼엔장",
            "description": "에메랄드빛 해변, 산호, 야시장, 고급 리조트로 유명한 베트남의 대표 섬입니다.",
            "highlights": ["바이사오", "선셋 타운", "혼톰"],
        },
    },
    "can-tho": {
        "en": {
            "name": "Can Tho",
            "province": "Can Tho",
            "description": "The heart of the Mekong Delta with floating markets, orchards, and river culture.",
            "highlights": [
                "Cai Rang Floating Market",
                "Ninh Kieu Wharf",
                "Binh Thuy Ancient House",
            ],
        },
        "ko": {
            "name": "껀터",
            "province": "껀터",
            "description": "수상시장, 과수원, 강 문화가 살아 있는 메콩델타의 중심 도시입니다.",
            "highlights": ["까이랑 수상시장", "닌끼에우 부두", "빈투이 고택"],
        },
    },
    "ho-chi-minh-city": {
        "en": {
            "name": "Ho Chi Minh City",
            "province": "Ho Chi Minh City",
            "description": "A dynamic city full of history, shopping, food, and nightlife.",
            "highlights": ["Independence Palace", "Ben Thanh Market", "Nguyen Hue Walking Street"],
        },
        "ko": {
            "name": "호찌민시",
            "province": "호찌민시",
            "description": "역사 유적, 쇼핑, 미식, 야간 문화가 공존하는 역동적인 대도시입니다.",
            "highlights": ["통일궁", "벤탄 시장", "응우옌후에 거리"],
        },
    },
}

PLACE_ALIASES = {
    "ha-long-bay": ["vịnh hạ long", "ha long bay", "halong bay", "하롱", "하롱베이"],
    "sapa": ["sa pa", "sapa", "사파"],
    "trang-an": ["tràng an", "trang an", "짱안"],
    "hue-imperial-city": ["huế", "hue", "cố đô huế", "후에"],
    "hoi-an": ["hội an", "hoi an", "호이안"],
    "ba-na-hills": ["bà nà", "ba na hills", "바나힐", "다낭 바나힐"],
    "phu-quoc": ["phú quốc", "phu quoc", "푸꾸옥"],
    "can-tho": ["cần thơ", "can tho", "껀터"],
    "ho-chi-minh-city": [
        "hồ chí minh",
        "ho chi minh",
        "ho chi minh city",
        "sài gòn",
        "saigon",
        "호찌민",
        "호찌민시",
    ],
}

AR_TRANSLATIONS = {
    "Hoàng thành Thăng Long": {
        "en": {
            "name": "Thang Long Imperial Citadel",
            "province": "Hanoi",
            "note": "Scan with the phone camera to view historical facts and 3D reconstructions of the site.",
        },
        "ko": {
            "name": "탕롱 황성",
            "province": "하노이",
            "note": "휴대폰 카메라로 스캔하면 역사 정보와 3D 복원 모델을 볼 수 있습니다.",
        },
    },
    "Đại Nội Huế": {
        "en": {
            "name": "Hue Imperial Citadel",
            "province": "Thua Thien Hue",
            "note": "AR recreates parts of the imperial court and explains the architectural heritage.",
        },
        "ko": {
            "name": "후에 황궁",
            "province": "트어티엔후에",
            "note": "AR로 궁중 공간을 복원하고 건축적 가치를 설명합니다.",
        },
    },
    "Địa đạo Củ Chi": {
        "en": {
            "name": "Cu Chi Tunnels",
            "province": "Ho Chi Minh City",
            "note": "Shows wartime timelines, tunnel maps, and interactive historical content.",
        },
        "ko": {
            "name": "꾸찌 터널",
            "province": "호찌민시",
            "note": "전쟁 연표, 터널 지도, 상호작용형 역사 정보를 제공합니다.",
        },
    },
}

OFFLINE_PACK_TRANSLATIONS = {
    "Tây Bắc Safe Travel Pack": {
        "en": {
            "name": "Northwest Safe Travel Pack",
            "coverage": "Sapa, Y Ty, Bac Ha, and other low-signal mountain areas.",
        },
        "ko": {
            "name": "북서부 안전 여행 팩",
            "coverage": "사파, 이띠, 박하 등 통신이 약한 산악 지역을 포함합니다.",
        },
    },
    "Gói du lịch an toàn Tây Bắc": {
        "en": {
            "name": "Northwest Safe Travel Pack",
            "coverage": "Sapa, Y Ty, Bac Ha, and other low-signal mountain areas.",
        },
        "ko": {
            "name": "북서부 안전 여행 팩",
            "coverage": "사파, 이띠, 박하 등 통신이 약한 산악 지역을 포함합니다.",
        },
    },
    "Gói di sản miền Trung": {
        "en": {
            "name": "Central Heritage Pack",
            "coverage": "Hue, Hoi An, Da Nang, and surrounding heritage or hill regions.",
        },
        "ko": {
            "name": "중부 문화유산 팩",
            "coverage": "후에, 호이안, 다낭과 주변 유산·산악 지역을 포함합니다.",
        },
    },
    "Gói đảo và miền Tây sông nước": {
        "en": {
            "name": "Island and Mekong Pack",
            "coverage": "Phu Quoc, Ha Tien, Can Tho, and coastal or river-based destinations.",
        },
        "ko": {
            "name": "섬과 메콩 팩",
            "coverage": "푸꾸옥, 하띠엔, 껀터와 해안·수변 지역을 포함합니다.",
        },
    },
}


def resolve_language(language: str | None) -> str:
    return language if language in LANGUAGE_CODES else DEFAULT_LANGUAGE


def text(language: str | None, key: str, **kwargs: Any) -> str:
    lang = resolve_language(language)
    value = UI_TEXTS.get(lang, {}).get(key) or UI_TEXTS[DEFAULT_LANGUAGE].get(key) or key
    return value.format(**kwargs)


def get_language_options() -> list[dict[str, str]]:
    return LANGUAGE_OPTIONS


def get_region_labels(language: str | None) -> dict[str, str]:
    lang = resolve_language(language)
    return {
        code: labels.get(lang, labels[DEFAULT_LANGUAGE])
        for code, labels in REGION_LABELS_BY_LANG.items()
    }


def get_category_labels(language: str | None) -> dict[str, str]:
    lang = resolve_language(language)
    return {
        code: labels.get(lang, labels[DEFAULT_LANGUAGE])
        for code, labels in CATEGORY_LABELS_BY_LANG.items()
    }


def _model_dump(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def translate_location(name: str, language: str | None) -> str:
    lang = resolve_language(language)
    if lang == DEFAULT_LANGUAGE:
        return name
    mapping = LOCATION_TRANSLATIONS.get(name)
    if mapping:
        return mapping.get(lang, name)
    if lang == "en":
        normalized = unicodedata.normalize("NFD", name.replace("Đ", "D").replace("đ", "d"))
        return "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    return name


def _fallback_place_description(place: Place, lang: str) -> str:
    category_labels = [
        CATEGORY_LABELS_BY_LANG.get(code, {}).get(lang, code.title()) for code in place.categories
    ]
    categories = ", ".join(category_labels)
    highlights = ", ".join(
        translate_location(highlight, lang) for highlight in place.highlights[:3]
    )
    province = translate_location(normalize_province_name(place.province), lang)
    name = translate_location(place.name, lang)
    if lang == "ko":
        return (
            f"{name}은(는) {province}의 대표 여행지로 {categories} 여행을 함께 즐길 수 있습니다. "
            "현지 문화와 풍경을 균형 있게 경험할 수 있어 베트남 국내 여행 일정에 잘 어울립니다."
        )
    return (
        f"{name} is a notable destination in {province}, combining {categories}. "
        f"Key experiences include {highlights}. It is well suited to a clear, locally grounded "
        "Vietnam itinerary."
    )


def translate_place(place: Place, language: str | None) -> Place:
    lang = resolve_language(language)
    if lang == DEFAULT_LANGUAGE:
        return place
    translated = PLACE_TRANSLATIONS.get(place.id, {}).get(lang)
    payload = _model_dump(place)
    if translated:
        payload.update(translated)
    else:
        payload["name"] = translate_location(place.name, lang)
        payload["description"] = _fallback_place_description(place, lang)
    payload["province"] = translate_location(
        normalize_province_name(place.province),
        lang,
    )
    return Place(**payload)


def get_place_aliases(place: Place) -> list[str]:
    aliases = set(PLACE_ALIASES.get(place.id, []))
    aliases.add(place.name.lower())
    for language in ("en", "ko"):
        translated = translate_place(place, language)
        aliases.add(translated.name.lower())
        aliases.add(translated.province.lower())
    return list(aliases)


def translate_ticket_offer(offer: TicketOffer, language: str | None) -> TicketOffer:
    lang = resolve_language(language)
    if lang == DEFAULT_LANGUAGE:
        return offer
    payload = _model_dump(offer)
    payload["origin"] = translate_location(offer.origin, lang)
    payload["destination"] = translate_location(offer.destination, lang)
    return TicketOffer(**payload)


def translate_service_name(kind: str, language: str | None) -> str:
    lang = resolve_language(language)
    mapping = SERVICE_NAMES_BY_LANG.get(kind)
    if not mapping:
        return kind.title()
    return mapping.get(lang, mapping[DEFAULT_LANGUAGE])


def translate_ar_item(item: dict[str, str], language: str | None) -> dict[str, str]:
    lang = resolve_language(language)
    if lang == DEFAULT_LANGUAGE:
        return item
    translated = AR_TRANSLATIONS.get(item["name"], {}).get(lang)
    if not translated:
        return item
    return translated


def translate_offline_pack(item: dict[str, str], language: str | None) -> dict[str, str]:
    lang = resolve_language(language)
    if lang == DEFAULT_LANGUAGE:
        return item
    translated = OFFLINE_PACK_TRANSLATIONS.get(item["name"], {}).get(lang)
    if not translated:
        return item
    return {
        "region": item["region"],
        "name": translated["name"],
        "coverage": translated["coverage"],
    }
