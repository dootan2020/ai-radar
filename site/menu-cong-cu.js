(() => {
  const apps = [
    ['Account', 'myaccount.google.com'],
    ['Search', 'www.google.com'],
    ['Maps', 'maps.google.com'],
    ['YouTube', 'www.youtube.com'],
    ['Gmail', 'mail.google.com'],
    ['Drive', 'drive.google.com'],
    ['Calendar', 'calendar.google.com'],
    ['News', 'news.google.com'],
    ['Photos', 'photos.google.com'],
    ['Meet', 'meet.google.com'],
    ['Translate', 'translate.google.com'],
    ['Docs', 'docs.google.com'],
    ['Gemini', 'gemini.google.com']
  ];
  const header = document.querySelector('header.feed-bar, header.bt-bar, header.bar');
  if (!header) return;

  const host = document.createElement('div');
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
  for (const [name, domain] of apps) {
    const link = document.createElement('a');
    link.className = 'tool-launcher-tile';
    link.href = `https://${domain}/`;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.setAttribute('aria-label', name);

    const image = document.createElement('img');
    image.className = 'tool-launcher-icon';
    image.alt = name;
    image.width = 40;
    image.height = 40;
    image.dataset.iconUrl = `https://www.google.com/s2/favicons?domain=${domain}&sz=64`;

    const fallback = document.createElement('span');
    fallback.className = 'tool-launcher-fallback';
    fallback.setAttribute('aria-hidden', 'true');
    fallback.textContent = name.slice(0, 1);

    const label = document.createElement('span');
    label.className = 'tool-launcher-label';
    label.setAttribute('aria-hidden', 'true');
    label.textContent = name;

    image.addEventListener('error', () => {
      image.hidden = true;
      fallback.hidden = false;
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

  const actions = header.querySelector('.bt-bar-actions') || header.querySelector('.feed-bar-in') || header;
  actions.append(host);

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

  function open() {
    window.clearTimeout(closeTimer);
    loadIcons();
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
