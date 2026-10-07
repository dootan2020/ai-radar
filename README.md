# Radar AI · Bản tin sáng

Mở mỗi sáng để xem các phòng lab AI vừa có gì mới, buổi phát trực tiếp nào đáng theo dõi và dự án nào đang nổi. Mỗi tin dẫn về nguồn gốc để đọc tiếp.

## Chạy trên máy

Cần **Python 3.11+**, chỉ dùng thư viện chuẩn, không phải cài thêm package hay cung cấp API key. Chạy trong thư mục dự án:

```sh
python -m unittest discover -s tests
python build.py
python serve.py
```

Mở **http://localhost:8790**. Test chạy offline; build cần Internet để lấy dữ liệu thật và ghi vào [site/data/radar.json](site/data/radar.json). Chạy lại `python build.py`, rồi tải lại trang khi muốn cập nhật. Dừng server bằng `Ctrl+C`; nếu cổng 8790 đang bận, server báo lỗi và không tự đổi cổng.

Optional **Node.js 18+** runs the UI behavior tests through Python test discovery; no npm packages are needed. If Node is absent, that test reports an explicit skip. Python collection/build remains standard-library only.

## Đọc bản tin

| Mục | Nội dung và nguồn |
| --- | --- |
| Đáng chú ý nhất | Tin được chọn từ feed; chỉ hiện khi có tin phù hợp. Nhãn “Mới” và nút “Đánh dấu đã xem hết” giúp theo dõi lần đọc. |
| Tin từ các phòng lab | Tin và nghiên cứu, lọc theo lab. RSS chính thức của OpenAI, Google AI, DeepMind, Hugging Face; feed cộng đồng cho Anthropic, xAI, Meta và Mistral. [Danh mục feed](radar/feeds.py). |
| Phát trực tiếp | Đang live, sắp bắt đầu và vừa kết thúc trong 7 ngày từ YouTube OpenAI, Anthropic, Google, DeepMind; trạng thái kiểm tra bằng metadata video. [Kênh và collector](radar/youtube.py). |
| Đang nổi | GitHub Trending hôm nay và Hugging Face Trending. GitHub là xu hướng chung, không chỉ AI. [GitHub](radar/github.py) · [Hugging Face](radar/huggingface.py). |
| Mô hình mở mới trên Hugging Face | Repository model mới từ các tổ chức OpenAI, Google, DeepSeek, Meta, Mistral, Qwen và xAI. [Danh mục tổ chức](radar/huggingface.py). |
| Nguồn của bản tin này | Thời điểm build, số mục đọc được và nguồn gặp lỗi; nguồn lỗi không làm mất dữ liệu từ nguồn thành công. |

## Giới hạn cần biết

- Nhãn `kind` (mô hình, sản phẩm, nghiên cứu…) dựa trên tiêu đề và mô tả trong feed, không đọc toàn bài. Có thể bỏ sót thông báo ra mắt hoặc phân loại sai; nhãn không phải xác nhận độc lập.
- Feed cộng đồng có thể chậm hoặc thiếu tin. Đọc được nguồn không đồng nghĩa nguồn còn mới hay bao phủ đầy đủ; ngày đăng gốc được giữ nguyên.
- **Chưa xác minh được kênh YouTube chính thức của xAI**; `@xai` là tài khoản không liên quan nên không nằm trong nguồn thu thập. xAI vẫn có tin từ feed cộng đồng và model từ `xai-org` trên Hugging Face.
- Hugging Face `created_at` là ngày tạo repository, **không phải ngày ra mắt model**. Tên mục “Mô hình mở” không xác nhận giấy phép mở; cần kiểm tra model card và license ở nguồn.
- YouTube và các trang công khai có thể đổi cấu trúc hoặc tạm lỗi; lượt quét có giới hạn nên không bảo đảm tìm đủ mọi buổi phát. Trang hiển thị snapshot từ lần build gần nhất, không phải theo dõi thời gian thực.

## YouTube collection and runner verification

The collector verifies each channel's `externalId` and reads only its selected Live tab. Readable, identity-verified watch metadata remains authoritative, including ordinary videos and broadcasts older than seven days. If a watch page is blocked, unavailable, or lacks broadcast metadata, the collector can use that channel's explicit live/upcoming badges or recent `Streamed … ago` text. Ordinary uploads and premiere labels are excluded. A positive watch video/channel mismatch vetoes fallback for that video.

Fallback items retain the existing fields and add `status_source: "channel_streams"`, `time_text`, and `time_precision` (`exact`, `relative`, or `unknown`). Relative ages and schedules without a timezone never become exact timestamps: `start_at` / `end_at` remain `null` unless YouTube supplies an exact value. Relative ended ages are retained only when the entire displayed age bucket fits within seven days (for example, `6d ago` qualifies; `7d ago` does not).

The UI displays relative ended ages in Vietnamese. Timezone-free upcoming schedules preserve the source's printed date/clock, localize their label and AM/PM, and say `chưa rõ múi giờ`; they are never interpreted as Vietnam time. On a first visit, a relative-ended item can receive `Mới` only when its whole rounded age bucket plus elapsed snapshot age fits within 24 hours. Thus `Streamed 1d ago` displays but is not new; missing, invalid or future snapshot timestamps cannot establish freshness. Exact-time precedence and existing seen/session persistence remain unchanged.

A YouTube source is failed only when its Live tab is unreadable or invalid. RSS/watch problems appear in optional source `diagnostics`; they do not fail a valid channel. RSS can still discover identity-verified watch items when the Live tab fails. Missing or malformed embedded `ytInitialData` permits one retry after a 0.5-second pause, only when the shared deadline has room for another request. Identity or selected Live-tab validation failures are not retried. The collector requests at most eight Live-tab pages across four channels, four optional RSS feeds, and 24 watch pages. The same transport and 100-second overall build deadline apply. Valid channel fallback items outside the watch budget are retained.

To verify the real network behavior on a GitHub hosted runner without deploying:

```sh
python -m unittest discover -s tests
python tests/verify_youtube_runner.py --require-fallback
```

The probe exits nonzero unless all four configured channels pass identity verification and at least one returned item uses channel fallback after an actual failed watch request. A build exit code alone is not that proof. On a network where watch pages all work, the strict probe may fail because fallback was not exercised; omit `--require-fallback` for a general channel-health probe. Optional `--capture-blocked plans/reports/youtube-blocked.html` saves an actually observed metadata-free `LOGIN_REQUIRED` bot-check status/reason for regression evidence, with no cookies or playback URLs. Its HTML comment records the source URL, UTC capture time, extraction notes, and extracted-player SHA-256. Responses containing video details or microformat are never reduced to an absent-metadata fixture.

Offline fixtures include captured live/upcoming/ended channel metadata and actual restricted watch responses. The metadata-free bot-check response is separately identified as a synthetic regression case matching the reported runner failure; local success does not establish hosted-runner success.

## Website and automatic updates

The published site is [AI Radar](https://radar-ai-vn.pages.dev/). The existing [Update AI Radar workflow](.github/workflows/update.yml) runs tests, builds fresh data, deploys `site/` through Cloudflare Pages, and refreshes GitHub Pages redirects for old links. It is scheduled at minutes 07 and 37 of every hour; GitHub may delay scheduled runs. A manual run is available in the repository's Actions tab.

The separate [Offline CI workflow](.github/workflows/ci.yml) checks pushes and pull requests. Making its test job a required branch check needs repository settings; adding the workflow does not enable that protection automatically. See [operations and rollback](docs/operations.md), the [data contract](docs/data-pipeline-v2.md), and the [dated feed verification](docs/source-feed-check-2026-10-03.md).

## Optional translation and attribution

The optional translation step can use Gemini for Vietnamese titles and existing summaries, with Meta's [NLLB-200 distilled 600M](https://huggingface.co/facebook/nllb-200-distilled-600M) and original text as fallbacks. Gemini requests require `GEMINI_API_KEY` and `RADAR_GEMINI_FREE_TIER_CONFIRMED=1`; before enabling, the owner must verify that the key's project has no billing attached and check its actual free quotas in AI Studio. The confirmation flag and application limits cannot verify billing or guarantee Google's quota. See the [translation contract and setup](docs/data-pipeline-v2.md#title-and-summary-translation) for provider status, cache, budgets and offline verification. Frontend summary display and provider attribution still require the separate UI integration.

NLLB output uses [Creative Commons Attribution-NonCommercial 4.0](https://creativecommons.org/licenses/by-nc/4.0/). AI Radar applies the model to source text and adds terminology corrections; originals remain available. This attribution does not imply endorsement by Meta.

The NLLB fallback must be replaced before commercial use of its translations, including advertising or paid access. Its license does not license the articles linked by the site. [NLLB dependencies](requirements-translate.txt) belong to the optional [translation step](radar/translate.py); core collection/build and Gemini HTTP remain Python standard-library only. Collection/build needs no model API key. Name/number guards apply to fresh and cached translations; rejected text keeps the original.
