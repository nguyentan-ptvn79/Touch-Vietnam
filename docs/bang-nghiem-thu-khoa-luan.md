# Bảng nghiệm thu — Touch! Việt Nam

Cập nhật: 30/07/2026.

## Kết quả tự động

Chạy tại thư mục gốc:

```powershell
.\scripts\run_quality_checks.ps1
```

Kết quả gần nhất: `20 tests — OK`, quality gate `PASS`.

## Nhóm ca kiểm thử

| Nhóm | Nội dung đã kiểm tra | Kết quả |
| --- | --- | --- |
| Điểm đến | 63 điểm, đủ 34 tỉnh/thành hiện hành, ba miền, tìm kiếm kết hợp bộ lọc, 8 danh mục, must-go | PASS |
| Đa ngôn ngữ | Bộ khóa VI/EN/KO đồng nhất; toàn bộ mô tả điểm đến được bản địa hóa | PASS |
| Planner AI | Số ngày, ngân sách, người, sở thích; structured Responses output; smart fallback | PASS |
| Vé | Máy bay, tàu hỏa, xe khách, khu vui chơi; ưu tiên provider ngoài; giữ chỗ | PASS |
| Tài khoản | Đăng nhập admin, session, CSRF, quyền truy cập web và REST API | PASS |
| Chat | Lịch sử hội thoại và fallback nội bộ khi không có OpenAI | PASS |
| Chi tiêu | Chuyến đi, người trả, thành viên chia, danh mục, ghi chú, số dư | PASS |
| Offline/AR | JSON, GeoJSON tải được; route QR/camera hoạt động | PASS |
| Hiệu năng | Các route chính phản hồi dưới ngưỡng nghiệm thu 2 giây trong môi trường test | PASS |
| Bảo mật | Secret production, SSRF/private network, SQL injection, dependency pinning, security headers | PASS |

## Luồng demo nghiệm thu

1. Mở `/places`, tìm theo từ khóa và lọc đồng thời vùng, tỉnh, danh mục.
2. Chuyển `VI / EN / KO`; mở chi tiết điểm đến để kiểm tra nội dung và session.
3. Mở `/tickets`, thử lần lượt bốn loại vé và thực hiện giữ chỗ sau khi đăng nhập.
4. Mở `/planner`, nhập số ngày, ngân sách, số người, sở thích và tạo lịch trình.
5. Lưu chuyến đi, mở `/expenses`, thêm khoản chi và xem quyết toán nhóm.
6. Dùng chatbox, đóng/mở lại để kiểm tra lịch sử.
7. Mở QR/AR, cho phép camera hoặc chọn ảnh QR; tải JSON/GeoJSON theo miền.
8. Cấu hình tài khoản demo qua `.env` local, đăng nhập và kiểm tra dashboard, nội dung,
   địa điểm, đề xuất, analytics CSV, module hiển thị và cổng tích hợp.

## Ghi chú bàn giao

- Tài khoản demo chỉ được seed từ `.env` local và không nằm trong gói phát hành.
- Không có khóa nhà cung cấp trong mã nguồn hay gói phát hành.
- Khi chưa cấu hình dịch vụ ngoài, website vẫn vận hành bằng dữ liệu và cơ chế dự phòng.
