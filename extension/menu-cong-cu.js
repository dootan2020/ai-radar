(() => {
  /* Each tile draws its own vector glyph on a tinted squircle (the monogram tile of tokens.css, hue per app), so the
     panel is sharp at any screen density and calls no icon server (captain, 08/11: the remote 64px favicons were
     blurry on the iPhone). The glyphs are this site's own line drawings, not the products' logos. */
  const apps = [
    ['Account', 'myaccount.google.com', 255, '<circle cx="12" cy="9" r="3.5"/><path d="M5.5 19.5a6.5 6.5 0 0 1 13 0"/>'],
    ['Search', 'www.google.com', 220, '<circle cx="10.5" cy="10.5" r="6"/><path d="m15 15 5 5"/>'],
    ['Maps', 'maps.google.com', 150, '<path d="M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0 1 13 0c0 5.4-6.5 11-6.5 11z"/><circle cx="12" cy="10" r="2.3"/>'],
    ['YouTube', 'www.youtube.com', 25, '<rect x="3" y="6" width="18" height="12" rx="4"/><path d="M10.5 9.6v4.8l4-2.4z"/>'],
    ['Gmail', 'mail.google.com', 12, '<rect x="3.5" y="6" width="17" height="12" rx="2"/><path d="m4 7.5 8 5.5 8-5.5"/>'],
    ['Drive', 'drive.google.com', 85, '<path d="M8.5 4.5h7l5.5 9.5-3.2 5.5H6.2L3 14z"/><path d="M3 14h18M8.5 4.5l6.4 11M15.5 4.5 9 15.5"/>'],
    ['Calendar', 'calendar.google.com', 262, '<rect x="4" y="5.5" width="16" height="14" rx="2.5"/><path d="M4 10h16M8.5 3.5v4M15.5 3.5v4"/>'],
    ['News', 'news.google.com', 235, '<path d="M5 5h11v14H6a1 1 0 0 1-1-1z"/><path d="M16 9h3v9a1 1 0 0 1-1 1h-2M8 9h5M8 12.5h5M8 16h3"/>'],
    ['Photos', 'photos.google.com', 55, '<rect x="4" y="5" width="16" height="14" rx="2.5"/><circle cx="9" cy="10" r="1.6"/><path d="m5 17 4.5-4.5 3 3 2.5-2.5L19 17"/>'],
    ['Meet', 'meet.google.com', 165, '<rect x="3.5" y="7" width="12" height="10" rx="2"/><path d="m15.5 11 5-3v8l-5-3"/>'],
    ['Translate', 'translate.google.com', 200, '<path d="M4 6h8M8 4v2M6 6c0 3 2.5 5.5 5 6.5M10 6c-.5 3-3 6-5.5 7"/><path d="m12.5 20 3.5-9 3.5 9M13.8 17h4.4"/>'],
    ['Docs', 'docs.google.com', 250, '<path d="M6 3.5h8l4 4v13H6z"/><path d="M14 3.5v4h4M9 12h6M9 15.5h6"/>'],
    ['Gemini', 'gemini.google.com', 290, '<path d="M12 3.5c.7 4.3 3.5 7.1 8.5 8.5-5 1.4-7.8 4.2-8.5 8.5-.7-4.3-3.5-7.1-8.5-8.5 5-1.4 7.8-4.2 8.5-8.5z"/>']
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
  for (const [name, domain, hue, glyph] of apps) {
    const link = document.createElement('a');
    link.className = 'tool-launcher-tile';
    link.href = `https://${domain}/`;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.setAttribute('aria-label', name);

    const icon = document.createElement('span');
    icon.className = 'tool-launcher-icon';
    icon.setAttribute('aria-hidden', 'true');
    icon.style.setProperty('--app-hue', hue);
    icon.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${glyph}</svg>`;

    const label = document.createElement('span');
    label.className = 'tool-launcher-label';
    label.setAttribute('aria-hidden', 'true');
    label.textContent = name;

    link.append(icon, label);
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
  const current = 'index.html';
  const destinations = [
    ['index.html', 'Dòng tin', '<path d="M4 6h16M4 12h16M4 18h10"/>'],
    ['ban-tin.html', 'Bản tin', '<rect x="4" y="5" width="16" height="16" rx="2"/><path d="M8 3v4m8-4v4M4 10h16"/>'],
    // The search lives in the home's news bar (07/11); on the home itself the link only opens it.
    ['index.html#tim', 'Tìm tin', '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>'],
    ['nguon.html', 'Nguồn', '<path d="M5 5h14v14H5zM8 9h8M8 13h8M8 17h5"/>']
  ];
  const mobileNav = document.createElement('nav');
  mobileNav.className = 'mobile-nav';
  mobileNav.setAttribute('aria-label', 'Điều hướng chính');
  for (const [file, label, paths] of destinations) {
    const link = document.createElement('a');
    link.href = !story && current === 'index.html' && file.startsWith('index.html#') ? file.slice('index.html'.length) : file === 'index.html' ? '#top' : file.startsWith('index.html#') ? file.slice(10) : `https://radar-ai-vn.pages.dev/${file}`;
    link.className = 'mobile-nav-link';
    if (file === 'ban-tin.html') link.setAttribute('aria-label', 'Bản tin sáng');
    if (file === current || (page === 'bento.html' && file === 'index.html')) link.setAttribute('aria-current', 'page');
    link.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${paths}</svg><span>${label}</span>`;
    mobileNav.append(link);
  }
  header.after(mobileNav);

  let closeTimer;
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

  function open() {
    window.clearTimeout(closeTimer);
    panel.hidden = false;
    requestAnimationFrame(() => panel.classList.add('is-open'));
    button.setAttribute('aria-expanded', 'true');
    button.setAttribute('aria-label', 'Đóng ứng dụng Google');
    panel.querySelector('a')?.focus();
  }

  button.addEventListener('click', () => {
    if (button.getAttribute('aria-expanded') === 'true') close(true);
    else open();
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
