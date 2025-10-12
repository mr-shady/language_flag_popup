import os
import time
import threading
import ctypes
import sys
import json
from PIL import Image, ImageTk
import tkinter as tk
from tkinter import ttk
from screeninfo import get_monitors
from queue import Queue
from pystray import Icon, Menu, MenuItem
from PIL import Image as PILImage

# --- CONFIG ---
if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS  
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

IMAGE_DIR = os.path.join(BASE_DIR, "images")
CONFIG_FILE = os.path.join(BASE_DIR, "settings.json")
ICON_FILE = os.path.join(IMAGE_DIR, "icon.ico")

FLAG_IMAGES = {
    '0x409': os.path.join(IMAGE_DIR, 'usa.png'),   # English
    '0x429': os.path.join(IMAGE_DIR, 'iran.png'),  # Persian
}

# Language display text
LANGUAGE_TEXT = {
    '0x409': 'EN',  # English
    '0x429': 'FA',  # Persian/Farsi
}

# Default settings
DEFAULT_SETTINGS = {
    'show_time': 0.2,
    'screen_width_percent': 0.3,
    'animation_duration': 10,
    'animation_steps': 10,
    'debug': False,
    'display_mode': 'flag',  # 'flag' or 'text'
    'font_size': 200  # Font size for text mode
}

# Load settings
def load_settings():
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                settings = json.load(f)
                # Merge with defaults in case new settings were added
                return {**DEFAULT_SETTINGS, **settings}
    except Exception as e:
        print(f"Error loading settings: {e}")
    return DEFAULT_SETTINGS.copy()

# Save settings
def save_settings(settings):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=4)
        return True
    except Exception as e:
        print(f"Error saving settings: {e}")
        return False

# Current settings
settings = load_settings()
DEBUG = settings['debug']

def debug_print(msg):
    if DEBUG:
        print(f"[DEBUG] {msg}")

# --- GET CURRENT INPUT LANGUAGE ---
def get_foreground_window_info():
    """Get both language and window handle"""
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        thread_id = ctypes.windll.user32.GetWindowThreadProcessId(hwnd, 0)
        klid = ctypes.windll.user32.GetKeyboardLayout(thread_id)
        lang_id = hex(klid & (2**16 - 1))
        return lang_id, hwnd
    except Exception as e:
        debug_print(f"Error in get_foreground_window_info: {e}")
        return None, None

# Queue for thread-safe communication
flag_queue = Queue()
currently_showing = False
active_windows = []

# --- SETTINGS WINDOW ---
class SettingsWindow:
    def __init__(self, parent):
        self.window = tk.Toplevel(parent)
        self.window.title("Flag Popup Settings")
        self.window.geometry("450x450")
        self.window.resizable(False, False)
        
        # Set icon if available
        if os.path.exists(ICON_FILE):
            self.window.iconbitmap(ICON_FILE)
        
        # Center window
        self.window.update_idletasks()
        x = (self.window.winfo_screenwidth() // 2) - (450 // 2)
        y = (self.window.winfo_screenheight() // 2) - (450 // 2)
        self.window.geometry(f"450x450+{x}+{y}")
        
        # Make it stay on top
        self.window.attributes("-topmost", True)
        
        self.create_widgets()
        self.load_current_settings()
        
    def create_widgets(self):
        # Main frame with padding
        main_frame = ttk.Frame(self.window, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        title = ttk.Label(main_frame, text="⚙️ Settings", font=("Segoe UI", 14, "bold"))
        title.pack(pady=(0, 20))
        
        # Display Mode
        mode_frame = ttk.LabelFrame(main_frame, text="Display Mode", padding=10)
        mode_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.mode_var = tk.StringVar()
        ttk.Radiobutton(mode_frame, text="🚩 Flag Images", variable=self.mode_var, 
                       value='flag', command=self.on_mode_change).pack(anchor=tk.W)
        ttk.Radiobutton(mode_frame, text="📝 Text (EN/FA)", variable=self.mode_var, 
                       value='text', command=self.on_mode_change).pack(anchor=tk.W)
        
        # Font Size (only for text mode)
        self.font_frame = ttk.Frame(mode_frame)
        self.font_frame.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(self.font_frame, text="Font Size:", width=15).pack(side=tk.LEFT)
        self.font_size_var = tk.IntVar()
        self.font_size_spin = ttk.Spinbox(self.font_frame, from_=50, to=500, increment=10, 
                                          textvariable=self.font_size_var, width=10)
        self.font_size_spin.pack(side=tk.LEFT, padx=5)
        ttk.Label(self.font_frame, text="px").pack(side=tk.LEFT)
        
        # Show Time
        frame1 = ttk.Frame(main_frame)
        frame1.pack(fill=tk.X, pady=5)
        ttk.Label(frame1, text="Display Duration (seconds):", width=25).pack(side=tk.LEFT)
        self.show_time_var = tk.DoubleVar()
        self.show_time_spin = ttk.Spinbox(frame1, from_=0.1, to=5.0, increment=0.1, 
                                          textvariable=self.show_time_var, width=10)
        self.show_time_spin.pack(side=tk.LEFT, padx=5)
        
        # Screen Width Percent (only for flag mode)
        self.width_frame = ttk.Frame(main_frame)
        self.width_frame.pack(fill=tk.X, pady=5)
        ttk.Label(self.width_frame, text="Flag Width (% of screen):", width=25).pack(side=tk.LEFT)
        self.width_var = tk.DoubleVar()
        self.width_spin = ttk.Spinbox(self.width_frame, from_=0.1, to=1.0, increment=0.05, 
                                      textvariable=self.width_var, width=10)
        self.width_spin.pack(side=tk.LEFT, padx=5)
        self.width_label = ttk.Label(self.width_frame, text="(30%)")
        self.width_label.pack(side=tk.LEFT)
        self.width_var.trace('w', self.update_percent_label)
        
        # Animation Duration
        frame3 = ttk.Frame(main_frame)
        frame3.pack(fill=tk.X, pady=5)
        ttk.Label(frame3, text="Animation Duration (ms):", width=25).pack(side=tk.LEFT)
        self.duration_var = tk.IntVar()
        self.duration_spin = ttk.Spinbox(frame3, from_=5, to=100, increment=5, 
                                         textvariable=self.duration_var, width=10)
        self.duration_spin.pack(side=tk.LEFT, padx=5)
        
        # Animation Steps
        frame4 = ttk.Frame(main_frame)
        frame4.pack(fill=tk.X, pady=5)
        ttk.Label(frame4, text="Animation Steps:", width=25).pack(side=tk.LEFT)
        self.steps_var = tk.IntVar()
        self.steps_spin = ttk.Spinbox(frame4, from_=5, to=30, increment=1, 
                                      textvariable=self.steps_var, width=10)
        self.steps_spin.pack(side=tk.LEFT, padx=5)
        
        # Debug Mode
        frame5 = ttk.Frame(main_frame)
        frame5.pack(fill=tk.X, pady=15)
        self.debug_var = tk.BooleanVar()
        ttk.Checkbutton(frame5, text="Debug Mode (show console logs)", 
                       variable=self.debug_var).pack(side=tk.LEFT)
        
        # Separator
        ttk.Separator(main_frame, orient='horizontal').pack(fill=tk.X, pady=10)
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=10)
        
        ttk.Button(button_frame, text="💾 Save", command=self.save_settings, 
                  width=12).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="🔄 Reset", command=self.reset_defaults, 
                  width=12).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="❌ Cancel", command=self.window.destroy, 
                  width=12).pack(side=tk.LEFT, padx=5)
        
        # Info
        info_label = ttk.Label(main_frame, 
                              text="Note: Changes take effect immediately after saving",
                              font=("Segoe UI", 8), foreground="gray")
        info_label.pack(pady=(10, 0))
    
    def on_mode_change(self):
        """Show/hide relevant options based on display mode"""
        mode = self.mode_var.get()
        if mode == 'text':
            self.font_frame.pack(fill=tk.X, pady=(10, 0))
            self.width_frame.pack_forget()
        else:
            self.font_frame.pack_forget()
            self.width_frame.pack(fill=tk.X, pady=5)
    
    def update_percent_label(self, *args):
        try:
            percent = int(self.width_var.get() * 100)
            self.width_label.config(text=f"({percent}%)")
        except:
            pass
        
    def load_current_settings(self):
        self.show_time_var.set(settings['show_time'])
        self.width_var.set(settings['screen_width_percent'])
        self.duration_var.set(settings['animation_duration'])
        self.steps_var.set(settings['animation_steps'])
        self.debug_var.set(settings['debug'])
        self.mode_var.set(settings['display_mode'])
        self.font_size_var.set(settings['font_size'])
        self.on_mode_change()  # Update UI based on mode
        
    def reset_defaults(self):
        self.show_time_var.set(DEFAULT_SETTINGS['show_time'])
        self.width_var.set(DEFAULT_SETTINGS['screen_width_percent'])
        self.duration_var.set(DEFAULT_SETTINGS['animation_duration'])
        self.steps_var.set(DEFAULT_SETTINGS['animation_steps'])
        self.debug_var.set(DEFAULT_SETTINGS['debug'])
        self.mode_var.set(DEFAULT_SETTINGS['display_mode'])
        self.font_size_var.set(DEFAULT_SETTINGS['font_size'])
        self.on_mode_change()
        
    def save_settings(self):
        global settings, DEBUG
        
        new_settings = {
            'show_time': self.show_time_var.get(),
            'screen_width_percent': self.width_var.get(),
            'animation_duration': self.duration_var.get(),
            'animation_steps': self.steps_var.get(),
            'debug': self.debug_var.get(),
            'display_mode': self.mode_var.get(),
            'font_size': self.font_size_var.get()
        }
        
        if save_settings(new_settings):
            settings = new_settings
            DEBUG = settings['debug']
            
            # Show success message
            success_window = tk.Toplevel(self.window)
            success_window.title("Success")
            success_window.geometry("300x100")
            success_window.resizable(False, False)
            success_window.attributes("-topmost", True)
            
            if os.path.exists(ICON_FILE):
                success_window.iconbitmap(ICON_FILE)
            
            # Center it
            success_window.update_idletasks()
            x = (success_window.winfo_screenwidth() // 2) - 150
            y = (success_window.winfo_screenheight() // 2) - 50
            success_window.geometry(f"300x100+{x}+{y}")
            
            ttk.Label(success_window, text="✅ Settings saved successfully!", 
                     font=("Segoe UI", 10)).pack(expand=True)
            ttk.Button(success_window, text="Close", 
                      command=success_window.destroy).pack(pady=10)
            
            self.window.destroy()
        else:
            # Show error
            error_window = tk.Toplevel(self.window)
            error_window.title("Error")
            error_window.geometry("300x100")
            error_window.attributes("-topmost", True)
            
            if os.path.exists(ICON_FILE):
                error_window.iconbitmap(ICON_FILE)
            
            ttx.Label(error_window, text="❌ Error saving settings!", 
                     font=("Segoe UI", 10)).pack(expand=True)
            ttk.Button(error_window, text="Close", 
                      command=error_window.destroy).pack(pady=10)

# --- SHOW FLAG OR TEXT ON ALL MONITORS ---
def show_on_monitors(lang_id):
    global currently_showing, active_windows
    
    if settings['display_mode'] == 'flag':
        # Flag mode - use image
        if lang_id not in FLAG_IMAGES:
            debug_print(f"No flag for language {lang_id}")
            return
        image_path = FLAG_IMAGES[lang_id]
        debug_print(f"Attempting to show flag: {image_path}")
        
        if not os.path.exists(image_path):
            debug_print(f"ERROR: Image not found at {image_path}")
            currently_showing = False
            return
    else:
        # Text mode
        if lang_id not in LANGUAGE_TEXT:
            debug_print(f"No text for language {lang_id}")
            return
        debug_print(f"Attempting to show text: {LANGUAGE_TEXT[lang_id]}")
    
    # Close existing windows
    if active_windows:
        debug_print(f"Closing {len(active_windows)} existing windows")
        for window in active_windows:
            try:
                window.withdraw()
                window.destroy()
            except:
                pass
        active_windows = []
        root.update()
        time.sleep(0.05)
    
    currently_showing = True
    
    try:
        monitors = get_monitors()
        debug_print(f"Found {len(monitors)} monitors")
        windows = []
        
        if settings['display_mode'] == 'flag':
            # Flag mode - create image windows
            img_width = int(monitors[0].width * settings['screen_width_percent'])
            
            img = Image.open(image_path)
            aspect_ratio = img.height / img.width
            new_height = int(img_width * aspect_ratio)
            img = img.resize((img_width, new_height), Image.LANCZOS)
            
            tk_img = ImageTk.PhotoImage(img)
            
            for i, monitor in enumerate(monitors):
                window = tk.Toplevel(root)
                window.overrideredirect(True)
                window.attributes("-topmost", True)
                window.attributes("-transparentcolor", "black")
                window.configure(bg='black')
                
                label = tk.Label(window, image=tk_img, bg='black')
                label.image = tk_img
                label.pack()
                
                x = monitor.x + (monitor.width - img_width) // 2
                y = monitor.y + (monitor.height - new_height) // 2
                window.geometry(f"{img_width}x{new_height}+{x}+{y}")
                window.attributes("-alpha", 0.0)
                
                windows.append(window)
                debug_print(f"Created flag window {i+1} on monitor {i+1}")
        else:
            # Text mode - create text windows
            text = LANGUAGE_TEXT[lang_id]
            font_size = settings['font_size']
            
            for i, monitor in enumerate(monitors):
                window = tk.Toplevel(root)
                window.overrideredirect(True)
                window.attributes("-topmost", True)
                window.attributes("-transparentcolor", "black")
                window.configure(bg='black')
                
                # Create label with large text
                label = tk.Label(window, text=text, 
                               font=("Arial", font_size, "bold"),
                               fg='white', bg='black')
                label.pack()
                
                # Get text size and center it
                window.update_idletasks()
                text_width = label.winfo_reqwidth()
                text_height = label.winfo_reqheight()
                
                x = monitor.x + (monitor.width - text_width) // 2
                y = monitor.y + (monitor.height - text_height) // 2
                window.geometry(f"{text_width}x{text_height}+{x}+{y}")
                window.attributes("-alpha", 0.0)
                
                windows.append(window)
                debug_print(f"Created text window {i+1} on monitor {i+1}")
        
        active_windows = windows
        
        def fade_in(step=0):
            if step <= settings['animation_steps']:
                alpha = step / settings['animation_steps']
                for window in windows:
                    try:
                        window.attributes("-alpha", alpha)
                    except:
                        pass
                root.after(settings['animation_duration'] // settings['animation_steps'], 
                          lambda: fade_in(step + 1))
            else:
                debug_print("Fade in complete")
                root.after(int(settings['show_time'] * 1000), 
                          lambda: fade_out(settings['animation_steps']))
        
        def fade_out(step):
            if step >= 0:
                alpha = step / settings['animation_steps']
                for window in windows:
                    try:
                        window.attributes("-alpha", alpha)
                    except:
                        pass
                root.after(settings['animation_duration'] // settings['animation_steps'], 
                          lambda: fade_out(step - 1))
            else:
                debug_print("Fade out complete, closing windows")
                close_windows()
        
        def close_windows():
            global currently_showing, active_windows
            for window in windows:
                try:
                    window.withdraw()
                    window.destroy()
                except:
                    pass
            active_windows = []
            currently_showing = False
        
        fade_in()
        
    except Exception as e:
        debug_print(f"ERROR in show_on_monitors: {e}")
        import traceback
        debug_print(traceback.format_exc())
        currently_showing = False

# --- LANGUAGE DETECTION ---
last_lang = None
last_detection_time = 0
DEBOUNCE_TIME = 0.1

def check_lang_change():
    global last_lang, last_detection_time
    
    consecutive_same = 0
    REQUIRED_SAME = 2
    temp_lang = None
    
    debug_print("Language detection thread started")
    
    while True:
        try:
            current_lang, current_hwnd = get_foreground_window_info()
            
            if current_lang is None:
                time.sleep(0.05)
                continue
            
            current_time = time.time()
            
            if current_lang != temp_lang:
                temp_lang = current_lang
                consecutive_same = 1
                debug_print(f"Language detected: {current_lang} (count: 1)")
            else:
                consecutive_same += 1
                if consecutive_same == REQUIRED_SAME:
                    debug_print(f"Language stable: {current_lang}")
            
            if (consecutive_same >= REQUIRED_SAME and 
                current_lang != last_lang and
                (current_time - last_detection_time) > DEBOUNCE_TIME):
                
                debug_print(f"Language changed from {last_lang} to {current_lang}")
                
                # Check if we have either flag or text for this language
                has_content = (settings['display_mode'] == 'flag' and current_lang in FLAG_IMAGES) or \
                             (settings['display_mode'] == 'text' and current_lang in LANGUAGE_TEXT)
                
                if has_content:
                    debug_print(f"Content available for {current_lang}, adding to queue")
                    last_lang = current_lang
                    last_detection_time = current_time
                    
                    while not flag_queue.empty():
                        try:
                            flag_queue.get_nowait()
                        except:
                            break
                    
                    flag_queue.put(current_lang)
                else:
                    debug_print(f"No content for language {current_lang}")
                    last_lang = current_lang
        
        except Exception as e:
            debug_print(f"Error in check_lang_change: {e}")
        
        time.sleep(0.05)

# --- PROCESS QUEUE ---
def process_queue():
    try:
        if not flag_queue.empty():
            latest_lang = None
            while not flag_queue.empty():
                try:
                    latest_lang = flag_queue.get_nowait()
                except:
                    break
            
            if latest_lang and not currently_showing:
                debug_print(f"Processing queue item: {latest_lang}")
                show_on_monitors(latest_lang)
    except Exception as e:
        debug_print(f"Error in process_queue: {e}")
    
    root.after(30, process_queue)

# --- SYSTEM TRAY ICON ---
def create_tray_icon():
    # Load icon from file or create default
    if os.path.exists(ICON_FILE):
        try:
            icon_image = PILImage.open(ICON_FILE)
        except:
            icon_image = PILImage.new('RGB', (64, 64), color='blue')
    else:
        icon_image = PILImage.new('RGB', (64, 64), color='blue')
    
    def open_settings(icon, item):
        root.after(0, lambda: SettingsWindow(root))
    
    def quit_app(icon, item):
        icon.stop()
        root.quit()
    
    menu = Menu(
        MenuItem('⚙️ Settings', open_settings),
        MenuItem('❌ Exit', quit_app)
    )
    
    icon = Icon("Flag Popup", icon_image, "Flag Popup", menu)
    
    threading.Thread(target=icon.run, daemon=True).start()

# --- MAIN ---
print("="*60)
print("Flag Popup - Language Indicator")
print("="*60)
print(f"Base directory: {BASE_DIR}")
print(f"Image directory: {IMAGE_DIR}")
print(f"Settings file: {CONFIG_FILE}")
print(f"Icon file: {ICON_FILE} - {'Found' if os.path.exists(ICON_FILE) else 'Not Found'}")
print("")

for lang_id, path in FLAG_IMAGES.items():
    exists = os.path.exists(path)
    status = "✓" if exists else "✗"
    print(f"{status} {lang_id}: {os.path.basename(path)}")

print("="*60)
print("Right-click system tray icon to open settings")
print("="*60)

root = tk.Tk()
root.withdraw()
root.attributes("-topmost", True)

# Set icon for main window if available
if os.path.exists(ICON_FILE):
    root.iconbitmap(ICON_FILE)

# Create system tray icon
create_tray_icon()

# Start threads
threading.Thread(target=check_lang_change, daemon=True).start()
root.after(30, process_queue)

try:
    root.mainloop()
except KeyboardInterrupt:
    print("\nExiting...")