# Hợp đồng ứng viên (hãng tin → toà soạn)

Phiên bản 1. Lucy viết 2026-10-28 22:0x cho lát 1 (ai-radar `radar/ung_vien.py`) và lát 2 (firstmate-control `integration/phong-bao/chu-ky.py`). Hai lát không chia sẻ mã; chúng chia sẻ đúng tệp JSON này. Sửa hợp đồng = sửa cả hai lát, nên hỏi phiên chủ trước khi thêm hoặc đổi nghĩa một trường.

## Lệnh

```
python -m radar.ung_vien --hours 8 --limit 30 --out <đường dẫn json> [--snapshot <tệp hoặc URL>] [--decisions <tệp>] [--same-event-hours 48]
```

- Mặc định đọc ảnh chụp site `https://radar-ai-vn.pages.dev/data/radar-intake.json` (hằng `SNAPSHOT_URL` trong `phong_bao/cycle.py`); `--snapshot` nhận tệp cục bộ hoặc URL thay cho ảnh chụp.
- Chạy hoàn toàn không mạng cần thêm `--articles <tệp json>` (`{url: {text, reason, fetched_at}}`, chép từ một lần tải thật): chỉ `--snapshot` thì bài vẫn được tải qua mạng. `--now <ISO UTC>` neo cửa sổ thời gian cho test và chạy lại. Hai cờ này không thêm trường nào vào tệp JSON.
- `--same-event-hours` đổi cửa sổ so tiêu đề với decision `publish` (mặc định 48 giờ, phải dương). Decision cần có `published_at`, hoặc story cùng `id` trong snapshot cần có `published_at`; decision thiếu cả hai không được so tiêu đề.
- Exit 0 khi ghi được tệp, kể cả khi 0 ứng viên. Exit khác 0 chỉ khi không lấy được ảnh chụp hoặc không ghi được tệp. Lỗi tải từng bài không làm lệnh thất bại; bài đó vào `rejected`.
- Chỉ in ra stdout một dòng tóm tắt đếm (`in_window=… candidates=… rejected=…`); mọi thứ khác vào tệp.

## Tệp JSON

```json
{
  "schema_version": 1,
  "generated_at": "2026-10-28T15:05:12Z",
  "snapshot_generated_at": "2026-10-28T14:37:00Z",
  "window_hours": 8,
  "limit": 30,
  "counts": {"in_window": 41, "candidates": 23, "rejected": 18},
  "candidates": [
    {
      "id": "64295c3ae779f4acba31",
      "title": "Frontier AI labs say their models refuted the Exponential Time Hypothesis",
      "title_vi": "OpenAI và Anthropic nói mô hình của họ bác bỏ Giả thuyết Thời gian Hàm mũ",
      "url": "https://techcrunch.com/2026/10/27/…",
      "source": {"name": "techcrunch", "kind": "outlet"},
      "published_at": "2026-10-28T09:12:00Z",
      "text": "… toàn văn bài, đã bỏ điều hướng, quảng cáo, chú thích ảnh …",
      "text_chars": 5120,
      "text_source": "full",
      "text_fetched_at": "2026-10-28T15:04:58Z",
      "coverage": [{"id": "244281e7cfee66fe46a3", "title": "…", "url": "https://…"}],
      "same_event_published": [],
      "same_event_links": []
    }
  ],
  "rejected": [
    {"id": "…", "title": "…", "url": "https://…", "reason": "already_summarised", "detail": "key_points x4"},
    {"id": "…", "title": "…", "url": "https://www.bloomberg.com/…", "reason": "unreadable", "detail": "fetch_article_result: paywall"}
  ]
}
```

### Trường của một ứng viên

| Trường | Kiểu | Nghĩa |
| --- | --- | --- |
| `id` | string | `id` của story trong ảnh chụp site; cũng là `id` ghi vào `decisions.json` |
| `title` | string | tiêu đề gốc |
| `title_vi` | string hoặc null | `editorial_headline_vi` hay bản dịch tiêu đề đã có trên site, nếu có |
| `url` | string https | bài đại diện (`url` của story) |
| `source.name` | string | tên nguồn như site ghi (`publisher`/`source`) |
| `source.kind` | `outlet` / `lab` / `paper` / `regulator` / `blog` / `other` | phân loại theo luật đơn giản từ tên miền và nhãn nguồn có sẵn trong ảnh chụp (arxiv, openai.com, anthropic.com, deepmind, europa.eu, ftc.gov…); không gọi model |
| `published_at` | string ISO UTC | thời điểm đăng của story |
| `text` | string | toàn văn đã làm sạch, tối đa 24 000 ký tự (cắt ở ranh giới đoạn, ghi `text_truncated: true` khi cắt) |
| `text_chars` | int | độ dài `text` |
| `text_source` | `full` / `abstract` / `partial` | `full` = bộ tải trả bài đầy đủ; `abstract` = chỉ có tóm tắt công bố (paper); `partial` = bài bị cắt bởi nguồn (đoạn dẫn, "continue reading") |
| `text_fetched_at` | string ISO UTC | lúc tải |
| `coverage` | list | các bài khác cùng sự kiện trong ảnh chụp (`coverage` của story), mỗi phần tử `{id, title, url}` |
| `same_event_published` | list id | story cùng sự kiện đã có tóm tắt trên site (để bàn Chọn đánh giá "cập nhật" theo tiêu chí 4) |
| `same_event_links` | list `{id, kind, reason}` | giải thích từng liên kết; `kind` là `published` hoặc `candidate`, `reason` ghi alias/URL hoặc các từ tiêu đề trùng; liên kết `candidate` xuất hiện ở cả hai hàng trong batch |

Liên kết qua tiêu đề chỉ xét decision `publish` trong cửa sổ trên. Sau khi bỏ dấu và từ nối thông dụng, hai tiêu đề cần trùng ít nhất ba từ; tên ngắn ba từ có số phiên bản chỉ nối với tiêu đề công bố/phát hành hoặc tên giống hệt, còn tiêu đề dài cần trùng ít nhất bốn từ và đủ tỷ lệ từ ở cả hai phía. Các số phiên bản khác nhau không nối. Ứng viên trùng trong cùng batch chỉ được đánh dấu, không bị loại; bàn Chọn quyết định đăng hay cập nhật. Liên kết alias/coverage đã có vẫn được giữ.

### Lý do loại (`rejected[].reason`)

| reason | Khi nào |
| --- | --- |
| `already_summarised` | story đã có `key_points` không rỗng trên ảnh chụp (máy hoặc bàn người viết) |
| `outside_window` | `published_at` cũ hơn `--hours` (chỉ ghi khi dùng `--keep-rejected-window`, mặc định không liệt kê để tệp gọn) |
| `unreadable` | bộ tải hiện có (`phong_bao.newsroom.fetch_article_result`) trả lý do: tường phí, robots cấm, lỗi HTTP, nội dung rỗng; `detail` chép lý do đó |
| `too_short` | `text_chars` < 600 sau khi làm sạch và không phải `abstract` |
| `duplicate_published` | mọi bài trong `coverage` đã có tóm tắt và story không có gì mới (cùng `id` cụm sự kiện) |
| `limit` | vượt `--limit` sau khi xếp theo `published_at` giảm dần |

Mỗi hàng `rejected` có `id`, `title`, `url`, `reason`, `detail` (string ngắn, có thể rỗng).

## Thứ tự và giới hạn

- `candidates` xếp theo `published_at` giảm dần, tối đa `--limit`.
- Hãng tin không chấm tiêu chí nào trong năm tiêu chí chọn tin; nó chỉ cung cấp dữ liệu để bàn Chọn chấm. Tiêu chí 3 (đọc được toàn văn) được mã hoá một phần qua `text_source` và `unreadable`.
- Không gọi model nào trong lát 1. Không ghi gì ngoài `--out`.

## Toà soạn ghi gì về sau (để lát 1 biết id phải khớp)

Toà soạn ghi vào `phong-bao/decisions.json` (hợp đồng `radar/newsroom_decisions.py`, `schema_version` 1) một hàng mỗi bản đăng:

```json
{"id": "<candidate.id>", "decision": "publish", "written_by": "nguoi-viet",
 "key_points": ["đoạn 1", "đoạn 2", "đoạn 3"], "editorial_headline_vi": "…",
 "summary_sources": [{"id": "outlet", "role": "outlet", "name": "<source.name>", "url": "<candidate.url>"}],
 "summary_limitations": [], "key_points_prompt_version": "summary-vi-6-prose",
 "content_kind": "event_news", "source_url": "<candidate.url>",
 "doi_thuyen": {"prompt_version": "doi-thuyen-v1", "writer": "codex:gpt-6-sol", "checker": "claude:sonnet", "score": 9}}
```

`key_points_prompt_version` giữ nguyên `summary-vi-6-prose` vì `desk_fields_valid` của site chỉ nhận giá trị đó (đo 2026-10-28, `radar/newsroom_decisions.py` dòng 19); phiên bản prompt thật nằm trong `doi_thuyen`, site bỏ qua trường lạ. Mọi hàng cũ trong tệp được giữ; hàng cùng `id` bị thay.
