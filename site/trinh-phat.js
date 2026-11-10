/* The stream player (captain, 10/11 22:12: "Làm trình phát tại halcyon"). A reader taps a live, upcoming or replayed
   stream and watches it in Halcyon's modal frame, without leaving the page. Nothing from YouTube loads until then:
   the iframe is made when the player opens, from youtube-nocookie.com, and removed when it closes, so the sound stops
   with it. Some owners refuse embedding; the player always carries "Mở trên YouTube", so no stream is unreachable. */

export const YT_ID = /^[\w-]{11}$/;
export const playable = v => !!v && YT_ID.test(String(v.video_id || ''));
export const embedSrc = id => `https://www.youtube-nocookie.com/embed/${encodeURIComponent(id)}?autoplay=1&playsinline=1&rel=0`;
export const watchURL = v => `https://www.youtube.com/watch?v=${encodeURIComponent(v.video_id)}`;

/* dialog: the page's #player-dialog. Its body holds one [data-player-frame] once filled; open() puts the iframe in it.
   A phone's back gesture closes the player as it closes a story: opening adds a history entry, Back takes it away. */
export function createPlayer(dialog) {
  const body = dialog.querySelector('[data-player-body]');
  let opener = null;

  function open(v, html, from) {
    if (!playable(v)) return false;
    opener = from || document.activeElement;
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
    if (!(history.state && history.state.player)) history.pushState({ player: v.video_id }, '');
    return true;
  }

  function close(opts = {}) {
    if (!dialog.open) return;
    body.replaceChildren();           // the iframe goes, and its sound with it
    dialog.close();
    if (!opts.fromHistory && history.state && history.state.player) history.back();
    const back = opener;
    opener = null;
    if (back && back.isConnected && typeof back.focus === 'function') back.focus({ preventScroll: true });
  }

  dialog.addEventListener('cancel', e => { e.preventDefault(); close(); });
  dialog.addEventListener('click', e => {
    if (e.target === dialog || (e.target instanceof Element && e.target.closest('[data-player-close]'))) close();
  });
  window.addEventListener('popstate', e => { if (dialog.open && !(e.state && e.state.player)) close({ fromHistory: true }); });

  return { open, close, isOpen: () => dialog.open };
}
