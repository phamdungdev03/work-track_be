# WorkTrack Backend — demo chấm công, không đăng nhập

Dùng source `work-track_be` và 10 bảng MySQL đã tạo. Không chạy `migrate`, không import lại schema/seed khi khởi động. Models là `managed=False`; MySQL giữ FK/CHECK và các cột generated. SQLite cũ không còn được sử dụng.

## Khởi động trên máy hiện tại

File `.env` đã được tạo với host **127.0.0.1**, port **3307**, mật khẩu trống. Điền DB_PASSWORD, kiểm tra DB_NAME và DB_USER theo database của bạn. Nếu mật khẩu có `#` hoặc khoảng trắng, đặt giá trị trong dấu nháy. Không đưa `.env` lên Git.

```bash
cd work-track_be
source .venv/bin/activate
python manage.py check
python manage.py check_db
python manage.py runserver 127.0.0.1:8000
```

`check_db` chỉ đọc và kiểm tra đủ 10 bảng. **Không cần đăng nhập, đặt mật khẩu tài khoản seed hoặc gửi token.** Mở demo, chọn nhân viên/cơ sở và gọi API quét trực tiếp. Mật khẩu MySQL trong `.env` vẫn cần để backend kết nối database.

- Liveness không cần MySQL: `GET http://127.0.0.1:8000/api/health/`.
- Đã kiểm chứng kết nối và đọc ORM trên MySQL 127.0.0.1:3307 sau khi bạn điền mật khẩu; các test ghi dữ liệu vẫn chạy trên instance riêng.
- DB_NAME mặc định `worktrack`, DB_USER mặc định `root`: đổi nếu bạn đã tạo database/tài khoản khác.
- CORS cho localhost/127.0.0.1 cổng 3000 và 5173, phù hợp FE đang có hoặc Vite.
- DEMO_MODE=true cho phép API mô phỏng, không kiểm tra vai trò. Tắt flag sẽ khóa endpoint; API thiết bị thật chưa triển khai.

## Cài lại ở môi trường khác

Python 3.12, Django 5.2, MySQL >= 8.0.16 (mục tiêu 8.4). Ubuntu cần thư viện build của mysqlclient:

```bash
sudo apt-get install python3-dev default-libmysqlclient-dev build-essential pkg-config
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Đặt chuỗi vừa tạo vào DJANGO_SECRET_KEY và điền thông tin MySQL. Trên workspace hiện tại thư viện client được cài cục bộ trong `.venv/mysql-client` vì sudo yêu cầu mật khẩu. Virtualenv có đường dẫn máy hiện tại; không copy virtualenv sang máy khác, hãy cài lại theo các lệnh trên.

## Phạm vi demo

Theo yêu cầu, backend không có login/token/phân quyền. Các màn nhân viên và HR là góc nhìn demo, không phải quyền tài khoản. API đọc và quét gọi trực tiếp trên localhost.

Bảng users và các FK người tạo/người duyệt trong dữ liệu SQL vẫn giữ để không phá dữ liệu đã nhập. Không có API quản lý tài khoản. Lượt quét demo mới lưu actor_user_id=NULL, source_key=`demo:kiosk`; không giả danh HR. Client tạo request_id mới (nên dùng UUID) cho mỗi lần quét, giữ nguyên mã khi retry.

## API đã có

| Method | Path | Mục đích |
|---|---|---|
| GET | /api/health/ | Kiểm tra process, không truy vấn DB |
| GET | /api/health/database/ | Kiểm tra MySQL |
| GET | /api/facilities/ | Cơ sở |
| GET | /api/employees/ | Nhân viên |
| GET | /api/employees/{id}/ | Chi tiết nhân viên |
| GET | /api/schedules/ | Lịch ca |
| POST | /api/schedules/demo-create/ | Tạo ca demo khi chưa có ca |
| GET | /api/support-assignments/ | Phân công support |
| POST | /api/support-assignments/create/ | Tạo phân công, có request_id chống trùng |
| PUT | /api/support-assignments/{id}/ | Sửa phân công, kiểm tra updated_at |
| POST | /api/support-assignments/{id}/cancel/ | Hủy phân công, ghi lý do và audit |
| GET | /api/scans/ | Lịch sử lượt thử/quét |
| POST | /api/scans/demo/ | Quét mô phỏng mặt, tự IN/OUT |
| POST | /api/qr/challenges/ | Phát QR động cho cơ sở |
| POST | /api/qr/scans/ | Chấm công QR với vị trí mô phỏng |
| GET | /api/alerts/ | Cảnh báo HR |
| POST | /api/alerts/{id}/verify/ | Xác minh support, yêu cầu ghi chú |
| GET | /api/requests/ | Giải trình |
| POST | /api/requests/{id}/review/ | Duyệt hoặc từ chối yêu cầu, yêu cầu ghi chú |

List phân trang: `count`, `next`, `previous`, `results`; `page=1&page_size=20` (tối đa 100).

Ví dụ:

```text
/api/employees/?facility_id=1&search=NV001
/api/scans/?employee_id=1&date=2026-10-28&outcome=ACCEPTED
/api/schedules/?date=2026-10-28&facility_id=1
/api/requests/?status=PENDING
/api/alerts/?status=OPEN
```

Ngày lọc theo giờ Việt Nam; timestamps trả ISO 8601 có múi giờ. Không trả password hash, token QR hay payload hash ở API danh sách.

### Quét mô phỏng

```http
POST /api/scans/demo/
Content-Type: application/json

{
  "request_id": "demo-nv001-20261029-01",
  "employee_id": 1,
  "facility_id": 1,
  "occurred_at": "2026-10-29T08:30:00+07:00",
  "recognition": "MATCH"
}
```

- `occurred_at` tùy chọn: bỏ thì dùng giờ server. Nếu gửi bắt buộc có Z hoặc offset. Ngày 29 tránh đụng chuỗi lịch sử seed 26–28; vì chưa có lịch ngày 29 nên trả cảnh báo NO_SCHEDULE và chưa tính công.
- `recognition`: MATCH/NO_FACE/UNREGISTERED; mặc định MATCH. Không nhận input event_type, source_type hoặc kết quả từ client.
- Request mới trả 201 kể cả quyết định IGNORED/REJECTED, vì đã lưu lần thử. Kiểm tra `scan.outcome` để biết có ghi nhận công hay không. Replay cùng mã/nội dung trả 200, `replayed=true`; cùng mã khác nội dung trả 409.
- Cùng nhân viên khóa trong transaction; ngưỡng hiện lấy cấu hình cơ sở đang quét. Retry deadlock có giới hạn. Lượt lỗi/quét trùng không đảo chiều hoặc kéo dài cooldown.
- Đầu ngày hoặc sau OUT → IN; sau IN cùng cơ sở → OUT; sau IN khác cơ sở → IN kèm MISSING_PREVIOUS_OUT. Xét lớp điều chỉnh APPROVED trong database.
- Thiếu phân công vẫn ACCEPTED; gộp SUPPORT_UNASSIGNED theo người/ngày/cơ sở. Cảnh báo đã VERIFIED có lượt mới sẽ OPEN lại và giữ audit xác minh trước.
- Giờ lùi trước lượt được nhận gần nhất hoặc điều chỉnh có hiệu lực bị từ chối. Chưa hỗ trợ nhập sự kiện offline đến muộn.
- Trả `message` sẵn cho FE đọc “Xin chào …, mời vào”, “Xin tạm biệt …” hoặc lý do không ghi nhận; `warnings` độc lập.
- Không sửa lịch/snapshot công đã khóa. Dữ liệu demo là dữ liệu được ghi thật vào database đang cấu hình; dùng database dành cho demo.

### QR support

`POST /api/qr/challenges/` nhận `facility_id`; trả token ngẫu nhiên và thời điểm hết hạn theo giờ server. Có thể gửi thêm `previous_token` để thu hồi mã cũ khi đổi mã thủ công. Chỉ lưu hash token, không lưu nội dung token rõ. Thời hạn lấy từ `facilities.qr_ttl_seconds` (demo mặc định 20 giây).

`POST /api/qr/scans/` nhận `request_id`, `employee_id`, `facility_id`, `qr_token`, `gps_status` (`IN_RANGE`, `OUT_OF_RANGE`, `UNAVAILABLE`) và `occurred_at` demo tùy chọn. Lượt QR dùng chung lịch sử/cooldown và suy chiều với quét mặt. `IN_RANGE` là giá trị **mô phỏng**, không phải GPS thật. `OUT_OF_RANGE`, `UNAVAILABLE` hoặc thiếu QR tạo lượt PENDING_REVIEW và yêu cầu PRESENCE chờ xử lý, không tự ghi IN/OUT. Mã sai/hết hạn/thu hồi/sai cơ sở/đã dùng bị từ chối. Không có phân công support vẫn chấm thành công và cảnh báo HR.

Mã hợp lệ dùng được cho nhiều nhân viên, mỗi người một lần. Khóa nhân viên và UNIQUE của MySQL chống sử dụng trùng khi gửi đồng thời. Retry đúng request trả lại quyết định cũ trước khi kiểm tra mã hết hạn. Thời gian QR luôn là giờ server, độc lập đồng hồ demo. Mô phỏng không có login; `actor_user_id` và `requested_by` cho yêu cầu hiện diện có thể NULL.

Database tạo từ schema 10 bảng cũ cần chạy một lần [qr-demo-schema-update.sql](../database/qr-demo-schema-update.sql). Trên database đã cấu hình của bạn, migration đã được áp dụng và xác nhận số hàng không thay đổi. Database mới tạo từ schema cập nhật không cần chạy lại migration.

### HR xác minh và xử lý giải trình

- `POST /api/alerts/{id}/verify/`: gửi `review_note` và `expected_last_seen_at` từ cảnh báo. Nếu có lượt mới sau lúc mở xác minh, API trả 409 để HR tải lại và xem bằng chứng. Xác minh không sửa lượt hoặc tự đổi công.
- `POST /api/requests/{id}/review/`: gửi `decision` là APPROVED/REJECTED, `review_note` và `expected_version` của yêu cầu. Duyệt tạo hiệu lực cho nội dung đã đề xuất, không sửa scan gốc. Từ chối không tạo hiệu lực. Retry đúng quyết định/ghi chú/phiên bản trả kết quả cũ; yêu cầu đã thay đổi hoặc đã xử lý khác sẽ trả 409.
- PRESENCE có thể duyệt khi chưa có lịch ca: vẫn được coi là lượt vào/ra đã xác minh khi xác định chiều tiếp theo. Chưa có lịch thì chưa kết luận được số công. Ngày đã khóa không được duyệt thay đổi công.
- Không có đăng nhập theo phạm vi demo. `reviewed_by`/`verified_by` để NULL; audit ghi SYSTEM và `mode=HR_DEMO`, không giả danh nhân sự thật. Muốn xác thực người duyệt trong sản phẩm thật cần bổ sung phân quyền.
- Cần schema HR cập nhật từ [hr-demo-schema-update.sql](../database/hr-demo-schema-update.sql). Database hiện tại của bạn đã áp dụng và giữ nguyên số hàng; schema mới đã gồm thay đổi, không chạy lại migration trên database mới.

### HR tạo, sửa, hủy support

- Cần ca `SCHEDULED` và chưa khóa của nhân viên. Nếu chưa có ca, HR có thể chủ động `POST /api/schedules/demo-create/` với `employee_id`, `work_date` để tạo ca 08:30–17:30, 60 phút nghỉ, 480 phút chuẩn. Một ca/người/ngày; gửi lại cùng nhân viên/ngày trả ca sẵn có, không tạo trùng. Giờ nghỉ là lịch dự kiến, không tự khẳng định nhân viên đã nghỉ (`break_confirmed=false`). Không tự phục hồi ca đã hủy.
- Tạo support gửi `request_id`, `schedule_id`, `from_facility_id`, `to_facility_id`, `depart_at`, `expected_arrival_at`, `support_ends_at` (ISO 8601 có offset) và `reason`. HR demo tạo trạng thái CONFIRMED; `created_by`/`confirmed_by` NULL, timestamp và audit SYSTEM/HR_DEMO thể hiện thao tác mô phỏng.
- Sửa gửi toàn bộ trường phân công và `expected_updated_at` mới nhất. Hủy gửi `expected_updated_at` và lý do. Phân công hủy vẫn lưu, không thể sửa; tạo mới khi cần. Cập nhật ca đã khóa bị từ chối.
- Validate cơ sở đang hoạt động, đi khác đến; giờ đi ≤ đến < kết thúc, tất cả trong ca; các khoảng support trong một ca không chồng nhau (sát biên được phép). Ghi đồng thời khóa theo nhân viên/ca; request_id giống nội dung trả kết quả cũ, khác nội dung báo 409. Khi sửa/hủy bị mất kết nối, tải lại danh sách trước khi thực hiện tiếp.
- Có thể tạo bù từ cảnh báo HR. Việc tạo/sửa/hủy không sửa lượt quét, không tự đóng/xác minh cảnh báo hoặc tự tính công. HR cần xác minh cảnh báo riêng; các lượt sau được đối chiếu với phân công mới.
- Database hiện tại đã được nâng cấp và không thay đổi số hàng. Database cũ khác cần [support-assignment-demo-update.sql](../database/support-assignment-demo-update.sql) và [support-demo-shift-update.sql](../database/support-demo-shift-update.sql); database mới tạo từ schema hiện tại không cần chạy lại.

## Chưa triển khai trong bước này

GPS thật và xác thực thực địa; tích hợp camera/máy; quản lý ca tổng quát/ca qua đêm; công thức tính công/bảng công; tạo giải trình thủ công từ UI; xác thực/phân quyền người dùng. Dữ liệu seed của các phần này đã đọc được nhưng không có nghĩa luồng ghi đã triển khai.

## Kiểm thử MySQL

Tests import SQL thật và INSERT của seed vào database test riêng, không đổi model sang managed hay dùng SQLite thay MySQL. Có guard yêu cầu bật rõ chế độ test:

```bash
# Chọn instance MySQL dành cho test. Account cần quyền tạo/xóa database test.
export WORKTRACK_ALLOW_TEST_DB=true
export WORKTRACK_TEST_DB_NAME=test_worktrack_backend
# Đặt DB_HOST/DB_PORT/DB_USER/DB_PASSWORD cho instance test qua môi trường.
python manage.py test attendance --settings=config.test_settings --noinput
```

Không dùng `--keepdb`: test runner tạo schema mới cho unmanaged models. Chỉ dùng tên bắt đầu `test_worktrack_`; Django tạo/xóa database này. 

Các case: đọc đúng bộ 100 người/5 cơ sở không cần token; endpoint login đã bỏ; quét không cần tài khoản; IN/OUT/cooldown/replay/conflict; thiếu phân công/thiếu OUT; áp giải trình đã duyệt; lỗi nhận diện/giờ lùi; không sửa snapshot khóa; JSON sai định dạng; lượt chưa nhận diện; hai lượt đầu đồng thời chỉ một ACCEPTED.

Kiểm chứng bản hiện tại: `manage.py check` thành công; **18 test** qua trên MySQL 8.0.44 riêng với schema/seed thật. Kết nối đọc tới MySQL 127.0.0.1:3307 của người dùng đã kiểm chứng ở bước trước; không sửa dữ liệu của bạn trong thay đổi bỏ đăng nhập này.

Giữ thư mục `attendance/`: đây là app chứa models, API, logic chấm công và tests. `config/` chỉ chứa cấu hình/route tổng. `__pycache__/` có thể xóa; `.venv/` là môi trường Python, cần tạo/cài lại nếu xóa.
