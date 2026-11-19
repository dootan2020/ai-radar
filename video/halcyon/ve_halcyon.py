"""Halcyon look, CPU drawing half (Pillow). Lifted function by function from video-halcyon-02/storyboard/nguon/ve-storyboard-02.py
(the approved look: skin, marks, chip, kicker row, big block, number card, row chart, caption geometry, TikTok overlay), with the video-#2 data
(captions, chip strings, chart rows, picture list) removed so that a spec file supplies it. Loaded by dung-video-gpu.py; not run on its own.

Everything here runs once before the frame loop and returns RGBA layers or pictures; the per-frame pixel work is in dung-video-gpu.py (CUDA)."""
import json, math, os, subprocess
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1080, 1920
INK, CORAL_L, CORAL, PLUM = (16, 24, 40), (244, 105, 138), (240, 68, 110), (91, 23, 56)
BARLOW, BARLOW_XB = 'BarlowCondensed-Bold.ttf', 'BarlowCondensed-ExtraBold.ttf'
BVP_M, BVP_SB = 'BeVietnamPro-Medium.ttf', 'BeVietnamPro-SemiBold.ttf'
_WIN_FONTS = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'Fonts'     # Segoe UI draws only the phone previews (TikTok interface), never the video itself
UI, UIB = (_WIN_FONTS / 'segoeui.ttf').as_posix(), (_WIN_FONTS / 'segoeuib.ttf').as_posix()
# Assets resolve from the tool's own folder first, then from the repository's brand kit (BeVietnamPro and the wordmark are the brand kit's own files).
_REPO = Path(__file__).resolve().parent.parent.parent
DEFAULT_FONT_DIRS = (Path(__file__).resolve().parent / 'fonts', _REPO / 'brand' / 'fonts')
DEFAULT_MARK_DIRS = (_REPO / 'brand' / 'logo' / 'coral-tile' / 'logos',)
X_L, X_R, TW = 120, 860, 740                     # text column: left edge, right edge, width (inside the safe frame)
ROW_Y, TOP_R = 288, 960                          # top of the chip / pill row; right edge of the top-right pill
SAFE_TOP, COL_Y, COL_X = 288, 840, 863
SAFE_L, SAFE_R, SAFE_R_COL = 120, 960, 860     # safe frame: x 120-960 (x <= 860 from row COL_Y down), y SAFE_TOP-SAFE_BOT
CROP_FB, CROP_MAX = 56, 97                      # side crop of a tall phone: measured Facebook Reels, upper bound
CROP_TT = 54                                    # measured TikTok side crop (iPhone 15 Pro Max)
# TikTok feed with the caption collapsed, measured 19/11/2026 on a 1290 x 2796 screenshot of another account's public TikTok video (vung-an-toan/thu-gon-1119/do.md): the video fills the
# screen down to the tab bar (native y 2548 = frame y 1920), so one frame px = TT2_K native px, frame x = 54 + native x / TT2_K, frame y = native y / TT2_K.
TT2_K = 2548 / 1920
TT2_RAIL = [(1132, 1178, 1266, 1345), (1145, 1418, 1262, 1545), (1145, 1620, 1262, 1742), (1145, 1815, 1262, 1945), (1145, 1985, 1262, 2140),
            (1139, 2210, 1259, 2330), (1145, 2390, 1255, 2485)]                     # follow, like, comment, save, share, sound disc, sticker (native px)
TT2_CAPTION = (38, 2312, 891, 2505)              # channel name + the two lines under it (native px); frame y 1742-1888
PIC_X0, PIC_W, PIC_W_MIN = 97, 886, 700         # a picture is drawn inside x 97-983, so the narrowest phone shows all of it
REC_W = 886                                     # a screen recording keeps this width on every layout (thu-gon-r narrows only captures, PIC_W)

# Layout presets. 'A' is the Halcyon layout and the default (owner, 18/11/2026: "Dựng theo A"); 'hien-tai' is the earlier layout, kept by name
# for comparison (spec key "layout": "hien-tai"), and builds as before.
# dy: how far the text column (kicker row, block, credit line, card rows, caption) and the bottom edge of the safe frame move down;
# the picture windows grow by the same dy. veil: top veil strength (0.40 -> 0 at y 280). fade: length of the coral fade as a share of the earlier
# layout's (1.0 = 200 px on an opening beat) and of the melt; hook_off: where the opening-beat fade starts relative to the bottom of its window.
# strict (A only): a capture beat must give its shown rows (`u_rows`), the picture ends on a line boundary above the fade (captures and recordings),
# and a card (a beat without a picture) has its content block centred between the chip row and the caption.
DEFAULT_LAYOUT = 'A'
LAYOUTS = {
    'hien-tai': dict(dy=0, veil=.40, fade=1.0, hook_off=-40, strict=False),
    'A': dict(dy=192, veil=.12, fade=.65, hook_off=-20, strict=True),
    # 'thu-gon' (19/11/2026, owner: the safe area is measured with the caption COLLAPSED, three lines: channel name, one description line, hashtags).
    # Same as A, 248 px lower: dy 440 puts the safe frame's bottom at y 1688 (measured collapsed caption starts y 1748 in the feed, 1693 in the composer
    # preview, see vung-an-toan/thu-gon-1119/do.md); `wash` shifts the colour field's absolute stops down by the same 248 px (A: 0, so A is unchanged).
    # 'thu-gon-2': the same with the picture window starting at y 244 (below TikTok's top tabs, band ends y 228) instead of 364, so a picture can use the
    # room above the "hco.news" pill; the pill (x 800-960, y 288-348) must then stay over picture background (check_pill).
    'thu-gon': dict(dy=440, veil=.12, fade=.65, hook_off=-20, strict=True, wash=248),
    'thu-gon-2': dict(dy=440, veil=.12, fade=.65, hook_off=-20, strict=True, wash=248, win_top=244),
    # 'thu-gon-r': thu-gon with pictures only 763 px wide (x 97-860): below y 840 the right-hand button column starts at x 907, so a full-width picture (x 97-983) puts text under it
    'thu-gon-r': dict(dy=440, veil=.12, fade=.65, hook_off=-20, strict=True, wash=248, pic_w=763),
    # 'thu-gon-r2' (owner 19/11 08:38, to approve): thu-gon-r with the opening-picture window 108 px taller (the rows a dropped kicker line frees, spec key drop_kickers),
    # the colour field's opening-beat stops 108 px lower with it, and the hco.news pill at y 244 (TikTok's top tabs end at y 228) instead of 288
    'thu-gon-r2': dict(dy=440, veil=.12, fade=.65, hook_off=-20, strict=True, wash=248, pic_w=763, hook_extra=108, pill_y=244),
    # 'thu-gon-r3' / 'thu-gon-r3-b' (owner 19/11 22:05, to approve by eye): thu-gon-r2 with (1) the karaoke subtitle `cap_up` px higher, so its lowest ink ends well above the
    # collapsed three-line TikTok caption (starts y 1693 in the composer preview, 1748 in the feed), and (2) the big two-line headline taken off the picture beats, because the
    # voice and the subtitle already say it. `headline` says where a headline stays: 'hook' = on the opening beat only (the beat with the wordmark pill, readable with sound off),
    # 'none' = nowhere (the opening beat keeps only its pill + kicker row, seated right above the subtitle). `hook_lift`: how far the opening beat's block moves up so it ends above the
    # raised subtitle (headline 'hook'), and how far the ending card moves up (both variants: the end card would otherwise run into the raised subtitle); `hook_extra` shrinks
    # accordingly (r2: 108) since those blocks and their kicker rows now sit higher than in r2. Both variants share every number except `headline`.
    'thu-gon-r3': dict(dy=440, veil=.12, fade=.65, hook_off=-20, strict=True, wash=248, pic_w=763, hook_extra=38, pill_y=244, cap_up=120, headline='hook', hook_lift=70),
    'thu-gon-r3-b': dict(dy=440, veil=.12, fade=.65, hook_off=-20, strict=True, wash=248, pic_w=763, hook_extra=38, pill_y=244, cap_up=120, headline='none', hook_lift=70),
}
LAYOUTS_A = ('A', 'thu-gon', 'thu-gon-2', 'thu-gon-r', 'thu-gon-r2', 'thu-gon-r3', 'thu-gon-r3-b')      # layouts that carry the colour fields (strict layouts)
# Colour field of layout A (spec key "field"). Owner, 18/11/2026 22:50, from three stills: "1 Chữ mực" is the Halcyon look and the default.
#   chu-muc (default): a thin wash that starts at mid-frame and thickens to the bottom; the text of a picture beat (kicker, headline, credit line,
#     caption) is drawn in ink when the measured background is light and in white when it is dark; no source chip (a chip stays only if it is an
#     illustration marker, keeps_chip). The contrast gate (`gate`) refuses a still whose text is hard to read.
#   dac: the dense field of the earlier layout A (white text on an opaque coral fade, every chip drawn). Kept by name for comparison and as the way
#     back; its numbers are printed but not gated (its kicker measures 4.05-4.18 on a light picture, under the 4.5 floor).
# hook / foot: opacity stops (frame y, opacity) after the first fade row (FADE_AT, opacity 0). c_stops: colour stops of the wash for picture beats
# (cards keep C_STOPS). small_alpha: kicker, credit line and the small text of a card (source line, note) are drawn at full strength.
_THIN_HOOK = [(960, .20), (1084, .30), (1276, .44), (1401, .52), (1440, .56), (1600, .80), (1920, .97)]
_THIN_FOOT = [(1276, .30), (1401, .52), (1440, .56), (1600, .80), (1920, .97)]
_THIN_C = [(0, (240, 68, 110)), (1276, (232, 64, 106)), (1500, (196, 50, 92)), (1920, (91, 23, 56))]     # a thin wash stays coral longer, plum only at the bottom
DEFAULT_FIELD = 'chu-muc'
FIELDS = {
    'chu-muc': dict(ink=True, ink_unspoken=.60, small_alpha=255, no_chip=True, gate=True, hook=_THIN_HOOK, foot=_THIN_FOOT, c_stops=_THIN_C),
    'dac': dict(),
}
FIELD = None            # name of the active field, or None (layout hien-tai)
FP = {}                 # its preset
FIELD_C_ROWS = None     # its colour rows for picture beats, when it has c_stops
INK_TEXT = False        # set by the builder while it draws a beat whose text is ink
INK_SWITCH_L = 0.199    # background luminance at which white and ink text have the same contrast: (L + .05)^2 = 1.05 * (L_ink + .05)
STRICT = False
FADE_AT = None
CAP_TOP = None
LAYOUT = None
DY = 0
SLOT = SAFE_BOT = WIN = CENTRE = None
PILL_Y = 288; HOOK_EXTRA = 0
HEADLINE, HOOK_LIFT = 'all', 0      # where the big headline block stays on a picture beat ('all', 'hook', 'none'), and the opening block's extra lift (set_layout)
BLOCK_B = CREDIT_Y = NOTE_Y = CH_BASE0 = NUM_Y1 = NUM_Y2 = LIST_T = LIST_R0 = CAPY = None
C_STOPS = C_ROWS = ALPHA_STOPS = MELT = DM_STOPS = None
VEIL = .40
BIG_SH = (3, 8, INK + (71,))                  # 0 3px 16px rgba(16,24,40,.28)
CAP_SH = (2, 6, PLUM + (140,))                  # 0 2px 12px rgba(91,23,56,.55)
SPOKEN, UNSPOKEN_RGB, UNSPOKEN_A = (255, 255, 255), (255, 228, 234), .68
CAP_SIZE = 60
TINT = (250, 190, 204)                           # Hot Coral F0446E at about 35% on white

FONTS = MARKS = KH = None
CAP_BASE = None
CHIP_S = 26
WM_PILL = TR_PILL = None


def set_layout(name):
    """Select a layout preset (LAYOUTS) and derive every number that depends on it. Called by configure() before anything is drawn."""
    global LAYOUT, DY, SLOT, SAFE_BOT, WIN, CENTRE, BLOCK_B, CREDIT_Y, NOTE_Y, CH_BASE0, NUM_Y1, NUM_Y2, LIST_T, LIST_R0, CAPY
    global C_STOPS, C_ROWS, ALPHA_STOPS, MELT, DM_STOPS, VEIL, STRICT, FADE_AT
    if name not in LAYOUTS:
        raise SystemExit(f'layout "{name}" is not one of {sorted(LAYOUTS)}')
    p = LAYOUTS[name]; LAYOUT, DY, VEIL, STRICT = name, p['dy'], p['veil'], p['strict']
    cu = p.get('cap_up', 0)                                                  # r3: the subtitle sits this many px higher (every other layout: 0)
    SLOT = (X_L, 1140 + DY - cu, X_R, 1236 + DY - cu); SAFE_BOT = 1248 + DY; CAPY = 1080 + DY - cu
    global HEADLINE, HOOK_LIFT
    HEADLINE, HOOK_LIFT = p.get('headline', 'all'), p.get('hook_lift', 0)
    wt = p.get('win_top', 364)
    global PIC_W
    PIC_W = p.get('pic_w', 886)
    WIN = {'HOOK': (wt, 600 + DY + p.get('hook_extra', 0)), 'FOOT': (wt, 900 + DY)}
    global PILL_Y, SAFE_TOP, HOOK_EXTRA
    PILL_Y = p.get('pill_y', ROW_Y); SAFE_TOP = min(288, PILL_Y); HOOK_EXTRA = p.get('hook_extra', 0)
    CENTRE = {k: (a + b) // 2 for k, (a, b) in WIN.items()}                  # seat S at the centre of its WIN window
    BLOCK_B, CREDIT_Y, NOTE_Y, CH_BASE0 = 1084 + DY, 1124 + DY, 1030 + DY, 577 + DY
    NUM_Y1, NUM_Y2, LIST_T, LIST_R0 = 780 + DY, 930 + DY, 590 + DY, 740 + DY
    C_STOPS = [(0, (240, 68, 110)), (800 + DY, (214, 58, 98)), (1100 + DY, (140, 28, 68)), (1920, (91, 23, 56))]
    C_ROWS = np.stack([np.interp(YS, [s[0] for s in C_STOPS], [s[1][c] for s in C_STOPS]) for c in range(3)], axis=1)
    f = p['fade']; hs = WIN['HOOK'][1] + p['hook_off']; fs = WIN['FOOT'][1]
    FADE_AT = {'HOOK': hs, 'FOOT': fs}                                          # first frame row the coral fade touches: a picture ends above it
    tail = [(1100 + DY, .92), (SAFE_BOT, .95), (1920, .97)]
    r = lambda start, pts: [(start + round(o * f), a) for o, a in pts]
    ALPHA_STOPS = {
        'FOOT': [(0, 0)] + r(fs, [(0, 0), (60, .18), (120, .55)]) + [(fs + round(200 * f), .92)] + tail[1:],
        'HOOK': [(0, 0)] + r(hs, [(0, 0), (80, .25), (140, .65)]) + [(hs + round(200 * f), .92)] + tail,
        'CARD': [(0, 1.0), (1920, 1.0)],
    }
    MELT = {'FOOT': (22, fs + 40, fs + 40 + round(110 * f)), 'HOOK': (28, WIN['HOOK'][1], WIN['HOOK'][1] + round(80 * f))}
    DM_STOPS = [0, 900 + DY, 1250 + DY, 1920]
    _SKIN.clear()


def set_field(name):
    """Select the colour field (FIELDS) on top of the layout preset already set. None = DEFAULT_FIELD on layout A; layout hien-tai has no field."""
    global FIELD, FP, FIELD_C_ROWS
    FIELD, FP, FIELD_C_ROWS = None, {}, None
    if name is None:
        if LAYOUT not in LAYOUTS_A:
            return
        name = DEFAULT_FIELD
    if name not in FIELDS:
        raise SystemExit(f'field "{name}" is not one of {sorted(FIELDS)}')
    if LAYOUT not in LAYOUTS_A:
        raise SystemExit(f'field "{name}" is defined on layout A only (layout is "{LAYOUT}")')
    FIELD, FP = name, FIELDS[name]
    ws = LAYOUTS[LAYOUT].get('wash', 0)            # a layout that sits lower than A moves the field's absolute stops down with it (A: 0)
    mv = lambda stops: [(y + ws if y < H else y, a) for y, a in stops]
    if 'hook' in FP:
        ALPHA_STOPS['HOOK'] = [(0, 0), (FADE_AT['HOOK'], 0)] + [(y + HOOK_EXTRA if y < H else y, a) for y, a in mv(FP['hook'])]
        ALPHA_STOPS['FOOT'] = [(0, 0), (FADE_AT['FOOT'], 0)] + mv(FP['foot'])
    if 'c_stops' in FP:
        cs = [(y + ws if y < H and y > 0 else y, c) for y, c in FP['c_stops']]
        FIELD_C_ROWS = np.stack([np.interp(YS, [s[0] for s in cs], [s[1][c] for s in cs]) for c in range(3)], axis=1)
    _SKIN.clear()


def configure(fonts, marks, cache, layout=DEFAULT_LAYOUT, field=None, pattern=None, motion=True):
    """Point the module at its font folder, brand-mark folder and cache folder, select the layout preset (and a field candidate, if any),
    then build the two brand pills."""
    global FONTS, MARKS, KH, CAP_BASE, CAP_TOP, WM_PILL, TR_PILL
    FONTS = tuple(Path(p) for p in ([fonts] if isinstance(fonts, (str, Path)) else fonts))     # one folder or an ordered list of folders
    MARKS = tuple(Path(p) for p in ([marks] if isinstance(marks, (str, Path)) else marks))
    KH = Path(cache)
    KH.mkdir(parents=True, exist_ok=True)
    set_layout(layout)
    set_field(field)
    set_pattern(pattern, motion)
    cap_h = -font(BARLOW, CAP_SIZE).getbbox('H', anchor='ls')[1]
    CAP_BASE = SLOT[1] + (96 + cap_h) // 2                                                           # 1211 (+ DY)
    CAP_TOP = CAP_BASE - cap_h                                                                        # top of the caption's capital letters
    if LAYOUTS[LAYOUT].get('cap_up'):                                                                 # r3: the credit line of a kept chip goes below the raised subtitle, not into it
        global CREDIT_Y
        CREDIT_Y = CAP_BASE + 64
    WM_PILL, TR_PILL = wordmark_pill(), topright_pill()


def find_asset(dirs, name):
    """The first folder of `dirs` that holds `name`, or None."""
    for folder in dirs:
        if (folder / name).exists():
            return folder / name
    return None


def font(name, px):
    found = find_asset(FONTS, name)
    if found:
        return ImageFont.truetype(str(found), px)
    return ImageFont.truetype(name, px)


def mode_colour(arr):
    a = arr.reshape(-1, 3)
    vals, counts = np.unique(a, axis=0, return_counts=True)
    return tuple(int(v) for v in vals[counts.argmax()])


# ================= skin (colour field + opacity levels) =================
YS = np.arange(H, dtype=float)                 # colour field, opacity levels and melt come from the layout preset (set_layout)
_yy, _xx = np.mgrid[0:H, 0:W]
_d = np.hypot((_xx % 22) - 10.5, (_yy % 22) - 10.5)
DOT = np.clip((2.3 - _d) / 0.6, 0, 1) * 0.16
_SKIN = {}                                       # MELT[level] = (sigma px, melt starts y, full melt y)
set_layout(DEFAULT_LAYOUT)

# ================= field pattern: the white mesh (default) or the dots =================
# Owner, 18/11/2026 23:52: "mạng nơ-ron màu trắng nhé em"; 19/11 00:2x: "Làm mạng nơ-ron chuyển động nhẹ nhàng cho anh". The pattern is white at WHITE_K
# under the dots' own vertical envelope (DM_STOPS). The mesh moves: every node drifts around its home on a slow closed path that is a function of the
# frame number alone (mesh_pos), the links follow. `cham` is the dot grid by name (spec key "pattern": "cham"), byte for byte, and does not move.
# Geometry is the designer's (vung-an-toan/hoa-tiet/ve-hoa-tiet.py, mang_no_ron: seed 7, pitch 156, links under 1.3 pitch kept with p .52, 16% ringed nodes);
# only nodes are moved or dropped so that none sits in the kicker row or the caption line of a picture beat.
DEFAULT_PATTERN = 'mang-no-ron'
PATTERNS = ('mang-no-ron', 'cham')
PATTERN = None
COVER = None                                     # dots only: coverage 0..0.16 of the dot grid, W x H (the mesh is drawn per frame on the GPU, see dung-video-gpu.mesh_cover)
WHITE_K = 0.40                                   # peak white of the mesh (owner's phone could not see it at 0.16; coordinator measured 0.16/0.30/0.45 on stills, 19/11 00:2x)
MESH_INFO = {}
MESH_NODES = []                                  # (x, y, ringed) of every node drawn at home, for the checks
MESH = None                                      # geometry and motion of the active mesh (dict), None for the dots
MESH_MOTION = True
MESH_FPS = 30.0
# motion: per node and axis, offset = c + a sin(2 pi f / (30 T) + phase); a 5..7.5 px, T 12..18 s, so no node is faster than 7.5 x 2 pi / 12 = 3.9 px/s per axis
# (5.6 px/s on the diagonal) and none is further than 7.5 x sqrt 2 = 10.6 px from home. Nodes within one amplitude of a text band swing one-sidedly (c, a chosen so
# the offset toward the band never exceeds the gap to it).
# presets of the drift (spec key "mesh_motion": a preset name, true = DEFAULT_MOTION, false = frozen, or {"amplitude": [lo, hi], "period": [lo, hi]}):
#   rat-nhe  a 5-7.5 px, T 12-18 s   (19/11 00:3x build; <= 10.6 px from home, <= 5.6 px/s)
#   nhe      a 14-20 px, T 9-13 s    (default; coordinator's limits: no node further than 26 px from home, none faster than 13 px/s)
# A node whose drawn amplitudes and periods would break those limits is slowed (period up to 1.35x the range's top), then shrunk, until it fits
# (MOTION_VMAX px/s on the diagonal, MOTION_RMAX px from home); the changed nodes are counted in the info line.
MOTION_PRESETS = {'rat-nhe': ((5.0, 7.5), (12.0, 18.0)), 'nhe': ((14.0, 20.0), (9.0, 13.0))}
DEFAULT_MOTION = 'nhe'
MOTION_VMAX = 12.5
MOTION_RMAX = 25.5


def motion_params(motion):
    """(amplitude range, period range) for a spec value: True -> DEFAULT_MOTION, a preset name, or a dict with amplitude and period ranges."""
    if motion is True or motion is None:
        motion = DEFAULT_MOTION
    if isinstance(motion, str):
        if motion not in MOTION_PRESETS:
            raise SystemExit(f'mesh_motion "{motion}" is not one of {sorted(MOTION_PRESETS)}, true, false or an object with amplitude and period')
        return MOTION_PRESETS[motion]
    if isinstance(motion, dict):
        return tuple(motion['amplitude']), tuple(motion['period'])
    raise SystemExit(f'mesh_motion must be a preset name, true, false or an object, got {motion!r}')


def mesh_keep_out():
    """Bands (y0, y1) across the text column where small text lives on a picture beat, from the layout's own rows: the kicker row (its bottom is 32 px
    above the block's ink top, 76 px high; the block is one to two lines of at most 124 px, so it lies in BLOCK_B-346 .. BLOCK_B-146) and the
    caption line with its credit line (SLOT top - 32 .. SLOT bottom + 12). A node inside a band moves out through its 'up' edge (the kicker band: above it
    the wash is nil on a picture beat) or its 'down' edge (the caption band: below it is clear of text)."""
    return [(BLOCK_B - 346, BLOCK_B - 146, 'up'), (SLOT[1] - 32, SLOT[3] + 12, 'down')]


def _footprint(ring):
    return (14 if ring else 6) + 3                          # ring 14 px / dot 5.5 px, +3 px


def mesh_geometry(keep_out, motion=True):
    """The designer's neural mesh: home positions, links, ringed flags, nodes kept out of `keep_out` bands across x X_L-X_R; returns (G, info)."""
    rng = np.random.default_rng(7); p = 156.0; pts = []
    for j, y in enumerate(np.arange(-p, H + p, p * .866)):
        for x in np.arange(-p, W + p, p):
            pts.append((x + (p / 2 if j % 2 else 0) + rng.uniform(-.27, .27) * p, y + rng.uniform(-.27, .27) * p))
    pts = np.array(pts)
    edges = []
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            if np.hypot(*(pts[i] - pts[j])) < 1.30 * p and rng.random() < .52:
                edges.append((i, j))
    ringed = [bool(rng.random() < .16) for _ in range(len(pts))]
    n_all = len(pts); moved = []; dropped = set()
    for i in range(n_all):                                   # a node whose footprint touches a band moves to the band edge
        m = _footprint(ringed[i]); x, y = pts[i]
        if not (X_L - m - 24 <= x <= X_R + m + 24):                 # the text column, and 24 px beside it (a dot next to the first letter)
            continue
        for a, b, way in keep_out:
            if a - m < y < b + m:
                ny = a - m if way == 'up' else b + m
                moved.append((i, round(float(y - ny)))); pts[i, 1] = ny
                break
    for i, _ in moved:                                       # two nodes pushed onto the same edge: the later one goes
        for k in range(n_all):
            if k != i and k not in dropped and np.hypot(*(pts[i] - pts[k])) < 60:
                dropped.add(i); break
    keep = [e for e in edges if e[0] not in dropped and e[1] not in dropped and np.hypot(*(pts[e[0]] - pts[e[1]])) <= 1.30 * p * 1.25]   # a link a moved node stretched past 1.25x the longest designed one goes
    alive = np.array([i not in dropped for i in range(n_all)])
    # ---- motion parameters (fixed seed 11, independent of the geometry stream)
    rg = np.random.default_rng(11)
    (a_lo, a_hi), (t_lo, t_hi) = motion_params(motion)
    A = rg.uniform(a_lo, a_hi, (n_all, 2)); T = rg.uniform(t_lo, t_hi, (n_all, 2)); ph = rg.uniform(0, 2 * np.pi, (n_all, 2)); fitted = 0
    for i in range(n_all):                                   # fit each node inside the speed and distance limits: slow it first, then shrink it
        for _ in range(200):
            v = float(np.hypot(*(A[i] * 2 * np.pi / T[i]))); r = float(np.hypot(*A[i]))
            if v <= MOTION_VMAX and r <= MOTION_RMAX:
                break
            fitted += 1 if _ == 0 else 0
            if v > MOTION_VMAX and T[i].max() < t_hi * 1.35:
                T[i] = np.minimum(T[i] * 1.03, t_hi * 1.35)
            else:
                A[i] *= 0.98
    c = np.zeros((n_all, 2)); a = A.copy(); restricted = 0
    for i in range(n_all):
        if not alive[i]:
            continue
        m = _footprint(ringed[i]); x, y = pts[i]
        for ylo, yhi in ((b0 - m, b1 + m) for b0, b1, _w in keep_out):
            xlo, xhi = X_L - m - 24, X_R + m + 24
            gx, gy = max(xlo - x, x - xhi), max(ylo - y, y - yhi)         # <= 0 inside the band's range on that axis
            if gx < -1e-6 and gy < -1e-6:
                raise SystemExit(f'mesh node {i} at ({x:.1f}, {y:.1f}) lies inside a keep-out band at home')
            if gx > 0 and gy > 0:
                axis = 0 if gx <= gy else 1                                # corner: closing either gap alone keeps it out; the smaller gap is the tighter one
            else:
                axis = 1 if gx <= 0 else 0
            g, lo_side = (gy, y <= ylo) if axis == 1 else (gx, x <= xlo)
            g = max(float(g), 0.0); s = 1.0 if lo_side else -1.0
            if g < A[i, axis]:
                c[i, axis] = s * (g - A[i, axis]) / 2; a[i, axis] = (g + A[i, axis]) / 2; restricted += 1
    om = 2 * np.pi / (MESH_FPS * T)
    G = dict(home=pts, ringed=ringed, keep=keep, alive=alive, c=c, a=a, om=om, ph=ph, A=A)
    info = dict(nodes=n_all - len(dropped), links=len(keep), links_cut=len(edges) - len(keep), ringed=sum(1 for i in range(n_all) if ringed[i] and i not in dropped),
                moved=len(moved), dropped=len(dropped), bands=list(keep_out),
                longest_link=round(max(float(np.hypot(*(pts[i] - pts[j]))) for i, j in keep), 1), one_sided_nodes=restricted, fitted_nodes=fitted)
    info['xy'] = [(round(float(pts[i][0]), 1), round(float(pts[i][1]), 1), ringed[i]) for i in range(n_all) if alive[i]]
    return G, info


def mesh_pos(f):
    """Node positions (n_all, 2) at frame f: home + c + a sin(om f + phase). A function of f alone (no state, no restart at a cut); home when the motion is off."""
    G = MESH
    if not MESH_MOTION:
        return G['home'].copy()
    return G['home'] + G['c'] + G['a'] * np.sin(G['om'] * float(f) + G['ph'])


def set_pattern(name, motion=True):                    # motion: see motion_params; False freezes the mesh
    """Select the field pattern (PATTERNS); None = DEFAULT_PATTERN on the chu-muc field, the dots on field dac and layout hien-tai (they exist only to
    reproduce earlier approved files). `motion` False keeps the mesh at its home positions. Called by configure() after set_layout() and set_field()."""
    global PATTERN, COVER, MESH_INFO, MESH, MESH_MOTION
    name = name or (DEFAULT_PATTERN if FIELD == DEFAULT_FIELD else 'cham')
    if name not in PATTERNS:
        raise SystemExit(f'pattern "{name}" is not one of {sorted(PATTERNS)}')
    PATTERN, MESH_INFO, MESH, MESH_MOTION = name, {}, None, (motion is not False)
    if name == 'cham':
        COVER = DOT
    else:
        COVER = None
        MESH, MESH_INFO = mesh_geometry(mesh_keep_out(), True if motion is False else motion); MESH_NODES[:] = MESH_INFO.pop('xy')
    _SKIN.clear()


def mesh_dm(level):
    """The vertical envelope of the pattern's white (0..1) for an opacity level, length H."""
    if level == 'CARD':
        return np.interp(YS, [0, 900, 1920], [.25, .9, .6])
    return np.interp(YS, DM_STOPS, [0, 0, .9, .5])


def skin(level):
    if level in _SKIN:
        return _SKIN[level]
    a = np.interp(YS, [s[0] for s in ALPHA_STOPS[level]], [s[1] for s in ALPHA_STOPS[level]])
    dm = mesh_dm(level)
    k = (COVER * dm[:, None])[..., None] if COVER is not None else np.zeros((H, W, 1))     # the mesh adds its own white per frame (dung-video-gpu.apply_skin_gpu)
    crows = C_ROWS if (FIELD_C_ROWS is None or level == 'CARD') else FIELD_C_ROWS
    rgb = crows[:, None, :] * (1 - k) + 255.0 * k
    A = np.repeat(a[:, None], W, axis=1)
    if level != 'CARD':                                               # top veil, #F0446E .40 -> 0 at y 280
        va = np.clip(VEIL * (1 - YS / 280.0), 0, 1)
        vcol = np.array(C_STOPS[0][1], float)
        rgb = np.where(va[:, None, None] > 0, vcol[None, None, :], rgb)
        A = A + va[:, None]
    _SKIN[level] = (rgb, A)
    return _SKIN[level]


# ================= brand marks =================
def raster(svg, h, name):
    out = KH / f'{name}-{h}.png'
    if not out.exists():
        src = find_asset(MARKS, svg)
        if src is None:
            raise FileNotFoundError(f'brand mark {svg} not found in {[str(m) for m in MARKS]}')
        subprocess.run(['magick', '-background', 'none', '-density', '600', str(src), '-resize', f'x{h}', f'PNG32:{out}'], check=True)
    return Image.open(out).convert('RGBA')


def rr(w, h, r, fill=255):
    m = Image.new('L', (w, h), 0); ImageDraw.Draw(m).rounded_rectangle((0, 0, w - 1, h - 1), radius=r, fill=fill)
    return m


def glow(canvas, box, r, col, alpha, sigma, off=(0, 0), grow=0):
    l = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(l).rounded_rectangle((box[0] - grow + off[0], box[1] - grow + off[1], box[2] + grow + off[0], box[3] + grow + off[1]), radius=r + grow, fill=col + (int(255 * alpha),))
    canvas.alpha_composite(l.filter(ImageFilter.GaussianBlur(sigma)) if sigma > 0 else l)


def wordmark_pill():
    """76 px high: 135deg plum->B4234D, 3 px white 55% border, 8 px ring at 10%, drop shadow and coral glow, white wordmark."""
    wm = raster('halcyon-mono-white.svg', 44, 'wordmark')
    h, pad = 76, 70
    w = wm.width + 2 * 32
    cv = Image.new('RGBA', (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0)); box = (pad, pad, pad + w, pad + h)
    glow(cv, box, 38, INK, .40, 17, off=(0, 14)); glow(cv, box, 38, CORAL, .45, 20)
    glow(cv, box, 38, (255, 255, 255), .10, 0, grow=8)
    cv.paste((255, 255, 255, 140), (pad, pad), rr(w, h, 38))
    iw, ih = w - 6, h - 6
    gx, gy = np.meshgrid(np.linspace(0, 1, iw), np.linspace(0, 1, ih))
    t = ((gx * iw + gy * ih) / (iw + ih))[..., None]
    c0, c1 = np.array(PLUM, float), np.array((180, 35, 77), float)
    g = Image.fromarray((c0 * (1 - t) + c1 * t).astype(np.uint8)).convert('RGBA')
    cv.paste(g, (pad + 3, pad + 3), rr(iw, ih, 35))
    cv.alpha_composite(wm, (pad + 32, pad + (h - wm.height) // 2))
    return cv, pad, w, h


def topright_pill():
    """hco.news, Be Vietnam Pro SemiBold 32 px (+0.6 px tracking), white on opaque plum, pill 60 px high, right edge x TOP_R (960), top y ROW_Y (288)."""
    f = font(BVP_SB, 32); txt = 'hco.news'; track = 0.6
    tw = sum(f.getlength(c) for c in txt) + track * (len(txt) - 1)
    h, pad = 60, 20; w = int(round(tw)) + 52
    cv = Image.new('RGBA', (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    glow(cv, (pad, pad, pad + w, pad + h), 30, INK, .22, 2.5, off=(0, 3))
    cv.paste((255, 255, 255, 255), (pad, pad), rr(w, h, 30))
    cv.paste(PLUM + (255,), (pad + 3, pad + 3), rr(w - 6, h - 6, 27))
    xh = -f.getbbox('x', anchor='ls')[1]; base = pad + h / 2 + xh / 2
    d = ImageDraw.Draw(cv); x = pad + (w - tw) / 2
    for c in txt:
        d.text((x, base), c, font=f, fill=(255, 255, 255, 255), anchor='ls'); x += f.getlength(c) + track
    return cv, pad, w, h


def check_safe(rgba, where):
    """Safe-frame gate. rgba: (H, W, 4) uint8 array or PIL RGBA image. Pixels with alpha > 200 (text, pill and chip bodies, bars; shadows and
    glows stay below 200) must lie inside x SAFE_L-SAFE_R, y SAFE_TOP-SAFE_BOT, and x <= SAFE_R_COL from row COL_Y down. Raises with the offending bbox."""
    a = np.asarray(rgba)
    if a.ndim != 3 or a.shape[2] != 4 or a.shape[:2] != (H, W):
        raise SystemExit(f'safe frame: {where}: expected a {W}x{H} RGBA layer, got shape {a.shape}')
    solid = a[..., 3] > 200
    ys, xs = np.nonzero(solid)
    bad = (xs < SAFE_L) | (xs > SAFE_R) | (ys < SAFE_TOP) | (ys >= SAFE_BOT) | ((ys >= COL_Y) & (xs > SAFE_R_COL))
    if bad.any():
        bx, by = xs[bad], ys[bad]
        raise SystemExit(f'safe frame: {where}: {int(bad.sum())} solid px outside x {SAFE_L}-{SAFE_R} (x <= {SAFE_R_COL} from y {COL_Y}), y {SAFE_TOP}-{SAFE_BOT - 1}; '
                         f'offending bbox x {int(bx.min())}-{int(bx.max())}, y {int(by.min())}-{int(by.max())}')


def check_pic(where, x0, x1, s_y, level, wmax=None):
    """Picture gate: the drawn picture (x0 to x1) lies inside x PIC_X0-(PIC_X0+PIC_W) and its focus S (frame y a, b) inside WIN[level]."""
    wm = PIC_W if wmax is None else wmax
    if x0 < PIC_X0 or x1 > PIC_X0 + wm:
        raise SystemExit(f'safe frame: {where}: picture spans x {x0}-{x1}, outside x {PIC_X0}-{PIC_X0 + wm}')
    lo, hi = WIN[level]
    if s_y[0] < lo or s_y[1] > hi:
        raise SystemExit(f'safe frame: {where}: focus S spans frame y {s_y[0]}-{s_y[1]}, outside the {level} window y {lo}-{hi}')


PILL_GATE = 'refuse'


def check_pill(where, frame):
    """Layout thu-gon-2 only (the picture window starts at y 244, above the "hco.news" pill): the picture under the pill (x TOP_R-200..TOP_R+10, y ROW_Y-10..ROW_Y+70)
    must be background only, no pixel differing from its right or lower neighbour by more than 12 levels, so the pill is read against flat colour and never
    covers a letter. Other layouts: no test."""
    if LAYOUT != 'thu-gon-2':
        return
    a = np.asarray(frame).astype(int)[PILL_Y - 10:PILL_Y + 70, TOP_R - 200:TOP_R + 10]
    d = max(int(np.abs(np.diff(a, axis=1)).max()), int(np.abs(np.diff(a, axis=0)).max()))
    if d > 12 and PILL_GATE == 'print':               # spec key pill_gate: print (a working copy that builds every beat of a video to look at only the ones it is about)
        print(f'pill: {where}: picture under the hco.news pill is not flat ({d} levels); not refused (pill_gate print)', flush=True)
        return
    if d > 12:
        raise SystemExit(f'safe frame: {where}: the picture under the hco.news pill (x {TOP_R - 200}-{TOP_R + 10}, y {ROW_Y - 10}-{ROW_Y + 70}) is not flat '
                         f'(neighbouring pixels differ by {d} levels); move u_rows so a text line does not sit under the pill')


def put_mark(im, which, x=None, y=None):
    cv, pad, w, h = {'wm': WM_PILL, 'tr': TR_PILL}[which]
    if which == 'tr':
        x, y = TOP_R - w, PILL_Y
    im.alpha_composite(cv, (x - pad, y - pad))
    return (x, y, x + w, y + h)


# ================= text =================
def put(im, xy, s, f, fill, anchor='ls', shadow=None):
    """Text with an optional CSS-like shadow: (dy, sigma, (r,g,b,a)). Returns the ink bbox."""
    bb = ImageDraw.Draw(im).textbbox(xy, s, font=f, anchor=anchor)
    m = 60
    box = (max(0, bb[0] - m), max(0, bb[1] - m), min(W, bb[2] + m), min(H, bb[3] + m))
    if shadow:
        dy, sg, col = shadow
        l = Image.new('RGBA', (box[2] - box[0], box[3] - box[1]), (0, 0, 0, 0))
        ImageDraw.Draw(l).text((xy[0] - box[0], xy[1] - box[1] + dy), s, font=f, fill=col, anchor=anchor)
        im.alpha_composite(l.filter(ImageFilter.GaussianBlur(sg)), (box[0], box[1]))
    l = Image.new('RGBA', (box[2] - box[0], box[3] - box[1]), (0, 0, 0, 0))
    ImageDraw.Draw(l).text((xy[0] - box[0], xy[1] - box[1]), s, font=f, fill=fill, anchor=anchor)
    im.alpha_composite(l, (box[0], box[1]))
    return bb


def tcol(a=255):
    """Text colour of a picture beat: white, or ink while the builder draws a beat whose measured background is light (field chu-muc)."""
    return (INK if INK_TEXT else (255, 255, 255)) + (a,)


def tsh(shadow):
    """Ink text carries no shadow."""
    return None if INK_TEXT else shadow


def keeps_chip(chip):
    """Field chu-muc: the only chip that stays marks a screen recording as Halcyon's own illustration ("MINH HOẠ ..."); a chip that says where
    and when a capture was taken is not drawn."""
    if chip.get('line') and not chip.get('title'):          # 19/11/2026: the "MINH HOẠ" chips are gone; the factual line that says where a recording comes from stays
        return True
    return (chip.get('title') or chip.get('text') or '').upper().startswith('MINH HOẠ')


def fit_size(lines, fontname, maxw, cap, field='text'):
    for s in range(cap, 20, -1):
        f = font(fontname, s)
        if max(f.getlength(l) for l in lines) <= maxw:
            return s
    raise SystemExit(f'{field}: {lines} does not fit x {X_L}-{X_R} at any size >= 21 px')


def kicker(im, top_ink, mark_wm, text, fnt, alpha):
    """Kicker row, 76 px high, its bottom 32 px above the block's ink top. The kicker font shrinks 1 px at a time until the text ends <= X_R."""
    bottom = top_ink - 32; y0 = bottom - 76; box = None
    x_end = X_L
    if mark_wm:
        box = put_mark(im, 'wm', X_L, y0); x_end = box[2] + 26
    if text:
        s = fnt.size
        while x_end + fnt.getlength(text) > X_R:
            s -= 1
            if s < 24:
                raise SystemExit(f'kicker "{text}" does not fit x {x_end}-{X_R} at 24 px')
            fnt = ImageFont.truetype(fnt.path, s)
    bb = put(im, (x_end, y0 + 38), text, fnt, tcol(alpha), 'lm')
    return dict(row_y=(y0, bottom), pill=box, text=bb)


# ---------------- chips (top-left, y ROW_Y to ROW_Y + 60) ----------------
def chip_text_size(texts):
    """One chip size for the whole video: the largest size <= 34 at which the longest single-line chip text fits x X_L to the pill (TOP_R - pill - 20)."""
    limit = TOP_R - TR_PILL[2] - 20
    for s_ in range(34, 20, -1):
        if all(X_L + int(font(BVP_SB, s_).getlength(t)) + 52 <= limit for t in texts):
            return s_
    raise SystemExit(f'chip text does not fit x {X_L}-{limit} at 21 px: {max(texts, key=len)}')


def solid_chip(im, text):
    """Solid ink #101828, white Be Vietnam Pro SemiBold, no outline, no glow; box y ROW_Y to ROW_Y + 60."""
    f = font(BVP_SB, CHIP_S); w, h = int(round(f.getlength(text))) + 52, 60
    l = Image.new('RGBA', (w, h), (0, 0, 0, 0)); l.paste(INK + (255,), (0, 0), rr(w, h, 30)); im.alpha_composite(l, (X_L, ROW_Y))
    xh = -f.getbbox('x', anchor='ls')[1]
    ImageDraw.Draw(im).text((X_L + 26, ROW_Y + h / 2 + xh / 2), text, font=f, fill=(255, 255, 255, 255), anchor='ls')
    return dict(box=(X_L, ROW_Y, X_L + w, ROW_Y + h), size=CHIP_S)


def put_disc(im, title, line):
    """Title chip at the top left; the sentence (never shortened) is a quiet credit line (x X_L, baseline y 1124, Be Vietnam Pro Medium, white 85%)."""
    info = solid_chip(im, title) if title else dict(box=None, size=None)     # no title: the credit line alone
    for s_ in range(26, 15, -1):
        if font(BVP_M, s_).getlength(line) <= TW:
            break
    else:
        raise SystemExit(f'chip.line does not fit x {X_L}-{X_R} at 16 px: {line}')
    put(im, (X_L, CREDIT_Y), line, font(BVP_M, s_), tcol(FP.get('small_alpha', 217)), 'ls', tsh(CAP_SH))
    return info


def put_chip(im, chip):
    """chip = {"text": ...} (one chip) or {"title": ..., "line": ...} (chip plus credit line)."""
    if chip.get('line'):
        return put_disc(im, chip.get('title'), chip['line'])
    return solid_chip(im, chip['text'])


# ---------------- text stacks ----------------
def two_line(im, lines, kick_text=None, mark_wm=False, cap=124, show=(True, True), kfont=None, lines_off=False):
    """Big block of two lines ending at y 1084 (Barlow ExtraBold, largest size <= cap that fits x X_L-X_R); optional kicker row.
    lines_off (layout r3, headline 'none'): no block at all; the kicker row alone, its bottom 36 px above the subtitle's capitals."""
    if lines_off:
        k = kicker(im, CAP_TOP - 4, mark_wm, kick_text or '', kfont or font(BVP_M, 30), FP.get('small_alpha', 217))
        return dict(size=None, block=None, kicker=k, kicker_only=True)
    size = fit_size(lines, BARLOW_XB, TW, cap, 'text.lines'); f = font(BARLOW_XB, size); lh = round(size * 1.04)
    d = ImageDraw.Draw(im)
    bb = [d.textbbox((X_L, BLOCK_B - lh * (1 - i)), l, font=f, anchor='ls') for i, l in enumerate(lines)]
    top = min(b[1] for b in bb)
    for i, l in enumerate(lines):
        if show[i]:
            put(im, (X_L, BLOCK_B - lh * (1 - i)), l, f, tcol(), 'ls', tsh(BIG_SH))
    k = kicker(im, top, mark_wm, kick_text or '', kfont or font(BVP_M, 30), FP.get('small_alpha', 217)) if (kick_text or mark_wm) else None
    return dict(size=size, block=(X_L, top, max(b[2] for b in bb), BLOCK_B), kicker=k)


def stack_end(im, t, mark_wm=True):
    f1, f2 = font(BARLOW, 56), font(BARLOW_XB, 150)
    b2 = put(im, (X_L, BLOCK_B), t.get('line2', 'HCO.NEWS'), f2, tcol(), 'ls', tsh(BIG_SH))
    b1 = put(im, (X_L, b2[1] - 22), t.get('line1', 'ĐỌC ĐẦY ĐỦ:'), f1, tcol(), 'ls', tsh(BIG_SH))
    k = kicker(im, b1[1], mark_wm, t.get('kicker', 'những mẩu tin AI ngắn gọn'), font(BVP_M, 32), FP.get('small_alpha', 230))
    return dict(block=(X_L, b1[1], max(b1[2], b2[2]), BLOCK_B), kicker=k)


def _source_line(im, text):
    return put(im, (X_L, BLOCK_B), text, font(BVP_M, 28), (255, 255, 255, FP.get('small_alpha', 217)), 'ls', BIG_SH)


def chart(im, t, nrows, foot):
    """Row chart (CARD): name left and value right on a 56 / 110 px baseline, a bar under each row on a 22% track, x X_L-X_R.
    Bars are proportional to `bars` with `bar_full` as the full TW px."""
    rows = t['rows']; fn = font(BARLOW, 56)
    d = ImageDraw.Draw(im); base0, pitch = CH_BASE0, 170
    full = float(t['bar_full'])
    sizes = []
    for r in rows:                                   # value size: 110 px, smaller only when name + value would not fit the row
        for s in range(110, 59, -1):
            if fn.getlength(r['name']) + 40 + font(BARLOW_XB, s).getlength(r['value']) <= TW:
                sizes.append(s); break
        else:
            raise SystemExit(f'text.rows: "{r["name"]}" + "{r["value"]}" does not fit one row')
    for i, r in enumerate(rows):
        if i >= nrows:
            break
        by = base0 + i * pitch; bw = int(round(TW * float(r['bar']) / full))
        put(im, (X_L, by), r['name'], fn, UNSPOKEN_RGB + (255,), 'ls', BIG_SH)
        put(im, (X_R, by), r['value'], font(BARLOW_XB, sizes[i]), (255, 255, 255, 255), 'rs', BIG_SH)
        tr = Image.new('RGBA', (TW, 26), (0, 0, 0, 0)); ImageDraw.Draw(tr).rounded_rectangle((0, 0, TW - 1, 25), radius=13, fill=(255, 255, 255, 56))
        im.alpha_composite(tr, (X_L, by + 20))
        fl = Image.new('RGBA', (bw, 26), (0, 0, 0, 0)); ImageDraw.Draw(fl).rounded_rectangle((0, 0, bw - 1, 25), radius=13, fill=(255, 255, 255, 255))
        im.alpha_composite(fl, (X_L, by + 20))
    top = d.textbbox((X_L, base0), rows[0]['value'], font=font(BARLOW_XB, sizes[0]), anchor='ls')[1]
    k = kicker(im, top, False, t['kicker'], font(BVP_SB, 28), FP.get('small_alpha', 230))
    nb = _source_line(im, t['source']) if t.get('source') else None
    if t.get('note') and foot:
        put(im, (X_L, NOTE_Y), t['note'], font(BVP_M, 30), (255, 255, 255, FP.get('small_alpha', 230)), 'ls', BIG_SH)
    return dict(kicker=k, rows=nrows, source=nb, content=nrows > 0)   # content: whether any row was drawn in this state


def number_card(im, t, nrows):
    """Number card (CARD): kicker row, a big number line, a second line that may cut in, optional source line. Invented layout, same type
    family, colours and shadow as the chart: line 1 Barlow ExtraBold <= 250 px white at baseline 780, line 2 <= 110 px #FFE4EA at baseline 930."""
    s1 = fit_size([t['line1']], BARLOW_XB, TW, 250, 'text.line1'); s2 = fit_size([t['line2']], BARLOW_XB, TW, 110, 'text.line2')
    b1 = put(im, (X_L, NUM_Y1), t['line1'], font(BARLOW_XB, s1), (255, 255, 255, 255), 'ls', BIG_SH)
    if nrows >= 1:
        put(im, (X_L, NUM_Y2), t['line2'], font(BARLOW_XB, s2), UNSPOKEN_RGB + (255,), 'ls', BIG_SH)
    k = kicker(im, b1[1], False, t['kicker'], font(BVP_SB, 28), FP.get('small_alpha', 230))
    if t.get('source'):
        _source_line(im, t['source'])
    return dict(kicker=k, sizes=(s1, s2))


def list_card(im, t, nrows):
    """List card (CARD): kicker row, a title, then rows that cut in one by one, with no track behind them. Invented layout:
    title Barlow Bold <= 72 px #FFE4EA at baseline 590; rows Barlow ExtraBold <= 110 px white at baselines 740, 890, 1040 (pitch 150)."""
    ts = fit_size([t['title']], BARLOW, TW, 72, 'text.title')
    tb = put(im, (X_L, LIST_T), t['title'], font(BARLOW, ts), UNSPOKEN_RGB + (255,), 'ls', BIG_SH)
    for i, r in enumerate(t['rows']):
        if i >= nrows:
            break
        by = LIST_R0 + i * 150
        s = fit_size([r], BARLOW_XB, TW, 110, f'text.rows[{i}]')
        put(im, (X_L, by), r, font(BARLOW_XB, s), (255, 255, 255, 255), 'ls', BIG_SH)
    k = kicker(im, tb[1], False, t['kicker'], font(BVP_SB, 28), FP.get('small_alpha', 230))
    if t.get('source'):
        _source_line(im, t['source'])
    return dict(kicker=k)


def n_states(t):
    """Number of different drawings of a text element = reveals + 1; `cuts` lists one time per reveal."""
    return len(t.get('cuts', [])) + 1


def draw_text(im, t, state, mark_wm):
    """Draw text element t as it stands after `state` reveals (0 = as the beat opens)."""
    kind = t['kind']
    if kind == 'block':
        show = (True, state >= 1) if t.get('cuts') else (True, True)
        return two_line(im, t['lines'], t.get('kicker'), mark_wm, t.get('cap', 124), show, font(BVP_M, t.get('kicker_size', 30)), bool(t.get('lines_off')))
    if kind == 'end':
        return stack_end(im, t, mark_wm)
    if kind == 'chart':
        return chart(im, t, state, state > len(t['rows']))
    if kind == 'number':
        return number_card(im, t, state)
    if kind == 'list':
        return list_card(im, t, state)
    raise SystemExit(f'text.kind: unknown "{kind}" (block, end, chart, number, list)')


# ================= pictures =================
INK_MARGIN = 85          # luminance levels from the page's own background that make a pixel text (255 - 170 on a white page)


def ink_mask(img, y0=0, y1=None, x0=60, x1=1110):
    """The one definition of ink: a pixel whose luminance differs from the page background (the most common luminance of the whole capture)
    by more than INK_MARGIN. Works on a light page and on a dark one."""
    g = np.asarray(img.convert('L'))
    bg = int(np.bincount(g.ravel(), minlength=256).argmax())
    return np.abs(g.astype(int)[y0:y1, x0:x1] - bg) > INK_MARGIN


def ink_bands(img, y0, y1, x0=60, x1=1110, minpx=2):
    ink = ink_mask(img, y0, y1, x0, x1).sum(axis=1) >= minpx
    bands, s = [], None
    for i, v in enumerate(ink):
        if v and s is None: s = i
        if not v and s is not None:
            if i - s >= 10: bands.append((y0 + s, y0 + i))
            s = None
    if s is not None: bands.append((y0 + s, y1))
    return bands


def article_pic(img, ra, rb, x0, x1, k, centre, pad=10, u_rows=None):
    """U = the S rows (plus a pad, or u_rows) of the capture, scaled to fill the frame width; everything else is the paper colour,
    extended from the flat edge row. S is centred on `centre`."""
    sa, sb = ra, rb
    y_top = centre - (sb - sa) * k / 2
    y0 = sa - y_top / k
    ua, ub = (sa - pad, sb + pad) if u_rows is None else u_rows
    crop = img.crop((x0, ua, x1, ub)).convert('RGB')
    row = np.asarray(crop)[0].reshape(-1, 3)
    paper = mode_colour(row[None, :, :]); std = float(row.std(axis=0).max())
    fr = Image.new('RGB', (W, H), paper)
    cs = crop.resize((round((x1 - x0) * k), round((ub - ua) * k)), Image.LANCZOS)
    px = PIC_X0 if (cs.width < PIC_W or PIC_W < 886) else round((W - cs.width) / 2)    # thu-gon-r (PIC_W 763): left edge, clear of the button column   # a capture narrower than the picture area sits on its left edge, so its text meets the column
    fr.paste(cs, (px, round((ua - y0) * k)))
    return fr, y0, dict(paper=paper, edge_std=round(std, 2), px=px, x_range=[px, px + cs.width])


def check_shown(where, img, ua, ub, y0, k, level):
    """Strict layouts: the capture rows ua-ub a picture beat shows must (1) start inside its window and end above the fade, in frame rows
    ((row - y0) * k), and (2) begin and end between two text lines, never through one. A line of the capture straddling ua or ub, or any ink in the
    two rows next to the cut, is refused, so nothing readable or half-readable sits under the fade."""
    lo, hi = WIN[level]; fade = FADE_AT[level]
    top, bot = (ua - y0) * k, (ub - y0) * k
    if top < lo - 0.5 or bot > fade + 0.5:
        raise SystemExit(f'safe frame: {where}: shown rows {ua}-{ub} of the capture fall on frame y {top:.0f}-{bot:.0f}; the {level} picture must lie inside '
                         f'y {lo}-{fade} (window to the first fade row). Pick fewer lines')
    ink = ink_mask(img, 0, None, 60, 1110)
    for name, r in (('first', ua), ('last', ub - 1)):
        if r < 0 or r >= ink.shape[0]:
            raise SystemExit(f'safe frame: {where}: shown row {r} is outside the capture (height {ink.shape[0]})')
        lo_r, hi_r = (r, r + 2) if name == 'first' else (r - 1, r + 1)
        if ink[max(0, lo_r):hi_r].any():
            raise SystemExit(f'safe frame: {where}: the {name} shown row {r} has ink beside it, so the picture would cut through a line; '
                             f'move u_rows to a gap between two lines')
    for b0, b1 in ink_bands(img, 0, img.height):
        for r, name in ((ua, 'first'), (ub, 'last')):
            if b0 < r < b1:
                raise SystemExit(f'safe frame: {where}: the {name} shown row {r} cuts through the text line at rows {b0}-{b1}; move u_rows to a gap between two lines')


def blank_rows(imgs):
    """Rows of a 390x844 recording that hold only background in every sampled frame: no pixel differs from its right-hand neighbour by more than
    12 levels in any channel (text, icons and the edge of a bubble or input box all do; a soft background gradient does not)."""
    ok = np.ones(844, bool)
    for im in imgs:
        a = np.asarray(im.convert('RGB')).astype(int)
        ok &= np.abs(np.diff(a, axis=1)).max(axis=(1, 2)) <= 12
    return ok


def rec_cut(where, imgs, s_bottom, hi):
    """Strict layouts: the source row from which a recording continues as its own background only (its last row, repeated downwards): the lowest row c <= hi (the first row the fade
    touches, in source rows) such that rows c-4..c are blank in every sampled frame, and c >= s_bottom so the focus S stays whole."""
    ok = blank_rows(imgs)
    hi = min(int(hi), 843)
    for c in range(hi, max(int(s_bottom), 3) - 1, -1):
        if ok[c - 4:c + 1].all():
            return c
    raise SystemExit(f'safe frame: {where}: no flat background row between the focus bottom (source row {int(s_bottom)}) and the first fade row ({hi}), '
                     f'so the recording cannot end on a line boundary; show a shorter part of the screen or give the beat another shot')


def rec_top(where, imgs, top_src, s_top):
    """Strict layouts, the mirror of rec_cut: the source row where a recording's picture starts: the first row c >= top_src (the top of what the window would show) such that
    rows c..c+4 are blank in every sampled frame, and c <= s_top so the focus S stays whole. Above it the picture continues as its own background only."""
    ok = blank_rows(imgs)
    for c in range(max(int(top_src), 0), min(int(s_top), 839) + 1):
        if ok[c:c + 5].all():
            return c
    raise SystemExit(f'safe frame: {where}: no flat background row between the top of the window (source row {int(top_src)}) and the focus top (source row {int(s_top)}), '
                     f'so the recording cannot start on a line boundary; show a shorter part of the screen or give the beat another shot')


def shift_rows(arr, dy):
    """Move an (H, W, 4) layer down by dy px (up when negative), filling with transparent."""
    out = np.zeros_like(arr)
    if dy >= 0:
        out[dy:] = arr[:H - dy]
    else:
        out[:H + dy] = arr[-dy:]
    return out


def card_shift(t, mark_wm):
    """Strict layouts: how far (px, down positive) a picture-less beat's text block moves so that its ink sits centred between the chip row
    (bottom y ROW_Y + 60) and the top of the caption capitals. Measured on the fully revealed state, so one shift serves every state of the beat
    and nothing already shown moves when a row cuts in."""
    im = Image.new('RGBA', (W, H), (0, 0, 0, 0)); draw_text(im, t, n_states(t) - 1, mark_wm)
    rows = np.nonzero((np.asarray(im)[..., 3] > 200).any(axis=1))[0]
    return round((ROW_Y + 60 + CAP_TOP) / 2 - (int(rows.min()) + int(rows.max()) + 1) / 2)


def cap_frame(webm, t, cache):
    """One source frame of a recording at time t (CPU ffmpeg, geometry measurement only), cached as PNG."""
    p = Path(cache) / f'{Path(webm).stem}-{int(round(t * 1000)):06d}.png'
    if not p.exists():
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{t:.3f}', '-i', str(webm), '-frames:v', '1', str(p)], check=True)
    return Image.open(p).convert('RGB')


def typed_bbox(img):
    a = np.asarray(img).astype(int)[640:800, 30:300]
    m = (a.sum(axis=2) < 330) & ((a[..., 0] - a[..., 1]) < 50)
    ys, xs = np.where(m)
    if len(ys) == 0: return None
    return (30 + int(xs.min()), 640 + int(ys.min()), 30 + int(xs.max()) + 1, 640 + int(ys.max()) + 1)


def bubble_bbox(img):
    a = np.asarray(img).astype(int)[64:320, 10:380]
    bg = np.array(mode_colour(a[None, 180:256, 0:40].reshape(1, -1, 3)))
    m = np.abs(a - bg).max(axis=2) > 6
    ys, xs = np.where(m)
    if len(ys) == 0: return None
    return (10 + int(xs.min()), 64 + int(ys.min()), 10 + int(xs.max()) + 1, 64 + int(ys.max()) + 1)


def union(boxes):
    boxes = [b for b in boxes if b]
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


# ================= captions =================
def make_norm(aliases):
    def norm(s):
        s = s.lower().strip(',.:;?!“”"%*')
        return aliases.get(s, aliases.get(s.replace('.', ''), s.replace('.', '')))
    return norm


def cap_width(T):
    return font(BARLOW, CAP_SIZE).getlength(T.upper())


def build_caps(pieces, words, aliases, lead, total_s):
    """One unit per caption piece, starting at its first word (Whisper words, minus lead); split again if wider than x X_L-X_R;
    a unit under 18 frames (0.6 s) is joined to a neighbour when the pair still fits. Returns [(start, end, TEXT)], notes."""
    norm = make_norm(aliases); ptr = 0; units = []; notes = []
    for p in pieces:
        key = norm(p.split()[0])
        for i in range(ptr, len(words)):
            if norm(words[i]['w']) == key:
                units.append([words[i]['s'] - lead, p]); ptr = i + 1; break
        else:
            raise SystemExit(f'captions: first word of "{p}" not found in the timing file after word {ptr}')
    units[0][0] = 0.0
    out = [[s, units[i + 1][0] if i + 1 < len(units) else total_s, p] for i, (s, p) in enumerate(units)]
    res = []
    for s, e, p in out:
        if cap_width(p) <= TW:
            res.append([s, e, p]); continue
        ws = p.split(); best = None
        for k in range(1, len(ws)):
            a, b = ' '.join(ws[:k]), ' '.join(ws[k:]); m = max(cap_width(a), cap_width(b))
            if best is None or m < best[0]: best = (m, a, b)
        _, a, b = best; cut = s + (e - s) * len(a) / (len(a) + len(b))
        res += [[s, cut, a], [cut, e, b]]; notes.append(f'split "{p}" -> "{a}" / "{b}"')
    i = 0
    while i < len(res):
        s, e, p = res[i]
        if e - s < 0.6 and i + 1 < len(res):
            q = p + ' ' + res[i + 1][2]
            if cap_width(q) <= TW:
                res[i:i + 2] = [[s, res[i + 1][1], q]]; notes.append(f'joined short unit "{p}" ({e - s:.2f}s)'); continue
        i += 1
    return [(s, e, p.upper()) for s, e, p in res], notes


# ================= phone previews (grey = where an app draws its own interface) =================
def phone_preview(im, case):
    """case 'fb': measured Facebook Reels on a 15 Pro Max, columns CROP_FB..W-CROP_FB, with its measured icon shapes in 60% grey.
    case 'xau-nhat': the upper-bound crop CROP_MAX..W-CROP_MAX, with 60% grey over y < SAFE_TOP, y >= SAFE_BOT and x >= COL_X from COL_Y down.
    Readable matter under grey is a defect."""
    im = im.convert('RGBA'); o = Image.new('RGBA', (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(o); g = (110, 110, 110, 153)
    if case == 'fb':
        d.rectangle((0, 0, W, 133), fill=g)                                             # status band
        d.rounded_rectangle((72, 171, 153, 254), radius=40, fill=g)                      # back arrow
        d.rounded_rectangle((846, 166, 995, 254), radius=44, fill=g)                     # search + menu
        for y in (1278, 1393, 1508, 1623, 1738):                                         # five rail icons between y 1278 and 1840
            d.rounded_rectangle((930, y, 989, y + 100), radius=28, fill=g)
        d.rectangle((86, 1744, 779, 1883), fill=g)                                       # page name and caption
        c = CROP_FB
    elif case == 'xau-nhat':
        d.rectangle((0, 0, W, SAFE_TOP - 1), fill=g); d.rectangle((0, SAFE_BOT, W, H), fill=g); d.rectangle((COL_X, COL_Y, W, SAFE_BOT), fill=g)
        c = CROP_MAX
    elif case == 'tt':                                                                   # measured TikTok on a 15 Pro Max (own profile, promotion bar), crop CROP_TT
        d.rectangle((0, 0, W, 223), fill=g)                                              # status band, search bar
        d.ellipse((907, 929, 1026, 1029), fill=g)                                        # avatar
        for y0, y1 in ((1108, 1208), (1255, 1355), (1407, 1507), (1570, 1600), (1670, 1759)):   # like, comment, save, more, sound disc
            d.rounded_rectangle((920, y0, 1012, y1), radius=30, fill=g)
        d.rectangle((26, 1535, 760, 1780), fill=g)                                       # location, name, caption (starts y 1535)
        d.rectangle((0, 1790, W, H), fill=g)                                             # promotion bar and bottom bar
        c = CROP_TT
    elif case == 'tt2':                                                                  # TikTok feed, collapsed caption, measured 19/11/2026 on another account's public video (do.md)
        k = TT2_K
        fx = lambda n: round(CROP_TT + n / k); fy = lambda n: round(n / k)             # screenshot native px (1290 x 2796) -> frame px
        d.rectangle((0, 0, W, fy(130)), fill=g)                                          # status bar
        d.rounded_rectangle((fx(46), fy(205), fx(1244), fy(302)), radius=24, fill=g)     # LIVE, the five tabs, search, the underline
        for x0, y0, x1, y1 in TT2_RAIL:
            d.rounded_rectangle((fx(x0), fy(y0), fx(x1), fy(y1)), radius=30, fill=g)
        x0, y0, x1, y1 = TT2_CAPTION
        d.rectangle((fx(x0), fy(y0), fx(x1), fy(y1)), fill=g)                            # channel name, one description line, hashtags
        c = CROP_TT
    else:
        raise SystemExit(f'phone_preview: unknown case "{case}" (fb, xau-nhat, tt, tt2)')
    im.alpha_composite(o)
    return im.convert('RGB').crop((c, 0, W - c, H))


# ================= TikTok interface preview =================
def overlay(im, caption):
    """The estimated TikTok interface (sample caption from the spec: two lines)."""
    im = im.convert('RGBA'); o = Image.new('RGBA', (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(o)
    for y in range(0, 240):
        d.line((0, y, W, y), fill=(0, 0, 0, int(110 * (1 - y / 240))))
    for y in range(1260, H):
        d.line((0, y, W, y), fill=(0, 0, 0, int(150 * (y - 1260) / (H - 1260))))
    fr, fs = font(UI, 36), font(UIB, 30)
    d.text((40, 120), 'LIVE', font=fs, fill='white')
    d.text((300, 112), 'Đang theo dõi', font=font(UIB, 38), fill=(255, 255, 255, 170))
    d.text((585, 112), 'Dành cho bạn', font=font(UIB, 38), fill='white')
    d.line((612, 168, 742, 168), fill='white', width=5)
    d.ellipse((990, 112, 1030, 152), outline='white', width=5); d.line((1026, 148, 1046, 168), fill='white', width=6)
    cxr = 1010
    d.ellipse((cxr - 48, 930, cxr + 48, 1026), fill=(240, 240, 240), outline='white', width=4)
    d.ellipse((cxr - 18, 1010, cxr + 18, 1046), fill=CORAL)
    for i, (y, cnt) in enumerate(((1110, '12,4K'), (1270, '318'), (1420, '2.051'), (1570, '960'))):
        if i == 0:
            d.polygon([(cxr - 40, y + 10), (cxr, y + 55), (cxr + 40, y + 10), (cxr + 22, y - 12), (cxr, y), (cxr - 22, y - 12)], fill='white')
        elif i == 1:
            d.ellipse((cxr - 40, y - 15, cxr + 40, y + 55), fill='white'); d.polygon([(cxr - 30, y + 40), (cxr - 40, y + 70), (cxr - 5, y + 52)], fill='white')
        elif i == 2:
            d.polygon([(cxr - 30, y - 15), (cxr + 30, y - 15), (cxr + 30, y + 60), (cxr, y + 38), (cxr - 30, y + 60)], fill='white')
        else:
            d.polygon([(cxr - 38, y + 50), (cxr - 10, y + 5), (cxr - 10, y - 15), (cxr + 40, y + 22), (cxr - 10, y + 58), (cxr - 10, y + 36)], fill='white')
        d.text((cxr, y + 95), cnt, font=fs, fill='white', anchor='mm')
    d.ellipse((cxr - 45, 1720, cxr + 45, 1810), fill=(40, 40, 40), outline=(120, 120, 120), width=10)
    d.text((40, 1560), '@hco.news', font=font(UIB, 40), fill='white')
    d.text((40, 1615), caption[0], font=fr, fill='white')
    d.text((40, 1660), caption[1], font=fr, fill='white')
    d.text((40, 1720), 'Âm thanh gốc - Halcyon', font=font(UI, 34), fill='white')
    d.rectangle((0, 1800, W, H), fill=(0, 0, 0, 255))
    for x, t in ((95, 'Trang chủ'), (310, 'Bạn bè'), (755, 'Hộp thư'), (975, 'Hồ sơ')):
        d.text((x, 1860), t, font=font(UI, 28), fill=(255, 255, 255, 230), anchor='mm')
    d.rounded_rectangle((480, 1828, 600, 1892), radius=14, fill='white'); d.text((540, 1858), '+', font=font(UIB, 50), fill='black', anchor='mm')
    im.alpha_composite(o); d = ImageDraw.Draw(im)
    for y, tag in ((SAFE_TOP, 'đỉnh an toàn 288 (Shorts)'), (SAFE_BOT, f'đáy an toàn {SAFE_BOT}')):
        for x in range(0, W, 28):
            d.line((x, y, x + 16, y), fill=(255, 230, 0), width=4)
        d.text((W // 2, y - 8), tag, font=font(UIB, 28), fill=(255, 230, 0), anchor='mb', stroke_width=3, stroke_fill='black')
    for y in range(COL_Y, SAFE_BOT, 28):
        d.line((COL_X, y, COL_X, y + 16), fill=(255, 230, 0), width=4)
    d.text((W // 2, 30), 'GIAO DIỆN TIKTOK · ƯỚC LƯỢNG', font=font(UIB, 30), fill=(255, 230, 0), anchor='mt', stroke_width=3, stroke_fill='black')
    return im.convert('RGB')
