# AI Radar Scheduler (Cloudflare Worker)

External cron scheduler for [ai-radar](https://github.com/dootan2020/ai-radar) hosted on Cloudflare Workers (Free Plan).

---

## 1. Mục đích & Bối cảnh

- **Vấn đề**: ai-radar cam kết thông tin cập nhật không quá 30 phút (`freshness < 30m`). Tuy nhiên, cron tích hợp của GitHub Actions (`7,37 * * * *` trong `.github/workflows/update.yml`) hoạt động không ổn định khi tải cao — thực tế ngày 03/10/2026 chỉ kích hoạt 4 lần (02:17, 08:31, 13:39, 17:52 UTC) thay vì 48 lần.
- **Giải pháp**: Cloudflare Worker độc lập định kỳ gọi GitHub REST API trigger workflow bằng `workflow_dispatch` trên nhánh `main`.
- **Dự phòng hai lớp**: Cron nội bộ của GitHub vẫn được giữ nguyên (`7,37 * * * *`). Nhóm `concurrency` trong `update.yml` (`group: github-pages-${{ github.ref }}`, `cancel-in-progress: false`) đảm bảo các lượt chạy không bao giờ bị chồng lấn hay xung đột.

---

## 2. Quyết định Nhịp độ (Cadence Proposal & Decision)

### Đề xuất và Lựa chọn
Worker được cấu hình lịch chạy cho 2 workflow độc lập:
1. **`update.yml`**: chạy **mỗi 20 phút** (`*/20 * * * *`) vào các phút 00, 20, 40 của mỗi giờ (UTC).
2. **`shadow-collector.yml`**: chạy **mỗi 1 giờ** (`5 * * * *`) vào phút thứ 5 của mỗi giờ (UTC).

```toml
[triggers]
crons = ["*/20 * * * *", "5 * * * *"]
```

### Lập luận & So sánh (Arguments)
- **update.yml (20 phút)**: Đảm bảo 3 lần chạy/giờ; ngay cả khi GitHub cron tê liệt hoàn toàn, tuổi đời tin tức tối đa chỉ 20-25 phút. Khoảng trống 10-15 phút đủ cho runner hoàn tất lưu cache và deploy Pages an toàn.
- **shadow-collector.yml (phút 05 mỗi giờ)**:
  - Tránh hoàn toàn các mốc chạy của `update.yml` do Worker dispatch (`00`, `20`, `40`).
  - Tránh mốc cron dự phòng của GitHub Actions cho `update.yml` (`07`, `37`).
  - Tránh mốc cron nội bộ ban đầu của shadow collector (`17`).
  - Shadow collector có timeout 15 phút, kết thúc hoàn toàn trước mốc `update.yml` kế tiếp tại phút 20.

**Chi phí & Hạn mức Cloudflare Free**:
- `update.yml`: 3 lần/giờ = 72 lần/ngày = ~2.160 lần/tháng.
- `shadow-collector.yml`: 1 lần/giờ = 24 lần/ngày = ~720 lần/tháng.
- **Tổng cộng**: 96 lần/ngày (~2.880 lần/tháng).
- Hạn mức Free của Cloudflare Workers: 100.000 requests/ngày.
- Sử dụng chỉ **0,096%** hạn mức miễn phí, hoàn toàn an toàn và không phát sinh chi phí.

---

## 3. Chuẩn bị Token GitHub (Dành cho Repo Owner)

Tạo **Fine-grained Personal Access Token (PAT)** với nguyên tắc đặc quyền tối thiểu (*least privilege*):

1. Truy cập [GitHub Token Settings](https://github.com/settings/tokens?type=beta) -> **Generate new token**.
2. **Token name**: `ai-radar-scheduler-cloudflare`
3. **Expiration**: 90 ngày hoặc 1 năm (đặt lịch nhắc nhở trước ngày hết hạn).
4. **Repository access**:
   - Chọn **Only select repositories** -> chọn đúng `dootan2020/ai-radar`.
5. **Permissions**:
   - Mục **Repository permissions**:
     - `Actions`: chọn **Read and write** (để trigger `workflow_dispatch`).
   - Mọi quyền khác: để mặc định **No access**.
6. Nhấn **Generate token** và sao chép mã token.

> **Quy tắc an toàn bảo mật (secrets-hygiene)**:
> - Tuyệt đối KHÔNG commit token vào git.
> - Tuyệt đối KHÔNG dán token vào khung chat, issue, PR hay gửi qua tin nhắn.
> - Token chỉ được lưu dưới dạng Secret của Worker trên Cloudflare.
> - Sau khi copy token, chạy `Set-Clipboard -Value ' '` trên máy trạm để xóa clipboard.

---

## 4. Các bước triển khai (Dành cho Coordinator)

Toàn bộ quá trình triển khai chỉ cần thực hiện từ thư mục `scheduler/`:

### Bước 1: Kiểm tra đăng nhập Wrangler
```bash
npx wrangler whoami
```
*(Nếu chưa đăng nhập, chạy `npx wrangler login` và làm theo hướng dẫn trên trình duyệt)*.

### Bước 2: Thiết lập Secret `GITHUB_TOKEN`
Chạy lệnh sau và dán token do Owner cung cấp khi terminal yêu cầu:
```bash
npx wrangler secret put GITHUB_TOKEN --config scheduler/wrangler.toml
```

### Bước 3: Triển khai Worker (One Command Deploy)
```bash
npx wrangler deploy --config scheduler/wrangler.toml
```
*(Hoặc `cd scheduler` rồi chạy `npx wrangler deploy`)*.

### Bước 4: Kiểm tra trạng thái hoạt động (Health Check)
Truy cập URL của Worker (được in ra sau lệnh deploy, dạng `https://ai-radar-scheduler.<subdomain>.workers.dev/health`):
```bash
curl -s https://ai-radar-scheduler.<subdomain>.workers.dev/health
```
Kết quả trả về JSON xác nhận Secret đã có mặt mà không để lộ giá trị:
```json
{
  "status": "ok",
  "service": "ai-radar-scheduler",
  "hasToken": true,
  "workflow": "update.yml",
  "shadowWorkflow": "shadow-collector.yml",
  "repo": "dootan2020/ai-radar",
  "ref": "main"
}
```

> **Không có endpoint kích hoạt thủ công qua HTTP.** Worker chỉ phục vụ `/` và `/health`; chỉ cron mới gọi được `dispatchWorkflow` (mọi đường dẫn khác, kể cả `POST /trigger`, trả 404). Muốn thử thủ công: chạy cục bộ `npx wrangler dev --test-scheduled --port 8798 --config scheduler/wrangler.toml` rồi `curl "http://localhost:8798/__scheduled"`, hoặc chờ cron và đọc `gh run list` ở mục 5.

---

## 5. Xác minh nhịp độ thực tế (Verify Cadence)

Sau khi deploy, sử dụng GitHub CLI (`gh`) để theo dõi các lượt kích hoạt:

```bash
gh run list --workflow update.yml --limit 10
gh run list --workflow shadow-collector.yml --limit 10
```

Kết quả hiển thị rõ nguồn gốc kích hoạt:
- **`update.yml`**:
  - `workflow_dispatch`: Các lượt do Cloudflare Worker kích hoạt vào các phút `:00`, `:20`, `:40`.
  - `schedule`: Các lượt do GitHub Actions cron nội bộ kích hoạt vào các phút `:07`, `:37`.
- **`shadow-collector.yml`**:
  - `workflow_dispatch`: Các lượt do Cloudflare Worker kích hoạt vào phút `:05` mỗi giờ.
  - `schedule`: Lượt dự phòng do GitHub Actions cron nội bộ kích hoạt vào phút `:17`.

Ví dụ minh họa:
```text
STATUS  TITLE              WORKFLOW           BRANCH  EVENT              ID          ELAPSED  AGE
*       Update AI Radar    Update AI Radar    main    workflow_dispatch  1823901234  6m12s    2m
✓       Update AI Radar    Update AI Radar    main    workflow_dispatch  1823875641  5m45s    22m
✓       Update AI Radar    Update AI Radar    main    schedule           1823851092  6m01s    35m
✓       Update AI Radar    Update AI Radar    main    workflow_dispatch  1823819001  5m50s    42m
```

---

## 6. Xử lý khi Token hết hạn hoặc xoay vòng (Token Expiry & Rotation)

Khi token hết hạn, GitHub API sẽ trả về lỗi `401 Unauthorized`. Worker sẽ:
1. Ghi log lỗi đúng 1 lần vào Cloudflare Logs (`GitHub API dispatch failed with status 401 Unauthorized: Bad credentials`).
2. Dừng ngay lập tức, **không gửi dồn dập (no retry burst)**.
3. Fallback: Cron nội bộ của GitHub (`schedule`) vẫn tiếp tục kích hoạt độc lập vì dùng `GITHUB_TOKEN` nội bộ của GitHub Actions.

**Quy trình xoay vòng token**:
1. Owner tạo token mới trên GitHub.
2. Coordinator chỉ cần chạy lại một lệnh duy nhất:
   ```bash
   npx wrangler secret put GITHUB_TOKEN --config scheduler/wrangler.toml
   ```
   *Không cần deploy lại mã nguồn!*

---

## 7. Chạy kiểm thử offline (Offline Testing)

Toàn bộ test suite được viết bằng Node.js built-in test runner (`node:test`), chạy 100% offline, không phụ thuộc network hay external packages:

```bash
npm test --prefix scheduler
```
Hoặc:
```bash
node --test scheduler/test/worker.test.mjs
```

Suite kiểm chứng đầy đủ:
- URL, HTTP method (POST), Headers (Accept, Authorization, X-GitHub-Api-Version, User-Agent, Content-Type), và Body (`{"ref":"main"}`).
- Thiếu `GITHUB_TOKEN`: ghi log tên biến và **không** gửi bất kỳ HTTP request nào.
- Phản hồi lỗi (401, 500, lỗi mạng): ghi log lỗi 1 lần và **không retry**.
- Endpoint `/health` hoạt động chính xác và không bao giờ rò rỉ token.
