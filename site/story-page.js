/* ai·radar · site/story-page.js
   Boot script for static story pages (site/tin/<story id>/index.html).
   Reads story data from #story-data JSON script and hydrates #story-root
   using the shared renderStoryHTML function from site/story.js.
*/

import { renderStoryHTML } from './story.js';
import { headlineShown } from './titles.js';

const $ = s => document.querySelector(s);

const K = {
  theme: 'air2:theme',
  read: 'air2:read',
  saved: 'air2:saved',
};

const store = {
  get(k, d) {
    try {
      const v = localStorage.getItem(k);
      return v == null ? d : JSON.parse(v);
    } catch {
      return d;
    }
  },
  set(k, v) {
    try {
      localStorage.setItem(k, JSON.stringify(v));
    } catch {}
  }
};

function toast(msg) {
  let box = $('#toast-container');
  if (!box) {
    box = document.createElement('div');
    box.className = 'toast-container';
    box.id = 'toast-container';
    box.setAttribute('aria-live', 'polite');
    document.body.appendChild(box);
  }
  const t = document.createElement('div');
  t.className = 'toast';
  t.textContent = msg;
  box.appendChild(t);
  setTimeout(() => {
    t.classList.add('is-fadeout');
    setTimeout(() => t.remove(), 250);
  }, 2500);
}

function markRead(id) {
  if (!id) return;
  const list = store.get(K.read, []);
  if (!list.includes(id)) {
    list.push(id);
    store.set(K.read, list.slice(-3000));
  }
}

function toggleSave(story, btn) {
  if (!story || !story.id) return;
  const list = store.get(K.saved, []);
  const idx = list.findIndex(x => x && x.key === story.id);
  let isSaved = false;
  if (idx >= 0) {
    list.splice(idx, 1);
    toast('Đã bỏ lưu bài viết');
  } else {
    list.push({
      key: story.id,
      title: headlineShown(story),
      url: story.url || '',
      at: new Date().toISOString()
    });
    isSaved = true;
    toast('Đã lưu bài viết');
  }
  store.set(K.saved, list);
  if (btn) {
    btn.classList.toggle('is-saved', isSaved);
    btn.setAttribute('aria-label', isSaved ? 'Bỏ lưu bài viết' : 'Lưu bài viết');
    btn.title = isSaved ? 'Bỏ lưu' : 'Lưu đọc sau (phím S)';
  }
}

function setupTheme() {
  const themeBtn = $('#theme-btn');
  if (!themeBtn) return;

  const currentTheme = () => document.documentElement.dataset.theme || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  themeBtn.setAttribute('aria-pressed', currentTheme() === 'dark' ? 'true' : 'false');

  themeBtn.addEventListener('click', () => {
    const isDark = document.documentElement.dataset.theme === 'dark';
    const next = isDark ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    themeBtn.setAttribute('aria-pressed', next === 'dark' ? 'true' : 'false');
    store.set(K.theme, next);
  });
}

async function boot() {
  setupTheme();

  const dataScript = $('#story-data');
  const root = $('#story-root');
  if (!dataScript || !root) return;

  let story = null;
  try {
    story = JSON.parse(dataScript.textContent);
  } catch (err) {
    console.error('Failed to parse #story-data', err);
    return;
  }

  if (!story || !story.id) return;

  // Build source map from story's own source records and coverage
  const srcMap = new Map();
  const sourceRecords = story.sources || story.source_records || [];
  if (Array.isArray(sourceRecords)) {
    sourceRecords.forEach(s => {
      if (s && s.id) srcMap.set(s.id, s);
    });
  }

  (story.coverage || []).forEach(c => {
    if (c && c.source && !srcMap.has(c.source)) {
      srcMap.set(c.source, {
        id: c.source,
        publisher: c.publisher || c.source,
        name: c.publisher || c.source,
        lab: c.lab || ''
      });
    }
  });

  const savedList = store.get(K.saved, []);
  const isSaved = savedList.some(x => x && x.key === story.id);

  // Render content into story-root
  root.innerHTML = renderStoryHTML(story, srcMap, {
    isPage: true,
    isSaved
  });

  markRead(story.id);

  // Bind save action
  const saveBtn = $('#story-act-save');
  if (saveBtn) {
    saveBtn.addEventListener('click', () => toggleSave(story, saveBtn));
  }

  // Bind share action
  const shareBtn = $('#story-act-share');
  if (shareBtn) {
    shareBtn.addEventListener('click', () => {
      const url = location.href;
      (navigator.clipboard ? navigator.clipboard.writeText(url) : Promise.reject(new Error()))
        .then(() => toast('Đã sao chép liên kết bài viết'), () => toast(url));
    });
  }

  // Keyboard shortcut S to save
  window.addEventListener('keydown', e => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === 's' || e.key === 'S') {
      const t = e.target instanceof Element ? e.target : null;
      if (t && t.closest('input,textarea,select')) return;
      toggleSave(story, saveBtn);
    }
  });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}
