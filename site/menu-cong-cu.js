(() => {
  /* Each tile shows the product's own colour logo, sharp at any screen density (captain, 08/11: "Logo Account bị
     nhoè"; the 64px favicon service was scaled up). Nine logos are vector files shipped with the site (google-apps/,
     CC0 "SVG Logos" set, see google-apps/LICENSE.txt); News, Translate and Docs are missing from that set and come
     from Google's own 192px product icons. Every icon loads only when the panel first opens. */
  const GS = 'https://ssl.gstatic.com/images/branding/product/2x/';
  const BASE = new URL('google-apps/', (document.currentScript && document.currentScript.src) || location.href).href;
  const apps = [
    ['Account', 'myaccount.google.com', 'google.svg'],
    ['Search', 'www.google.com', 'google.svg'],
    ['Maps', 'maps.google.com', 'maps.svg'],
    ['YouTube', 'www.youtube.com', 'youtube.svg'],
    ['Gmail', 'mail.google.com', 'gmail.svg'],
    ['Drive', 'drive.google.com', 'drive.svg'],
    ['Calendar', 'calendar.google.com', 'calendar.svg'],
    ['News', 'news.google.com', GS + 'news_96dp.png'],
    ['Photos', 'photos.google.com', 'photos.svg'],
    ['Meet', 'meet.google.com', 'meet.svg'],
    ['Translate', 'translate.google.com', GS + 'translate_96dp.png'],
    ['Docs', 'docs.google.com', GS + 'docs_2020q4_96dp.png'],
    ['Gemini', 'gemini.google.com', 'gemini.svg']
  ];
  const header = document.querySelector('header.masthead, header.feed-bar, header.bt-bar, header.bar');
  if (!header) return;
  if (header.querySelector('.tool-launcher-button')) return;

  const host = header.querySelector('.tool-launcher') || document.createElement('div');
  host.className = 'tool-launcher';

  const button = document.createElement('button');
  button.className = 'tool-launcher-button';
  button.type = 'button';
  button.setAttribute('aria-label', 'Mở ứng dụng Google');
  button.setAttribute('aria-expanded', 'false');
  button.setAttribute('aria-controls', 'google-apps-panel');
  button.innerHTML = '<span class="tool-launcher-dots" aria-hidden="true">' + '<i></i>'.repeat(9) + '</span>';

  const panel = document.createElement('div');
  panel.className = 'tool-launcher-panel';
  panel.id = 'google-apps-panel';
  panel.hidden = true;
  panel.setAttribute('role', 'region');
  panel.setAttribute('aria-label', 'Ứng dụng Google');

  const grid = document.createElement('div');
  grid.className = 'tool-launcher-grid';
  for (const [name, domain, logo] of apps) {
    const link = document.createElement('a');
    link.className = 'tool-launcher-tile';
    link.href = `https://${domain}/`;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.setAttribute('aria-label', name);

    const image = document.createElement('img');
    image.className = 'tool-launcher-icon';
    image.alt = '';
    image.width = 40;
    image.height = 40;
    image.decoding = 'async';
    image.referrerPolicy = 'no-referrer';
    image.dataset.iconUrl = logo.startsWith('https://') ? logo : BASE + logo;

    const fallback = document.createElement('span');
    fallback.className = 'tool-launcher-fallback';
    fallback.setAttribute('aria-hidden', 'true');
    fallback.textContent = name.slice(0, 1);

    const label = document.createElement('span');
    label.className = 'tool-launcher-label';
    label.setAttribute('aria-hidden', 'true');
    label.textContent = name;

    // The letter holds the slot until the logo has loaded; offline or blocked, the letter stays.
    image.hidden = true;
    image.addEventListener('load', () => {
      image.hidden = false;
      fallback.hidden = true;
    }, { once: true });
    link.append(image, fallback, label);
    grid.append(link);
  }

  const more = document.createElement('a');
  more.className = 'tool-launcher-more';
  more.href = 'https://about.google/products/';
  more.target = '_blank';
  more.rel = 'noopener noreferrer';
  more.textContent = 'Thêm từ Google';
  grid.append(more);
  panel.append(grid);
  host.append(button, panel);

  const actions = header.querySelector('.masthead-actions') || header.querySelector('.bt-bar-actions') || header.querySelector('.feed-bar-in') || header;
  if (!host.isConnected) actions.append(host);

  const story = location.pathname.includes('/tin/');
  const prefix = story ? '../../' : '';
  const page = location.pathname.split('/').pop() || 'index.html';
  const current = story ? 'index.html' : page;
  const destinations = [
    ['index.html', 'Dòng tin', '<path d="M4 6h16M4 12h16M4 18h10"/>'],
    ['ban-tin.html', 'Bản tin', '<rect x="4" y="5" width="16" height="16" rx="2"/><path d="M8 3v4m8-4v4M4 10h16"/>'],
    // The search lives in the home's news bar (07/11); on the home itself the link only opens it.
    ['index.html#tim', 'Tìm tin', '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>'],
    // Owner, 09/11: every story names its source, so the dock drops "Nguồn" (the page stays, linked from the footer)
    // and gives the place to the upcoming events, the home's "Sắp diễn ra" view.
    ['index.html#sap-toi', 'Sự kiện', '<path d="M20 11V7a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h5M8 3v4m8-4v4M4 10h16"/><circle cx="17" cy="17" r="4"/><path d="M17 15.5V17l1 1"/>']
  ];
  const DEST = { 'index.html': 'feed', 'index.html#sap-toi': 'events' };
  const eventsOpen = !story && current === 'index.html' && location.hash === '#sap-toi';
  const mobileNav = document.createElement('nav');
  mobileNav.className = 'mobile-nav';
  mobileNav.setAttribute('aria-label', 'Điều hướng chính');
  for (const [file, label, paths] of destinations) {
    const link = document.createElement('a');
    link.href = !story && current === 'index.html' && file.startsWith('index.html#') ? file.slice('index.html'.length) : `${prefix}${file}`;
    link.className = 'mobile-nav-link';
    if (file === 'ban-tin.html') link.setAttribute('aria-label', 'Bản tin sáng');
    if (DEST[file]) link.dataset.dest = DEST[file];   // the home's feed.js moves the mark between these two
    const here = file === 'index.html#sap-toi' ? eventsOpen : file === current && !(file === 'index.html' && eventsOpen);
    if (here) link.setAttribute('aria-current', 'page');
    link.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${paths}</svg><span>${label}</span>`;
    mobileNav.append(link);
  }
  header.after(mobileNav);

  let closeTimer;
  function loadIcons() {
    panel.querySelectorAll('.tool-launcher-icon[data-icon-url]').forEach(image => {
      image.src = image.dataset.iconUrl;
      delete image.dataset.iconUrl;
    });
  }

  function close(restoreFocus = false) {
    if (panel.hidden) return;
    window.clearTimeout(closeTimer);
    button.setAttribute('aria-expanded', 'false');
    button.setAttribute('aria-label', 'Mở ứng dụng Google');
    panel.classList.remove('is-open');
    closeTimer = window.setTimeout(() => {
      panel.hidden = true;
      if (restoreFocus) button.focus();
    }, 150);
  }

  // Opened from the keyboard, focus lands on the first tile so arrow/Tab navigation starts there. Opened by
  // mouse or touch, the panel itself takes focus so no tile shows a ring nobody asked for; Tab still walks
  // the tiles from the top.
  panel.tabIndex = -1;
  function open(fromKeyboard) {
    window.clearTimeout(closeTimer);
    loadIcons();
    panel.hidden = false;
    requestAnimationFrame(() => panel.classList.add('is-open'));
    button.setAttribute('aria-expanded', 'true');
    button.setAttribute('aria-label', 'Đóng ứng dụng Google');
    if (fromKeyboard) panel.querySelector('a')?.focus();
    else panel.focus({ preventScroll: true });
  }

  button.addEventListener('click', event => {
    if (button.getAttribute('aria-expanded') === 'true') close(true);
    else open(event.detail === 0);
  });
  document.addEventListener('pointerdown', event => {
    if (!host.contains(event.target)) close();
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !panel.hidden) {
      event.preventDefault();
      close(true);
    }
  });
  panel.addEventListener('click', event => {
    if (event.target.closest('a')) close(true);
  });
})();
