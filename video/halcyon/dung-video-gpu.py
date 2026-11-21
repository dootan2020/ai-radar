"""Halcyon video builder: one spec file (JSON) in, storyboard stills or the finished video out. See SPEC.md.

Run (PowerShell), from any folder, with the GPU interpreter (see README.md; run.ps1 does this):
  $env:HALCYON_PYTHON -I -X utf8 dung-video-gpu.py <spec.json> --stills
  $env:HALCYON_PYTHON -I -X utf8 dung-video-gpu.py <spec.json> --render

Both modes use the same drawing path (ve_halcyon.py for the CPU drawing, this file for the CUDA compositing) and write next to the spec.
GPU only: NVDEC decode of recordings, CUDA tensor compositing (Lanczos, unsharp, melt blur, skin, highlighter fade, alpha layers, karaoke caption,
TikTok overlay, RGB -> YUV 4:2:0 BT.709) and NVENC (h264_nvenc). CUDA missing, NVDEC refusing a clip or NVENC failing aborts; there is no CPU fallback.
The look is the approved one of video #1/#2 (co-van-chinh-chu.md, co-van-bo-cuc-video-02.md); the drawing code is lifted from the video #2 builder."""
import sys
sys.dont_write_bytecode = True
import difflib, importlib.util, json, math, re, shutil, subprocess, time, unicodedata
from pathlib import Path
import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
FPS, W, H = 30, 1080, 1920
LEAD = 0.08                                    # captions lead the Whisper word starts by 0.08 s
FADE = 8                                       # highlighter bands fade in over 8 frames
if not torch.cuda.is_available():
    raise SystemExit('CUDA is not available: refusing to fall back to the CPU')
DEV = torch.device('cuda')
_s = importlib.util.spec_from_file_location('ve', HERE / 've_halcyon.py')
ve = importlib.util.module_from_spec(_s); _s.loader.exec_module(ve)
_s = importlib.util.spec_from_file_location('halcyon_spec', HERE / 'halcyon_spec.py')     # spec loading: stdlib only, tested without a GPU
spec_mod = importlib.util.module_from_spec(_s); _s.loader.exec_module(spec_mod)
_s = importlib.util.spec_from_file_location('halcyon_repo_walk', HERE / 'halcyon_repo_walk.py')   # the repo picture's manifest and camera plan: stdlib only, tested without a GPU
repo_mod = importlib.util.module_from_spec(_s); _s.loader.exec_module(repo_mod)
assert (ve.W, ve.H) == (W, H)


# ---------------- spec loading ----------------
need, need_file = spec_mod.need, spec_mod.need_file


# ---------------- GPU primitives (lifted from the video #2 builder) ----------------
_MAT = {}


def lanczos_matrix(n_in, n_out):
    """Pillow's Lanczos (support 3) resampling as a dense (n_out, n_in) matrix, for upscaling and downscaling alike."""
    key = ('lz', n_in, n_out)
    if key not in _MAT:
        scale = n_in / n_out; fs = max(scale, 1.0); support = 3.0 * fs
        M = np.zeros((n_out, n_in), np.float32)
        for i in range(n_out):
            c = (i + 0.5) * scale
            x0, x1 = max(int(c - support + 0.5), 0), min(int(c + support + 0.5), n_in)
            t = (np.arange(x0, x1) - c + 0.5) / fs
            w = np.sinc(t) * np.sinc(t / 3) * (np.abs(t) < 3)
            M[i, x0:x1] = w / w.sum()
        _MAT[key] = torch.from_numpy(M).to(DEV)
    return _MAT[key]


def gauss_matrix(n, sigma):
    key = ('g', n, sigma)
    if key not in _MAT:
        r = int(math.ceil(3 * sigma)); k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2); k /= k.sum()
        M = np.zeros((n, n), np.float32)
        for i in range(n):
            np.add.at(M[i], np.clip(np.arange(i - r, i + r + 1), 0, n - 1), k)
        _MAT[key] = torch.from_numpy(M).to(DEV)
    return _MAT[key]


def blur(x, sigma):                            # x (3, h, w) float
    return (gauss_matrix(x.shape[1], sigma) @ x) @ gauss_matrix(x.shape[2], sigma).T


def to_gpu_rgba(arr):                          # (h, w, 4) uint8 -> (4, h, w) uint8 on the GPU
    return torch.from_numpy(np.ascontiguousarray(arr)).permute(2, 0, 1).contiguous().to(DEV)


def to_gpu_rgb(img):                           # PIL RGB -> (3, h, w) float on the GPU
    return torch.from_numpy(np.asarray(img.convert('RGB')).copy()).permute(2, 0, 1).float().to(DEV)


def comp(out, layer, y0=0):
    """Straight-alpha 'over' of an RGBA uint8 layer (4, h, w) onto out (3, H, W) at row y0, in place."""
    h = layer.shape[1]
    a = layer[3:4].float() / 255.0
    out[:, y0:y0 + h] = out[:, y0:y0 + h] * (1 - a) + layer[:3].float() * a


_SKIN = {}
_DM = {}
_MESH = {}                                     # frame -> coverage of the mesh at that frame (the last one only)


def _seg_patch(gx, gy, x0, y0, x1, y1):
    return gx[x0:x1][None, :], gy[y0:y1][:, None]


def mesh_cover(f):
    """Coverage 0..1 (H, W) of the white mesh at frame f, drawn analytically with sub-pixel accuracy: every pixel's value is the clamped distance to the
    shape (links 2.2 px wide, dots r 5.5, rings r 10.5..13 with a 14 px clear disc, a r 5 dot in the middle), at the pixel's centre, from the node
    positions ve.mesh_pos(f) in float. Nothing is rounded to a pixel, so a node that moves 0.1 px moves its edge values by a tenth of a step."""
    if f in _MESH:
        return _MESH[f]
    G = ve.MESH; pos = ve.mesh_pos(f)
    gx = torch.arange(W, device=DEV, dtype=torch.float32) + 0.5; gy = torch.arange(H, device=DEV, dtype=torch.float32) + 0.5
    M = torch.zeros(H, W, device=DEV)

    def box(cx0, cy0, cx1, cy1, pad):
        x0, x1 = max(0, int(math.floor(min(cx0, cx1) - pad))), min(W, int(math.ceil(max(cx0, cx1) + pad)) + 1)
        y0, y1 = max(0, int(math.floor(min(cy0, cy1) - pad))), min(H, int(math.ceil(max(cy0, cy1) + pad)) + 1)
        return x0, y0, x1, y1

    for i, j in G['keep']:
        (px, py), (qx, qy) = pos[i], pos[j]
        x0, y0, x1, y1 = box(px, py, qx, qy, 3.0)
        if x1 <= x0 or y1 <= y0:
            continue
        X, Y = _seg_patch(gx, gy, x0, y0, x1, y1)
        dx, dy = qx - px, qy - py; L2 = dx * dx + dy * dy
        t = (((X - px) * dx + (Y - py) * dy) / L2).clamp(0, 1)
        d = torch.hypot(X - (px + t * dx), Y - (py + t * dy))
        M[y0:y1, x0:x1] = torch.maximum(M[y0:y1, x0:x1], (1.1 + 0.5 - d).clamp(0, 1))
    for i in range(len(pos)):
        if not G['alive'][i]:
            continue
        x, y = pos[i]; ring = G['ringed'][i]; r = 17 if ring else 8
        x0, y0, x1, y1 = box(x, y, x, y, r)
        if x1 <= x0 or y1 <= y0:
            continue
        X, Y = _seg_patch(gx, gy, x0, y0, x1, y1)
        d = torch.hypot(X - float(x), Y - float(y))
        sub = M[y0:y1, x0:x1]
        if ring:
            sub = sub * (d - 14 + 0.5).clamp(0, 1)                                       # the clear disc inside the ring
            sub = torch.maximum(sub, torch.minimum((d - 10.5 + 0.5).clamp(0, 1), (13.0 + 0.5 - d).clamp(0, 1)))
            sub = torch.maximum(sub, (5.0 + 0.5 - d).clamp(0, 1))
        else:
            sub = torch.maximum(sub, (5.5 + 0.5 - d).clamp(0, 1))
        M[y0:y1, x0:x1] = sub
    _MESH.clear(); _MESH[f] = M
    return M


def apply_skin_gpu(p, level, f):
    if level not in _SKIN:
        rgb, A = ve.skin(level)
        _SKIN[level] = (torch.from_numpy(np.ascontiguousarray(rgb.transpose(2, 0, 1))).float().to(DEV), torch.from_numpy(np.ascontiguousarray(A)).float()[None].to(DEV))
    rgb, A = _SKIN[level]
    if ve.MESH is not None:                              # the mesh: white at WHITE_K x the vertical envelope, over the wash, at this frame's node positions
        if level not in _DM:
            _DM[level] = torch.from_numpy(ve.mesh_dm(level)).float().to(DEV)
        k = (mesh_cover(f) * (ve.WHITE_K * _DM[level])[:, None])[None]
        rgb = rgb * (1 - k) + 255.0 * k
    if level in ve.MELT:
        sg, m0, m1 = ve.MELT[level]
        ys = max(0, m0 - int(math.ceil(3 * sg)))
        sub = p[:, ys:]
        bl = blur(sub, sg)
        y = torch.arange(ys, H, device=DEV).float()
        w = ((y - m0) / (m1 - m0)).clamp(0, 1); w = w * w * (3 - 2 * w)
        p = p.clone(); p[:, ys:] = sub * (1 - w[None, :, None]) + bl * w[None, :, None]
    return p * (1 - A) + rgb * A


def decode_nv12(webm, nframes, w=390, h=844):
    """Frames 0..nframes-1 of a recording, decoded by NVDEC (hwaccel cuda) -> uint8 (n, w*h*3/2)."""
    fb = w * h * 3 // 2
    cmd = ['ffmpeg', '-v', 'error', '-hwaccel', 'cuda', '-hwaccel_output_format', 'cuda', '-i', str(webm),
           '-vf', 'hwdownload,format=nv12', '-frames:v', str(nframes), '-f', 'rawvideo', '-pix_fmt', 'nv12', '-']
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise SystemExit('NVDEC decode failed: ' + r.stderr.decode('utf-8', 'replace')[-1500:])
    n = len(r.stdout) // fb
    if n < nframes:
        raise SystemExit(f'decoded only {n} of {nframes} frames from {webm} (is it 390x844?)')
    return np.frombuffer(r.stdout, np.uint8)[:nframes * fb].reshape(nframes, fb), cmd


def nv12_to_rgb(buf, w=390, h=844):
    Y = buf[:w * h].view(h, w).float()
    UV = buf[w * h:].view(h // 2, w // 2, 2).float()
    u = F.interpolate(UV[..., 0][None, None], size=(h, w), mode='bilinear', align_corners=False)[0, 0] - 128
    v = F.interpolate(UV[..., 1][None, None], size=(h, w), mode='bilinear', align_corners=False)[0, 0] - 128
    u, v = u * (255 / 224), v * (255 / 224)
    y = (Y - 16) * (255 / 219)
    return torch.stack([y + 1.402 * v, y - 0.344136 * u - 0.714136 * v, y + 1.772 * u]).clamp(0, 255)


def vid_picture(rgb, g):
    """Crop U, Lanczos to out_w x out_h (at x_at), unsharp (1.5 < k <= 3), flat fills above/below; the side strips repeat each row's first and last column."""
    x = rgb[:, g['top_src']:g['bot_src'], g['ux0']:g['ux1']]
    part = (lanczos_matrix(x.shape[1], g['out_h']) @ x) @ lanczos_matrix(x.shape[2], g['out_w']).T
    if 1.5 < g['k'] <= 3.0:
        part = part + 0.55 * (part - blur(part, 2.0))
    part = part.clamp(0, 255)
    fr = torch.zeros(3, H, W, device=DEV)
    y_at, end, xa = g['y_at'], g['y_at'] + g['out_h'], g['x_at']
    if y_at > 0:
        fr[:, :y_at] = rgb[:, g['ut'], g['ux0']:g['ux1']].median(dim=1).values[:, None, None]
    fr[:, y_at:min(end, H), xa:xa + g['out_w']] = part[:, :min(end, H) - y_at]
    fr[:, y_at:min(end, H), :xa] = part[:, :min(end, H) - y_at, :1]
    fr[:, y_at:min(end, H), xa + g['out_w']:] = part[:, :min(end, H) - y_at, -1:]
    if end < H:
        if g.get('hold_last'):                 # strict layouts: the last (background-only) row carries on downwards, gradient included
            fr[:, end:] = fr[:, end - 1:end]
        else:
            fr[:, end:] = rgb[:, g['ub'] - 1, g['ux0']:g['ux1']].median(dim=1).values[:, None, None]
    return fr


# ---------------- repo picture: desktop github.com stills played through a camera (see SPEC.md, halcyon_repo_walk.py) ----------------
_REPO_IMG = {}                                  # still path -> uint8 (3, h, w) on the GPU, one upload per file
_POINTER = []


def repo_image(path):
    key = str(path)
    if key not in _REPO_IMG:
        arr = np.asarray(Image.open(path).convert('RGB'))      # PIL only decodes the PNG
        _REPO_IMG[key] = torch.from_numpy(arr.copy()).to(DEV).permute(2, 0, 1).contiguous()
    return _REPO_IMG[key]


def lz_weights(c0, step, n_out, j0, j1):
    """Lanczos-3 weights (n_out, j1 - j0) for output pixel i centred at input coordinate c0 + (i + .5) * step, built on the GPU for any fractional crop."""
    fs = max(step, 1.0)
    j = torch.arange(j0, j1, device=DEV, dtype=torch.float32) + 0.5
    c = c0 + (torch.arange(n_out, device=DEV, dtype=torch.float32) + 0.5) * step
    t = (j[None, :] - c[:, None]) / fs
    w = torch.sinc(t) * torch.sinc(t / 3) * (t.abs() < 3)
    return w / w.sum(1, keepdim=True)


def pointer_sprite():
    """The mouse pointer (arrow tip at the sprite's (PAD, PAD)): ink fill, white outline, soft shadow; drawn once with PIL at 4x and reduced."""
    if not _POINTER:
        s, pad, hgt = 4, 6, 46
        k = hgt / 19.0
        pts = [(0, 0), (0, 16), (4, 12.5), (6.5, 18.5), (8.8, 17.5), (6.5, 11.8), (11.5, 11.8)]
        cw_, ch_ = int(12 * k) + 2 * pad + 4, hgt + 2 * pad + 4
        big = Image.new('RGBA', (cw_ * s, ch_ * s), (0, 0, 0, 0))
        poly = [((pad + x * k) * s, (pad + y * k) * s) for x, y in pts]
        sh = Image.new('RGBA', big.size, (0, 0, 0, 0)); ImageDraw.Draw(sh).polygon([(x + 2 * s, y + 3 * s) for x, y in poly], fill=(0, 0, 0, 90))
        sh = sh.filter(ve.ImageFilter.GaussianBlur(2 * s))
        d = ImageDraw.Draw(big); d.polygon(poly, fill=(255, 255, 255, 255), outline=(255, 255, 255, 255), width=int(3.2 * s))
        inner = Image.new('RGBA', big.size, (0, 0, 0, 0)); ImageDraw.Draw(inner).polygon(poly, fill=ve.INK + (255,))
        inner = inner.filter(ve.ImageFilter.MinFilter(2 * s + 1))
        big = Image.alpha_composite(Image.alpha_composite(sh, big), inner)
        _POINTER.append((to_gpu_rgba(np.asarray(big.resize((cw_, ch_), Image.LANCZOS))), pad))
    return _POINTER[0]


def repo_resample(show, key, cam):
    """The page's still seen through the camera: (3, hh, ww) float, Lanczos on the GPU, bg beyond the page, plus the feather mask (hh, ww)."""
    img = repo_image(show['pages'][key]['picture'])
    bg = show['bg']; ww, hh, sc = show['ww'], show['hh'], show['scale']
    H_, W_ = img.shape[1], img.shape[2]
    stepx = cam[2] * sc / ww                                  # still px per frame px (both axes)
    cx0 = (cam[0] - cam[2] / 2) * sc; cy0 = (cam[1] - hh / (ww / cam[2]) / 2) * sc
    sup = 3 * max(stepx, 1.0)
    j0x, j1x = int(math.floor(cx0 - sup)), int(math.ceil(cx0 + ww * stepx + sup))
    j0y, j1y = int(math.floor(cy0 - sup)), int(math.ceil(cy0 + hh * stepx + sup))
    band = bg[:, None, None].expand(3, j1y - j0y, j1x - j0x).clone()
    ya, yb, xa, xb = max(j0y, 0), min(j1y, H_), max(j0x, 0), min(j1x, W_)
    if yb > ya and xb > xa:
        band[:, ya - j0y:yb - j0y, xa - j0x:xb - j0x] = img[:, ya:yb, xa:xb].float()
    out = (lz_weights(cy0, stepx, hh, j0y, j1y) @ band) @ lz_weights(cx0, stepx, ww, j0x, j1x).T
    def ramp(n, lo_len, hi_len):                               # 0 -> 1 over lo_len px at the start, 1 -> 0 over hi_len px at the end; a length of 0 is a hard edge
        i = torch.arange(n, device=DEV, dtype=torch.float32) + 0.5
        a = torch.ones(n, device=DEV)
        if lo_len > 0:
            u = (i / lo_len).clamp(0, 1); a = a * (u * u * (3 - 2 * u))
        if hi_len > 0:
            u = ((n - i) / hi_len).clamp(0, 1); a = a * (u * u * (3 - 2 * u))
        return a
    ln = lambda d_, F_: float(min(max(d_ / stepx, 0.0), F_))   # the feather shrinks to nothing where the crop edge is the page edge
    fy, fl, fr = repo_mod.FEATHER_Y, repo_mod.FEATHER_L, repo_mod.FEATHER_R
    ay = ramp(hh, ln(cy0, fy), ln(H_ - (cy0 + hh * stepx), fy))
    ax = ramp(ww, ln(cx0, fl), ln(W_ - (cx0 + ww * stepx), fr))
    return out, ay[:, None] * ax[None, :]


def repo_layer(show, sg, f):
    """One page of a repo beat at frame f: camera, hover tint on the row, feather, mouse pointer. (3, hh, ww) float."""
    cam = repo_mod.cam_at(sg, f)
    out, mask = repo_resample(show, sg['page'], cam)
    out = out.clamp(0, 255)
    ptr, hover, press = repo_mod.pointer_at(sg, f)
    p = sg['ptr']
    if p and (hover > 0 or press > 0):
        x, y, w, h = p['rect']
        yy = torch.arange(show['hh'], device=DEV, dtype=torch.float32) + 0.5; xx = torch.arange(show['ww'], device=DEV, dtype=torch.float32) + 0.5
        cov = ((torch.minimum(yy - y, y + h - yy) + 0.5).clamp(0, 1))[:, None] * ((torch.minimum(xx - x, x + w - xx) + 0.5).clamp(0, 1))[None, :]
        a = (0.075 * hover + 0.07 * press) * cov
        out = out * (1 - a[None]) + torch.tensor(ve.INK, device=DEV, dtype=torch.float32)[:, None, None] * a[None]
    bg = show['bg'][:, None, None]
    out = bg + (out - bg) * mask[None]
    if ptr:
        sprite, pad = pointer_sprite()
        sh_, sw_ = sprite.shape[1], sprite.shape[2]
        x0, y0 = int(round(ptr[0])) - pad, int(round(ptr[1])) - pad
        xa, ya, xb, yb = max(x0, 0), max(y0, 0), min(x0 + sw_, show['ww']), min(y0 + sh_, show['hh'])
        if xb > xa and yb > ya:
            sp = sprite[:, ya - y0:yb - y0, xa - x0:xb - x0]
            a = sp[3:4].float() / 255.0 * ptr[2]
            out[:, ya:yb, xa:xb] = out[:, ya:yb, xa:xb] * (1 - a) + sp[:3].float() * a
    return out


def repo_window(b, f):
    show, segs = b['show'], b['plan']['segments']
    sg = repo_mod.seg_at(segs, f)
    lay = repo_layer(show, sg, f)
    if sg['i'] > 0 and f < sg['s'] + repo_mod.XF:                # the page changes: a desktop browser swaps the page, so a quick dip through the page colour (old page frozen on its press,
        u = (f - sg['s'] + 1) / repo_mod.XF                       # out over the first half, new page in over the second): two text-dense views cross-faded at once would ghost
        bg = show['bg'][:, None, None]
        if u < 0.5:                                               # the dip never reaches an empty frame (a blank frame reads as a glitch): the page stays at 25% at the turn
            lay = bg + (repo_layer(show, segs[sg['i'] - 1], sg['s'] - 1) - bg) * (1 - 0.75 * repo_mod.smooth(2 * u))
        else:
            lay = bg + (lay - bg) * (0.25 + 0.75 * repo_mod.smooth(2 * u - 1))
    return lay


def repo_picture(b, f):
    show = b['show']
    pic = show['flat'].clone()
    pic[:, show['top']:show['top'] + show['hh'], ve.PIC_X0:ve.PIC_X0 + show['ww']] = repo_window(b, f)
    return pic


def check_blank_window(where, layer, bg):
    """A repo still whose window holds (almost) nothing but the page colour is refused: fewer than 0.5% of the window's pixels differ from it by more than 24 levels."""
    share = float(((layer - bg[:, None, None]).abs().amax(0) > 24).float().mean())
    if share < 0.005:
        raise SystemExit(f'blank window: {where}: only {share * 100:.2f}% of the window differs from the page colour (floor 0.5%): the still is empty or the camera looks past the page')
    return share


# ---------------- captions ----------------
def nrm(norm, w):
    return unicodedata.normalize('NFC', re.sub(r'[^\w]', '', norm(w).lower()))


def map_words(norm, display, heard):
    """Display word -> start of the matching spoken word; unmatched words take the start of the first spoken word in their gap; monotonic."""
    dn = [nrm(norm, w) for w in display]; hn = [nrm(norm, w) for w, _ in heard]
    out = [None] * len(display)
    da = ha = 0
    for a, b, n in difflib.SequenceMatcher(None, dn, hn, autojunk=False).get_matching_blocks():
        for i in range(da, a):
            out[i] = heard[min(ha, len(heard) - 1)][1]
        for k in range(n):
            out[a + k] = heard[b + k][1]
        da, ha = a + n, b + n
    for i in range(1, len(out)):
        out[i] = max(out[i], out[i - 1])
    return out


def build_units(S):
    total_s = S['total'] / FPS
    caps, _ = ve.build_caps(S['captions'], S['words'], S['aliases'], LEAD, total_s)
    units = [dict(s=s, e=e, T=T, words=T.split()) for s, e, T in caps]
    flat = [w for u in units for w in u['words']]
    starts = map_words(ve.make_norm(S['aliases']), flat, [(w['w'], w['s']) for w in S['words']])
    j = 0; notes = []
    for u in units:
        u['wstart'] = [round(s - LEAD, 3) for s in starts[j:j + len(u['words'])]]; j += len(u['words'])
        u['wstart'][0] = max(u['wstart'][0], 0.0)
        sbs = u['s']
        u['s'] = 0.0 if u is units[0] else u['wstart'][0]
        if abs(u['s'] - sbs) > 0.02:
            notes.append(f'unit "{u["T"]}" starts {u["s"]:.3f} (split/join rule: {sbs:.3f})')
    for i, u in enumerate(units):
        u['e'] = units[i + 1]['s'] if i + 1 < len(units) else total_s
        u['wstart'] = [max(s, u['s']) for s in u['wstart']]
    i = 0                                        # a unit under 18 frames joins a neighbour when the pair still fits x 120-860
    while i < len(units):
        u = units[i]
        if round(u['e'] * FPS) - round(u['s'] * FPS) < 18:
            for j in (i + 1, i - 1):
                if 0 <= j < len(units):
                    a, b = (u, units[j]) if j > i else (units[j], u)
                    T = a['T'] + ' ' + b['T']
                    if ve.cap_width(T) <= ve.TW:
                        notes.append(f'joined short unit "{u["T"]}" with "{units[j]["T"]}"')
                        a.update(T=T, e=b['e'], words=a['words'] + b['words'], wstart=a['wstart'] + b['wstart'])
                        del units[max(i, j)]; i = max(0, min(i, j) - 1); break
            else:
                notes.append(f'unit "{u["T"]}" stays under 18 frames: no neighbour pair fits x 120-860')
                i += 1
            continue
        i += 1
    spec_mod.end_units_at_silences(units, S['silences'])       # after the joins: a unit before a silent span ends at the span's start, not at the next unit's
    return units, notes


def caption_layers(T):
    """Per caption unit: blurred shadow, all-words-spoken text, all-words-unspoken text (rows 1080-1300), and a column -> word index map."""
    f = ve.font(ve.BARLOW, ve.CAP_SIZE); words = T.split(); sp = f.getlength(' ')
    x = ve.SLOT[0]; pos = []
    shl = Image.new('RGBA', (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(shl)
    for w in words:
        pos.append(x); d.text((x, ve.CAP_BASE + ve.CAP_SH[0]), w, font=f, fill=ve.CAP_SH[2], anchor='ls'); x += f.getlength(w) + sp
    shadow = shl.crop((0, ve.CAPY, W, ve.CAPY + 220)).filter(ve.ImageFilter.GaussianBlur(ve.CAP_SH[1]))
    box = (0, ve.CAPY, W, ve.CAPY + 220)

    def line(col):
        tl = Image.new('RGBA', (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(tl)
        for w, px in zip(words, pos):
            d.text((px, ve.CAP_BASE), w, font=f, fill=col, anchor='ls')
        return tl

    out = []
    for spoken in (True, False):
        tl = line(ve.SPOKEN + (255,) if spoken else ve.UNSPOKEN_RGB + (int(255 * ve.UNSPOKEN_A),))
        if spoken:
            ve.check_safe(tl, f'caption unit "{T}"')
        out.append(tl.crop(box))
    bounds = np.array([pos[i + 1] - sp / 2 for i in range(len(words) - 1)])
    colw = (np.arange(W)[:, None] >= bounds[None, :]).sum(axis=1) if len(bounds) else np.zeros(W, int)
    res = dict(shadow=to_gpu_rgba(np.asarray(shadow)), spoken=to_gpu_rgba(np.asarray(out[0])), unspoken=to_gpu_rgba(np.asarray(out[1])),
               colw=torch.from_numpy(colw).to(DEV))
    if ve.FP.get('ink'):                           # field chu-muc: the same line in ink, for beats whose text is ink (no shadow)
        res['spoken_ink'] = to_gpu_rgba(np.asarray(line(ve.INK + (255,)).crop(box)))
        res['unspoken_ink'] = to_gpu_rgba(np.asarray(line(ve.INK + (int(255 * ve.FP['ink_unspoken']),)).crop(box)))
    return res


def caption_time(units, words, after, where):
    """Start (karaoke time) of the first run of consecutive caption words equal to `words`, not earlier than `after`."""
    flat = [(w, s) for u in units for w, s in zip(u['words'], u['wstart'])]
    for n in range(len(flat) - len(words) + 1):
        if all(flat[n + q][0] == words[q] for q in range(len(words))) and flat[n][1] >= after:
            return flat[n][1]
    raise SystemExit(f'spec: {where}: caption words {words} not found after {after} s (captions are upper-case, with their punctuation)')


# ---------------- beats ----------------
SRC_FPS = 25


def merged_layer(beat, state, S):
    """Text element (state), top-right mark and chip of one beat state as one RGBA layer, in the storyboard's order; a hook block is lifted by `lift` px."""
    base = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    ve.INK_TEXT = bool(beat.get('ink'))               # field chu-muc; False everywhere else
    t = beat.get('text')
    regions = []                                         # text blocks the contrast gate measures: (name, floor, (x0, y0, x1, y1)) in frame pixels
    if t:
        st = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        try:
            r = ve.draw_text(st, t, state, beat['mark'] == 'wm')
        except KeyError as e:
            raise SystemExit(f'spec: beats[{beat["id"]}].text.{e.args[0]} is missing (text.kind "{t.get("kind")}")')
        shift = int(t.get('lift', 0))                     # px upward
        if (t['kind'] == 'block' and beat['mark'] == 'wm' and not t.get('lines_off')) or t['kind'] == 'end':
            shift += ve.HOOK_LIFT                          # layout r3: the opening block and the ending card end above the raised subtitle (other layouts: 0)
        if ve.STRICT and beat['cardlike']:               # a beat without a picture: the block sits centred between the chip row and the caption
            shift -= beat.setdefault('card_dy', ve.card_shift(t, beat['mark'] == 'wm'))
        if shift:
            st = Image.fromarray(ve.shift_rows(np.asarray(st), -shift))
        base.alpha_composite(st)
        k = r.get('kicker')
        kb = k['text'] if k and k.get('text') and k['text'][2] > k['text'][0] else None
        if kb:
            regions.append(('kicker', 4.5, (kb[0] - 2, kb[1] - 8 - shift, kb[2] + 2, kb[3] + 8 - shift)))
        if r.get('kicker_only'):                          # layout r3, headline 'none': the kicker row is all this beat draws; its region is measured above
            pass
        elif r.get('block'):
            x0, y0, x1, y1 = r['block']
            regions.append(('headline', 3.0, (x0 - 2, y0 - 6 - shift, x1 + 2, y1 + 30 - shift)))
        else:                                             # chart, number or list card: everything the card draws below its kicker
            top = (k['row_y'][1] + 4 - shift) if k else ve.ROW_Y + 80
            bottom = ve.CAP_TOP - 20
            if t.get('source'):                           # the card's source line is small text: its own block at 4.5, and the content block stops above it
                regions.append(('source', 4.5, (ve.X_L - 2, ve.BLOCK_B - 32 - shift, ve.X_R + 2, ve.BLOCK_B + 10 - shift)))
                bottom = ve.BLOCK_B - 40 - shift
            regions.append(('content', 3.0, (ve.X_L - 2, top, ve.X_R + 2, bottom)))
            if r.get('content', True) is False:               # the draw itself says nothing went into the content block in this state (chart rows that cut in later)
                beat.setdefault('undrawn', {}).setdefault(state, set()).add('content')
    elif beat['mark'] == 'wm':
        raise SystemExit(f'spec: beats[{beat["id"]}].mark "wm" needs a text element (the wordmark pill sits in its kicker row)')
    if beat['mark'] == 'tr':
        ve.put_mark(base, 'tr')
    if beat.get('chip'):
        ve.put_chip(base, beat['chip'])
        if beat['chip'].get('line'):                      # the credit line under a kept chip
            regions.append(('credit', 4.5, (ve.X_L - 2, ve.CREDIT_Y - 30, ve.X_R + 2, ve.CREDIT_Y + 12)))
    ve.INK_TEXT = False
    ve.check_safe(base, f'beat {beat["id"]} state {state} (text, mark, chip)')
    beat.setdefault('regions', {})[state] = regions
    return to_gpu_rgba(np.asarray(base))


def load_spec(path):
    return spec_mod.load_spec(path, FPS, ve.DEFAULT_LAYOUT)


def build_beats(S, units):
    beats = []; nvid = {}; nclip = {}; byid = {}
    chip_texts = [b['chip']['title'] if b.get('chip', {}).get('line') else b['chip']['text'] for b in S['beats'] if b.get('chip') and (b['chip'].get('title') or b['chip'].get('text'))]   # a chip with only a "line" has no chip box to size
    if chip_texts:
        ve.CHIP_S = ve.chip_text_size(chip_texts)
    if ve.FP.get('no_chip'):                           # field chu-muc: a chip that only says where and when a capture was taken is not drawn
        for sp in S['beats']:                          # (after the chip size is set from every chip of the spec, so a chip that stays keeps today's size)
            if sp.get('chip') and not ve.keeps_chip(sp['chip']):
                print(f'field {ve.FIELD}: beat {sp.get("id")}: source chip not drawn: {sp["chip"].get("title") or sp["chip"].get("text")}', flush=True)
                sp['chip'] = None
    if S['drop_kickers']:
        for sp in S['beats']:
            tx = sp.get('text')
            if tx and tx.get('kind') == 'block' and sp.get('mark', 'tr') != 'wm' and tx.get('kicker') is not None and not tx.get('keep_kicker'):
                tx['kicker'] = ''
    if ve.HEADLINE != 'all':                           # layout r3: the voice and the subtitle already say the headline of a picture beat, so it is not drawn
        for sp in S['beats']:
            tx = sp.get('text')
            if not tx or tx.get('kind') != 'block':
                continue
            if sp.get('mark', 'tr') != 'wm':
                sp['text'] = None                      # a picture beat after the opening one: no headline (and no kicker: it is a block's kicker)
            elif ve.HEADLINE == 'none':
                tx['lines_off'] = True                 # the opening beat keeps its pill + kicker row only
    for bi, sp in enumerate(S['beats']):
        where = f'beats[{bi}]'
        i = str(need(sp, 'id', where)); where = f'beats[{i}]'
        t = sp.get('text')
        level = sp.get('level') or ('CARD' if t and t['kind'] in ('chart', 'number', 'list') else None)
        if level not in ('HOOK', 'FOOT', 'CARD'):
            raise SystemExit(f'spec: {where}.level must be HOOK, FOOT or CARD')
        b = dict(id=i, name=sp.get('name', i), a=float(need(sp, 'a', where)), b_=float(need(sp, 'b', where)), level=level, kind=None, bands=[], notes={},
                 mark=sp.get('mark', 'tr'), chip=sp.get('chip'), text=t, cardlike=(level == 'CARD' or sp.get('picture') is None), ink_spec=sp.get('text_ink'),
                 captions=spec_mod.beat_captions(sp, where))      # False: no subtitle is drawn during this beat (a silent stretch)
        b['f0'] = round(b['a'] * FPS); b['f1'] = min(round(b['b_'] * FPS), S['total'])
        if t is None and level == 'CARD':
            raise SystemExit(f'spec: {where}: a CARD beat needs a text element')
        states = ve.n_states(t) if t else 1
        b['layers'] = [merged_layer(b, s, S) for s in range(states)]
        b['switch'] = [b['f0']]
        for ci, c in enumerate(t.get('cuts', []) if t else []):
            if isinstance(c, dict):
                tt = caption_time(units, need(c, 'word', f'{where}.text.cuts[{ci}]'), c.get('after', 0.0), f'{where}.text.cuts[{ci}]')
                b['switch'].append(max(round(tt * FPS), b['f0']))
            else:
                b['switch'].append(round(float(c) * FPS))
        pic = sp.get('picture')
        if level == 'CARD' or pic is None:
            b['kind'] = 'card'; b['pic'] = torch.zeros(3, H, W, device=DEV)
        elif pic['kind'] == 'capture':
            img = ve.Image.open(need_file(S['base'], need(pic, 'file', where + '.picture'), where + '.picture.file')).convert('RGB')
            K = ve.PIC_W / img.width
            if 'rows' in pic:
                sa, sb_ = pic['rows']
            else:
                lines = pic.get('lines', 'all'); r0, r1 = pic.get('band_rows', [0, img.height])
                bands = ve.ink_bands(img, r0, r1)
                if lines == 'all':
                    sa, sb_ = bands[0][0], bands[-1][1]
                else:
                    a_, b_ = lines
                    if len(bands) <= b_:
                        raise SystemExit(f'spec: {where}.picture.lines {lines}: the capture has only {len(bands)} text lines in rows {r0}-{r1}')
                    sa, sb_ = bands[a_][0], bands[b_][1]
            win_h = ve.WIN[level][1] - ve.WIN[level][0]
            if (sb_ - sa) * K > win_h:                                   # the focus must fit its window: shrink the whole picture
                K = win_h / (sb_ - sa)
            if img.width * K < ve.PIC_W_MIN:
                raise SystemExit(f'safe frame: {where}: focus S is {sb_ - sa} capture px high, the {level} window is {win_h} px, so the picture would be '
                                 f'{round(img.width * K)} px wide (floor {ve.PIC_W_MIN}); pick fewer lines or a narrower focus')
            u_rows = pic.get('u_rows')
            if ve.STRICT and u_rows is None:
                raise SystemExit(f'spec: {where}.picture.u_rows is missing: layout {ve.LAYOUT} shows only the capture rows the spec names '
                                 f'(a gap above the first line to show, a gap below the last), so nothing is chosen silently')
            if ve.STRICT and not (u_rows[0] <= sa and sb_ <= u_rows[1]):
                raise SystemExit(f'spec: {where}.picture.u_rows {u_rows} does not contain the focus rows {sa}-{sb_}')
            if ve.LAYOUTS[ve.LAYOUT].get('fit_shown'):       # layouts thu-gon-r3-l<n> (short opening window): shrink the picture until the whole shown span fits the window, centred
                lo_, hi_ = ve.WIN[level]; c_ = ve.CENTRE[level]
                K = min(K, 2 * min(c_ - lo_, ve.FADE_AT[level] - c_) / (u_rows[1] - u_rows[0]))
                if img.width * K < ve.PIC_W_MIN:
                    raise SystemExit(f'safe frame: {where}: the shown rows {u_rows} need the picture shrunk to {round(img.width * K)} px wide (floor {ve.PIC_W_MIN}) to fit the {level} window')
            frame, y0, ex = ve.article_pic(img, sa, sb_, 0, img.width, K, ve.CENTRE[level], u_rows=u_rows)
            px = ex['px']
            ve.check_pic(where + ' (capture)', px, px + round(img.width * K), (round((sa - y0) * K), round((sb_ - y0) * K)), level)
            if ve.STRICT:
                ve.check_shown(where + ' (capture)', img, u_rows[0], u_rows[1], y0, K, level)
                if b['mark'] == 'tr':
                    ve.check_pill(where + ' (capture)', frame)
            b['kind'] = 'still'; b['pic'] = to_gpu_rgb(frame); b['notes'] = dict(ex, S_rows=[sa, sb_], y0=round(y0, 1), k=round(K, 4),
                                                                              S_frame_h=round((sb_ - sa) * K), S_frame_y=[round((sa - y0) * K), round((sb_ - y0) * K)])
            for bd in sp.get('bands', []):
                x, y, w, h = bd['rect']
                r = [px + round(x * K), round((y - y0) * K), px + round((x + w) * K), round((y + h - y0) * K)]
                ya, yb, xa, xb = max(0, r[1] - 4), r[3] + 4, max(0, r[0] - 7), r[2] + 7
                crop = b['pic'][:, ya:yb, xa:xb]
                L = (crop * torch.tensor([.299, .587, .114], device=DEV)[:, None, None]).sum(0)
                b['bands'].append(dict(rect=r, box=(ya, yb, xa, xb), fm=((L - 60) / 195).clamp(0, 1)[None], spec=bd))
        elif pic['kind'] == 'recording':
            webm = need_file(S['base'], need(pic, 'file', where + '.picture'), where + '.picture.file')
            src0, sdur = float(need(pic, 'start', where + '.picture')), float(need(pic, 'dur', where + '.picture'))
            k = ve.REC_W / 390
            samples = [src0 + j * 0.3 for j in range(int(sdur / 0.3) + 1)] + [src0 + sdur - 0.04]
            if 'rect' in pic:
                Su = tuple(pic['rect'])
            else:
                det = need(pic, 'detect', where + '.picture')
                fr_s = [ve.cap_frame(webm, tm, S['tmp']) for tm in samples]
                Su = ve.union([ve.bubble_bbox(f) if det == 'bubble' else ve.typed_bbox(f) for f in fr_s])
            win_h = ve.WIN[level][1] - ve.WIN[level][0]
            if (Su[3] - Su[1]) * k > win_h:                              # the focus must fit its window: shrink the whole picture
                k = win_h / (Su[3] - Su[1])
            if 390 * k < ve.PIC_W_MIN:
                raise SystemExit(f'safe frame: {where}: focus S is {Su[3] - Su[1]} recording px high, the {level} window is {win_h} px, so the picture would be '
                                 f'{round(390 * k)} px wide (floor {ve.PIC_W_MIN})')
            y0 = round((Su[1] + Su[3]) / 2 - ve.CENTRE[level] / k)
            ut = int(pic.get('u_top', 0))
            top_src, bot_src = max(y0, ut), min(math.ceil(y0 + H / k), 844)
            if ve.STRICT:                                                # the screen ends on a line boundary above the fade; below it only its background
                fr_c = [ve.cap_frame(webm, tm, S['tmp']) for tm in samples]
                cut = ve.rec_cut(where + ' (recording)', fr_c, Su[3], math.floor(y0 + ve.FADE_AT[level] / k))
                bot_src = min(bot_src, cut)
                c0 = ve.rec_top(where + ' (recording)', fr_c, top_src, Su[1])
                if c0 > top_src:                                         # the first rows would cut a line: start on a background-only row, flat background above it
                    top_src = ut = c0
            out_w = round(390 * k); x_at = round((W - 390 * k) / 2)
            g = dict(k=k, ut=ut, ub=bot_src, hold_last=ve.STRICT, top_src=top_src, bot_src=bot_src, ux0=0, ux1=390, y_at=round((top_src - y0) * k), out_h=round((bot_src - top_src) * k),
                     out_w=out_w, x_at=x_at)
            ve.check_pic(where + ' (recording)', x_at, x_at + out_w, (round((Su[1] - y0) * k), round((Su[3] - y0) * k)), level, ve.REC_W)
            b['kind'] = 'video'; b['geom'] = g; b['clip'] = str(webm); b['src0'] = src0; b['sdur'] = sdur
            b['notes'] = dict(S_src=list(Su), y0=y0, k=round(k, 4), S_frame_h=round((Su[3] - Su[1]) * k), x_range=[x_at, x_at + out_w],
                              S_frame_y=[round((Su[1] - y0) * k), round((Su[3] - y0) * k)], geom=g)
            nvid.setdefault(str(webm), []).append(b)
        elif pic['kind'] == 'clip':
            if level not in ('HOOK', 'FOOT'):
                raise SystemExit(f'spec: {where}.level must be HOOK or FOOT for a clip picture')
            man = spec_mod.load_clip_manifest(need_file(S['base'], need(pic, 'manifest', where + '.picture'), where + '.picture.manifest'), where + '.picture')
            cp = spec_mod.plan_clip(man, pic, ve.WIN[level], W, ve.REC_W, ve.PIC_X0, where + '.picture')
            ve.check_pic(where + ' (clip)', cp['x_at'], cp['x_at'] + man['w'], (cp['y_at'], cp['y_at'] + man['h']), level, ve.REC_W)
            b['kind'] = 'clip'; b['clip'] = str(man['video']); b['src0'] = cp['src0']; b['sdur'] = cp['sdur']; b['sfps'] = cp['sfps']; b['sframes'] = cp['sframes']
            b['cw'], b['ch'], b['cx'], b['cy'] = man['w'], man['h'], cp['x_at'], cp['y_at']
            b['clipbg'] = torch.tensor(man['bg'], device=DEV, dtype=torch.float32)[:, None, None].expand(3, H, W).contiguous()
            b['stills_t'] = [s['t'] for s in man['stills'] if cp['src0'] - 1e-6 <= s['t'] <= cp['src0'] + cp['sdur'] + 1e-6]
            b['notes'] = dict(manifest=str(man['path']), source=man['source'], captured=man['captured'], tool_sha=man['tool_sha'], x_range=[cp['x_at'], cp['x_at'] + man['w']],
                              y_range=[cp['y_at'], cp['y_at'] + man['h']], min_text_px=man['min_text_px'], src=[cp['src0'], cp['src0'] + cp['sdur']])
            nclip.setdefault((str(man['video']), man['w'], man['h'], cp['sfps']), []).append(b)
        elif pic['kind'] == 'repo':
            if level not in ('HOOK', 'FOOT'):
                raise SystemExit(f'spec: {where}.level must be HOOK or FOOT for a repo picture')
            man = repo_mod.load_manifest(need_file(S['base'], need(pic, 'manifest', where + '.picture'), where + '.picture.manifest'))
            top = ve.WIN[level][0]
            bottom = ve.FADE_AT['HOOK'] if level == 'HOOK' else min(ve.FADE_AT['FOOT'], ve.SLOT[1] - 54)    # thu-gon-r3-l2: HOOK 364-866, FOOT 364-1214 (60 px above the subtitle ink)
            hh, ww = bottom - top, ve.PIC_W
            first_repo = not any(bb['kind'] == 'repo' for bb in beats)         # the first repo beat of the video opens on the whole page for a moment (walk[0].camera.overview overrides)
            plan_r = repo_mod.plan_walk(man, need(pic, 'walk', where + '.picture'), b['f0'], b['f1'], hh, ww, FPS, default_overview=1.0 if first_repo else 0.0, where=where + '.picture')
            ve.check_pic(where + ' (repo)', ve.PIC_X0, ve.PIC_X0 + ww, (top, bottom), level)
            bg = torch.tensor(man['bg'], device=DEV, dtype=torch.float32)
            show = dict(pages=man['pages'], bg=bg, ww=ww, hh=hh, top=top, scale=man['scale'], flat=bg[:, None, None].expand(3, H, W).contiguous())
            b['kind'] = 'repo'; b['show'] = show; b['plan'] = plan_r
            b['notes'] = dict(manifest=str(man['path']), window=dict(x=[ve.PIC_X0, ve.PIC_X0 + ww], y=[top, bottom]), **repo_mod.plan_notes(plan_r))
            for lab, ff in [(f'still {lab}', fr_) for lab, fr_ in plan_r['stills']] + [(f'hold {h["kind"]} step {h["step"]}', h['frame']) for h in plan_r['holds']]:
                sg_ = repo_mod.seg_at(plan_r['segments'], ff)
                share = check_blank_window(f'{where} ({lab}, frame {ff})', repo_window(b, ff), bg)
                b['notes'].setdefault('ink_share', {})[f'{lab} f{ff}'] = round(share, 3)
            print(f'repo beat {i}: {len(plan_r["segments"])} pages, largest pan step {plan_r["max_pan_px_per_frame"]} px/frame (cap {plan_r["pan_cap_px_per_frame"]}), '
                  f'largest zoom step {plan_r["max_zoom_per_frame"]} ln/frame (cap {plan_r["zoom_cap_per_frame"]}); hold text sizes (frame px): '
                  + ', '.join(f'{h["page"] or "home"}:{h["kind"]}={h["text_frame_px"]}' for h in plan_r['holds']), flush=True)
        elif pic['kind'] == 'same_as':
            b['kind'] = 'same_as'; b['of'] = str(need(pic, 'beat', where + '.picture'))
        else:
            raise SystemExit(f'spec: {where}.picture.kind "{pic["kind"]}" is not capture, recording, clip, repo or same_as')
        if b['bands'] and not b['level'] in ('HOOK', 'FOOT'):
            raise SystemExit(f'spec: {where}: bands need a picture beat')
        beats.append(b); byid[i] = b
    for clip, bl in nvid.items():
        need_n = max(int(math.floor((bb['src0'] + bb['sdur']) * SRC_FPS + 1e-6)) for bb in bl) + 1
        t0 = time.time(); raw, cmd = decode_nv12(clip, need_n); print(f'NVDEC decoded {need_n} frames of {Path(clip).name} in {time.time() - t0:.2f} s', flush=True)
        lo = min(int(math.floor(bb['src0'] * SRC_FPS + 1e-6)) for bb in bl)
        buf = torch.from_numpy(raw[lo:need_n].copy()).to(DEV)
        for bb in bl:
            bb['frames'] = buf; bb['lo'] = lo
    for (clip, cw, ch, sfps), bl in nclip.items():
        need_n = min(max(int(math.floor((bb['src0'] + bb['sdur']) * sfps + 1e-6)) for bb in bl) + 1, bl[0]['sframes'])
        t0 = time.time(); raw, cmd = decode_nv12(clip, need_n, cw, ch); print(f'NVDEC decoded {need_n} frames of {Path(clip).name} ({cw}x{ch}) in {time.time() - t0:.2f} s', flush=True)
        lo = min(int(math.floor(bb['src0'] * sfps + 1e-6)) for bb in bl)
        buf = torch.from_numpy(raw[lo:need_n].copy()).to(DEV)
        for bb in bl:
            bb['frames'] = buf; bb['lo'] = lo
            ts = bb['stills_t'] or [bb['src0'] + bb['sdur'] / 2]        # a frame that is only the clip's background is refused: the producer drew nothing, or the span is past its content
            bgc = bb['clipbg'][:, 0, 0]
            for tm in ts:
                f_ = min(max(int(math.floor(tm * sfps + 1e-6)), lo), need_n - 1)
                win = clip_picture(bb, f_)[:, bb['cy']:bb['cy'] + ch, bb['cx']:bb['cx'] + cw]
                bb['notes'].setdefault('ink_share', {})[f't{tm:g}'] = round(check_blank_window(f'beat {bb["id"]} (clip, source time {tm:g} s)', win, bgc), 3)
    return beats, byid


def choose_ink(beats):
    """Field chu-muc: per picture beat, the text colour with the higher contrast against the measured background. Background = median
    relative luminance of the finished picture-plus-field at the beat's middle frame, in the text column, from the first text row below the chip
    row down to the caption. Ink when it is above ve.INK_SWITCH_L (where ink and white are equal), white below. A spec may name it: text_ink.
    The choice is printed and written to the plan; cards keep white."""
    for b in beats:
        if b['cardlike']:
            continue
        f = (b['f0'] + b['f1']) // 2
        bg = apply_skin_gpu(beat_pic(b, f), b['level'], f)
        rows = (b['layers'][-1][3, 700:] > 200).any(dim=1).nonzero()
        top = 700 + int(rows.min()) if len(rows) else ve.CAP_TOP
        c = (bg[:, top:ve.CAP_BASE + 16, ve.X_L:ve.X_R] / 255.0).clamp(0, 1)
        lin = torch.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
        L = float((0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]).median())
        b['ink'] = bool(b['ink_spec']) if b['ink_spec'] is not None else L > ve.INK_SWITCH_L
        b['notes']['text_colour'] = dict(colour='ink' if b['ink'] else 'white', background_L=round(L, 3), rows=[top, ve.CAP_BASE + 16],
                                         by='spec text_ink' if b['ink_spec'] is not None else f'measured, switch at L {ve.INK_SWITCH_L}')
        print(f'field {ve.FIELD}: beat {b["id"]}: text {b["notes"]["text_colour"]["colour"]} (background L {L:.3f}, rows {top}-{ve.CAP_BASE + 16})', flush=True)
        if b['ink']:
            b['layers'] = [merged_layer(b, s, None) for s in range(len(b['layers']))]


def src_index(b, f):
    """Recording frame shown at output frame f of a footage beat: the latest source frame at that moment; held at the end of the shot."""
    ts = min(b['src0'] + (f / FPS - b['a']), b['src0'] + b['sdur'])
    i = int(math.floor(ts * b.get('sfps', SRC_FPS) + 1e-6))
    return min(i, b['sframes'] - 1) if 'sframes' in b else i


def clip_picture(b, si):
    """A clip frame (source index si) placed 1:1 on the clip's flat background colour: the picture of a clip beat, never scaled."""
    fr = b['clipbg'].clone()
    fr[:, b['cy']:b['cy'] + b['ch'], b['cx']:b['cx'] + b['cw']] = nv12_to_rgb(b['frames'][si - b['lo']], b['cw'], b['ch'])
    return fr


def beat_pic(b, f):
    if b['kind'] == 'video':
        return vid_picture(nv12_to_rgb(b['frames'][src_index(b, f) - b['lo']]), b['geom'])
    if b['kind'] == 'clip':
        return clip_picture(b, src_index(b, f))
    if b['kind'] == 'repo':
        return repo_picture(b, f)
    return b['pic']


def resolve_same_as(beats, byid):
    for b in beats:
        if b['kind'] == 'same_as':
            src = byid.get(b['of'])
            if src is None:
                raise SystemExit(f'spec: beats[{b["id"]}].picture.beat "{b["of"]}" is not a beat id')
            if src['kind'] == 'video':
                b['pic'] = vid_picture(nv12_to_rgb(src['frames'][src_index(src, src['f1'] - 1) - src['lo']]), src['geom'])
                b['notes'] = dict(source=f'last frame of beat {src["id"]}', src_index=src_index(src, src['f1'] - 1))
            elif src['kind'] == 'clip':
                b['pic'] = clip_picture(src, src_index(src, src['f1'] - 1)); b['notes'] = dict(source=f'last frame of clip beat {src["id"]}', src_index=src_index(src, src['f1'] - 1))
            elif src['kind'] == 'repo':
                b['pic'] = repo_picture(src, src['f1'] - 1); b['notes'] = dict(source=f'last frame of repo beat {src["id"]}')
            elif src['kind'] in ('still', 'card'):
                b['pic'] = src['pic']; b['notes'] = dict(source=f'beat {src["id"]} picture')
            else:
                raise SystemExit(f'spec: beats[{b["id"]}].picture.beat "{b["of"]}" is itself a same_as; point at the original beat')
            b['kind'] = 'still'


def band_times(units, beats):
    rep = {}
    for b in beats:
        for n, band in enumerate(b['bands']):
            sp = band['spec']; where = f'beats[{b["id"]}].bands[{n}]'
            if 'at' in sp:
                band['f'] = round(float(sp['at']) * FPS); why = 'fixed time from the spec'
            else:
                t = caption_time(units, need(sp, 'word', where), sp.get('after', 0.0), where)
                band['f'] = max(round(t * FPS), b['f0']); why = f'{sp["word"][0]} (caption word, karaoke time {t:.3f})'
            rep.setdefault(b['id'], []).append(dict(rect=band['rect'], frame=band['f'], why=why))
    return rep


def frame_state(units, f):
    t = f / FPS; ui = None
    for n, u in enumerate(units):
        if u['s'] - 1e-9 <= t < u['e'] - 1e-9:
            ui = n; break
    if ui is None:
        ui = len(units) - 1
    u = units[ui]
    return ui, max(1, sum(1 for s in u['wstart'] if round(s * FPS) <= f))


TINT = torch.tensor(ve.TINT, device=DEV, dtype=torch.float32)


def compose(f, bymap, units, ulay, tt=None):
    b = bymap[f]
    pic = beat_pic(b, f)
    if b['bands']:
        pic = pic.clone()
        for bd in b['bands']:
            al = min(max((f - bd['f'] + 1) / FADE, 0.0), 1.0)
            if al > 0:
                al = al * al * (3 - 2 * al)
                ya, yb, xa, xb = bd['box']
                pic[:, ya:yb, xa:xb] += (TINT - 255)[:, None, None] * bd['fm'] * al
    out = apply_skin_gpu(pic, b['level'], f)
    ui, lit = frame_state(units, f)
    L = ulay[ui]
    si = max(n for n, s in enumerate(b['switch']) if s <= f)
    comp(out, b['layers'][si])
    if not b['captions']:                             # a silent beat (spec `captions: false`): no subtitle during its frames, the frames on either side are drawn as before
        pass
    elif b.get('ink'):                                # field chu-muc: ink caption, no shadow
        comp(out, torch.where((L['colw'] < lit)[None, None, :], L['spoken_ink'], L['unspoken_ink']), ve.CAPY)
    else:
        comp(out, L['shadow'], ve.CAPY)
        comp(out, torch.where((L['colw'] < lit)[None, None, :], L['spoken'], L['unspoken']), ve.CAPY)
    if tt is None:
        return out
    tik = out.clone(); comp(tik, tt)
    return out, tik


RING = 12                                           # contrast gate: the pixels measured lie within RING px of a text block's glyphs, glyphs themselves (grown 3 px) excluded


def _lum(c):
    c = np.asarray(c, float) / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return lin[..., 0] * 0.2126 + lin[..., 1] * 0.7152 + lin[..., 2] * 0.0722


def _ring_contrast(still, mask, text_rgb):
    """WCAG ratio between the text colour and the median luminance of the finished pixels around the glyphs. still: (H, W, 3) float 0-255; mask: (H, W) bool."""
    ys, xs = np.nonzero(mask)
    if not len(ys):
        return None
    y0, y1, x0, x1 = max(ys.min() - RING, 0), min(ys.max() + RING + 1, H), max(xs.min() - RING, 0), min(xs.max() + RING + 1, W)
    grown = np.asarray(Image.fromarray((mask * 255).astype(np.uint8)).filter(ve.ImageFilter.MaxFilter(7))) > 0
    ring = np.zeros_like(mask); ring[y0:y1, x0:x1] = True; ring &= ~grown
    lb = float(np.median(_lum(still[ring]))); lt = float(_lum(np.array(text_rgb)))
    return (max(lb, lt) + .05) / (min(lb, lt) + .05), lb


def _ring_median_rgb(still, mask):
    ys, xs = np.nonzero(mask)
    y0, y1, x0, x1 = max(ys.min() - RING, 0), min(ys.max() + RING + 1, H), max(xs.min() - RING, 0), min(xs.max() + RING + 1, W)
    grown = np.asarray(Image.fromarray((mask * 255).astype(np.uint8)).filter(ve.ImageFilter.MaxFilter(7))) > 0
    ring = np.zeros_like(mask); ring[y0:y1, x0:x1] = True; ring &= ~grown
    return np.median(still[ring], axis=0)


def contrast_gate(units, beats, bymap, ulay):
    """Every still the builder can write: the text colour against the pixels actually around each text block of the finished frame, at the middle of
    every state of every beat (kicker, headline or card content, credit line) and of every caption unit (spoken colour). Floors: 4.5 for kicker, credit
    line and caption, 3.0 for headline and card content. Field chu-muc refuses (nothing is written) and names beat, block and number; field dac and
    layout hien-tai print what is under the floor. A block that has no glyphs in its region raises: nothing is skipped silently."""
    t0 = time.time(); results = []; fails = []; warns = []; ncheck = 0; nskip = 0
    for f, b, label in contrast_frames(units, beats, bymap):
        ui, _ = frame_state(units, f)
        fr = compose(f, bymap, units, ulay).cpu().numpy().transpose(1, 2, 0)
        col = ve.INK if b.get('ink') else (255, 255, 255)
        si = max(n for n, s in enumerate(b['switch']) if s <= f)
        jobs = []
        if label[0] == 'state':
            for name, floor, (x0, y0, x1, y1) in b['regions'][si]:
                if name in b.get('undrawn', {}).get(si, ()):      # the builder drew nothing here: nothing to measure; a drawn block with no glyphs still raises below
                    nskip += 1; print(f'beat {b["id"]} {label[1]} {name}: nothing drawn in this state, not measured', flush=True); continue
                m = np.zeros((H, W), bool); a = (b['layers'][si][3].cpu().numpy() > 100)
                m[max(y0, 0):y1, max(x0, 0):x1] = a[max(y0, 0):y1, max(x0, 0):x1]
                jobs.append((name, floor, m, col))
        else:                                             # caption unit: its glyph mask is the rows CAPY.. of the unit's spoken layer
            m = np.zeros((H, W), bool); m[ve.CAPY:ve.CAPY + 220] = ulay[ui]['spoken'][3].cpu().numpy() > 100
            jobs.append(('caption', 4.5, m, col))
            if b.get('ink'):                              # unspoken words: ink at ink_unspoken over the same pixels, 60 px bold = large text, 3:1
                a_ = ve.FP['ink_unspoken']; jobs.append(('unspoken', 3.0, m, tuple(a_ * np.array(ve.INK) + (1 - a_) * _ring_median_rgb(fr, m))))
        for name, floor, m, tcol_ in jobs:
            got = _ring_contrast(fr, m, tcol_)
            if got is None:
                raise SystemExit(f'contrast gate: beat {b["id"]} {label[1]}: block {name} has no glyph pixels in its region (the gate cannot measure it)')
            c, lb = got; ncheck += 1
            results.append(dict(beat=b['id'], where=label[1], block=name, colour=('ink' if b.get('ink') else 'white') + (f" {ve.FP['ink_unspoken']:.2f}" if name == 'unspoken' else ''), ratio=round(c, 2), background_L=round(lb, 3), floor=floor))
            if b['cardlike'] and c >= 3.0:                # a card is flat brand coral: refused only under 3:1 (regression guard); small text between 3 and 4.5 is reported, never silent
                if c < floor and name in ('kicker', 'source', 'credit', 'note', 'caption') and not any(w['beat'] == b['id'] and w['where'] == label[1] and w['block'] == name for w in warns):
                    warns.append(dict(beat=b['id'], where=label[1], block=name, ratio=round(c, 2), floor=floor))
                continue
            if c < floor:
                fails.append(f'beat {b["id"]} {label[1]}: {name} {"ink" if b.get("ink") else "white"} text measures {c:.2f}:1 against the surrounding pixels '
                             f'(background luminance {lb:.3f}), floor {floor}:1')
    if fails:
        msg = 'contrast gate: ' + str(len(fails)) + ' block(s) under the floor:\n  ' + '\n  '.join(fails)
        if ve.FP.get('gate'):
            raise SystemExit(msg)
        print(msg + '\n  (field ' + str(ve.FIELD) + ' is not gated: printed only)', flush=True)
    for w in warns:
        print(f'card small text under 4.5:1: beat {w["beat"]} {w["where"]} {w["block"]} measures {w["ratio"]}:1', flush=True)
    tail = f'{len(fails)} under the floor' if fails else (f'{len(warns)} card block(s) between 3:1 and 4.5:1 (printed above), none refused' if warns else 'all at or above the floor')
    if nskip:
        tail += f'; {nskip} block(s) with nothing drawn, not measured'
    print(f'contrast gate: {ncheck} blocks measured in {time.time() - t0:.1f} s, ' + tail, flush=True)
    return results, warns


def contrast_frames(units, beats, bymap):
    """(frame, beat, ('state', label) | ('unit', label)): the middle frame of every state of every beat, and the middle of every caption unit's time
    inside the beat that holds it."""
    out = []
    for b in beats:
        sw = b['switch'] + [b['f1']]
        for s in range(len(b['layers'])):
            lo, hi = sw[s], (sw[s + 1] if s + 1 < len(sw) else b['f1'])
            if hi > lo:
                out.append(((lo + hi) // 2, b, ('state', f'state {s} f{(lo + hi) // 2}')))
    for u in units:
        lo, hi = round(u['s'] * FPS), round(u['e'] * FPS)
        # a unit may straddle beats: measure it inside each beat it overlaps
        seen = {}
        for f in range(lo, min(hi, len(bymap))):
            bb = bymap[f]
            if not bb['captions']:                    # no subtitle is drawn in a silent beat, so there is nothing to measure there
                continue
            seen.setdefault(bb['id'], [bb, f, f])[2] = f
        for bb, a, z in seen.values():
            out.append(((a + z) // 2, bb, ('unit', f'caption "{u["T"]}" f{(a + z) // 2}')))
    return out


def tiktok_layer(S):
    """The estimated TikTok interface as one RGBA layer: overlay() on black and on white solves the alpha exactly."""
    bk = np.asarray(ve.overlay(Image.new('RGB', (W, H), (0, 0, 0)), S['tiktok_caption'])).astype(np.float64)
    wh = np.asarray(ve.overlay(Image.new('RGB', (W, H), (255, 255, 255)), S['tiktok_caption'])).astype(np.float64)
    a = 1 - (wh - bk).mean(axis=2) / 255.0
    c = np.where(a[..., None] > 1e-3, bk / np.maximum(a[..., None], 1e-3), 0)
    return to_gpu_rgba(np.dstack([np.clip(c + .5, 0, 255), np.clip(a * 255 + .5, 0, 255)]).astype(np.uint8))


def to_yuv(rgb):
    x = rgb.clamp(0, 255).round()
    R, G, B = x[0], x[1], x[2]
    Y = 16 + 0.182586 * R + 0.614231 * G + 0.062007 * B
    r, g, b = F.avg_pool2d(x[None], 2)[0]
    U = 128 - 0.100644 * r - 0.338572 * g + 0.439216 * b
    Vv = 128 + 0.439216 * r - 0.398942 * g - 0.040274 * b
    return torch.cat([Y.round().clamp(16, 235).flatten(), U.round().clamp(16, 240).flatten(), Vv.round().clamp(16, 240).flatten()]).to(torch.uint8)


def run(cmd):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode:
        raise SystemExit('ffmpeg failed: ' + r.stderr[-1500:])
    return r


def build_audio(S):
    """The voice, gain only (linear loudnorm to -16 LUFS), padded with silence to the video length."""
    tmp = S['tmp']; pad = tmp / 'giong-pad.wav'; out = tmp / 'giong-chuan.wav'; total = S['total'] / FPS
    run(['ffmpeg', '-v', 'error', '-y', '-i', S['voice'], '-af', f'aresample=48000,apad=whole_dur={total}', '-t', f'{total}', '-ac', '1', '-c:a', 'pcm_s24le', pad])
    r = run(['ffmpeg', '-hide_banner', '-nostats', '-i', pad, '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json', '-f', 'null', '-'])
    m = json.loads(r.stderr[r.stderr.rindex('{'):r.stderr.index('}', r.stderr.rindex('{')) + 1])
    run(['ffmpeg', '-v', 'error', '-y', '-i', pad, '-af', f"loudnorm=I=-16:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
         f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true,aresample=48000", '-c:a', 'pcm_s24le', out])
    return out


def encoder(path, audio, log, total):
    cmd = ['ffmpeg', '-y', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'yuv420p', '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv',
           '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-', '-i', str(audio),
           '-map', '0:v', '-map', '1:a', '-c:v', 'h264_nvenc', '-preset', 'p7', '-tune', 'hq', '-rc', 'vbr', '-cq', '18', '-b:v', '0', '-pix_fmt', 'yuv420p',
           '-profile:v', 'high', '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv',
           '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2', '-t', f'{total / FPS:.3f}', '-movflags', '+faststart', str(path)]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=open(log, 'wb')), cmd


# ---------------- main ----------------
def setup(S):
    t0 = time.time()
    S['tmp'].mkdir(parents=True, exist_ok=True)
    ve.configure(ve.DEFAULT_FONT_DIRS, ve.DEFAULT_MARK_DIRS, S['tmp'] / 'cache', S['layout'], S['field'], S['pattern'], S['mesh_motion'])
    ve.PILL_GATE = S['pill_gate']
    print(f'pattern {ve.PATTERN}' + (f': {ve.MESH_INFO}, white {ve.WHITE_K}, motion {"on" if ve.MESH_MOTION else "off"}' if ve.MESH_INFO else ''), flush=True)
    units, unit_notes = build_units(S)
    beats, byid = build_beats(S, units)
    resolve_same_as(beats, byid)
    if ve.FP.get('ink'):
        choose_ink(beats)
    rep = band_times(units, beats)
    bymap = {}
    for b in beats:
        for f in range(b['f0'], b['f1']):
            bymap[f] = b
    if sorted(bymap) != list(range(S['total'])):
        raise SystemExit(f'spec: beats do not tile frames 0-{S["total"] - 1} (duration {S["duration"]} s): check each beat a/b and the last b')
    ulay = [caption_layers(u['T']) for u in units]
    contrast, card_warn = contrast_gate(units, beats, bymap, ulay)         # before anything is written: a refusal leaves the earlier files as they were
    plan = dict(frames=S['total'], fps=FPS, lead=LEAD, fade_frames=FADE, chip_size=ve.CHIP_S, field=ve.FIELD, pattern=ve.PATTERN, mesh_white=(ve.WHITE_K if ve.MESH else None), mesh_motion=(ve.MESH_MOTION if ve.MESH else None), contrast=contrast, card_small_text_under_4_5=card_warn, bands=rep, unit_notes=unit_notes,
                units=[dict(s=round(u['s'], 3), e=round(u['e'], 3), T=u['T'], wstart=u['wstart']) for u in units],
                beats=[dict(id=b['id'], name=b['name'], f0=b['f0'], f1=b['f1'], level=b['level'], kind=b['kind'], switch=b['switch'], captions=b['captions'],
                            notes={k: v for k, v in b['notes'].items() if k != 'geom'}) for b in beats])
    (S['path'].with_name(S['path'].stem + '-plan.json')).write_text(json.dumps(plan, ensure_ascii=False, indent=1, default=str), encoding='utf-8', newline='\n')
    print(f'setup {time.time() - t0:.1f} s; {len(units)} caption units, {len(beats)} beats; unit notes: {unit_notes}', flush=True)
    return units, beats, bymap, ulay


def to_pil(t):
    return Image.fromarray(t.clamp(0, 255).round().byte().permute(1, 2, 0).cpu().numpy())


def stills(S):
    units, beats, bymap, ulay = setup(S)
    d = S['path'].with_name(S['path'].stem + '-stills'); d.mkdir(exist_ok=True)
    for old in d.iterdir():
        old.unlink()
    shots = []                                      # (label, frame)
    for b in beats:
        sw = b['switch'] + [b['f1']]
        if b['kind'] == 'repo':                       # one still per page of the walk, at its arrival and at its hover on the next row
            for lab, ff in b['plan']['stills']:
                shots.append((f'beat {b["id"]} {lab}', ff))
        elif b['kind'] == 'clip' and b['stills_t']:   # one still per time the clip's manifest names (inside the shown span), at that moment of the beat
            for tm in b['stills_t']:
                shots.append((f'beat {b["id"]} t{tm:g}', min(max(b['f0'] + round((tm - b['src0']) * FPS), b['f0']), b['f1'] - 1)))
        elif len(b['layers']) == 1:
            shots.append((f'beat {b["id"]}', (b['f0'] + b['f1']) // 2))
        else:
            for s in range(len(b['layers'])):
                lo, hi = sw[s], (sw[s + 1] if s + 1 < len(sw) else b['f1'])
                if hi > lo:
                    shots.append((f'beat {b["id"]} state {s}', (lo + hi) // 2))
    imgs = []
    for label, f in shots:
        im = to_pil(compose(f, bymap, units, ulay)); imgs.append((label, f, im))
        stem = re.sub(r'[^\w.-]+', '-', label) + f'-f{f}'
        im.convert('RGB').save(d / (stem + '.jpg'), quality=92)
        for case in ('fb', 'xau-nhat', 'tt'):
            ve.phone_preview(im, case).save(d / f'{stem}-{case}.jpg', quality=92)
    tw, th, cols = 270, 480, 5
    rows = math.ceil(len(imgs) / cols)
    sheet = Image.new('RGB', (cols * (tw + 8) + 8, rows * (th + 40) + 8), (24, 24, 28)); dr = ImageDraw.Draw(sheet)
    for n, (label, f, im) in enumerate(imgs):
        x, y = 8 + (n % cols) * (tw + 8), 8 + (n // cols) * (th + 40)
        sheet.paste(im.resize((tw, th), Image.LANCZOS), (x, y + 32)); dr.text((x, y + 8), f'{label}  f{f}  {f / FPS:.2f}s', fill=(255, 255, 255), font=ve.font(ve.UI, 18))
    sheet.save(d / 'contact-sheet.jpg', quality=90)
    mark_beat = next((x for x in imgs if x[0].split()[1] and next(bb for bb in beats if bb['id'] == x[0].split()[1])['mark'] == 'tr'), imgs[0])
    mark_beat[2].crop((600, 250, 1080, 410)).save(d / 'crop-corner-mark-1to1.png')
    imgs[0][2].crop((0, ve.CAPY, W, ve.CAPY + 220)).save(d / 'crop-caption-1to1.png')
    imgs[0][2].resize((390, 693), Image.LANCZOS).save(d / 'phone-size-390.png')
    print(f'{len(imgs)} stills + contact-sheet.jpg + crops written to {d}')


def render(S):
    units, beats, bymap, ulay = setup(S)
    tt = tiktok_layer(S); total = S['total']
    t_start = time.time()
    audio = build_audio(S)
    pc, cmd_c = encoder(S['out_clean'], audio, S['tmp'] / 'nvenc-clean.log', total)
    pt, cmd_t = encoder(S['out_tt'], audio, S['tmp'] / 'nvenc-tiktok.log', total)
    torch.cuda.reset_peak_memory_stats()
    t_comp = t_pipe = 0.0; t_frames = time.time()
    for f in range(total):
        torch.cuda.synchronize(); t0 = time.time()
        c, k = compose(f, bymap, units, ulay, tt)
        yc, yt = to_yuv(c), to_yuv(k)
        torch.cuda.synchronize(); t1 = time.time()
        try:
            pc.stdin.write(yc.cpu().numpy().tobytes()); pt.stdin.write(yt.cpu().numpy().tobytes())
        except (BrokenPipeError, OSError):
            raise SystemExit('encoder pipe closed: ' + (S['tmp'] / 'nvenc-clean.log').read_text(errors='replace')[-800:] + (S['tmp'] / 'nvenc-tiktok.log').read_text(errors='replace')[-800:])
        t2 = time.time(); t_comp += t1 - t0; t_pipe += t2 - t1
        if f % 300 == 0:
            print(f'frame {f}/{total}  composite {t_comp:.1f} s  pipe {t_pipe:.1f} s', flush=True)
    t_f0 = time.time()
    pc.stdin.close(); pt.stdin.close(); pc.wait(); pt.wait()
    for p, lg in ((pc, 'nvenc-clean.log'), (pt, 'nvenc-tiktok.log')):
        if p.returncode:
            raise SystemExit(f'encoder failed ({lg}): ' + (S['tmp'] / lg).read_text(errors='replace')[-1500:])
    wall = time.time() - t_start
    res = dict(frames=total, wall_s_total_with_audio=round(wall, 1), frame_loop_s=round(t_f0 - t_frames, 1), composite_gpu_s=round(t_comp, 1), pipe_write_s=round(t_pipe, 1),
               encoder_flush_s=round(time.time() - t_f0, 1), torch_peak_allocated_mib=round(torch.cuda.max_memory_allocated() / 2**20), encoder_cmd=' '.join(cmd_c))
    S['path'].with_name(S['path'].stem + '-render.json').write_text(json.dumps(res, indent=1), encoding='utf-8', newline='\n')
    print(json.dumps(res, indent=1)); print('written:', S['out_clean'], S['out_tt'])


if __name__ == '__main__':
    args = sys.argv[1:]
    if len(args) != 2 or args[1] not in ('--stills', '--render') or not args[0].endswith('.json'):
        raise SystemExit('usage: dung-video-gpu.py <spec.json> --stills | --render')
    spec = load_spec(args[0])
    t = time.time()
    (stills if args[1] == '--stills' else render)(spec)
    print(f'{args[1]} wall time {time.time() - t:.1f} s')
