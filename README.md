# Touch! Việt Nam

[![Quality checks](https://github.com/nguyentan-ptvn79/Touch-Vietnam/actions/workflows/quality.yml/badge.svg)](https://github.com/nguyentan-ptvn79/Touch-Vietnam/actions/workflows/quality.yml)

Đồ án môn học xây dựng nền tảng du lịch Việt Nam trên web, kết hợp nội dung điểm đến, lập kế hoạch bằng AI, bản đồ, thời tiết, vé, QR/AR và quản lý chi tiêu trong một hệ thống thống nhất.

## Điểm nổi bật

- Dữ liệu 63 điểm đến thuộc 34 tỉnh/thành, hỗ trợ tìm kiếm theo vùng, loại hình và từ khóa.
- Giao diện responsive với tiếng Việt, tiếng Anh và tiếng Hàn.
- Planner tạo lịch trình theo số ngày, ngân sách, số người và sở thích.
- Smart fallback giúp chức năng chính tiếp tục hoạt động khi dịch vụ AI hoặc API ngoài gián đoạn.
- Dashboard cho người dùng và quản trị viên, bao gồm analytics, nội dung và trạng thái tích hợp.
- REST API FastAPI dùng chung lớp nghiệp vụ với ứng dụng Flask.
- Các kiểm soát bảo mật chính gồm CSRF, CSP, phân quyền, rate limit, validation và audit log.
- Bộ nghiệm thu hiện tại gồm **22 bài kiểm thử**, được chạy tự động trên GitHub Actions.

## Kiến trúc và công nghệ

| Thành phần | Công nghệ |
| --- | --- |
| Web portal | Flask, Jinja2, HTML, CSS, JavaScript |
| REST API | FastAPI, Pydantic, OpenAPI |
| Lớp nghiệp vụ | Python service modules dùng chung |
| Dữ liệu | SQLite; thiết kế sẵn hướng mở rộng PostgreSQL/PostGIS |
| AI | OpenAI Responses API, có fallback nội bộ |
| Vận hành | Waitress, Uvicorn |
| Kiểm thử | `unittest`, GitHub Actions |

Luồng chính của hệ thống:

```text
Trình duyệt / REST client
          │
     Flask / FastAPI
          │
   Lớp dịch vụ dùng chung
     ├── SQLite
     ├── AI planner và chat
     ├── Weather / Nearby / Ticket gateways
     └── Logging, security và analytics
```

## Cài đặt nhanh

Yêu cầu Python 3.11 trở lên.

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

### Linux hoặc macOS

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

Trước khi triển khai, thay `APP_SECRET_KEY` trong `.env` bằng khóa bí mật mạnh. Các API key thật chỉ được đặt trong `.env`; tệp này đã được loại khỏi Git.

## Chạy ứng dụng

Website Flask:

```powershell
.\.venv\Scripts\python.exe run_web.py
```

Truy cập `http://127.0.0.1:5000/`.

REST API FastAPI:

```powershell
.\.venv\Scripts\python.exe run_api.py
```

Trong môi trường development/testing, OpenAPI UI có tại `http://127.0.0.1:8000/docs`.

## Cấu hình AI và dịch vụ ngoài

Đặt `OPENAI_API_KEY` trong `.env` để bật chat và Planner AI qua OpenAI Responses API. Model được cấu hình bằng `OPENAI_CHAT_MODEL` và `OPENAI_PLANNER_MODEL`.

Khi không có API key hoặc provider ngoài không phản hồi, hệ thống chuyển sang dữ liệu và logic dự phòng nội bộ. Các biến cấu hình đầy đủ được mô tả trong [.env.example](.env.example).

## Kiểm thử

Chạy bộ acceptance tests:

```powershell
.\.venv\Scripts\python.exe -m unittest -q tests.test_acceptance
```

Dependency có thể được cài đặt tái lập bằng lockfile có hash:

```powershell
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock
```

## Cấu trúc repository

```text
app/
  api/              REST API FastAPI
  shared/           Dữ liệu, nghiệp vụ, bảo mật và tích hợp
  web/              Flask app, templates và static assets
tests/              Bộ acceptance tests
run_web.py          Điểm chạy website
run_api.py          Điểm chạy REST API
```

Repository chỉ chứa mã nguồn, assets cần thiết, dependency, cấu hình mẫu, tests và CI. Báo cáo đồ án, PDF/PPTX/DOCX, database runtime, log, release ZIP, môi trường ảo và cấu hình bí mật `.env` được giữ ngoài Git.
