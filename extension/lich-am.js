/* The Vietnamese lunar date, for the new tab's dateline. Hồ Ngọc Đức's published conversion (new moons and solar
   terms computed for UTC+7), the one Vietnamese calendars print. Pure functions; tests/test_tab_moi.py runs them. */
const PI = Math.PI;
const INT = Math.floor;
const jdFromDate = (dd, mm, yy) => {
  const a = INT((14 - mm) / 12), y = yy + 4800 - a, m = mm + 12 * a - 3;
  return dd + INT((153 * m + 2) / 5) + 365 * y + INT(y / 4) - INT(y / 100) + INT(y / 400) - 32045;
};
function newMoon(k, tz) {
  const T = k / 1236.85, T2 = T * T, T3 = T2 * T, dr = PI / 180;
  const jd1 = 2415020.75933 + 29.53058868 * k + 0.0001178 * T2 - 0.000000155 * T3 + 0.00033 * Math.sin((166.56 + 132.87 * T - 0.009173 * T2) * dr);
  const M = 359.2242 + 29.10535608 * k - 0.0000333 * T2 - 0.00000347 * T3;
  const Mp = 306.0253 + 385.81691806 * k + 0.0107306 * T2 + 0.00001236 * T3;
  const F = 21.2964 + 390.67050646 * k - 0.0016528 * T2 - 0.00000239 * T3;
  let C1 = (0.1734 - 0.000393 * T) * Math.sin(M * dr) + 0.0021 * Math.sin(2 * dr * M);
  C1 = C1 - 0.4068 * Math.sin(Mp * dr) + 0.0161 * Math.sin(dr * 2 * Mp);
  C1 = C1 - 0.0004 * Math.sin(dr * 3 * Mp);
  C1 = C1 + 0.0104 * Math.sin(dr * 2 * F) - 0.0051 * Math.sin(dr * (M + Mp));
  C1 = C1 - 0.0074 * Math.sin(dr * (M - Mp)) + 0.0004 * Math.sin(dr * (2 * F + M));
  C1 = C1 - 0.0004 * Math.sin(dr * (2 * F - M)) - 0.0006 * Math.sin(dr * (2 * F + Mp));
  C1 = C1 + 0.0010 * Math.sin(dr * (2 * F - Mp)) + 0.0005 * Math.sin(dr * (2 * Mp + M));
  const deltat = T < -11
    ? 0.001 + 0.000839 * T + 0.0002261 * T2 - 0.00000845 * T3 - 0.000000081 * T * T3
    : -0.000278 + 0.000265 * T + 0.000262 * T2;
  return INT(jd1 + C1 - deltat + 0.5 + tz / 24);
}
/* The sun's apparent longitude, in radians, at local midnight starting day jdn. */
function sunRadians(jdn, tz) {
  const T = (jdn - 2451545.5 - tz / 24) / 36525, T2 = T * T, dr = PI / 180;
  const M = 357.52910 + 35999.05030 * T - 0.0001559 * T2 - 0.00000048 * T * T2;
  const L0 = 280.46645 + 36000.76983 * T + 0.0003032 * T2;
  let DL = (1.914600 - 0.004817 * T - 0.000014 * T2) * Math.sin(dr * M);
  DL = DL + (0.019993 - 0.000101 * T) * Math.sin(dr * 2 * M) + 0.000290 * Math.sin(dr * 3 * M);
  let L = (L0 + DL) * dr;
  L = L - PI * 2 * INT(L / (PI * 2));
  return L;
}
/* Which of the 12 major terms (30° each) the sun is in at midnight starting day jdn. */
const sunLongitude = (jdn, tz) => INT(sunRadians(jdn, tz) / PI * 6);
function lunarMonth11(yy, tz) {
  const off = jdFromDate(31, 12, yy) - 2415021;
  const k = INT(off / 29.530588853);
  let nm = newMoon(k, tz);
  if (sunLongitude(nm, tz) >= 9) nm = newMoon(k - 1, tz);
  return nm;
}
function leapMonthOffset(a11, tz) {
  const k = INT((a11 - 2415021.076998695) / 29.530588853 + 0.5);
  let last, i = 1, arc = sunLongitude(newMoon(k + i, tz), tz);
  do { last = arc; i++; arc = sunLongitude(newMoon(k + i, tz), tz); } while (arc !== last && i < 14);
  return i - 1;
}
/* Solar day, month, year -> {day, month, year, leap} in the lunar calendar. */
export function solarToLunar(dd, mm, yy, tz = 7) {
  const dayNumber = jdFromDate(dd, mm, yy);
  const k = INT((dayNumber - 2415021.076998695) / 29.530588853);
  let monthStart = newMoon(k + 1, tz);
  if (monthStart > dayNumber) monthStart = newMoon(k, tz);
  let a11 = lunarMonth11(yy, tz), b11 = a11, year;
  if (a11 >= monthStart) { year = yy; a11 = lunarMonth11(yy - 1, tz); }
  else { year = yy + 1; b11 = lunarMonth11(yy + 1, tz); }
  const day = dayNumber - monthStart + 1;
  const diff = INT((monthStart - a11) / 29);
  let leap = false, month = diff + 11;
  if (b11 - a11 > 365) {
    const leapDiff = leapMonthOffset(a11, tz);
    if (diff >= leapDiff) { month = diff + 10; if (diff === leapDiff) leap = true; }
  }
  if (month > 12) month -= 12;
  if (month >= 11 && diff < 4) year -= 1;
  return { day, month, year, leap };
}

const CAN = ['Canh', 'Tân', 'Nhâm', 'Quý', 'Giáp', 'Ất', 'Bính', 'Đinh', 'Mậu', 'Kỷ'];
const CHI = ['Thân', 'Dậu', 'Tuất', 'Hợi', 'Tý', 'Sửu', 'Dần', 'Mão', 'Thìn', 'Tỵ', 'Ngọ', 'Mùi'];
const MONTH = ['Giêng', 'Hai', 'Ba', 'Tư', 'Năm', 'Sáu', 'Bảy', 'Tám', 'Chín', 'Mười', 'Một', 'Chạp'];
const WEEKDAY = ['Chủ Nhật', 'Thứ Hai', 'Thứ Ba', 'Thứ Tư', 'Thứ Năm', 'Thứ Sáu', 'Thứ Bảy'];

/* "Âm lịch 29 tháng Chín, năm Bính Ngọ" (Mùng for days 1 to 10, Rằm for the 15th). */
export function lunarText({ day, month, year, leap }) {
  const d = day === 15 ? 'Rằm' : day <= 10 ? `Mùng ${day}` : String(day);
  return `Âm lịch ${d} tháng ${MONTH[month - 1]}${leap ? ' nhuận' : ''}, năm ${CAN[year % 10]} ${CHI[year % 12]}`;
}

/* ---------- the calendar card (mockup H "Linh vật của năm", captain 08/11 01:23) ----------
   Can chi of the day, the lunar month and the lunar year, their animals in the Vietnamese twelve (trâu, mèo), the solar
   term from the sun's longitude, and the one note a reader acts on today. Everything follows from the date. */
const CAN_FROM_GIAP = ['Giáp', 'Ất', 'Bính', 'Đinh', 'Mậu', 'Kỷ', 'Canh', 'Tân', 'Nhâm', 'Quý'];
const CHI_FROM_TY = ['Tý', 'Sửu', 'Dần', 'Mão', 'Thìn', 'Tỵ', 'Ngọ', 'Mùi', 'Thân', 'Dậu', 'Tuất', 'Hợi'];
/* In CHI_FROM_TY order; file is the Fluent Emoji (flat, MIT) name shipped in con-giap/. */
export const ANIMALS = [
  ['chuột', 'rat'], ['trâu', 'water-buffalo'], ['hổ', 'tiger'], ['mèo', 'cat'], ['rồng', 'dragon'], ['rắn', 'snake'],
  ['ngựa', 'horse'], ['dê', 'goat'], ['khỉ', 'monkey'], ['gà', 'rooster'], ['chó', 'dog'], ['lợn', 'pig'],
];
/* The 24 solar terms, counted from Xuân phân at 0°. */
export const TERMS = ['Xuân phân', 'Thanh minh', 'Cốc vũ', 'Lập hạ', 'Tiểu mãn', 'Mang chủng', 'Hạ chí', 'Tiểu thử', 'Đại thử',
  'Lập thu', 'Xử thử', 'Bạch lộ', 'Thu phân', 'Hàn lộ', 'Sương giáng', 'Lập đông', 'Tiểu tuyết', 'Đại tuyết', 'Đông chí',
  'Tiểu hàn', 'Đại hàn', 'Lập xuân', 'Vũ thủy', 'Kinh trập'];

const addDays = ([y, m, d], k) => { const t = new Date(Date.UTC(y, m - 1, d + k)); return [t.getUTCFullYear(), t.getUTCMonth() + 1, t.getUTCDate()]; };
const lunarOf = ([y, m, d]) => solarToLunar(d, m, y);
/* The term in force on a day, read at the day's end (the term that starts during the day counts for that day). */
export const solarTerm = (dd, mm, yy, tz = 7) => INT(sunRadians(jdFromDate(dd, mm, yy) + 1, tz) / PI * 12);
const termOf = ([y, m, d]) => solarTerm(d, m, y);
const beast = (chi, canchi) => ({ name: ANIMALS[chi][0], file: ANIMALS[chi][1], canchi });

/* Can chi of the day (from the Julian day number), of the lunar month (from the year's can) and of the lunar year. */
export function canChi(dd, mm, yy) {
  const jdn = jdFromDate(dd, mm, yy), l = solarToLunar(dd, mm, yy);
  const day = (jdn + 1) % 12, month = (l.month + 1) % 12, year = (l.year + 8) % 12;
  return {
    day: beast(day, `${CAN_FROM_GIAP[(jdn + 9) % 10]} ${CHI_FROM_TY[day]}`),
    month: beast(month, `${CAN_FROM_GIAP[(l.year * 12 + l.month + 3) % 10]} ${CHI_FROM_TY[month]}`),
    year: beast(year, `${CAN_FROM_GIAP[(l.year + 6) % 10]} ${CHI_FROM_TY[year]}`),
  };
}

/* "tháng Chín", "tháng Hai nhuận". */
export const lunarMonthName = ({ month, leap }) => `tháng ${MONTH[month - 1]}${leap ? ' nhuận' : ''}`;
/* The lunar day as the card prints it: "Mùng 3 tháng Mười", "Rằm tháng Mười", "30 tháng Chín". */
export function lunarDayText(l) {
  const d = l.day === 15 ? 'Rằm' : l.day <= 10 ? `Mùng ${l.day}` : String(l.day);
  return `${d} ${lunarMonthName(l)}`;
}

/* One note, the one a Vietnamese reader acts on today: mùng 1 or rằm today, a solar term that starts today, mùng 1 or
   rằm tomorrow, otherwise how many days to the nearer of the two. */
export function oneNote(dd, mm, yy) {
  const ymd = [yy, mm, dd], l = lunarOf(ymd);
  const moonName = x => x.day === 1 ? `mùng 1 ${lunarMonthName(x)}` : `rằm ${lunarMonthName(x)}`;
  if (l.day === 1 || l.day === 15) return `Hôm nay là ${moonName(l)}`;
  const t = termOf(ymd);
  if (termOf(addDays(ymd, -1)) !== t) return `Hôm nay vào tiết ${TERMS[t]}`;
  for (let k = 1; k <= 31; k++) {
    const lk = lunarOf(addDays(ymd, k));
    if (lk.day === 1 || lk.day === 15) return k === 1 ? `Mai là ${moonName(lk)}` : `Còn ${k} ngày tới ${moonName(lk)}`;
  }
  return '';
}

/* Everything the calendar card shows for one solar day. */
export function calendarDay(dd, mm, yy) {
  const l = solarToLunar(dd, mm, yy), wdi = new Date(Date.UTC(yy, mm - 1, dd)).getUTCDay();
  const t = solarTerm(dd, mm, yy);
  return {
    d: dd, m: mm, y: yy, wdi, weekday: WEEKDAY[wdi], lunar: l, lunarDay: lunarDayText(l),
    animals: canChi(dd, mm, yy), term: TERMS[t], note: oneNote(dd, mm, yy),
  };
}

/* Today in Vietnam, whatever the machine's timezone: [weekday words, day, month, year]. */
export function todayVN(now = new Date()) {
  const p = Object.fromEntries(new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Ho_Chi_Minh', year: 'numeric', month: 'numeric', day: 'numeric' })
    .formatToParts(now).map(x => [x.type, x.value]));
  const y = +p.year, m = +p.month, d = +p.day;
  return { weekday: WEEKDAY[new Date(Date.UTC(y, m - 1, d)).getUTCDay()], d, m, y };
}
