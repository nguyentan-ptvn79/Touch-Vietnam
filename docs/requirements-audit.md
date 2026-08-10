# Đối chiếu 13 mục tiêu cụ thể — Touch! Việt Nam

Cập nhật và kiểm tra lại: 06/08/2026.

## Kết luận

Phiên bản hiện tại đáp ứng cả 13 mục tiêu trong phạm vi một đồ án ứng dụng web. Các
luồng vé, AI, bản đồ, thời tiết và tiện ích ngoài có cổng cấu hình, timeout, kiểm tra
địa chỉ đích và cơ chế dự phòng; chúng không thay thế hợp đồng nhà cung cấp, SLA 24/7
hay ứng dụng AR native. OWASP Top 10 là khung nhận diện rủi ro, không phải chứng nhận
pentest; trước vận hành thương mại vẫn cần cấu hình secret/HTTPS thực tế, giám sát và
quy trình phản ứng sự cố.

## Ma trận mục tiêu

| STT | Mục tiêu | Trạng thái | Minh chứng |
| --- | --- | --- | --- |
| 1 | Kho điểm đến Bắc, Trung, Nam; tìm theo vùng, tỉnh và từ khóa | Đạt | 63 điểm đến, phủ đủ 34 tỉnh/thành hiện hành; `/places`, `GET /api/places` hỗ trợ kết hợp `region`, `province`, `category`, `q`. |
| 2 | Phân loại núi, biển, hải đảo, tâm linh, văn hóa, lịch sử, ẩm thực, vui chơi; xếp hạng must-go | Đạt | 8 nhóm danh mục, bộ lọc và điểm `must_go_score` trên danh sách/chi tiết. |
| 3 | Tra cứu và giữ chỗ máy bay, tàu hỏa, xe khách, khu vui chơi; cổng nhà cung cấp ngoài | Đạt trong phạm vi nguyên mẫu | `/tickets`, lịch sử giữ chỗ và cổng REST cấu hình bằng `EXTERNAL_TICKET_*`; bản ghi nội bộ không phải xác nhận tồn chỗ thương mại khi chưa cấp tài khoản đối tác. |
| 4 | Planner AI theo ngày, điểm đến, số ngày, ngân sách, số người, sở thích | Đạt | `/planner`, `POST /api/planner`; Responses API với structured output khi có `OPENAI_API_KEY`, tự chuyển sang smart fallback khi dịch vụ ngoài không sẵn sàng. |
| 5 | Tiện ích gần người dùng/điểm đến | Đạt | Khách sạn, ăn uống, nhà thuốc, cửa hàng, chợ, siêu thị, bệnh viện, vui chơi qua geolocation + OSM/Overpass/cổng ngoài và dữ liệu dự phòng; có test ánh xạ đủ tám nhóm yêu cầu. |
| 6 | Dự toán ngân sách và quản lý chi tiêu nhóm | Đạt | Budget breakdown, chuyến đi đã lưu, người thanh toán, danh mục, thành viên chia tiền, ghi chú, số dư và đề xuất quyết toán tại `/expenses`. |
| 7 | Tiếng Việt, Anh, Hàn; duy trì lựa chọn trong phiên | Đạt | Cùng tập 486 khóa UI cho VI/EN/KO; 63/63 mô tả điểm đến có nội dung theo ngôn ngữ; lựa chọn lưu trong session. |
| 8 | Chatbox 24/7 bằng ngôn ngữ tự nhiên, có lịch sử và fallback | Đạt chức năng | Chat nổi toàn site, HTTP/WebSocket API, lưu lịch sử SQLite; Responses API khi có khóa và bộ trả lời nội bộ khi mất dịch vụ. “24/7” mô tả khả năng truy cập khi hệ thống vận hành, chưa phải SLA hạ tầng. |
| 9 | Responsive theo nhận diện Touch VN, dễ đọc và nhất quán | Đạt | Hệ thống template/CSS dùng chung, kiểm tra desktop và mobile; điều hướng, form, card, trạng thái rỗng và thông báo đồng nhất. |
| 10 | Dashboard user/admin; quản trị địa điểm, nội dung, truy cập, đề xuất, hiển thị, tích hợp | Đạt | `/dashboard`, `/admin`, CRUD địa điểm/nội dung/đề xuất, analytics thật + CSV, bật/tắt module và trạng thái cổng tích hợp. |
| 11 | Đăng ký, đăng nhập, phiên và phân quyền; bảo vệ thao tác ghi | Đạt | Flask session, JWT cho REST API, password hash, decorator admin, CSRF, validation và security headers. |
| 12 | Google Maps, thời tiết, AR/QR và JSON/GeoJSON dùng khi mạng yếu | Đạt trong phạm vi web prototype | Map nhúng, Open-Meteo + cache/fallback, QR scanner + camera overlay và gói offline theo miền ở `/offline-packs/<region>.json|geojson`; AR là lớp thông tin camera trên web, không phải định vị marker 3D native. |
| 13 | Đánh giá chức năng, hiệu năng, responsive và OWASP Top 10:2025 | Đạt baseline tự động | 22/22 acceptance tests PASS; Ruff/Bandit/SAST PASS; pip-audit không phát hiện CVE; DAST PASS; stress smoke ngày 06/08/2026 với 120 request/12 worker, 0 lỗi, p95 0,921 giây và max 1,254 giây (ngưỡng p95 3 giây); chưa thay thế pentest độc lập. |

## Ma trận OWASP Top 10:2025

| Hạng mục | Kiểm soát trong dự án | Minh chứng kiểm thử |
| --- | --- | --- |
| A01 Broken Access Control | Phân quyền user/admin, kiểm tra quyền sở hữu, CSRF, SSRF, session reset và thu hồi JWT | Acceptance/API/DAST kiểm tra route ẩn danh, route admin và token sau logout |
| A02 Security Misconfiguration | Production bắt buộc secret mạnh, HTTPS/HSTS, docs API tắt, debug/auto-reload tắt và security headers | Test cấu hình production; DAST kiểm tra header, `.env`, `.git` và `/docs` |
| A03 Software Supply Chain Failures | `requirements.lock` có SHA-256 cho dependency trực tiếp/gián tiếp, SBOM CycloneDX và pip-audit | Lock/SBOM verify PASS; pip-audit báo “No known vulnerabilities found” |
| A04 Cryptographic Failures | Werkzeug password hash, JWT audience/issuer/JTI, cookie Secure/HttpOnly, HSTS và secret ngoài mã nguồn | Acceptance kiểm tra auth; DAST kiểm tra cookie/header; `.env` không vào ZIP |
| A05 Injection | SQLite parameter binding, Pydantic/form validation, Jinja autoescape, URL booking chỉ HTTP(S) | SQL injection test, static security check và DAST reflected-XSS/URL boundary PASS |
| A06 Insecure Design | Giới hạn đầu vào, giới hạn pixel ảnh, fallback an toàn, timeout và tách quyền nhà cung cấp | Acceptance planner/ticket/upload; stress smoke không lỗi tài nguyên |
| A07 Authentication Failures | Xóa session khi đăng nhập, idle/absolute timeout, POST logout, rate limit, JWT audience và revoke | Acceptance auth/CSRF/admin; DAST GET logout bị từ chối; token revoke được kiểm tra |
| A08 Software or Data Integrity Failures | Structured output Pydantic, chi phí do server tính, URL ngoài được kiểm tra và artifact có lock/SBOM | Acceptance planner/ticket; supply-chain artifact verification PASS |
| A09 Security Logging & Alerting Failures | Audit event có cấu trúc, HMAC signature, log sự kiện auth/admin/authorization/integration và ngưỡng cảnh báo | Kiểm tra runtime log, audit log verification và quality gate SAST/DAST PASS |
| A10 Mishandling of Exceptional Conditions | Global error handler, rollback, timeout, fallback provider, quota/rate limit và giới hạn ảnh | Acceptance fallback/offline; DAST; stress smoke 120 request, 0 lỗi |

## Điều kiện để triển khai thương mại

- Thay `APP_SECRET_KEY`, đổi mật khẩu tài khoản bàn giao và đặt `APP_ENV=production`.
- Đặt `SEED_DEMO_USERS=false`, để trống `DEMO_ADMIN_*`, dùng `APP_PUBLIC_BASE_URL` HTTPS
  và cấu hình `TRUSTED_PROXY_IPS` nếu triển khai sau reverse proxy.
- Cấp `OPENAI_API_KEY` nếu muốn dùng AI live thay vì smart fallback.
- Cấp endpoint/key của hãng vé hoặc aggregator nếu muốn trả tồn chỗ và giá thương mại.
- Dùng HTTPS/reverse proxy; cân nhắc PostgreSQL và kho session dùng chung khi chạy nhiều instance.
