/* The Vietnamese words the page shows for machine values in data/radar.json (kinds, metric keys, licenses,
   measured repository signals). One place, shared by app.js and design/tokens.js, read by tests/test_vietnamese_ui.py.
   Pure (no DOM). */

export const KIND = {model:'Mô hình', product:'Sản phẩm', research:'Nghiên cứu', other:'Bài viết', paper:'Bài báo khoa học',
  podcast:'Podcast', video:'Video', forum:'Thảo luận', event:'Sự kiện', repository:'Kho mã'};

export const METRIC = {points:'điểm', comments:'bình luận', score:'điểm', upvotes:'lượt bình chọn', likes:'lượt thích',
  downloads:'lượt tải', trendingScore:'điểm thịnh hành', trending_score:'điểm thịnh hành', stars_today:'sao hôm nay',
  stargazers_count:'sao', stars:'sao', forks:'lượt phân nhánh'};

/* SPDX ids (MIT, Apache-2.0) are names and stay; GitHub's placeholders for "no standard license" become words. */
export function licenseText(id){
  if (!id) return 'chưa rõ giấy phép';
  return ['noassertion', 'other', 'none', 'custom'].includes(String(id).toLowerCase()) ? 'giấy phép riêng' : String(id);
}

/* Measured repository signals worth showing a reader, in reading order. Anything else in `signals` is
   pipeline bookkeeping (score parts, fallback reasons) and stays out of the sheet. */
export const SIGNALS = [
  ['install_command', 'Lệnh cài'], ['install_type', 'Cách cài'], ['release_tag', 'Bản phát hành mới nhất'],
  ['release_days_ago', 'Số ngày từ bản phát hành'], ['has_binary_assets', 'Có bản dựng sẵn'], ['has_demo', 'Có bản chạy thử'],
  ['has_product_page', 'Có trang sản phẩm hoặc tài liệu'], ['has_docker', 'Có tệp Docker'], ['has_examples', 'Có thư mục ví dụ'],
  ['has_quickstart', 'Có hướng dẫn bắt đầu nhanh'], ['pushed_days_ago', 'Số ngày từ lần cập nhật mã gần nhất'],
  ['has_paper', 'Kèm bài báo khoa học'], ['has_manifest', 'Có tệp khai báo gói'], ['non_commercial', 'Hạn chế thương mại'],
  ['d_score', 'Điểm dùng ngay'], ['x_score', 'Điểm xào nấu'], ['inference_provider', 'Gọi được qua API'],
  ['gated', 'Điều khoản truy cập'], ['library_name', 'Thư viện'], ['quantized_count', 'Số bản lượng tử'],
  ['finetune_count', 'Số mô hình phái sinh'], ['spaces_count', 'Số bản chạy thử trên Spaces'], ['likes', 'Lượt thích'],
  ['downloads', 'Lượt tải'], ['hf_score', 'Điểm trên Hugging Face'],
];
const VALUE = {
  install_type: {binary:'gói dựng sẵn', source:'từ mã nguồn'},
  gated: {false:'không cần', auto:'đồng ý tự động', manual:'cần xét duyệt'},
};
/* A signal's value as the reader sees it; null means "do not show" (unmeasured). */
export function signalText(key, value){
  if (value === null || value === undefined || value === '') return null;
  if (VALUE[key] && String(value) in VALUE[key]) return VALUE[key][String(value)];
  if (typeof value === 'boolean') return value ? 'có' : 'không';
  if (typeof value === 'number') return new Intl.NumberFormat('vi-VN').format(value);
  return String(value);
}
