# Backfill bản tin chưa hiện

`python -m phong_bao bu-cham` kiểm tra các quyết định `publish` chưa có bản tin đã qua bàn chấm. Lệnh dùng bản ghi writer, reporter và các desk trong cycle đã lưu; bản `hold`, `summary: none` và prose đã chấm trượt không được chọn. Bàn chấm vẫn phải cho verdict đạt thì bản tin mới hiện trên site.

Chạy dry-run trước, với `--since` là ngày UTC của cycle cũ nhất muốn xét. Nếu bỏ `--since`, lệnh bắt đầu từ cycle cũ nhất đang lưu. Dry-run in số ứng viên `score` và `write`, lý do bị loại, cùng ngày mới nhất/cũ nhất của các cycle có ứng viên. Nó không sửa dữ liệu.

```sh
python -m phong_bao bu-cham --decisions phong-bao/decisions.json --cycles phong-bao/cycles
```

Chạy từng batch ngoài giờ cycle thường chạy, sau khi xem dry-run:

```sh
python -m phong_bao bu-cham --decisions phong-bao/decisions.json --cycles phong-bao/cycles --since 2026-10-27 --modes score,write --limit 20 --run
```

Lệnh chấm trước rồi mới viết, ưu tiên cycle mới nhất trong mỗi mode. `--modes score` hoặc `--modes write` chỉ chạy một mode. `--limit` là tổng số story trong một lượt. Kết quả được ghi vào `decisions.json` và thư mục retry `viet-bu` của các cycle mới; có thể chạy lại để tiếp tục batch sau. Lệnh `--run` giữ cùng `cycle.lock` với cycle định kỳ và từ chối chạy đồng thời. Không chạy hai lệnh backfill cùng lúc.
