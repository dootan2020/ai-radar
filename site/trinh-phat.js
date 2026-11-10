/* The stream player (captain, 10/11 22:12: "Làm trình phát tại halcyon"). A reader taps a live, upcoming or replayed
   stream and watches it in Halcyon's modal frame, without leaving the page. Nothing from YouTube loads until then:
   the iframe is made when the player opens, from youtube-nocookie.com, and removed when it closes, so the sound stops
   with it. Some owners refuse embedding; the player always carries "Mở trên YouTube", so no stream is unreachable. */

export const YT_ID = /^[\w-]{11}$/;
export const playable = v => !!v && YT_ID.test(String(v.video_id || ''));
export const embedSrc = id => `https://www.youtube-nocookie.com/embed/${encodeURIComponent(id)}?autoplay=1&playsinline=1&rel=0`;
export const watchURL = v => `https://www.youtube.com/watch?v=${encodeURIComponent(v.video_id)}`;

/* dialog: the page's #player-dialog. Its body holds one [data-player-frame] once filled; open() puts the iframe in it.
   History and the dialog say the same thing in every order. Opening pushes an entry of this page's own; on that
   entry the player is open and anywhere else it is closed: Back closes it, Forward onto the entry plays that stream
   again, and closing by Escape, the button or the backdrop steps back off the entry. An entry left by an earlier load
   of the page (a reload) is not this page's, so opening from it pushes a fresh one.
   landmark(): where focus goes when the control that opened the player is gone and no control plays its stream. */
export function createPlayer(dialog, { landmark = () => document.querySelector('main') } = {}) {
  const body = dialog.querySelector('[data-player-body]');
  const page = `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`;
  const ours = s => !!(s && s.player && s.page === page);
  const played = new Map();    // video id -> what open() was given, for Forward
  let current = null;          // { v, html, from }

  function show(v, html, from) {
    current = { v, html, from };
    played.set(v.video_id, current);
    body.innerHTML = html;
    const frame = body.querySelector('[data-player-frame]');
    const iframe = document.createElement('iframe');
    iframe.src = embedSrc(v.video_id);
    iframe.title = v.title ? `Video: ${v.title}` : 'Video';
    iframe.allow = 'autoplay; encrypted-media; picture-in-picture; fullscreen';
    iframe.allowFullscreen = true;
    // YouTube's embed needs the page's origin as the referrer (it refuses a player that sends none).
    iframe.referrerPolicy = 'strict-origin-when-cross-origin';
    frame.append(iframe);
    if (!dialog.open) dialog.showModal();
    dialog.querySelector('[data-player-close]')?.focus({ preventScroll: true });
  }

  function open(v, html, from) {
    if (!playable(v)) return false;
    const opener = from || document.activeElement;
    show(v, html, opener);
    if (ours(history.state)) history.replaceState({ player: v.video_id, page }, '');
    else history.pushState({ player: v.video_id, page }, '');
    return true;
  }

  /* The control to come back to: the one that opened the player, else the same stream's control after a redraw
     replaced it (the same kind first), else the page's main landmark. */
  function returnTo(from, id) {
    if (from && from.isConnected) return from;
    const sel = `[data-play="${CSS.escape(id)}"]`;
    const kind = from && from.classList && from.classList[0];
    return (kind && document.querySelector(`.${CSS.escape(kind)}${sel}`)) || document.querySelector(sel) || landmark();
  }

  function close(opts = {}) {
    if (!dialog.open) return;
    body.replaceChildren();           // the iframe goes, and its sound with it
    dialog.close();
    const was = current;
    current = null;
    if (!opts.fromHistory && ours(history.state)) history.back();
    const back = was && returnTo(was.from, was.v.video_id);
    if (back && typeof back.focus === 'function') back.focus({ preventScroll: true });
  }

  dialog.addEventListener('cancel', e => { e.preventDefault(); close(); });
  dialog.addEventListener('click', e => {
    if (e.target === dialog || (e.target instanceof Element && e.target.closest('[data-player-close]'))) close();
  });
  window.addEventListener('popstate', e => {
    const s = e.state, again = ours(s) && played.get(s.player);
    if (again) {
      if (!(dialog.open && current && current.v.video_id === s.player)) show(again.v, again.html, again.from);
    } else if (dialog.open) close({ fromHistory: true });
  });

  return { open, close, isOpen: () => dialog.open };
}
