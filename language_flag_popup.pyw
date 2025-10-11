import os
import time
import threading
import ctypes
import sys
from PIL import Image, ImageTk
import tkinter as tk
from screeninfo import get_monitors
from queue import Queue

# --- CONFIG ---
if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS  
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

IMAGE_DIR = os.path.join(BASE_DIR, "images")

FLAG_IMAGES = {
    '0x409': os.path.join(IMAGE_DIR, 'usa.png'),   # English
    '0x429': os.path.join(IMAGE_DIR, 'iran.png'),  # Persian
}
SHOW_TIME = 0.3  # seconds visible
SCREEN_WIDTH_PERCENT = 0.5  # 50% of screen width
ANIMATION_DURATION = 10  # milliseconds for fade in/out
ANIMATION_STEPS = 10  # number of steps in animation

# --- GET CURRENT INPUT LANGUAGE ---
def get_current_lang_id():
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    thread_id = ctypes.windll.user32.GetWindowThreadProcessId(hwnd, 0)
    klid = ctypes.windll.user32.GetKeyboardLayout(thread_id)
    lang_id = hex(klid & (2**16 - 1))
    return lang_id

def get_foreground_window_info():
    """Get both language and window handle"""
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    thread_id = ctypes.windll.user32.GetWindowThreadProcessId(hwnd, 0)
    klid = ctypes.windll.user32.GetKeyboardLayout(thread_id)
    lang_id = hex(klid & (2**16 - 1))
    return lang_id, hwnd

# Queue for thread-safe communication
flag_queue = Queue()
currently_showing = False  # Track if popup is currently showing
active_windows = []  # Track active windows globally

# --- SHOW FLAG ON ALL MONITORS ---
def show_flag_on_monitors(image_path):
    global currently_showing, active_windows
    
    # Force close ALL existing windows completely
    if active_windows:
        for window in active_windows:
            try:
                window.withdraw()  # Hide first
                window.destroy()  # Then destroy
            except:
                pass
        active_windows = []
        root.update()  # Force update to apply changes
        time.sleep(0.05)  # Give time for windows to close
    
    # Force reset the state
    currently_showing = True
    
    monitors = get_monitors()
    windows = []
    
    # Calculate image width based on first monitor
    img_width = int(monitors[0].width * SCREEN_WIDTH_PERCENT)
    
    # Load and resize image while maintaining aspect ratio
    img = Image.open(image_path)
    aspect_ratio = img.height / img.width
    new_height = int(img_width * aspect_ratio)
    img = img.resize((img_width, new_height), Image.LANCZOS)
    
    # Create ONE PhotoImage to share across all windows
    tk_img = ImageTk.PhotoImage(img)
    
    # Create fresh windows for each monitor
    for i, monitor in enumerate(monitors):
        # ALWAYS create new Toplevel windows
        window = tk.Toplevel(root)
        
        window.overrideredirect(True)
        window.attributes("-topmost", True)
        window.attributes("-transparentcolor", "black")
        window.configure(bg='black')
        
        # Use the SAME image reference for all windows
        label = tk.Label(window, image=tk_img, bg='black')
        label.image = tk_img  # Keep a reference!
        label.pack()
        
        # Center window on monitor
        x = monitor.x + (monitor.width - img_width) // 2
        y = monitor.y + (monitor.height - new_height) // 2
        window.geometry(f"{img_width}x{new_height}+{x}+{y}")
        
        # Start with transparent
        window.attributes("-alpha", 0.0)
        
        windows.append(window)
    
    active_windows = windows
    
    # Fade in animation
    def fade_in(step=0):
        if step <= ANIMATION_STEPS:
            alpha = step / ANIMATION_STEPS
            for window in windows:
                try:
                    window.attributes("-alpha", alpha)
                except:
                    pass
            root.after(ANIMATION_DURATION // ANIMATION_STEPS, lambda: fade_in(step + 1))
        else:
            # After fade in complete, schedule fade out
            root.after(int(SHOW_TIME * 1000), lambda: fade_out(ANIMATION_STEPS))
    
    # Fade out animation
    def fade_out(step=ANIMATION_STEPS):
        if step >= 0:
            alpha = step / ANIMATION_STEPS
            for window in windows:
                try:
                    window.attributes("-alpha", alpha)
                except:
                    pass
            root.after(ANIMATION_DURATION // ANIMATION_STEPS, lambda: fade_out(step - 1))
        else:
            # Close all windows after fade out
            close_windows()
    
    # Close all windows
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
    
    fade_in()  # Start fade in animation

# --- SMART LANGUAGE DETECTION ---
last_lang = None
last_hwnd = None
language_history = []  # Track recent language changes
HISTORY_SIZE = 5
MIN_STABLE_CHECKS = 3  # Language must be detected consistently

def check_lang_change():
    global last_lang, last_hwnd, language_history
    
    while True:
        try:
            current_lang, current_hwnd = get_foreground_window_info()
            
            # Add to history
            language_history.append(current_lang)
            if len(language_history) > HISTORY_SIZE:
                language_history.pop(0)
            
            # Check if language actually changed
            lang_changed = (current_lang != last_lang)
            
            # Check if it's stable (appeared multiple times in recent history)
            stable_count = language_history.count(current_lang)
            is_stable = (stable_count >= MIN_STABLE_CHECKS)
            
            # Only show if:
            # 1. Language changed
            # 2. Language is stable (not flickering)
            # 3. Window changed (optional: helps detect real switches)
            # 4. Not currently showing
            # 5. Language is in our list
            if (lang_changed and 
                is_stable and
                current_lang in FLAG_IMAGES and 
                not currently_showing):
                
                # Update tracking
                last_lang = current_lang
                last_hwnd = current_hwnd
                
                # Clear queue and add new request
                while not flag_queue.empty():
                    try:
                        flag_queue.get_nowait()
                    except:
                        break
                
                flag_queue.put(FLAG_IMAGES[current_lang])
            
            # Just update tracking even if not showing
            elif current_lang != last_lang and is_stable:
                last_lang = current_lang
                last_hwnd = current_hwnd
        
        except Exception as e:
            pass
        
        time.sleep(0.1)

# --- PROCESS QUEUE IN MAIN THREAD ---
def process_queue():
    try:
        if not flag_queue.empty() and not currently_showing:
            # Clear all but the last item in queue (only show latest)
            latest_image = None
            while not flag_queue.empty():
                try:
                    latest_image = flag_queue.get_nowait()
                except:
                    break
            
            if latest_image:
                show_flag_on_monitors(latest_image)
    except:
        pass
    root.after(50, process_queue)  # Check queue more frequently

# --- MAIN ---
root = tk.Tk()
root.withdraw()  # Hide the root window initially
root.attributes("-topmost", True)

# Start language checker thread
threading.Thread(target=check_lang_change, daemon=True).start()

# Start queue processor
root.after(50, process_queue)

print("Flag popup running with smart detection. Close this window to exit.")

try:
    root.mainloop()
except KeyboardInterrupt:
    print("\nExiting...")
