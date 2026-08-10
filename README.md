# Touch! Việt Nam

Ứng dụng web hỗ trợ khám phá và lập kế hoạch du lịch trong nước. Hệ thống tập trung vào nội dung điểm đến, vé và đặt chỗ, lịch trình gợi ý, thời tiết, bản đồ, QR/AR và quản lý chi tiêu theo chuyến đi.

## Chức năng chính

- Tra cứu 63 điểm đến, phủ đủ 34 tỉnh/thành hiện hành, theo vùng, tỉnh/thành, loại hình và từ khóa.
- Xem ảnh, thông tin chi tiết, thời tiết, bản đồ và tiện ích lân cận.
- Tìm chuyến bay, tàu hỏa, xe khách và vé tham quan.
- Tạo lịch trình AI theo số ngày, ngân sách, số người và sở thích; tự dùng smart fallback khi dịch vụ AI ngoài gián đoạn.
- Lưu chuyến đi và quản lý chi tiêu nhóm.
- Quét QR để mở nhanh trang thông tin điểm đến.
- Giao diện tiếng Việt, tiếng Anh và tiếng Hàn.
- Bảng điều khiển riêng cho người dùng và quản trị viên.
- REST API bằng FastAPI cho các chức năng tích hợp.

## Yêu cầu

- Python 3.11 trở lên.
- Windows PowerShell nếu sử dụng các lệnh mẫu bên dưới.

## Cài đặt

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Trước khi triển khai, cần thay `APP_SECRET_KEY` trong `.env` bằng một khóa bí mật mạnh và cấu hình các dịch vụ ngoài nếu sử dụng.

Để bật chat và Planner AI qua OpenAI Responses API, đặt `OPENAI_API_KEY` trong
`.env`. Model mặc định được cấu hình bằng `OPENAI_CHAT_MODEL` và
`OPENAI_PLANNER_MODEL`; khi không có khóa, cả hai luồng vẫn hoạt động bằng cơ chế
dự phòng nội bộ.

## Chạy ứng dụng web

```powershell
.\.venv\Scripts\python.exe run_web.py
```

Mở `http://127.0.0.1:5000/`.

## Chạy REST API

```powershell
.\.venv\Scripts\python.exe run_api.py
```

Tài liệu OpenAPI chỉ được cung cấp tại `http://127.0.0.1:8000/docs` trong môi trường development/testing và bị tắt ở production.

## Kiểm thử trước bàn giao

```powershell
.\scripts\run_quality_checks.ps1
```

Cổng chất lượng biên dịch Python, kiểm tra cú pháp JavaScript, chạy bộ nghiệm
thu, SAST nội bộ, xác minh lockfile/SBOM, quét CVE và các kiểm tra bảo mật tự động.
Để chạy thêm DAST và stress smoke trên web/API tạm thời:

```powershell
.\scripts\run_quality_checks.ps1 -IncludeDynamicSecurity
```

Dependency runtime được cài reproducible bằng lockfile có hash:

```powershell
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock
```

`pip-audit` cần kết nối advisory database để cập nhật kết quả CVE.

## Tài khoản quản trị demo cục bộ

Tài khoản demo không nằm trong mã nguồn, README, database hay ZIP phát hành. Khi cần demo local, đặt
`APP_ENV=development`, `SEED_DEMO_USERS=true`, `DEMO_ADMIN_EMAIL` và
`DEMO_ADMIN_PASSWORD` trong `.env` bị loại khỏi gói phát hành. Production bắt buộc
tắt seed demo và tạo tài khoản bằng quy trình quản trị riêng.

## Cấu trúc dự án

```text
app/
  api/             REST API FastAPI
  shared/          Mô hình dữ liệu, dịch vụ, cơ sở dữ liệu và đa ngôn ngữ
  web/             Ứng dụng Flask, template và tài nguyên giao diện
data/              Dữ liệu runtime; database và log không được đóng gói
docs/              Tài liệu phân tích, thiết kế và nghiệm thu
scripts/           Công cụ bảo trì dữ liệu, hình ảnh và tài liệu
run_web.py         Điểm chạy website
run_api.py         Điểm chạy REST API
```

## Đóng gói

Chỉ tạo gói phát hành sau khi đã hoàn tất sửa lỗi và kiểm thử:

```powershell
.\package_release.ps1 -Version 1.1.0
```

Tệp ZIP được tạo trong thư mục `release/`. Môi trường ảo, database runtime, log,
cache Python, tài khoản demo và cấu hình bí mật `.env` không được đưa vào gói.
