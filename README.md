<p align="center">
  <img src="app/web/static/uploads/site/site-logo.png" width="112" alt="Touch Việt Nam logo">
</p>

<h1 align="center">Touch! Việt Nam</h1>

<p align="center">
  Nền tảng web hỗ trợ khám phá và lập kế hoạch du lịch Việt Nam trong một hành trình thống nhất.
</p>

<p align="center">
  <a href="https://github.com/nguyentan-ptvn79/Touch-Vietnam/actions/workflows/quality.yml">
    <img src="https://github.com/nguyentan-ptvn79/Touch-Vietnam/actions/workflows/quality.yml/badge.svg" alt="Quality checks">
  </a>
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/Flask-3.1-000000?logo=flask&logoColor=white" alt="Flask 3.1">
  <img src="https://img.shields.io/badge/FastAPI-0.135-009688?logo=fastapi&logoColor=white" alt="FastAPI 0.135">
</p>

![Touch Việt Nam](app/web/static/uploads/site/home-hero.jpg)

## Tổng quan

Touch! Việt Nam là đồ án môn học xây dựng nền tảng du lịch nội địa trên web. Hệ thống kết hợp dữ liệu điểm đến, AI Planner, bản đồ, thời tiết, vé, QR/AR và quản lý chi tiêu; đồng thời cung cấp REST API để phục vụ tích hợp hoặc phát triển ứng dụng di động sau này.

Ứng dụng vẫn duy trì các chức năng cốt lõi khi AI hoặc dịch vụ bên ngoài gián đoạn nhờ cơ chế fallback và dữ liệu dự phòng nội bộ.

## Chức năng chính

- Khám phá 63 điểm đến thuộc 34 tỉnh/thành theo vùng, loại hình và từ khóa.
- Xem thông tin chi tiết, hình ảnh, thời tiết, bản đồ và tiện ích lân cận.
- Tạo lịch trình theo số ngày, ngân sách, số người và sở thích bằng AI Planner.
- Tra cứu phương án di chuyển, vé và tạo đặt chỗ mô phỏng.
- Lưu chuyến đi, theo dõi chi tiêu và phân bổ chi phí nhóm.
- Quét QR, trải nghiệm AR và tải gói dữ liệu JSON/GeoJSON dùng khi ngoại tuyến.
- Chuyển đổi giữa tiếng Việt, tiếng Anh và tiếng Hàn.
- Quản lý nội dung, điểm đến, tích hợp và analytics qua dashboard quản trị.
- Cung cấp REST API có validation, authentication, rate limit và tài liệu OpenAPI.

## Kiến trúc và công nghệ

| Lớp | Công nghệ |
| --- | --- |
| Web portal | Flask, Jinja2, HTML, CSS, JavaScript |
| REST API | FastAPI, Pydantic, OpenAPI |
| Nghiệp vụ | Python service modules dùng chung cho Flask và FastAPI |
| Dữ liệu | SQLite; có định hướng mở rộng PostgreSQL/PostGIS |
| AI | OpenAI Responses API, kèm fallback nội bộ |
| Vận hành | Waitress cho Flask, Uvicorn cho FastAPI |
| Kiểm thử | `unittest`, GitHub Actions |

```text
Trình duyệt / REST client
          │
     Flask / FastAPI
          │
   Lớp dịch vụ dùng chung
     ├── SQLite
     ├── AI Planner và Chat
     ├── Weather / Nearby / Ticket gateways
     └── Security, logging và analytics
```

## Bắt đầu nhanh

### 1. Tải mã nguồn

```bash
git clone https://github.com/nguyentan-ptvn79/Touch-Vietnam.git
cd Touch-Vietnam
```

### 2. Tạo môi trường và cài dependency

Yêu cầu **Python 3.11 trở lên**.

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Linux hoặc macOS:

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

Để cài đúng toàn bộ phiên bản và hash đã khóa:

```powershell
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock
```

### 3. Cấu hình môi trường local

Tạo khóa bí mật bằng Python:

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```

Mở `.env`, thay `APP_SECRET_KEY` bằng giá trị vừa tạo và đặt các biến sau để chạy local:

```dotenv
APP_ENV=development
APP_DEBUG=true
ENFORCE_HTTPS=false
ENABLE_API_DOCS=true
APP_PUBLIC_BASE_URL=http://127.0.0.1:5000
```

Không commit `.env` hoặc API key thật. Danh sách cấu hình đầy đủ nằm trong [.env.example](.env.example).

### 4. Chạy ứng dụng

Website Flask:

```powershell
.\.venv\Scripts\python.exe run_web.py
```

- Website: `http://127.0.0.1:5000/`
- Health check: `http://127.0.0.1:5000/healthz`

REST API FastAPI — mở một terminal khác:

```powershell
.\.venv\Scripts\python.exe run_api.py
```

- API base URL: `http://127.0.0.1:8000`
- Health check: `http://127.0.0.1:8000/api/health`
- OpenAPI UI: `http://127.0.0.1:8000/docs`

Trên Linux hoặc macOS, thay `.\.venv\Scripts\python.exe` bằng `./.venv/bin/python`.

## AI và dịch vụ tích hợp

Đặt `OPENAI_API_KEY` trong `.env` để bật Chat và Planner qua OpenAI Responses API. Hai model được chọn bằng `OPENAI_CHAT_MODEL` và `OPENAI_PLANNER_MODEL`.

Các gateway vé, analytics, AR, bản đồ ngoại tuyến, thời tiết và nearby có cấu hình URL/API key riêng trong `.env.example`. Nếu provider chưa được cấu hình hoặc tạm thời không phản hồi, ứng dụng sử dụng dữ liệu và logic dự phòng phù hợp.

## Kiểm thử

Chạy toàn bộ acceptance tests:

```powershell
.\.venv\Scripts\python.exe -m unittest -q tests.test_acceptance
```

Bộ hiện tại gồm **22 tests** cho API, phân quyền, CSRF, đa ngôn ngữ, AI fallback, planner, dashboard, offline pack và các luồng web chính. GitHub Actions tự động biên dịch nguồn và chạy lại bộ test trên mỗi lần push hoặc pull request vào `main`.

## Cấu trúc repository

```text
Touch-Vietnam/
├── app/
│   ├── api/                 # REST API FastAPI
│   ├── shared/              # Dữ liệu, nghiệp vụ, bảo mật và tích hợp
│   └── web/                 # Flask app, templates và static assets
├── tests/                   # Acceptance tests
├── .github/workflows/       # GitHub Actions
├── .env.example             # Mẫu cấu hình, không chứa bí mật thật
├── requirements.txt         # Dependency trực tiếp
├── requirements.lock        # Dependency khóa phiên bản và SHA-256
├── run_web.py               # Điểm chạy website
└── run_api.py               # Điểm chạy REST API
```

## Bảo mật và triển khai

- Thay `APP_SECRET_KEY` và toàn bộ credential trước khi triển khai.
- Bật HTTPS, tắt debug và giới hạn `CORS_ALLOWED_ORIGINS` ở production.
- Không seed tài khoản demo trong môi trường production.
- Đặt ứng dụng sau reverse proxy và quản lý secret bằng biến môi trường hoặc secret manager.
- Sao lưu database và theo dõi audit log theo chính sách vận hành thực tế.

## Phạm vi repository

Repository chỉ chứa những thành phần cần để chạy, kiểm thử và duy trì ứng dụng. Báo cáo đồ án, DOCX/PDF/PPTX, database runtime, log, release ZIP, môi trường ảo và `.env` được lưu ngoài Git.
