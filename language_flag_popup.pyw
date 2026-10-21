import os
import sys
import time
import json
import math
import threading
import ctypes
from ctypes import wintypes
from queue import Queue
from collections import namedtuple

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops, ImageTk
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox
import customtkinter as ctk
from pystray import Icon, Menu, MenuItem
from PIL import Image as PILImage

# ─────────────────────────────────────────────
# PILLOW COMPAT (constants moved under Image.Resampling in Pillow 9.1+)
# ─────────────────────────────────────────────
try:
    RESAMPLE_LANCZOS = Image.Resampling.LANCZOS
    RESAMPLE_BILINEAR = Image.Resampling.BILINEAR
    RESAMPLE_BICUBIC = Image.Resampling.BICUBIC
except AttributeError:                      # very old Pillow
    RESAMPLE_LANCZOS = Image.LANCZOS
    RESAMPLE_BILINEAR = Image.BILINEAR
    RESAMPLE_BICUBIC = Image.BICUBIC

# ─────────────────────────────────────────────
# DPI AWARENESS  (must run before any window is created so that screeninfo,
# tkinter and the Win32 layered windows all agree on physical pixels)
# ─────────────────────────────────────────────
def _enable_dpi_awareness():
    try:
        # Per-Monitor-V2 (Windows 10 1703+)
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # PROCESS_PER_MONITOR_DPI_AWARE
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

_enable_dpi_awareness()


# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

IMAGE_DIR = os.path.join(BASE_DIR, "images")

if getattr(sys, 'frozen', False):
    CONFIG_DIR = os.path.join(os.environ.get('LOCALAPPDATA', BASE_DIR), 'LanguagePopup')
else:
    CONFIG_DIR = BASE_DIR
CONFIG_FILE = os.path.join(CONFIG_DIR, "settings.json")
ICON_FILE = os.path.join(IMAGE_DIR, "icon.ico")

DEFAULT_LANGUAGES = [
    {'id': '0x409', 'name': 'English', 'text': 'EN', 'flag': 'usa.png', 'enabled': True},
    {'id': '0x429', 'name': 'Persian', 'text': 'FA', 'flag': 'iran.png', 'enabled': True},
]

FLAG_IMAGES = {}
LANGUAGE_TEXT = {}

ANIMATION_TYPES = {
    'genie':                 'Genie / Funnel',
    'soft_pop':              'Soft Pop',
    'float_up':              'Float Up',
    'fade':                  'Fade In / Out',
    'tada':                  'Tada (scale + wobble)',
    'slide_top':             'Slide from Top',
    'slide_bottom':          'Slide from Bottom',
    'slide_left':            'Slide from Left',
    'slide_right':           'Slide from Right',
    'drop_bounce':           'Drop with Bounce',
    'swing_up':              'Swing Up',
    'diagonal_top_left':     'Diagonal Top-Left',
    'diagonal_bottom_right': 'Diagonal Bottom-Right',
    'elastic_slide':         'Elastic Slide',
    'center_pop':            'Center Pop',
    'bounce_in':             'Bounce In',
    'elastic_rise':          'Elastic Rise',
    'spring_drop':           'Spring Drop',
    'glide_left':            'Glide from Left',
    'glide_right':           'Glide from Right',
    'wave_slide':            'Wave Slide',
    'snap_zoom':             'Snap Zoom',
}

# Animations that change scale/rotation (need a per-frame bitmap re-blit).
TRANSFORM_ANIMS = {'genie', 'soft_pop', 'tada', 'center_pop', 'snap_zoom'}

POSITION_TYPES = {
    'top_left': 'Top left', 'top_center': 'Top center', 'top_right': 'Top right',
    'center_left': 'Center left', 'center': 'Center', 'center_right': 'Center right',
    'bottom_left': 'Bottom left', 'bottom_center': 'Bottom center', 'bottom_right': 'Bottom right',
}

DEFAULT_SETTINGS = {
    'show_time': 1.0,
    'screen_width_percent': 30,
    'animation_duration': 350,
    'debug': False,
    'display_mode': 'flag',
    'languages': DEFAULT_LANGUAGES,
    'font_size': 180,
    'animation_type': 'soft_pop',
    'position_type': 'center',
    'edge_margin': 40,
    'text_color': '#FFFFFF',
    'text_bg_enabled': False,
    'text_bg_color': '#1A1A2E',
    'text_bg_opacity': 0.85,
    'text_border_color': '#E94560',
    'text_border_width': 3,
    'text_border_radius': 20,
    'text_padding_x': 60,
    'text_padding_y': 30,
    'text_font_family': 'Segoe UI',
    'text_font_weight': 'bold',
    'text_shadow': True,
    'text_shadow_color': '#000000',
    'text_shadow_offset': 4,
    'text_shadow_opacity': 0.6,
    'text_opacity': 1.0,
    'text_glow': False,
    'text_glow_color': '#FFFFFF',
    'text_glow_radius': 12,
    'flag_corner_radius': 18,
    'flag_opacity': 1.0,
    'flag_border_width': 0,
    'flag_border_color': '#FFFFFF',
    'flag_shadow': True,
    'flag_shadow_blur': 18,
    'flag_shadow_opacity': 0.35,
    'flag_text_gap': 16,
    'interface_theme': 'auto',
    'show_only_on_active_monitor': False,
}


def _normalise_lang_id(value):
    """Return a stable lower-case Windows LANGID string such as 0x409."""
    raw = str(value or '').strip().lower()
    try:
        number = int(raw, 16) if raw.startswith('0x') else int(raw)
        return hex(number & 0xffff)
    except (TypeError, ValueError):
        return raw


def _resolve_flag_path(value):
    if not value:
        return ''
    value = os.path.expandvars(os.path.expanduser(str(value)))
    if os.path.isabs(value):
        return value
    return os.path.join(IMAGE_DIR, value)


def _sanitise_languages(items):
    result, seen = [], set()
    if not isinstance(items, list):
        items = DEFAULT_LANGUAGES
    for item in items:
        if not isinstance(item, dict):
            continue
        lang_id = _normalise_lang_id(item.get('id'))
        if not lang_id or lang_id in seen:
            continue
        seen.add(lang_id)
        result.append({
            'id': lang_id,
            'name': str(item.get('name') or lang_id).strip(),
            'text': str(item.get('text') or lang_id).strip(),
            'flag': str(item.get('flag') or '').strip(),
            'enabled': bool(item.get('enabled', True)),
        })
    return result or [dict(item) for item in DEFAULT_LANGUAGES]


def _sync_language_maps(cfg):
    FLAG_IMAGES.clear()
    LANGUAGE_TEXT.clear()
    cfg['languages'] = _sanitise_languages(cfg.get('languages'))
    for item in cfg['languages']:
        if not item['enabled']:
            continue
        LANGUAGE_TEXT[item['id']] = item['text']
        path = _resolve_flag_path(item['flag'])
        if path:
            FLAG_IMAGES[item['id']] = path


def load_settings():
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                if ('screen_width_percent' in loaded
                        and isinstance(loaded['screen_width_percent'], float)
                        and loaded['screen_width_percent'] <= 1.0):
                    loaded['screen_width_percent'] = int(loaded['screen_width_percent'] * 100)
                merged = {**DEFAULT_SETTINGS, **loaded}
                merged['languages'] = _sanitise_languages(merged.get('languages'))
                return merged
    except Exception as e:
        print(f"Error loading settings: {e}")
    return DEFAULT_SETTINGS.copy()


def save_settings(new_settings):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(new_settings, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error saving settings: {e}")
        return False


settings = load_settings()
_sync_language_maps(settings)
DEBUG = settings['debug']


def debug_print(msg):
    if DEBUG:
        print(f"[DEBUG] {msg}")


def _hex_to_rgb(hex_color):
    h = (hex_color or '#000000').lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return (0, 0, 0)


# ─────────────────────────────────────────────
# WIN32 LAYER  (true per-pixel alpha via UpdateLayeredWindow)
# ─────────────────────────────────────────────
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

Monitor = namedtuple('Monitor', 'x y width height is_primary')


def get_monitors():
    """Enumerate displays through Win32, avoiding a runtime-only dependency."""
    monitors = []
    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
        ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def visit(_handle, _dc, rect_ptr, _data):
        rect = rect_ptr.contents
        monitors.append(Monitor(rect.left, rect.top, rect.right - rect.left,
                                rect.bottom - rect.top, rect.left == 0 and rect.top == 0))
        return True

    callback = callback_type(visit)
    user32.EnumDisplayMonitors(0, None, callback, 0)
    return monitors

HBITMAP = ctypes.c_void_p
HGDIOBJ = ctypes.c_void_p

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
GA_ROOT = 2
ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
HWND_TOPMOST = ctypes.c_void_p(-1)
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_byte), ("BlendFlags", ctypes.c_byte),
                ("SourceConstantAlpha", ctypes.c_byte), ("AlphaFormat", ctypes.c_byte)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


# Explicit signatures — critical on 64-bit so HWND/HDC/HBITMAP are not truncated.
user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = [wintypes.HWND]
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.GetWindowLongW.restype = wintypes.LONG
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowLongW.restype = wintypes.LONG
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
user32.GetAncestor.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.UpdateLayeredWindow.restype = wintypes.BOOL
user32.UpdateLayeredWindow.argtypes = [
    wintypes.HWND, wintypes.HDC, ctypes.POINTER(POINT), ctypes.POINTER(SIZE),
    wintypes.HDC, ctypes.POINTER(POINT), wintypes.DWORD,
    ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD]

gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateDIBSection.restype = HBITMAP
gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
                                   ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, wintypes.DWORD]
gdi32.SelectObject.restype = HGDIOBJ
gdi32.SelectObject.argtypes = [wintypes.HDC, HGDIOBJ]
gdi32.DeleteObject.argtypes = [HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]


def _root_hwnd(widget_id):
    try:
        return user32.GetAncestor(widget_id, GA_ROOT) or widget_id
    except Exception:
        return widget_id


def _make_window_layered(hwnd):
    ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(
        hwnd, GWL_EXSTYLE,
        ex | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
    try:
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
    except Exception:
        pass


def _premultiplied_bgra(img):
    """PIL RGBA -> premultiplied BGRA bytes (what UpdateLayeredWindow expects)."""
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    r, g, b, a = img.split()
    r = ImageChops.multiply(r, a)
    g = ImageChops.multiply(g, a)
    b = ImageChops.multiply(b, a)
    return Image.merge('RGBA', (b, g, r, a)).tobytes('raw', 'RGBA')


def _genie_frame(source, canvas_size, progress):
    """Return one frame of the curved bottom-centre funnel transition."""
    progress = max(0.0, min(1.0, progress))
    cw, ch = canvas_size
    canvas = Image.new('RGBA', canvas_size, (0, 0, 0, 0))
    if progress <= 0.002:
        return canvas
    bands = max(18, min(42, source.height // 10))
    final_left = (cw - source.width) // 2
    final_top = (ch - source.height) // 2
    funnel_y = final_top + source.height
    target_h = max(2, int(source.height * (0.06 + 0.94 * progress)))
    target_top = funnel_y - target_h
    for band in range(bands):
        sy0 = int(source.height * band / bands)
        sy1 = max(sy0 + 1, int(source.height * (band + 1) / bands))
        v = (band + 0.5) / bands
        width_factor = progress ** (0.42 + 1.55 * (v ** 1.7))
        width_factor *= 0.96 + 0.04 * progress
        dest_w = max(2, int(source.width * width_factor))
        dy0 = target_top + int(target_h * band / bands)
        dy1 = target_top + max(1, int(target_h * (band + 1) / bands))
        strip = source.crop((0, sy0, source.width, sy1)).resize(
            (dest_w, max(1, dy1 - dy0)), RESAMPLE_BILINEAR)
        dx = final_left + (source.width - dest_w) // 2
        canvas.alpha_composite(strip, (dx, dy0))
    return canvas


class LayeredPopup:
    """A click-through, top-most window painted from a 32-bit RGBA bitmap."""

    def __init__(self, root, base_img, transform_margin=0):
        self.base = base_img
        bw, bh = base_img.size
        self.cw = bw + transform_margin * 2
        self.ch = bh + transform_margin * 2
        self._last_blit_key = None
        self._dead = False

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.geometry(f"{self.cw}x{self.ch}+-12000+-12000")
        self.win.update_idletasks()

        self.hwnd = _root_hwnd(self.win.winfo_id())
        _make_window_layered(self.hwnd)

        self.hdc_screen = user32.GetDC(None)
        self.hdc_mem = gdi32.CreateCompatibleDC(self.hdc_screen)
        self.hbmp, self.bits = self._create_dib(self.cw, self.ch)
        self.old_obj = gdi32.SelectObject(self.hdc_mem, self.hbmp)

        self.blit(1.0, 0.0)
        self.update(-12000, -12000, 0.0)

    def _create_dib(self, w, h):
        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = w
        bmi.biHeight = -h          # negative => top-down, matches PIL row order
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0      # BI_RGB
        bits = ctypes.c_void_p()
        hbmp = gdi32.CreateDIBSection(self.hdc_mem, ctypes.byref(bmi), 0,
                                      ctypes.byref(bits), None, 0)
        return hbmp, bits

    def blit(self, scale, angle):
        """Render the (optionally scaled/rotated) base image into the DIB buffer."""
        key = (round(scale, 3), round(angle, 2))
        if key == self._last_blit_key:
            return
        self._last_blit_key = key

        im = self.base
        if scale != 1.0:
            nw = max(1, int(round(self.base.width * scale)))
            nh = max(1, int(round(self.base.height * scale)))
            im = self.base.resize((nw, nh), RESAMPLE_BILINEAR)
        if angle:
            im = im.rotate(angle, resample=RESAMPLE_BILINEAR, expand=True)

        if im.size == (self.cw, self.ch):
            canvas = im
        else:
            canvas = Image.new('RGBA', (self.cw, self.ch), (0, 0, 0, 0))
            px = (self.cw - im.width) // 2
            py = (self.ch - im.height) // 2
            canvas.alpha_composite(im, (px, py))

        raw = _premultiplied_bgra(canvas)
        ctypes.memmove(self.bits, raw, len(raw))

    def blit_genie(self, progress):
        """Warp the bitmap into a bottom-centre funnel, inspired by the macOS Genie effect."""
        progress = max(0.0, min(1.0, progress))
        key = ('genie', round(progress, 3))
        if key == self._last_blit_key:
            return
        self._last_blit_key = key

        canvas = _genie_frame(self.base, (self.cw, self.ch), progress)
        raw = _premultiplied_bgra(canvas)
        ctypes.memmove(self.bits, raw, len(raw))

    def update(self, center_x, center_y, alpha):
        if self._dead:
            return
        x = int(center_x - self.cw // 2)
        y = int(center_y - self.ch // 2)
        pt_dst = POINT(x, y)
        size = SIZE(self.cw, self.ch)
        pt_src = POINT(0, 0)
        a = int(max(0.0, min(1.0, alpha)) * 255)
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, a, AC_SRC_ALPHA)
        try:
            user32.UpdateLayeredWindow(
                self.hwnd, self.hdc_screen, ctypes.byref(pt_dst), ctypes.byref(size),
                self.hdc_mem, ctypes.byref(pt_src), 0, ctypes.byref(blend), ULW_ALPHA)
        except Exception:
            pass

    def destroy(self):
        if self._dead:
            return
        self._dead = True
        try:
            gdi32.SelectObject(self.hdc_mem, self.old_obj)
        except Exception:
            pass
        for fn, arg in ((gdi32.DeleteObject, self.hbmp),
                        (gdi32.DeleteDC, self.hdc_mem)):
            try:
                fn(arg)
            except Exception:
                pass
        try:
            user32.ReleaseDC(None, self.hdc_screen)
        except Exception:
            pass
        try:
            self.win.destroy()
        except Exception:
            pass


# ─────────────────────────────────────────────
# WIN API  (foreground language / taskbar icon)
# ─────────────────────────────────────────────
def get_foreground_window_info():
    try:
        hwnd = user32.GetForegroundWindow()
        thread_id = user32.GetWindowThreadProcessId(hwnd, 0)
        klid = user32.GetKeyboardLayout(thread_id)
        lang_id = hex(klid & (2 ** 16 - 1))
        return lang_id, hwnd
    except Exception as e:
        debug_print(f"get_foreground_window_info: {e}")
        return None, None


def _set_taskbar_icon(hwnd, icon_path):
    try:
        IMAGE_ICON, LR_LOADFROMFILE, WM_SETICON = 1, 0x0010, 0x0080
        hicon = user32.LoadImageW(0, icon_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE)
        if hicon:
            user32.SendMessageW(hwnd, WM_SETICON, 0, hicon)
            user32.SendMessageW(hwnd, WM_SETICON, 1, hicon)
    except Exception:
        pass


# ─────────────────────────────────────────────
# FONTS
# ─────────────────────────────────────────────
_SYSTEM_FONTS = []
_FONT_FILE_MAP = {}


def _init_font_list():
    global _SYSTEM_FONTS, _FONT_FILE_MAP
    allowed = ["Segoe UI", "Arial", "Calibri", "Tahoma", "Times New Roman"]
    _SYSTEM_FONTS = sorted(allowed)
    bold = {"Segoe UI": "segoeuib.ttf", "Arial": "arialbd.ttf", "Calibri": "calibrib.ttf",
            "Tahoma": "tahomabd.ttf", "Times New Roman": "timesbd.ttf"}
    reg = {"Segoe UI": "segoeui.ttf", "Arial": "arial.ttf", "Calibri": "calibri.ttf",
           "Tahoma": "tahoma.ttf", "Times New Roman": "times.ttf"}
    for f in allowed:
        _FONT_FILE_MAP[f] = reg.get(f, f.lower() + ".ttf")
        _FONT_FILE_MAP[f + " bold"] = bold.get(f, f.lower() + "bd.ttf")


_init_font_list()


def _find_font_file(family, weight='regular'):
    win_fonts = os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts')
    key = family if weight == 'regular' else family + " bold"
    if key in _FONT_FILE_MAP:
        full = os.path.join(win_fonts, _FONT_FILE_MAP[key])
        if os.path.exists(full):
            return full
    return os.path.join(win_fonts, 'arial.ttf')


def _load_font(family, weight, size):
    try:
        return ImageFont.truetype(_find_font_file(family, weight), size)
    except Exception:
        try:
            return ImageFont.truetype(
                os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts', 'arial.ttf'), size)
        except Exception:
            return ImageFont.load_default()


PERSIAN_ARABIC_MAP = {
    'ا': (0xFE8D, 0xFE8E, 0xFE8D, 0xFE8E, False),
    'آ': (0xFE81, 0xFE82, 0xFE81, 0xFE82, False),
    'أ': (0xFE83, 0xFE84, 0xFE83, 0xFE84, False),
    'إ': (0xFE87, 0xFE88, 0xFE87, 0xFE88, False),
    'ب': (0xFE8F, 0xFE90, 0xFE91, 0xFE92, True),
    'پ': (0xFB56, 0xFB57, 0xFB58, 0xFB59, True),
    'ت': (0xFE93, 0xFE94, 0xFE95, 0xFE96, True),
    'ث': (0xFE97, 0xFE98, 0xFE99, 0xFE9A, True),
    'ج': (0xFE9B, 0xFE9C, 0xFE9D, 0xFE9E, True),
    'چ': (0xFB7A, 0xFB7B, 0xFB7C, 0xFB7D, True),
    'ح': (0xFEA1, 0xFEA2, 0xFEA3, 0xFEA4, True),
    'خ': (0xFEA5, 0xFEA6, 0xFEA7, 0xFEA8, True),
    'د': (0xFEA9, 0xFEAA, 0xFEA9, 0xFEAA, False),
    'ذ': (0xFEAB, 0xFEAC, 0xFEAB, 0xFEAC, False),
    'ر': (0xFEAD, 0xFEAE, 0xFEAD, 0xFEAE, False),
    'ز': (0xFEAF, 0xFEB0, 0xFEAF, 0xFEB0, False),
    'ژ': (0xFB8A, 0xFB8B, 0xFB8A, 0xFB8B, False),
    'س': (0xFEB1, 0xFEB2, 0xFEB3, 0xFEB4, True),
    'ش': (0xFEB5, 0xFEB6, 0xFEB7, 0xFEB8, True),
    'ص': (0xFEB9, 0xFEBA, 0xFEBB, 0xFEBC, True),
    'ض': (0xFEBD, 0xFEBE, 0xFEBF, 0xFEC0, True),
    'ط': (0xFEC1, 0xFEC2, 0xFEC3, 0xFEC4, True),
    'ظ': (0xFEC5, 0xFEC6, 0xFEC7, 0xFEC8, True),
    'ع': (0xFEC9, 0xFECA, 0xFECB, 0xFECC, True),
    'غ': (0xFECD, 0xFECE, 0xFECF, 0xFED0, True),
    'ف': (0xFED1, 0xFED2, 0xFED3, 0xFED4, True),
    'ق': (0xFED5, 0xFED6, 0xFED7, 0xFED8, True),
    'ک': (0xFB8E, 0xFB8F, 0xFB90, 0xFB91, True),
    'ك': (0xFED9, 0xFEDA, 0xFEDB, 0xFEDC, True),
    'گ': (0xFB92, 0xFB93, 0xFB94, 0xFB95, True),
    'ل': (0xFEDD, 0xFEDE, 0xFEDF, 0xFEE0, True),
    'م': (0xFEE1, 0xFEE2, 0xFEE3, 0xFEE4, True),
    'ن': (0xFEE5, 0xFEE6, 0xFEE7, 0xFEE8, True),
    'و': (0xFEEE, 0xFEEF, 0xFEEE, 0xFEEF, False),
    'ه': (0xFEE9, 0xFEEA, 0xFEEB, 0xFEEC, True),
    'ی': (0xFBFC, 0xFBFD, 0xFBFE, 0xFBFF, True),
    'ي': (0xFEEF, 0xFEF0, 0xFEF1, 0xFEF2, True),
    'ئ': (0xFE89, 0xFE8A, 0xFE8B, 0xFE8C, True),
}

def shape_persian(text):
    if not any(c in PERSIAN_ARABIC_MAP for c in text):
        return text
    chars = list(text)
    n = len(chars)
    reshaped = []
    for i in range(n):
        c = chars[i]
        if c not in PERSIAN_ARABIC_MAP:
            reshaped.append(c)
            continue
        iso, fin, ini, med, can_join = PERSIAN_ARABIC_MAP[c]
        prev_joins = False
        if i > 0 and chars[i - 1] in PERSIAN_ARABIC_MAP:
            prev_joins = PERSIAN_ARABIC_MAP[chars[i - 1]][4]
        next_joins = False
        if i < n - 1 and chars[i + 1] in PERSIAN_ARABIC_MAP:
            next_joins = True
        if prev_joins and next_joins and can_join:
            form = med
        elif prev_joins:
            form = fin
        elif next_joins and can_join:
            form = ini
        else:
            form = iso
        reshaped.append(chr(form))
    result = []
    i = 0
    while i < len(reshaped):
        if reshaped[i] in PERSIAN_ARABIC_MAP or ord(reshaped[i]) > 0xFB00:
            run = []
            while i < len(reshaped) and (reshaped[i] in PERSIAN_ARABIC_MAP or ord(reshaped[i]) > 0xFB00 or reshaped[i] in ' \t'):
                run.append(reshaped[i])
                i += 1
            result.extend(reversed(run))
        else:
            result.append(reshaped[i])
            i += 1
    return ''.join(result)


# ─────────────────────────────────────────────
# BASE IMAGE RENDERING  (cached, supersampled, real alpha)
# ─────────────────────────────────────────────
_render_cache = {}
SS = 2  # supersample factor for crisp anti-aliased edges


def _render_text_base(lang_id, cfg):
    text = LANGUAGE_TEXT.get(lang_id, '??')
    text = shape_persian(text)
    fs = max(8, int(cfg.get('font_size', 180))) * SS
    family = cfg.get('text_font_family', 'Segoe UI')
    weight = cfg.get('text_font_weight', 'bold')
    font = _load_font(family, weight, fs)

    pad_x = int(cfg.get('text_padding_x', 60)) * SS
    pad_y = int(cfg.get('text_padding_y', 30)) * SS
    bw = int(cfg.get('text_border_width', 3)) * SS
    rad = int(cfg.get('text_border_radius', 20)) * SS

    sh_on = cfg.get('text_shadow', True)
    sh_off = int(cfg.get('text_shadow_offset', 4)) * SS
    sh_op = float(cfg.get('text_shadow_opacity', 0.6))
    gl_on = cfg.get('text_glow', False)
    gl_rad = int(cfg.get('text_glow_radius', 12)) * SS

    txt_rgb = _hex_to_rgb(cfg.get('text_color', '#FFFFFF'))
    txt_op = float(cfg.get('text_opacity', 1.0))
    bg_on = cfg.get('text_bg_enabled', False)
    bg_rgb = _hex_to_rgb(cfg.get('text_bg_color', '#1A1A2E'))
    bg_op = float(cfg.get('text_bg_opacity', 0.85))
    brd_rgb = _hex_to_rgb(cfg.get('text_border_color', '#E94560'))
    sh_rgb = _hex_to_rgb(cfg.get('text_shadow_color', '#000000'))
    gl_rgb = _hex_to_rgb(cfg.get('text_glow_color', '#FFFFFF'))

    # Measure glyph box from font metrics (no throwaway window).
    x0, y0, x1, y1 = font.getbbox(text)
    tw, th = x1 - x0, y1 - y0

    extra = gl_rad + max(sh_off, 0) + bw + 8 * SS
    cw = tw + pad_x * 2 + extra * 2
    ch = th + pad_y * 2 + extra * 2

    img = Image.new('RGBA', (cw, ch), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background + border
    if bg_on:
        bx1, by1 = extra, extra
        bx2, by2 = cw - extra, ch - extra
        draw.rounded_rectangle((bx1, by1, bx2, by2), radius=rad,
                               fill=(*bg_rgb, int(255 * bg_op)))
        if bw > 0:
            half = bw // 2
            draw.rounded_rectangle((bx1 + half, by1 + half, bx2 - half, by2 - half),
                                   radius=max(0, rad - half), outline=(*brd_rgb, 255), width=bw)

    tx = (cw - tw) // 2 - x0
    ty = (ch - th) // 2 - y0

    # Glow (real soft alpha — composited a couple of times for intensity)
    if gl_on and gl_rad > 0:
        glow = Image.new('RGBA', (cw, ch), (0, 0, 0, 0))
        ImageDraw.Draw(glow).text((tx, ty), text, font=font, fill=(*gl_rgb, 255))
        glow = glow.filter(ImageFilter.GaussianBlur(gl_rad))
        img.alpha_composite(glow)
        img.alpha_composite(glow)

    # Soft drop shadow
    if sh_on and sh_off > 0:
        sh = Image.new('RGBA', (cw, ch), (0, 0, 0, 0))
        ImageDraw.Draw(sh).text((tx + sh_off, ty + sh_off), text, font=font,
                                fill=(*sh_rgb, int(255 * sh_op)))
        sh = sh.filter(ImageFilter.GaussianBlur(max(1, SS)))
        img.alpha_composite(sh)

    # Main text
    tl = Image.new('RGBA', (cw, ch), (0, 0, 0, 0))
    ImageDraw.Draw(tl).text((tx, ty), text, font=font, fill=(*txt_rgb, int(255 * txt_op)))
    img.alpha_composite(tl)

    if SS != 1:
        img = img.resize((cw // SS, ch // SS), RESAMPLE_LANCZOS)
    return img


def _render_flag_base(lang_id, cfg, monitor_w):
    path = FLAG_IMAGES.get(lang_id)
    if not path or not os.path.exists(path):
        return None
    pct = max(1, min(100, int(cfg.get('screen_width_percent', 30)))) / 100.0
    w = max(1, int(monitor_w * pct))
    try:
        im = Image.open(path).convert('RGBA')
    except Exception as e:
        debug_print(f"flag open: {e}")
        return None
    h = max(1, int(w * im.height / im.width))
    im = im.resize((w, h), RESAMPLE_LANCZOS)
    opacity = max(0.05, min(1.0, float(cfg.get('flag_opacity', 1.0))))
    radius = max(0, int(cfg.get('flag_corner_radius', 18)))
    radius = min(radius, min(w, h) // 2)
    mask = Image.new('L', (w * 2, h * 2), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w * 2 - 1, h * 2 - 1),
                                           radius=radius * 2, fill=255)
    mask = mask.resize((w, h), RESAMPLE_LANCZOS)
    r, g, b, a = im.split()
    a = ImageChops.multiply(a, mask).point(lambda px: int(px * opacity))
    im = Image.merge('RGBA', (r, g, b, a))

    border_w = max(0, int(cfg.get('flag_border_width', 0)))
    shadow_on = bool(cfg.get('flag_shadow', True))
    blur = max(0, int(cfg.get('flag_shadow_blur', 18)))
    outer = max(border_w + 2, blur * 2 if shadow_on else 0)
    if outer:
        canvas = Image.new('RGBA', (w + outer * 2, h + outer * 2), (0, 0, 0, 0))
        if shadow_on and blur:
            shadow = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
            sd = ImageDraw.Draw(shadow)
            alpha = int(255 * max(0.0, min(1.0, float(cfg.get('flag_shadow_opacity', 0.35)))))
            sd.rounded_rectangle((outer, outer, outer + w, outer + h), radius=radius,
                                 fill=(12, 18, 28, alpha))
            shadow = shadow.filter(ImageFilter.GaussianBlur(blur))
            canvas.alpha_composite(shadow)
        canvas.alpha_composite(im, (outer, outer))
        if border_w:
            ImageDraw.Draw(canvas).rounded_rectangle(
                (outer, outer, outer + w - 1, outer + h - 1), radius=radius,
                outline=(*_hex_to_rgb(cfg.get('flag_border_color', '#FFFFFF')), 255),
                width=border_w)
        im = canvas

    if cfg.get('display_mode') == 'flag_text':
        label_cfg = dict(cfg)
        label_cfg.update({'font_size': max(18, int(cfg.get('font_size', 180) * 0.34)),
                          'text_bg_enabled': False, 'text_border_width': 0,
                          'text_padding_x': 8, 'text_padding_y': 4,
                          'text_glow': False})
        label = _render_text_base(lang_id, label_cfg)
        gap = max(0, int(cfg.get('flag_text_gap', 16)))
        combo = Image.new('RGBA', (max(im.width, label.width), im.height + gap + label.height),
                          (0, 0, 0, 0))
        combo.alpha_composite(im, ((combo.width - im.width) // 2, 0))
        combo.alpha_composite(label, ((combo.width - label.width) // 2, im.height + gap))
        im = combo
    return im


_TEXT_KEYS = ('font_size', 'text_font_family', 'text_font_weight', 'text_color',
              'text_bg_enabled', 'text_bg_color', 'text_bg_opacity', 'text_border_color',
              'text_border_width', 'text_border_radius', 'text_padding_x', 'text_padding_y',
              'text_shadow', 'text_shadow_color', 'text_shadow_offset', 'text_shadow_opacity',
              'text_opacity', 'text_glow', 'text_glow_color', 'text_glow_radius')


def get_base_image(mode, lang_id, cfg, monitor_w):
    if mode == 'text':
        key = ('t', lang_id) + tuple(cfg.get(k) for k in _TEXT_KEYS)
    else:
        flag_keys = ('screen_width_percent', 'flag_corner_radius', 'flag_opacity',
                     'flag_border_width', 'flag_border_color', 'flag_shadow',
                     'flag_shadow_blur', 'flag_shadow_opacity', 'flag_text_gap')
        key = ('f', mode, lang_id, monitor_w) + tuple(cfg.get(k) for k in flag_keys)
        if mode == 'flag_text':
            key += tuple(cfg.get(k) for k in _TEXT_KEYS)
    if key in _render_cache:
        return _render_cache[key]
    img = (_render_text_base(lang_id, cfg) if mode == 'text'
           else _render_flag_base(lang_id, cfg, monitor_w))
    if img is not None:
        if len(_render_cache) > 48:
            _render_cache.clear()
        _render_cache[key] = img
    return img


# ─────────────────────────────────────────────
# MONITOR CACHE
# ─────────────────────────────────────────────
_mon_cache = {'t': 0.0, 'v': None}


def get_monitors_cached():
    now = time.time()
    if _mon_cache['v'] is None or (now - _mon_cache['t']) > 5.0:
        try:
            _mon_cache['v'] = get_monitors()
        except Exception as e:
            debug_print(f"get_monitors: {e}")
            _mon_cache['v'] = _mon_cache['v'] or []
        _mon_cache['t'] = now
    return _mon_cache['v']


def _active_monitors(monitors):
    """Return the monitor containing the foreground window centre."""
    if not monitors:
        return []
    try:
        hwnd = user32.GetForegroundWindow()
        rect = wintypes.RECT()
        if hwnd and user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            cx, cy = (rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2
            for monitor in monitors:
                if (monitor.x <= cx < monitor.x + monitor.width and
                        monitor.y <= cy < monitor.y + monitor.height):
                    return [monitor]
    except Exception:
        pass
    return [monitors[0]]


# ─────────────────────────────────────────────
# PLACEMENT
# ─────────────────────────────────────────────
def _get_placement_coords(pos_key, w, h, m_x, m_y, m_w, m_h, margin=40):
    if "left" in pos_key:
        cx = m_x + margin + w // 2
    elif "right" in pos_key:
        cx = m_x + m_w - margin - w // 2
    else:
        cx = m_x + m_w // 2
    if "top" in pos_key:
        cy = m_y + margin + h // 2
    elif "bottom" in pos_key:
        cy = m_y + m_h - margin - h // 2
    else:
        cy = m_y + m_h // 2
    return cx, cy


# ─────────────────────────────────────────────
# EASING
# ─────────────────────────────────────────────
def _eo_quint(t): return 1 - pow(1 - t, 5)
def _ei_quint(t): return t * t * t * t * t
def _eo_cubic(t): return 1 - pow(1 - t, 3)
def _eo_back(t):
    c1 = 1.70158; c3 = c1 + 1
    return 1 + c3 * pow(t - 1, 3) + c1 * pow(t - 1, 2)
def _eo_bounce(t):
    n1, d1 = 7.5625, 2.75
    if t < 1 / d1: return n1 * t * t
    if t < 2 / d1: t -= 1.5 / d1; return n1 * t * t + 0.75
    if t < 2.5 / d1: t -= 2.25 / d1; return n1 * t * t + 0.9375
    t -= 2.625 / d1; return n1 * t * t + 0.984375
def _eo_elastic(t):
    if t == 0 or t == 1: return t
    return pow(2, -10 * t) * math.sin((t * 10 - 0.75) * (2 * math.pi) / 3) + 1


# Frame contract: f(t, entering, tcx, tcy, w, h, mx, my, mw, mh)
#                   -> (center_x, center_y, scale, angle, alpha)
def _slide_from(t, entering, sx, sy, tcx, tcy, ease):
    if entering:
        p = ease(t); a = min(1.0, t * 3)
        return sx + (tcx - sx) * p, sy + (tcy - sy) * p, a
    p = _ei_quint(t); a = min(1.0, (1 - t) * 3)
    return tcx + (sx - tcx) * p, tcy + (sy - tcy) * p, a


def _f_fade(t, e, tcx, tcy, w, h, mx, my, mw, mh):
    a = _eo_quint(t) if e else 1 - _ei_quint(t)
    return tcx, tcy, 1.0, 0.0, a


def _f_soft_pop(t, e, tcx, tcy, w, h, mx, my, mw, mh):
    if e:
        p = _eo_quint(t)
        return tcx, tcy + (1 - p) * 20, 0.92 + 0.08 * p, 0.0, p
    p = _ei_quint(t)
    return tcx, tcy - p * 10, 1.0 - 0.03 * p, 0.0, 1.0 - p


def _f_float_up(t, e, tcx, tcy, w, h, mx, my, mw, mh):
    distance = min(80, max(28, h * 0.22))
    if e:
        p = _eo_quint(t)
        return tcx, tcy + distance * (1 - p), 1.0, 0.0, p
    p = _ei_quint(t)
    return tcx, tcy - distance * p, 1.0, 0.0, 1.0 - p

def _f_slide_top(t, e, tcx, tcy, w, h, mx, my, mw, mh):
    cx, cy, a = _slide_from(t, e, tcx, my - h, tcx, tcy, _eo_quint)
    return cx, cy, 1.0, 0.0, a

def _f_slide_bottom(t, e, tcx, tcy, w, h, mx, my, mw, mh):
    cx, cy, a = _slide_from(t, e, tcx, my + mh + h, tcx, tcy, _eo_quint)
    return cx, cy, 1.0, 0.0, a

def _f_slide_left(t, e, tcx, tcy, w, h, mx, my, mw, mh):
    cx, cy, a = _slide_from(t, e, mx - w, tcy, tcx, tcy, _eo_quint)
    return cx, cy, 1.0, 0.0, a

def _f_slide_right(t, e, tcx, tcy, w, h, mx, my, mw, mh):
    cx, cy, a = _slide_from(t, e, mx + mw + w, tcy, tcx, tcy, _eo_quint)
    return cx, cy, 1.0, 0.0, a

def _f_diag_tl(t, e, tcx, tcy, w, h, mx, my, mw, mh):
    cx, cy, a = _slide_from(t, e, mx - w, my - h, tcx, tcy, _eo_quint)
    return cx, cy, 1.0, 0.0, a

def _f_diag_br(t, e, tcx, tcy, w, h, mx, my, mw, mh):
    cx, cy, a = _slide_from(t, e, mx + mw + w, my + mh + h, tcx, tcy, _eo_quint)
    return cx, cy, 1.0, 0.0, a

def _f_drop_bounce(t, e, tcx, tcy, w, h, mx, my, mw, mh):
    cx, cy, a = _slide_from(t, e, tcx, my - h, tcx, tcy, _eo_bounce)
    return cx, cy, 1.0, 0.0, a

def _f_swing_up(t, e, tcx, tcy, w, h, mx, my, mw, mh):
    cx, cy, a = _slide_from(t, e, tcx, tcy + int(h * 0.8), tcx, tcy, _eo_back)
    return cx, cy, 1.0, 0.0, a

def _f_bounce_in(t, e, tcx, tcy, w, h, mx, my, mw, mh):
    cx, cy, a = _slide_from(t, e, tcx, my - h, tcx, tcy, _eo_bounce)
    return cx, cy, 1.0, 0.0, a

def _f_elastic_rise(t, e, tcx, tcy, w, h, mx, my, mw, mh):
    cx, cy, a = _slide_from(t, e, tcx, my + mh + h, tcx, tcy, _eo_elastic)
    return cx, cy, 1.0, 0.0, a

def _f_elastic_slide(t, e, tcx, tcy, w, h, mx, my, mw, mh):
    cx, cy, a = _slide_from(t, e, mx + mw + w, tcy, tcx, tcy, _eo_elastic)
    return cx, cy, 1.0, 0.0, a

def _f_spring_drop(t, e, tcx, tcy, w, h, mx, my, mw, mh):
    cx, cy, a = _slide_from(t, e, tcx, my - int(h * 1.2), tcx, tcy, _eo_bounce)
    if e and t > 0.8:
        cy += int(math.sin((t - 0.8) * 18) * 6 * (1 - t))
    return cx, cy, 1.0, 0.0, a

def _f_glide_left(t, e, tcx, tcy, w, h, mx, my, mw, mh):
    cx, cy, a = _slide_from(t, e, mx - w, tcy, tcx, tcy, _eo_cubic)
    if e:
        cy += int(math.sin(t * math.pi) * 18)
    return cx, cy, 1.0, 0.0, a

def _f_glide_right(t, e, tcx, tcy, w, h, mx, my, mw, mh):
    cx, cy, a = _slide_from(t, e, mx + mw + w, tcy, tcx, tcy, _eo_cubic)
    if e:
        cy += int(math.sin(t * math.pi) * 18)
    return cx, cy, 1.0, 0.0, a

def _f_wave_slide(t, e, tcx, tcy, w, h, mx, my, mw, mh):
    cx, cy, a = _slide_from(t, e, tcx, my + mh + h, tcx, tcy, _eo_quint)
    if e:
        cx += int(math.sin(t * math.pi * 3) * (1 - t) * 36)
    return cx, cy, 1.0, 0.0, a

def _f_tada(t, e, tcx, tcy, w, h, mx, my, mw, mh):
    if e:
        wobble = math.sin(t * math.pi)            # 0..1..0
        scale = 1.0 + 0.12 * wobble
        angle = 7.0 * math.sin(t * math.pi * 5) * (1 - t)
        a = min(1.0, t * 6)
        return tcx, tcy, scale, angle, a
    p = _ei_quint(t)
    return tcx, tcy, 1.0 - 0.1 * p, 0.0, 1 - _ei_quint(t)

def _f_center_pop(t, e, tcx, tcy, w, h, mx, my, mw, mh):
    if e:
        scale = max(0.1, _eo_back(t))
        return tcx, tcy, scale, 0.0, min(1.0, t * 3)
    p = _ei_quint(t)
    return tcx, tcy, max(0.05, 1 - p), 0.0, max(0.0, 1 - t * 2)

def _f_snap_zoom(t, e, tcx, tcy, w, h, mx, my, mw, mh):
    if e:
        if t < 0.3:
            scale = 0.05 + (t / 0.3) * 0.65; a = min(1.0, t * 5)
        elif t < 0.55:
            scale = 0.70 + ((t - 0.3) / 0.25) * 0.45; a = 1.0
        else:
            scale = 1.15 - ((t - 0.55) / 0.45) * 0.15; a = 1.0
        return tcx, tcy, scale, 0.0, a
    p = _ei_quint(t)
    return tcx, tcy, max(0.05, 1 - p), 0.0, max(0.0, 1 - t * 3)


FRAME_FN = {
    'soft_pop': _f_soft_pop, 'float_up': _f_float_up,
    'fade': _f_fade, 'tada': _f_tada, 'slide_top': _f_slide_top, 'slide_bottom': _f_slide_bottom,
    'slide_left': _f_slide_left, 'slide_right': _f_slide_right, 'drop_bounce': _f_drop_bounce,
    'swing_up': _f_swing_up, 'diagonal_top_left': _f_diag_tl, 'diagonal_bottom_right': _f_diag_br,
    'elastic_slide': _f_elastic_slide, 'center_pop': _f_center_pop, 'bounce_in': _f_bounce_in,
    'elastic_rise': _f_elastic_rise, 'spring_drop': _f_spring_drop, 'glide_left': _f_glide_left,
    'glide_right': _f_glide_right, 'wave_slide': _f_wave_slide, 'snap_zoom': _f_snap_zoom,
}


# ─────────────────────────────────────────────
# ANIMATOR
# ─────────────────────────────────────────────
flag_queue = Queue()
currently_showing = False
active_popups = []
current_active_settings_window = None


def _animate(popups_info, cfg, on_done):
    anim = cfg.get('animation_type', 'slide_bottom')
    fn = FRAME_FN.get(anim, _f_fade)
    is_transform = anim in TRANSFORM_ANIMS
    is_genie = anim == 'genie'
    duration = max(0.05, max(50, cfg.get('animation_duration', 350)) / 1000.0)
    show_time = cfg.get('show_time', 1.0)
    frame_ms = 16

    def render(t, entering):
        for (p, tcx, tcy, w, h, mx, my, mw, mh) in popups_info:
            try:
                if is_genie:
                    progress = _eo_quint(t) if entering else 1.0 - _ei_quint(t)
                    p.blit_genie(progress)
                    p.update(tcx, tcy, min(1.0, progress * 2.8))
                    continue
                cx, cy, scale, angle, alpha = fn(t, entering, tcx, tcy, w, h, mx, my, mw, mh)
                if is_transform:
                    p.blit(scale, angle)
                p.update(cx, cy, alpha)
            except Exception:
                pass

    def phase(entering, callback):
        start = time.perf_counter()

        def step():
            t = (time.perf_counter() - start) / duration
            if t >= 1.0:
                render(1.0, entering)
                callback()
                return
            render(t, entering)
            root.after(frame_ms, step)
        step()

    def hold():
        root.after(int(show_time * 1000), lambda: phase(False, on_done))

    phase(True, hold)


def show_on_monitors(lang_id, cfg=None):
    global currently_showing, active_popups
    if cfg is None:
        cfg = settings

    mode = cfg.get('display_mode', 'flag')
    if mode in ('flag', 'flag_text') and lang_id not in FLAG_IMAGES:
        return
    if mode == 'text' and lang_id not in LANGUAGE_TEXT:
        return

    for p in active_popups:
        p.destroy()
    active_popups = []
    currently_showing = True

    try:
        pos_key = cfg.get('position_type', 'center')
        margin = cfg.get('edge_margin', 40)
        anim = cfg.get('animation_type', 'slide_bottom')
        info = []

        monitors = get_monitors_cached()
        if cfg.get('show_only_on_active_monitor', False):
            monitors = _active_monitors(monitors)
        for m in monitors:
            base = get_base_image(mode, lang_id, cfg, m.width)
            if base is None:
                continue
            bw, bh = base.size
            tmargin = int(max(bw, bh) * 0.20) + 8 if anim in TRANSFORM_ANIMS else 0
            popup = LayeredPopup(root, base, tmargin)
            tcx, tcy = _get_placement_coords(pos_key, bw, bh, m.x, m.y, m.width, m.height, margin)
            info.append((popup, tcx, tcy, bw, bh, m.x, m.y, m.width, m.height))
            active_popups.append(popup)

        if not info:
            currently_showing = False
            return

        def on_done():
            global currently_showing, active_popups
            for p in active_popups:
                p.destroy()
            active_popups = []
            currently_showing = False

        _animate(info, cfg, on_done)
    except Exception as e:
        debug_print(f"show_on_monitors: {e}")
        currently_showing = False


def _show_preview(lang_id, cfg):
    mode = cfg.get('display_mode', 'flag')
    if mode == 'text' and lang_id not in LANGUAGE_TEXT:
        lang_id = next(iter(LANGUAGE_TEXT))
    if mode in ('flag', 'flag_text') and lang_id not in FLAG_IMAGES:
        lang_id = next(iter(FLAG_IMAGES))
    show_on_monitors(lang_id, cfg)


# ═════════════════════════════════════════════
# MATERIAL-STYLE UI WIDGETS
# ═════════════════════════════════════════════
def _windows_prefers_dark():
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize')
        return winreg.QueryValueEx(key, 'AppsUseLightTheme')[0] == 0
    except Exception:
        return False


def _theme_tokens(choice='auto'):
    dark = choice == 'dark' or (choice == 'auto' and _windows_prefers_dark())
    if dark:
        return {
            'bg': '#070A10', 'card': '#161D2A', 'text': '#F4F7FB', 'muted': '#8E9BB0',
            'accent': '#4F8CFF', 'accent_dim': '#1A2E52', 'track_off': '#2A3648',
            'border': '#2C384C', 'sidebar': '#0C111A', 'side_txt': '#9AA8BC',
            'side_active': '#4F8CFF', 'danger': '#FF6B74', 'ok': '#2EE6A8',
            'field': '#101722', 'hover': '#1E2736', 'glow': '#16305C',
            'chip': '#121925', 'ink': '#081018',
        }
    return {
        'bg': '#EEF2F7', 'card': '#FFFFFF', 'text': '#101828', 'muted': '#5C6B82',
        'accent': '#2F6FED', 'accent_dim': '#E4EDFF', 'track_off': '#D4DEEC',
        'border': '#D8E1EE', 'sidebar': '#0E1524', 'side_txt': '#9AA8BC',
        'side_active': '#6BA1FF', 'danger': '#D64550', 'ok': '#0E9F6E',
        'field': '#F6F8FC', 'hover': '#E8EEF8', 'glow': '#D6E4FF',
        'chip': '#F3F6FB', 'ink': '#0E1524',
    }


THEME = _theme_tokens(settings.get('interface_theme', 'auto'))
F = lambda s, w='normal': ("Segoe UI", s, w)


def _lerp_hex(a, b, t):
    ra, ga, ba = _hex_to_rgb(a)
    rb, gb, bb = _hex_to_rgb(b)
    return '#%02x%02x%02x' % (int(ra + (rb - ra) * t),
                              int(ga + (gb - ga) * t),
                              int(ba + (bb - ba) * t))


def _round_rect(cv, x1, y1, x2, y2, r, **kw):
    r = min(r, (x2 - x1) // 2, (y2 - y1) // 2)
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


class ToggleSwitch(tk.Canvas):
    def __init__(self, parent, variable, bg, w=48, h=27):
        super().__init__(parent, width=w, height=h, bg=bg, highlightthickness=0, bd=0, cursor='hand2')
        self.var = variable
        self.w, self.h = w, h
        self.pos = 1.0 if variable.get() else 0.0
        self.bind('<Button-1>', lambda e: self.var.set(not self.var.get()))
        variable.trace_add('write', lambda *a: self._animate(1.0 if self.var.get() else 0.0))
        self._draw()

    def _animate(self, target):
        step = 0.2 if target > self.pos else -0.2

        def go():
            self.pos += step
            if (step > 0 and self.pos >= target) or (step < 0 and self.pos <= target):
                self.pos = target
                self._draw()
                return
            self._draw()
            self.after(10, go)
        go()

    def _draw(self):
        self.delete('all')
        r = self.h / 2
        col = _lerp_hex(THEME['track_off'], THEME['accent'], self.pos)
        _round_rect(self, 1, 1, self.w - 1, self.h - 1, int(r), fill=col, outline='')
        cx = (r + 1) + (self.w - 2 - 2 * r) * self.pos
        tr = r - 4
        self.create_oval(cx - tr, self.h / 2 - tr, cx + tr, self.h / 2 + tr,
                         fill='#FFFFFF', outline='')


class RadioDot(tk.Canvas):
    def __init__(self, parent, variable, value, bg, size=22):
        super().__init__(parent, width=size, height=size, bg=bg, highlightthickness=0, bd=0, cursor='hand2')
        self.var, self.value, self.size = variable, value, size
        self.bind('<Button-1>', lambda e: self.var.set(self.value))
        variable.trace_add('write', lambda *a: self._draw())
        self._draw()

    def _draw(self):
        self.delete('all')
        s = self.size
        on = (self.var.get() == self.value)
        ring = THEME['accent'] if on else '#B9C0CE'
        self.create_oval(2, 2, s - 2, s - 2, outline=ring, width=2)
        if on:
            self.create_oval(7, 7, s - 7, s - 7, fill=THEME['accent'], outline='')


class Slider(tk.Canvas):
    def __init__(self, parent, variable, mn, mx, step, bg, is_float=False, width=200, height=28):
        super().__init__(parent, width=width, height=height, bg=bg, highlightthickness=0, bd=0, cursor='hand2')
        self.var, self.mn, self.mx, self.step = variable, mn, mx, step
        self.is_float, self.W, self.H = is_float, width, height
        self.pad = 11
        self.bind('<Button-1>', self._set_from_x)
        self.bind('<B1-Motion>', self._set_from_x)
        variable.trace_add('write', lambda *a: self._draw())
        self._draw()

    def _ratio(self):
        try:
            v = float(self.var.get())
        except Exception:
            v = self.mn
        if self.mx == self.mn:
            return 0.0
        return max(0.0, min(1.0, (v - self.mn) / (self.mx - self.mn)))

    def _set_from_x(self, e):
        ratio = max(0.0, min(1.0, (e.x - self.pad) / (self.W - 2 * self.pad)))
        raw = self.mn + ratio * (self.mx - self.mn)
        snapped = round(raw / self.step) * self.step
        snapped = max(self.mn, min(self.mx, snapped))
        self.var.set(round(snapped, 2) if self.is_float else int(round(snapped)))

    def _draw(self):
        self.delete('all')
        cy = self.H / 2
        x1, x2 = self.pad, self.W - self.pad
        _round_rect(self, x1, cy - 3, x2, cy + 3, 3, fill=THEME['track_off'], outline='')
        tx = x1 + (x2 - x1) * self._ratio()
        if tx > x1 + 1:
            _round_rect(self, x1, cy - 3, tx, cy + 3, 3, fill=THEME['accent'], outline='')
        self.create_oval(tx - 9, cy - 9, tx + 9, cy + 9, fill='#FFFFFF',
                         outline=THEME['accent'], width=2)


class FlatButton(ctk.CTkButton):
    def __init__(self, parent, text, command, bg, fg='#FFFFFF', hover=None, pad=(0, 9), font=None):
        hover = hover or _lerp_hex(bg, '#000000', 0.14)
        super().__init__(parent, text=text, command=command, fg_color=bg,
                         hover_color=hover, text_color=fg,
                         font=font or F(10, 'bold'), height=max(34, pad[1] * 2 + 18),
                         corner_radius=12, border_width=0)
        self.bind('<Return>', lambda e: self.invoke(), add='+')
        self.bind('<space>', lambda e: self.invoke(), add='+')


class Chip(ctk.CTkButton):
    """A selectable segment, bound to a StringVar value."""
    def __init__(self, parent, text, variable, value, bg):
        self.var, self.value, self._bg = variable, value, bg
        super().__init__(parent, text=text, font=F(9, 'bold'), command=lambda: self.var.set(self.value),
                         height=34, corner_radius=11, border_width=1,
                         border_color=THEME['border'], width=92)
        variable.trace_add('write', lambda *a: self._refresh())
        self._refresh()

    def _refresh(self):
        on = (self.var.get() == self.value)
        self.configure(fg_color=THEME['accent'] if on else self._bg,
                       hover_color=THEME['accent'] if on else THEME['hover'],
                       text_color='#FFFFFF' if on else THEME['text'],
                       border_color=THEME['accent'] if on else THEME['border'])


# ─────────────────────────────────────────────
# TOAST
# ─────────────────────────────────────────────
def _toast(parent, msg, duration=1500):
    w = tk.Toplevel(parent)
    w.overrideredirect(True)
    w.attributes("-topmost", True)
    w.configure(bg=THEME['ink'])
    shell = tk.Frame(w, bg=THEME['ink'], highlightthickness=1, highlightbackground=THEME['ok'])
    shell.pack()
    tk.Label(shell, text=msg, bg=THEME['ink'], fg=THEME['ok'], font=F(10, 'bold'),
             padx=22, pady=11).pack()
    w.update_idletasks()
    sw, sh = w.winfo_screenwidth(), w.winfo_screenheight()
    ww, wh = w.winfo_width(), w.winfo_height()
    w.geometry(f"{ww}x{wh}+{(sw - ww) // 2}+{sh - wh - 96}")
    w.after(duration, w.destroy)


# ═════════════════════════════════════════════
# SETTINGS WINDOW
# ═════════════════════════════════════════════
class SettingsWindow:
    def __init__(self, parent):
        global current_active_settings_window
        self._current_tab = 'gen'
        self.language_rows = []

        ctk.set_appearance_mode('dark' if _theme_tokens('dark') == THEME else 'light')
        self.window = ctk.CTkToplevel(parent)
        self.window.title("Language Popup Settings")
        self.window.geometry("1080x760")
        self.window.minsize(920, 660)
        self.window.resizable(True, True)
        self.window.attributes("-topmost", True)
        self.window.configure(fg_color=THEME['bg'])
        if os.path.exists(ICON_FILE):
            try:
                self.window.iconbitmap(ICON_FILE)
            except Exception:
                pass

        self.window.update_idletasks()
        x = (self.window.winfo_screenwidth() - 1080) // 2
        y = (self.window.winfo_screenheight() - 760) // 2
        self.window.geometry(f"1080x760+{x}+{y}")
        if os.path.exists(ICON_FILE):
            _set_taskbar_icon(self.window.winfo_id(), ICON_FILE)

        self._build_header()
        self.body = tk.Frame(self.window, bg=THEME['bg'])
        self.body.pack(fill=tk.BOTH, expand=True)
        self._build_sidebar()
        self._build_content()

        self.views = {}
        self._build_general_view()
        self._build_languages_view()
        self._build_animation_view()
        self._build_style_view()
        self._build_about_view()
        
        self._load()
        self._switch_tab('gen')

        current_active_settings_window = self
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---- chrome ----
    def _build_header(self):
        header = tk.Frame(self.window, bg=THEME['sidebar'], height=80)
        header.pack(side=tk.TOP, fill=tk.X)
        header.pack_propagate(False)

        brand = tk.Frame(header, bg=THEME['sidebar'])
        brand.pack(side=tk.LEFT, padx=24, pady=12)
        try:
            icon_image = Image.open(os.path.join(IMAGE_DIR, 'app_icon.png')).convert('RGBA')
            icon_image.thumbnail((42, 42), RESAMPLE_LANCZOS)
            self._header_icon = ImageTk.PhotoImage(icon_image)
            tk.Label(brand, image=self._header_icon, bg=THEME['sidebar']).pack(side=tk.LEFT, padx=(0, 12))
        except Exception:
            pass
        copy = tk.Frame(brand, bg=THEME['sidebar'])
        copy.pack(side=tk.LEFT)
        title_row = tk.Frame(copy, bg=THEME['sidebar'])
        title_row.pack(anchor='w')
        tk.Label(title_row, text="Language Popup", font=F(15, 'bold'),
                 bg=THEME['sidebar'], fg=THEME['text']).pack(side=tk.LEFT)
        tk.Label(title_row, text="v9.2", font=F(8, 'bold'), padx=8, pady=2,
                 bg=THEME['accent_dim'], fg=THEME['accent'], relief=tk.FLAT).pack(side=tk.LEFT, padx=(10, 0))
        tk.Label(copy, text="Keyboard language indicator", font=F(9),
                 bg=THEME['sidebar'], fg=THEME['muted']).pack(anchor='w', pady=(4, 0))

        tk.Label(header, text="Configuration Panel",
                 font=F(10, 'bold'), bg=THEME['sidebar'], fg=THEME['muted']).pack(
                     side=tk.RIGHT, padx=32)

    def _build_sidebar(self):
        sb = ctk.CTkFrame(self.body, fg_color=THEME['sidebar'], width=248,
                          corner_radius=0, border_width=1, border_color=THEME['border'])
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        sb.pack_propagate(False)

        tk.Frame(sb, bg=THEME['sidebar'], height=22).pack()
        tk.Label(sb, text="SETTINGS", font=F(9, 'bold'),
                 bg=THEME['sidebar'], fg=THEME['muted']).pack(padx=20, anchor='w', pady=(0, 10))

        self._nav = {}
        for tab, label in (('gen', 'General'), ('langs', 'Languages'),
                           ('style', 'Popup appearance'), ('anim', 'Animation'), ('about', 'About')):
            self._nav[tab] = self._nav_btn(sb, label, tab)
            self._nav[tab].pack(fill=tk.X, padx=12, pady=2)

        tk.Frame(sb, bg=THEME['sidebar']).pack(fill=tk.BOTH, expand=True)

        act = tk.Frame(sb, bg=THEME['sidebar'])
        act.pack(side=tk.BOTTOM, fill=tk.X, padx=14, pady=14)
        self.status_var = tk.StringVar(value="Ready")
        tk.Label(act, textvariable=self.status_var, font=F(8), bg=THEME['sidebar'],
                 fg=THEME['muted'], anchor='w').pack(fill=tk.X, padx=3, pady=(0, 7))
        self.save_button = FlatButton(act, "Save and close", self._save, THEME['accent'])
        self.save_button.pack(fill=tk.X, pady=3)
        self.apply_button = FlatButton(act, "Apply changes", self._apply_changes, THEME['hover'],
                                       hover=THEME['accent_dim'])
        self.apply_button.pack(fill=tk.X, pady=3)
        self.reset_button = FlatButton(act, "Reset to defaults", self._reset, THEME['hover'],
                                       hover=THEME['accent_dim'])
        self.reset_button.pack(fill=tk.X, pady=3)
        self.close_button = FlatButton(act, "Close", self._on_close, THEME['hover'],
                                       hover=THEME['danger'])
        self.close_button.pack(fill=tk.X, pady=3)

    def _nav_btn(self, parent, text, tab):
        f = tk.Frame(parent, bg=THEME['sidebar'], cursor='hand2')
        bar = tk.Frame(f, bg=THEME['sidebar'], width=4)
        bar.pack(side=tk.LEFT, fill=tk.Y)
        lbl = tk.Label(f, text=text, font=F(11), bg=THEME['sidebar'],
                       fg=THEME['side_txt'], anchor='w', padx=16, pady=10)
        lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)
        f._bar, f._lbl, f._tab = bar, lbl, tab
        for wdg in (f, lbl, bar):
            wdg.bind('<Button-1>', lambda e, t=tab: self._switch_tab(t))
            wdg.bind('<Enter>', lambda e, ff=f: self._nav_hover(ff, True))
            wdg.bind('<Leave>', lambda e, ff=f: self._nav_hover(ff, False))
        return f

    def _nav_hover(self, f, on):
        if f._tab == self._current_tab:
            return
        f._lbl.config(fg='#FFFFFF' if on else THEME['side_txt'])

    def _build_content(self):
        outer = tk.Frame(self.body, bg=THEME['bg'])
        outer.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(outer, bg=THEME['bg'], highlightthickness=0, bd=0)
        sb = tk.Scrollbar(outer, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.frame = tk.Frame(self.canvas, bg=THEME['bg'])
        self.canvas.create_window((0, 0), window=self.frame, anchor="nw", tags="win")
        self.frame.bind("<Configure>",
                        lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig("win", width=e.width))
        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._wheel))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

    def _wheel(self, e):
        self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

    def _on_close(self):
        global current_active_settings_window
        current_active_settings_window = None
        self.window.destroy()

    def _switch_tab(self, name):
        for v in self.views.values():
            v.grid_remove()
        self.frame.grid_rowconfigure(0, weight=1)
        self.frame.grid_columnconfigure(0, weight=1)
        self.views[name].grid(row=0, column=0, sticky="nsew")
        self._current_tab = name
        self.canvas.yview_moveto(0)
        for tab, f in self._nav.items():
            active = (tab == name)
            f._bar.config(bg=THEME['side_active'] if active else THEME['sidebar'])
            f._lbl.config(fg='#FFFFFF' if active else THEME['side_txt'],
                          font=F(11, 'bold') if active else F(11))

    # ---- building blocks ----
    def _card(self, parent, title):
        wrap = tk.Frame(parent, bg=THEME['bg'])
        wrap.pack(fill=tk.X, pady=(0, 14), padx=18)
        card = ctk.CTkFrame(wrap, fg_color=THEME['card'], corner_radius=14,
                            border_width=1, border_color=THEME['border'])
        card.pack(fill=tk.X)
        tk.Label(card, text=title, font=F(10, 'bold'), bg=THEME['card'],
                 fg=THEME['text'], anchor='w').pack(fill=tk.X, padx=18, pady=(14, 6))
        body = tk.Frame(card, bg=THEME['card'])
        body.pack(fill=tk.X, padx=18, pady=(0, 16))
        return body

    def _label(self, parent, text, width=22):
        return tk.Label(parent, text=text, font=F(9), bg=THEME['card'],
                        fg=THEME['muted'], anchor='w', width=width)

    def _slider_row(self, parent, label, key, mn, mx, step, is_float=False):
        row = tk.Frame(parent, bg=THEME['card'])
        row.pack(fill=tk.X, pady=7)
        self._label(row, label).pack(side=tk.LEFT)
        var = tk.DoubleVar() if is_float else tk.IntVar()
        setattr(self, f"_{key}_var", var)
        val = tk.Label(row, bg=THEME['card'], fg=THEME['text'], font=F(10, 'bold'),
                       width=6, anchor='e')
        val.pack(side=tk.RIGHT)

        def fmt(*a):
            try:
                v = var.get()
            except Exception:
                return
            val.config(text=(f"{v:.2f}" if is_float else f"{int(v)}"))
        var.trace_add('write', fmt)
        fmt()
        Slider(row, var, mn, mx, step, THEME['card'], is_float=is_float).pack(side=tk.RIGHT, padx=10)
        return var

    def _toggle_row(self, parent, label, var):
        row = tk.Frame(parent, bg=THEME['card'])
        row.pack(fill=tk.X, pady=6)
        tk.Label(row, text=label, font=F(9, 'bold'), bg=THEME['card'],
                 fg=THEME['text'], anchor='w').pack(side=tk.LEFT)
        ToggleSwitch(row, var, THEME['card']).pack(side=tk.RIGHT)

    def _radio_row(self, parent, text, var, value):
        row = tk.Frame(parent, bg=THEME['card'], cursor='hand2')
        RadioDot(row, var, value, THEME['card']).pack(side=tk.LEFT)
        lbl = tk.Label(row, text=text, font=F(9), bg=THEME['card'],
                       fg=THEME['text'], anchor='w')
        lbl.pack(side=tk.LEFT, padx=8)
        lbl.bind('<Button-1>', lambda e: var.set(value))
        return row

    def _color_row(self, parent, label, key):
        row = tk.Frame(parent, bg=THEME['card'])
        row.pack(fill=tk.X, pady=6)
        self._label(row, label).pack(side=tk.LEFT)
        var = tk.StringVar()
        setattr(self, f"_{key}_var", var)

        sw = tk.Canvas(row, width=34, height=20, highlightthickness=1,
                       highlightbackground=THEME['border'], bd=0)
        sw.pack(side=tk.RIGHT, padx=8)
        for i in range(0, 34, 5):
            for j in range(0, 20, 5):
                sw.create_rectangle(i, j, i + 5, j + 5, outline='',
                                    fill='#CCCCCC' if (i // 5 + j // 5) % 2 == 0 else '#FFFFFF')
        rect = sw.create_rectangle(0, 0, 34, 20, fill='#000000', outline='')

        def upd(*a):
            try:
                sw.itemconfig(rect, fill=var.get() or '#ffffff')
            except Exception:
                pass
        var.trace_add('write', upd)

        def pick():
            c = colorchooser.askcolor(color=var.get(), parent=self.window,
                                      title=f"Choose {label}")[1]
            if c:
                var.set(c)
        FlatButton(row, "Choose", pick, THEME['accent'], pad=(12, 4),
                   font=F(8, 'bold')).pack(side=tk.RIGHT)
        tk.Label(row, textvariable=var, width=9, font=("Consolas", 9),
                 bg=THEME['card'], fg=THEME['muted']).pack(side=tk.RIGHT, padx=8)

    def _entry(self, parent, variable, width=18):
        return tk.Entry(parent, textvariable=variable, width=width, font=F(9),
                        bg=THEME['field'], fg=THEME['text'], insertbackground=THEME['text'],
                        justify=tk.LEFT,
                        relief=tk.FLAT, highlightthickness=1,
                        highlightbackground=THEME['border'], highlightcolor=THEME['accent'])

    def _set_language_rows(self, languages):
        for row in self.language_rows:
            row['frame'].destroy()
        self.language_rows.clear()
        for item in _sanitise_languages(languages):
            self._append_language_row(item)

    def _append_language_row(self, item=None):
        item = item or {'id': '', 'name': 'New language', 'text': '', 'flag': '', 'enabled': True}
        card = tk.Frame(self.languages_list, bg=THEME['card'], highlightthickness=1,
                        highlightbackground=THEME['border'])
        card.pack(fill=tk.X, pady=(0, 10))
        body = tk.Frame(card, bg=THEME['card'])
        body.pack(fill=tk.X, padx=16, pady=14)
        values = {key: tk.StringVar(value=str(item.get(key, '')))
                  for key in ('id', 'name', 'text', 'flag')}
        enabled = tk.BooleanVar(value=bool(item.get('enabled', True)))
        fields = (('Windows language ID', 'id', 12), ('Language name', 'name', 18),
                  ('Popup text', 'text', 12))
        for col, (label, key, width) in enumerate(fields):
            box = tk.Frame(body, bg=THEME['card'])
            box.grid(row=0, column=col, sticky='ew', padx=(0, 10))
            tk.Label(box, text=label, font=F(8, 'bold'), bg=THEME['card'],
                     fg=THEME['muted']).pack(anchor='w', pady=(0, 5))
            self._entry(box, values[key], width).pack(fill=tk.X, ipady=6)
            body.grid_columnconfigure(col, weight=1)

        flag_box = tk.Frame(body, bg=THEME['card'])
        flag_box.grid(row=1, column=0, columnspan=3, sticky='ew', pady=(12, 0))
        tk.Label(flag_box, text="Flag image", font=F(8, 'bold'), bg=THEME['card'],
                 fg=THEME['muted']).pack(side=tk.LEFT, padx=(0, 8))
        self._entry(flag_box, values['flag'], 42).pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=6)

        def browse():
            path = filedialog.askopenfilename(parent=self.window, title="Choose flag image",
                                              filetypes=[("Images", "*.png *.webp *.jpg *.jpeg"),
                                                         ("All files", "*.*")])
            if path:
                values['flag'].set(path)

        FlatButton(flag_box, "Browse", browse, THEME['hover'], fg=THEME['text'],
                   pad=(12, 6), font=F(8, 'bold')).pack(side=tk.LEFT, padx=(8, 0))
        tools_row = tk.Frame(body, bg=THEME['card'])
        tools_row.grid(row=2, column=0, columnspan=3, sticky='ew', pady=(12, 0))
        tk.Label(tools_row, text="Enabled", bg=THEME['card'], fg=THEME['text'],
                 font=F(8, 'bold')).pack(side=tk.LEFT, padx=(0, 8))
        ToggleSwitch(tools_row, enabled, THEME['card'], w=42, h=24).pack(side=tk.LEFT)
        row = {'frame': card, 'values': values, 'enabled': enabled}

        def remove():
            if len(self.language_rows) <= 1:
                _toast(self.window, "Keep at least one language")
                return
            card.destroy()
            self.language_rows.remove(row)

        FlatButton(tools_row, "Remove", remove, THEME['hover'], fg=THEME['danger'],
                   pad=(12, 5), font=F(8, 'bold')).pack(side=tk.RIGHT)
        self.language_rows.append(row)

    # ---- General ----
    def _build_general_view(self):
        v = tk.Frame(self.frame, bg=THEME['bg'])
        self.views['gen'] = v

        c = self._card(v, "Display mode")
        self.mode_var = tk.StringVar()
        seg = tk.Frame(c, bg=THEME['card'])
        seg.pack(anchor='w', pady=2)
        Chip(seg, "Flag", self.mode_var, 'flag', THEME['field']).pack(side=tk.LEFT)
        Chip(seg, "Text", self.mode_var, 'text', THEME['field']).pack(side=tk.LEFT, padx=(6, 0))
        Chip(seg, "Flag + text", self.mode_var, 'flag_text', THEME['field']).pack(side=tk.LEFT, padx=(6, 0))
        self.mode_var.trace_add('write', lambda *a: self._on_mode())

        c = self._card(v, "Popup position")
        self.pos_var = tk.StringVar()
        grid = tk.Frame(c, bg=THEME['card'])
        grid.pack(anchor='w', pady=(0, 8))
        keys = [['top_left', 'top_center', 'top_right'],
                ['center_left', 'center', 'center_right'],
                ['bottom_left', 'bottom_center', 'bottom_right']]
        for ri, rowk in enumerate(keys):
            for ci, k in enumerate(rowk):
                Chip(grid, POSITION_TYPES[k], self.pos_var, k, THEME['field']).grid(
                    row=ri, column=ci, padx=4, pady=4, sticky='ew')
        self._slider_row(c, "Edge margin (px)", 'edge_margin', 0, 400, 5)

        c = self._card(v, "Timing")
        self._slider_row(c, "Visible duration (seconds)", 'show_time', 0.1, 10.0, 0.1, is_float=True)

        c = self._card(v, "Displays")
        self.active_monitor_var = tk.BooleanVar()
        self._toggle_row(c, "Show only on the active monitor", self.active_monitor_var)

        c = self._card(v, "Size")
        self.flag_frame = tk.Frame(c, bg=THEME['card'])
        self.flag_frame.pack(fill=tk.X)
        self._slider_row(self.flag_frame, "Flag width (%)", 'screen_width_percent', 1, 100, 1)

        self.textsize_frame = tk.Frame(c, bg=THEME['card'])
        self._slider_row(self.textsize_frame, "Font size (px)", 'font_size', 40, 600, 10)
        ff = tk.Frame(self.textsize_frame, bg=THEME['card'])
        ff.pack(fill=tk.X, pady=6)
        self._label(ff, "Font family").pack(side=tk.LEFT)
        self.font_family_var = tk.StringVar()
        fam = tk.Frame(ff, bg=THEME['card'])
        fam.pack(side=tk.RIGHT)
        for name in _SYSTEM_FONTS:
            self._radio_row(fam, name, self.font_family_var, name).pack(anchor='w')

        c = self._card(v, "Interface theme")
        self.theme_var = tk.StringVar()
        theme_segments = tk.Frame(c, bg=THEME['card'])
        theme_segments.pack(anchor='w')
        for label, value in (("System", 'auto'), ("Light", 'light'), ("Dark", 'dark')):
            Chip(theme_segments, label, self.theme_var, value, THEME['field']).pack(
                side=tk.LEFT, padx=(0, 6))
        tk.Label(c, text="The selected theme is shown the next time Settings opens.",
                 font=F(8), bg=THEME['card'], fg=THEME['muted']).pack(anchor='w', pady=(8, 0))

        self.debug_var = tk.BooleanVar()
        c = self._card(v, "Diagnostics")
        self._toggle_row(c, "Enable debug logging", self.debug_var)

    # ---- Languages ----
    def _build_languages_view(self):
        v = tk.Frame(self.frame, bg=THEME['bg'])
        self.views['langs'] = v
        intro = tk.Frame(v, bg=THEME['bg'])
        intro.pack(fill=tk.X, padx=18, pady=(4, 14))
        tk.Label(intro, text="Languages", font=F(18, 'bold'), bg=THEME['bg'],
                 fg=THEME['text']).pack(anchor='w')
        tk.Label(intro, text="Assign a popup label and optional flag image to each Windows language.",
                 font=F(9), bg=THEME['bg'], fg=THEME['muted']).pack(anchor='w', pady=(4, 0))
        self.languages_list = tk.Frame(v, bg=THEME['bg'])
        self.languages_list.pack(fill=tk.X, padx=18)
        add_wrap = tk.Frame(v, bg=THEME['bg'])
        add_wrap.pack(fill=tk.X, padx=18, pady=(2, 18))
        FlatButton(add_wrap, "Add language", lambda: self._append_language_row(),
                   THEME['accent'], pad=(18, 8)).pack(side=tk.LEFT)
        tk.Label(add_wrap, text="Windows language ID examples: 0x409 and 0x429",
                 font=F(8), bg=THEME['bg'], fg=THEME['muted']).pack(side=tk.LEFT, padx=12)

    # ---- Animations ----
    def _build_animation_view(self):
        v = tk.Frame(self.frame, bg=THEME['bg'])
        self.views['anim'] = v

        c = self._card(v, "Animation style")
        self.anim_var = tk.StringVar()
        cont = tk.Frame(c, bg=THEME['card'])
        cont.pack(fill=tk.BOTH, expand=True)
        items = list(ANIMATION_TYPES.items())
        col_count = 2
        cols = [items[i::col_count] for i in range(col_count)]
        for chunk in cols:
            cf = tk.Frame(cont, bg=THEME['card'])
            cf.pack(side=tk.LEFT, anchor='n', padx=(0, 30))
            for key, label in chunk:
                self._radio_row(cf, label, self.anim_var, key).pack(anchor='w', pady=2)

        c = self._card(v, "Timing")
        self._slider_row(c, "Animation duration (ms)", 'animation_duration', 50, 2000, 25)

        wrap = tk.Frame(v, bg=THEME['bg'])
        wrap.pack(fill=tk.X, padx=18, pady=4)
        FlatButton(wrap, "Live preview", self._preview_animation, THEME['accent'],
                   pad=(10, 10)).pack()

    # ---- Text Style ----
    def _build_style_view(self):
        v = tk.Frame(self.frame, bg=THEME['bg'])
        self.views['style'] = v

        c = self._card(v, "Flag appearance")
        self._slider_row(c, "Corner radius (px)", 'flag_corner_radius', 0, 120, 2)
        self._slider_row(c, "Flag opacity", 'flag_opacity', 0.1, 1.0, 0.05, is_float=True)
        self._color_row(c, "Border color", 'flag_border_color')
        self._slider_row(c, "Border width (px)", 'flag_border_width', 0, 20, 1)
        self.flag_shadow_var = tk.BooleanVar()
        self._toggle_row(c, "Flag shadow", self.flag_shadow_var)
        self._slider_row(c, "Shadow blur (px)", 'flag_shadow_blur', 0, 60, 2)
        self._slider_row(c, "Shadow opacity", 'flag_shadow_opacity', 0.0, 1.0, 0.05, is_float=True)
        self._slider_row(c, "Flag and text gap (px)", 'flag_text_gap', 0, 80, 2)

        c = self._card(v, "Text background")
        self.bg_enabled_var = tk.BooleanVar()
        self._toggle_row(c, "Show background", self.bg_enabled_var)
        self._color_row(c, "Background color", 'text_bg_color')
        self._slider_row(c, "Background opacity", 'text_bg_opacity', 0.0, 1.0, 0.05, is_float=True)

        c = self._card(v, "Text border")
        self._color_row(c, "Border color", 'text_border_color')
        self._slider_row(c, "Border width (px)", 'text_border_width', 0, 20, 1)
        self._slider_row(c, "Corner radius (px)", 'text_border_radius', 0, 80, 2)

        c = self._card(v, "Typography and spacing")
        self._color_row(c, "Text color", 'text_color')
        self._slider_row(c, "Text opacity", 'text_opacity', 0.1, 1.0, 0.05, is_float=True)
        self._slider_row(c, "Horizontal padding (px)", 'text_padding_x', 0, 200, 10)
        self._slider_row(c, "Vertical padding (px)", 'text_padding_y', 0, 200, 10)
        wf = tk.Frame(c, bg=THEME['card'])
        wf.pack(fill=tk.X, pady=6)
        self._label(wf, "Font weight").pack(side=tk.LEFT)
        self.font_weight_var = tk.StringVar()
        seg = tk.Frame(wf, bg=THEME['card'])
        seg.pack(side=tk.RIGHT)
        Chip(seg, "Regular", self.font_weight_var, 'regular', THEME['field']).pack(side=tk.LEFT)
        Chip(seg, "Bold", self.font_weight_var, 'bold', THEME['field']).pack(side=tk.LEFT, padx=(6, 0))

        c = self._card(v, "Text shadow")
        self.shadow_var = tk.BooleanVar()
        self._toggle_row(c, "Show shadow", self.shadow_var)
        self._color_row(c, "Shadow color", 'text_shadow_color')
        self._slider_row(c, "Shadow offset (px)", 'text_shadow_offset', 1, 30, 1)
        self._slider_row(c, "Shadow opacity", 'text_shadow_opacity', 0.1, 1.0, 0.05, is_float=True)

        c = self._card(v, "Glow")
        self.glow_var = tk.BooleanVar()
        self._toggle_row(c, "Glow behind text", self.glow_var)
        self._color_row(c, "Glow color", 'text_glow_color')
        self._slider_row(c, "Glow radius (px)", 'text_glow_radius', 2, 50, 2)


    # ---- About ----
    def _build_about_view(self):
        import webbrowser
        v = tk.Frame(self.frame, bg=THEME['bg'])
        self.views['about'] = v

        c = self._card(v, "About")
        
        about_text = ("See the active keyboard language the moment it changes.\n"
                      "Designed and developed by mr.5hady")
        
        tk.Label(c, text=about_text, font=F(10), bg=THEME['card'], 
                 fg=THEME['muted'], justify=tk.LEFT).pack(anchor='w', pady=(0, 16))
        
        links_container = tk.Frame(c, bg=THEME['card'])
        links_container.pack(anchor='w', fill=tk.X)
        
        # GitHub Link
        gh_lbl = tk.Label(links_container, text="GitHub", font=F(10, 'bold'), 
                          bg=THEME['card'], fg=THEME['accent'], cursor='hand2')
        gh_lbl.pack(side=tk.LEFT, padx=(0, 20))
        gh_lbl.bind('<Button-1>', lambda e: webbrowser.open("https://github.com/mr-shady"))
        
        # Telegram Link
        tg_lbl = tk.Label(links_container, text="Telegram", font=F(10, 'bold'), 
                          bg=THEME['card'], fg=THEME['accent'], cursor='hand2')
        tg_lbl.pack(side=tk.LEFT)
        tg_lbl.bind('<Button-1>', lambda e: webbrowser.open("https://t.me/Mr_5hady"))

    # ---- load / collect ----
    def _load(self, src=None):
        s = src or settings
        self.mode_var.set(s['display_mode'])
        self.pos_var.set(s.get('position_type', 'center'))
        self.debug_var.set(s['debug'])
        self.anim_var.set(s.get('animation_type', 'slide_bottom'))
        self.shadow_var.set(s.get('text_shadow', True))
        self.flag_shadow_var.set(s.get('flag_shadow', True))
        self.glow_var.set(s.get('text_glow', False))
        self.bg_enabled_var.set(s.get('text_bg_enabled', False))
        self.active_monitor_var.set(s.get('show_only_on_active_monitor', False))
        self.theme_var.set(s.get('interface_theme', 'auto'))
        self.font_family_var.set(s.get('text_font_family', 'Segoe UI'))
        self.font_weight_var.set(s.get('text_font_weight', 'bold'))

        for k in ('show_time', 'text_bg_opacity', 'text_shadow_opacity', 'text_opacity',
                  'flag_opacity', 'flag_shadow_opacity'):
            var = getattr(self, f"_{k}_var", None)
            if var:
                var.set(round(s.get(k, DEFAULT_SETTINGS.get(k, 0.0)), 2))
        for k in ('screen_width_percent', 'animation_duration', 'font_size',
                  'text_border_width', 'text_border_radius', 'text_padding_x',
                  'text_padding_y', 'edge_margin', 'text_shadow_offset', 'text_glow_radius'):
            var = getattr(self, f"_{k}_var", None)
            if var:
                var.set(int(s.get(k, DEFAULT_SETTINGS.get(k, 0))))
        for k in ('text_color', 'text_bg_color', 'text_border_color',
                  'text_shadow_color', 'text_glow_color'):
            var = getattr(self, f"_{k}_var", None)
            if var:
                var.set(s.get(k, DEFAULT_SETTINGS.get(k, '')))
        for k in ('flag_corner_radius', 'flag_border_width', 'flag_shadow_blur', 'flag_text_gap'):
            var = getattr(self, f"_{k}_var", None)
            if var:
                var.set(int(s.get(k, DEFAULT_SETTINGS.get(k, 0))))
        if hasattr(self, '_flag_border_color_var'):
            self._flag_border_color_var.set(s.get('flag_border_color', '#FFFFFF'))
        self._set_language_rows(s.get('languages', DEFAULT_LANGUAGES))
        self._on_mode()

    def _reset(self):
        self._load(DEFAULT_SETTINGS)
        if hasattr(self, 'status_var'):
            self.status_var.set("Defaults loaded. Click Apply to keep them.")

    def _on_mode(self):
        if self.mode_var.get() == 'flag':
            self.flag_frame.pack(fill=tk.X)
            self.textsize_frame.pack_forget()
        elif self.mode_var.get() == 'flag_text':
            self.flag_frame.pack(fill=tk.X)
            self.textsize_frame.pack(fill=tk.X)
        else:
            self.flag_frame.pack_forget()
            self.textsize_frame.pack(fill=tk.X)

    def _collect(self):
        g = lambda k: getattr(self, f"_{k}_var").get()
        languages = []
        for row in self.language_rows:
            values = row['values']
            languages.append({
                'id': _normalise_lang_id(values['id'].get()),
                'name': values['name'].get().strip(),
                'text': values['text'].get().strip(),
                'flag': values['flag'].get().strip(),
                'enabled': row['enabled'].get(),
            })
        return {
            'show_time': round(g('show_time'), 2),
            'screen_width_percent': int(g('screen_width_percent')),
            'animation_duration': int(g('animation_duration')),
            'debug': self.debug_var.get(),
            'display_mode': self.mode_var.get(),
            'languages': languages,
            'position_type': self.pos_var.get(),
            'edge_margin': int(g('edge_margin')),
            'font_size': int(g('font_size')),
            'animation_type': self.anim_var.get(),
            'text_color': g('text_color'),
            'text_bg_enabled': self.bg_enabled_var.get(),
            'text_bg_color': g('text_bg_color'),
            'text_bg_opacity': round(g('text_bg_opacity'), 2),
            'text_border_color': g('text_border_color'),
            'text_border_width': int(g('text_border_width')),
            'text_border_radius': int(g('text_border_radius')),
            'text_padding_x': int(g('text_padding_x')),
            'text_padding_y': int(g('text_padding_y')),
            'text_font_family': self.font_family_var.get(),
            'text_font_weight': self.font_weight_var.get(),
            'text_shadow': self.shadow_var.get(),
            'text_shadow_color': g('text_shadow_color'),
            'text_shadow_offset': int(g('text_shadow_offset')),
            'text_shadow_opacity': round(g('text_shadow_opacity'), 2),
            'text_opacity': round(g('text_opacity'), 2),
            'text_glow': self.glow_var.get(),
            'text_glow_color': g('text_glow_color'),
            'text_glow_radius': int(g('text_glow_radius')),
            'flag_corner_radius': int(g('flag_corner_radius')),
            'flag_opacity': round(g('flag_opacity'), 2),
            'flag_border_width': int(g('flag_border_width')),
            'flag_border_color': g('flag_border_color'),
            'flag_shadow': self.flag_shadow_var.get(),
            'flag_shadow_blur': int(g('flag_shadow_blur')),
            'flag_shadow_opacity': round(g('flag_shadow_opacity'), 2),
            'flag_text_gap': int(g('flag_text_gap')),
            'interface_theme': self.theme_var.get(),
            'show_only_on_active_monitor': self.active_monitor_var.get(),
        }

    def _apply_changes(self):
        global settings, DEBUG
        try:
            new = self._collect()
        except Exception as exc:
            messagebox.showerror("Invalid settings", f"A setting could not be read:\n{exc}",
                                 parent=self.window)
            return False
        ids = [item['id'] for item in new['languages']]
        if any(not item['id'] or not item['text'] for item in new['languages']):
            messagebox.showerror("Missing information", "Enter a Windows language ID and popup text for every language.",
                                 parent=self.window)
            return False
        if len(ids) != len(set(ids)):
            messagebox.showerror("Duplicate language ID", "Each Windows language ID must be unique.",
                                 parent=self.window)
            return False
        enabled = [item for item in new['languages'] if item['enabled']]
        if not enabled:
            messagebox.showerror("No enabled language", "Enable at least one language.",
                                 parent=self.window)
            return False
        if new['display_mode'] in ('flag', 'flag_text') and not any(
                os.path.exists(_resolve_flag_path(item['flag'])) for item in enabled):
            messagebox.showerror("Flag image not found",
                                 "Flag modes require at least one valid image for an enabled language.",
                                 parent=self.window)
            return False
        if save_settings(new):
            settings = new
            _sync_language_maps(settings)
            DEBUG = settings['debug']
            _render_cache.clear()
            if hasattr(self, 'status_var'):
                self.status_var.set("Changes applied successfully")
            _toast(self.window, "Changes applied")
            return True
        messagebox.showerror("Could not save settings",
                             f"Language Popup could not write to:\n{CONFIG_FILE}",
                             parent=self.window)
        return False

    def _save(self):
        if self._apply_changes():
            global current_active_settings_window
            current_active_settings_window = None
            self.window.destroy()

    def _preview_animation(self):
        cfg = self._collect()
        _render_cache.clear()
        preview_languages = _sanitise_languages(cfg.get('languages'))
        enabled = [item for item in preview_languages if item['enabled']]
        if not enabled:
            _toast(self.window, "Enable a language to preview")
            return
        lang = enabled[0]['id']
        temp_cfg = dict(cfg)
        temp_cfg['languages'] = preview_languages
        old_flags, old_text = dict(FLAG_IMAGES), dict(LANGUAGE_TEXT)
        _sync_language_maps(temp_cfg)
        _show_preview(lang, temp_cfg)
        FLAG_IMAGES.clear(); FLAG_IMAGES.update(old_flags)
        LANGUAGE_TEXT.clear(); LANGUAGE_TEXT.update(old_text)


# ─────────────────────────────────────────────
# LANGUAGE DETECTION
# ─────────────────────────────────────────────
DEBOUNCE_TIME = 0.28


class LanguageChangeDetector:
    """Debounces layout changes while treating a focus change as a silent baseline."""
    def __init__(self, required=3, debounce=DEBOUNCE_TIME):
        self.required = required
        self.debounce = debounce
        self.last_lang = None
        self.last_hwnd = None
        self.candidate = None
        self.consecutive = 0
        self.last_emit = 0.0

    def observe(self, lang_id, hwnd, now=None):
        if not lang_id:
            return False
        now = time.time() if now is None else now
        if self.last_hwnd is None or hwnd != self.last_hwnd:
            self.last_hwnd = hwnd
            self.last_lang = lang_id
            self.candidate = lang_id
            self.consecutive = 1
            return False
        if lang_id != self.candidate:
            self.candidate = lang_id
            self.consecutive = 1
        else:
            self.consecutive += 1
        if self.consecutive < self.required:
            return False
        if lang_id != self.last_lang and now - self.last_emit > self.debounce:
            self.last_lang = lang_id
            self.last_emit = now
            return True
        self.last_lang = lang_id
        return False


def check_lang_change():
    detector = LanguageChangeDetector()

    while True:
        try:
            current_lang, current_hwnd = get_foreground_window_info()
            if current_lang is None:
                time.sleep(0.05)
                continue

            now = time.time()
            changed_by_user = detector.observe(current_lang, current_hwnd, now)
            if changed_by_user:
                # Never read Tk variables from this worker thread. Unsaved settings
                # are exercised through the explicit preview button on the UI thread.
                cfg_source = settings

                mode = cfg_source.get('display_mode', 'flag')
                has_content = ((mode in ('flag', 'flag_text') and current_lang in FLAG_IMAGES) or
                               (mode == 'text' and current_lang in LANGUAGE_TEXT))

                if has_content:
                    while not flag_queue.empty():
                        try:
                            flag_queue.get_nowait()
                        except Exception:
                            break
                    flag_queue.put((current_lang, cfg_source))
        except Exception as e:
            debug_print(f"check_lang_change: {e}")
        time.sleep(0.05)


# ─────────────────────────────────────────────
# QUEUE PROCESSOR
# ─────────────────────────────────────────────
def process_queue():
    try:
        latest = None
        while not flag_queue.empty():
            try:
                latest = flag_queue.get_nowait()
            except Exception:
                break
        if latest and not currently_showing:
            show_on_monitors(latest[0], latest[1])
    except Exception as e:
        debug_print(f"process_queue: {e}")
    root.after(30, process_queue)


# ─────────────────────────────────────────────
# SYSTEM TRAY
# ─────────────────────────────────────────────
def create_tray_icon():
    if os.path.exists(ICON_FILE):
        try:
            icon_image = PILImage.open(ICON_FILE)
        except Exception:
            icon_image = PILImage.new('RGB', (64, 64), color='#5B6CFF')
    else:
        icon_image = PILImage.new('RGB', (64, 64), color='#5B6CFF')

    def open_settings(icon, item):
        def show_settings():
            if current_active_settings_window is not None:
                try:
                    current_active_settings_window.window.deiconify()
                    current_active_settings_window.window.lift()
                    current_active_settings_window.window.focus_force()
                    return
                except Exception:
                    pass
            SettingsWindow(root)
        root.after(0, show_settings)

    def quit_app(icon, item):
        icon.stop()
        root.quit()

    menu = Menu(MenuItem('Settings', open_settings, default=True), MenuItem('Exit', quit_app))
    icon = Icon("Language Popup", icon_image, "Language Popup", menu)
    threading.Thread(target=icon.run, daemon=True).start()


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
root = None


def main():
    global root
    debug_print(f"Starting Language Popup with {len(LANGUAGE_TEXT)} enabled languages")
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    if os.path.exists(ICON_FILE):
        try:
            root.iconbitmap(ICON_FILE)
        except Exception:
            pass
    create_tray_icon()
    threading.Thread(target=check_lang_change, daemon=True).start()
    root.after(30, process_queue)
    if '--settings' in sys.argv:
        root.after(150, lambda: SettingsWindow(root))
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
