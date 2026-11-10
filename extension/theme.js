// Before first paint, as the website's inline script does: the saved theme and the "Tùy chỉnh" choices (thanh-tren.js).
{
  const d = document.documentElement.dataset;
  try {
    const theme = JSON.parse(localStorage.getItem('air2:theme'));
    if (theme === 'light' || theme === 'dark') d.theme = theme;
  } catch { /* Use the system theme when storage is unavailable. */ }
  try {
    const c = JSON.parse(localStorage.getItem('halcyon:tuy-chinh')) || {};
    if (c.layout === 'part' || c.layout === 'head') d.layout = c.layout;
    if (c.picture === false) d.nen = 'off';
    if (c.weather === false) d.wx = 'off';
  } catch { /* The defaults when storage is unavailable. */ }
}
