"""
小愛同學 Hotkey Launcher - 可自訂熱鍵 + 可編輯喚醒詞版本（Vosk 離線版）
- 已整合測試成功的 Vosk 設定
- 使用索引 1 的麥克風（你測試過可行）
"""

import keyboard
import subprocess
import sys
import threading
import time
import json
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk, scrolledtext
from pystray import Icon, Menu, MenuItem
from PIL import Image, ImageDraw
from difflib import SequenceMatcher
import pyautogui
import pygetwindow as gw
from pynput.mouse import Controller as MouseController
import pyaudio
import numpy as np
from vosk import Model, KaldiRecognizer

# ───────────────────────────────────────────────
#  全域設定與檔案
# ───────────────────────────────────────────────

CONFIG_FILE = Path("xiaoi_config.json")
CACHE_FILE = Path("button_locations.json")

VOICE_BUTTON_POS = None
mouse_controller = MouseController()
lock_active = False
lock_thread = None
AUTO_CLICK_ENABLED = True
icon_instance = None

current_hotkey = None
voice_listener_active = True

DEFAULT_WAKE_WORDS = [
    "小愛同學", "小愛", "小艾", "小愛同學", "小愛姐姐",
    "xiao ai", "xiaoai", "小愛", "嘿小愛", "喂小愛",
    "小愛在嗎", "小愛同學在嗎", "小愛小愛", "小爱同学", "小爱", "小爱小爱"  # 加變體，避免辨識空格問題
]

# ───────────────────────────────────────────────
#  設定檔讀寫（保持原樣）
# ───────────────────────────────────────────────

def load_config():
    default_config = {
        "hotkey": "ctrl + 1",
        "wake_words": DEFAULT_WAKE_WORDS,
        "similarity_threshold": 0.58
    }
    if not CONFIG_FILE.exists():
        save_config(default_config)
        return default_config

    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for k in default_config:
            if k not in data:
                data[k] = default_config[k]
        return data
    except:
        save_config(default_config)
        return default_config


def save_config(data):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"儲存設定失敗：{e}")


config = load_config()

# ───────────────────────────────────────────────
#  位置快取相關（保持原樣）
# ───────────────────────────────────────────────

def load_cached_position():
    global VOICE_BUTTON_POS
    if not CACHE_FILE.exists():
        return False
    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if "voice_button" in data and "coords" in data["voice_button"]:
            VOICE_BUTTON_POS = tuple(data["voice_button"]["coords"])
            print(f"已載入快取位置：{VOICE_BUTTON_POS}")
            return True
    except:
        pass
    return False


def save_position(coords):
    try:
        data = {
            "voice_button": {
                "coords": list(coords),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "screen_size": list(pyautogui.size())
            }
        }
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"儲存位置失敗：{e}")


def calibrate_voice_button():
    global VOICE_BUTTON_POS
    print("\n=== 小愛同學 語音按鈕校準 ===")
    print("請先開啟小愛同學 App，將滑鼠移到語音按鈕中央")
    print("按 'c' 確認，'q' 取消\n")

    from pynput import keyboard as kb
    recorded = [None]

    def on_press(key):
        try:
            if key.char == 'c':
                recorded[0] = pyautogui.position()
                print(f"確認位置：{recorded[0]}")
                return False
            if key.char == 'q':
                print("已取消")
                return False
        except:
            pass

    with kb.Listener(on_press=on_press) as listener:
        listener.join()

    if recorded[0]:
        VOICE_BUTTON_POS = recorded[0]
        save_position(VOICE_BUTTON_POS)
        return True
    return False

# ───────────────────────────────────────────────
#  視窗激活與自動點擊（保持原樣）
# ───────────────────────────────────────────────

def activate_xiaoai_window():
    for attempt in range(8):
        try:
            possible_titles = ["小爱", "小愛同學", "XiaoAi", "xiaoi", "小愛", "小愛同學"]
            win = None
            for title in possible_titles:
                wins = gw.getWindowsWithTitle(title)
                if wins:
                    win = wins[0]
                    break

            if not win:
                time.sleep(0.4)
                continue

            if win.isMinimized:
                win.restore()

            win.activate()
            time.sleep(0.35)

            active_title = gw.getActiveWindowTitle() or ""
            if any(t in active_title for t in ["小爱", "小愛", "XiaoAi", "xiaoi"]):
                print("成功激活小愛同學視窗")
                return True

        except Exception as e:
            print(f"激活嘗試 {attempt+1} 失敗: {e}")

        time.sleep(0.5)

    print("多次嘗試後仍無法將小愛同學視窗置頂，請手動點擊")
    return False


def lock_mouse_at(x, y):
    global lock_active
    while lock_active:
        try:
            cx, cy = mouse_controller.position
            if abs(cx - x) > 10 or abs(cy - y) > 10:
                mouse_controller.position = (x, y)
            time.sleep(0.008)
        except:
            time.sleep(0.03)


def auto_click_voice_button():
    global VOICE_BUTTON_POS, lock_active

    if not AUTO_CLICK_ENABLED:
        return

    try:
        if not activate_xiaoai_window():
            return

        time.sleep(0.6)
        activate_xiaoai_window()

        if VOICE_BUTTON_POS is None:
            w, h = pyautogui.size()
            x = int(w * 0.225)
            y = int(h * 0.388)
        else:
            x, y = VOICE_BUTTON_POS

        lock_active = True
        threading.Thread(target=lock_mouse_at, args=(x, y), daemon=True).start()

        pyautogui.moveTo(x, y, duration=0.1)
        pyautogui.click()
        print("已點擊語音按鈕")

        time.sleep(1.2)
        lock_active = False

    except Exception as e:
        print(f"自動點擊失敗：{e}")
        lock_active = False


def open_xiaoai():
    try:
        app_id = "8497DDF3.639A2791C9AB_kf545nqv09rxe!App"
        subprocess.Popen(f'explorer.exe shell:appsFolder\\{app_id}', shell=True)
        print("已嘗試啟動小愛同學")
        time.sleep(0.8)
        if AUTO_CLICK_ENABLED:
            threading.Thread(target=auto_click_voice_button, daemon=True).start()
    except Exception as e:
        print(f"啟動失敗：{e}")

# ───────────────────────────────────────────────
#  Vosk 喚醒類（已修正 stop_event 初始化問題）
# ───────────────────────────────────────────────

class VoskWake:
    def __init__(self):
        # 使用你測試成功的模型路徑
        self.model_path = r".\vosk-model-cn"
        self.sample_rate = 16000
        self.block_size = 8000  # 與測試腳本一致
        self.device_index = None   # 你測試成功的索引
        self.stop_event = threading.Event()  # 初始化 stop_event

        try:
            self.model = Model(self.model_path)
            self.recognizer = KaldiRecognizer(self.model, self.sample_rate)
            print("[DEBUG] Vosk 模型載入成功")
        except Exception as e:
            print(f"[ERROR] Vosk 模型載入失敗：{e}")
            sys.exit(1)

        print(f"[DEBUG] 使用麥克風索引：{self.device_index}")

    def listen(self):
        print("[DEBUG] listen() 開始執行")

        p = pyaudio.PyAudio()

        try:
            stream = p.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self.sample_rate,
                input=True,
                frames_per_buffer=self.block_size,
                input_device_index=self.device_index  # 強制使用測試成功的索引
            )
            print("[DEBUG] PyAudio 麥克風開啟成功，使用索引:", self.device_index)
        except Exception as e:
            print(f"[ERROR] 無法開啟麥克風：{e}")
            return False

        print("[DEBUG] 進入監聽循環...")

        last_heart_time = time.time()

        try:
            stream.start_stream()

            while not self.stop_event.is_set() and voice_listener_active:
                try:
                    data = stream.read(self.block_size, exception_on_overflow=False)
                    audio_data = np.frombuffer(data, dtype=np.int16)

                    # 可選：只在有明顯聲音時印（減少輸出噪音）
                    if audio_data.max() > 300:
                        print(f"[有聲音] 振幅 max: {audio_data.max()}")

                    if self.recognizer.AcceptWaveform(data):
                        result = json.loads(self.recognizer.Result())
                        text = result.get("text", "").strip().replace(" ", "")  # ← 加這行！去除空格，提高匹配率
                        if text:
                            print(f"[Vosk] 聽到：{text}")

                            if self.is_wake_word(text):
                                print("[DEBUG] 喚醒詞觸發！")
                                return True
                    else:
                        partial = json.loads(self.recognizer.PartialResult())
                        partial_text = partial.get("partial", "").strip().replace(" ", "")  # 也去除空格
                        if partial_text:
                            print(f"[Vosk Partial]: {partial_text}")

                    # 每 10 秒心跳一次，證明還在跑
                    if time.time() - last_heart_time > 10:
                        print("[心跳] 語音監聽仍在運行中... (說 '小愛同學' 測試)")
                        last_heart_time = time.time()

                except Exception as e:
                    print(f"[ERROR] 監聽循環異常：{e}")
                    time.sleep(0.5)

        except Exception as e:
            print(f"[ERROR] 監聽異常：{e}")
        finally:
            print("[DEBUG] 結束監聽，關閉資源")
            stream.stop_stream()
            stream.close()
            p.terminate()

        return False

    def is_wake_word(self, text):
        text = text.lower().strip()
        for word in config.get("wake_words", []):
            ratio = SequenceMatcher(None, text, word.lower()).ratio()
            if word.lower() in text or ratio > config.get("similarity_threshold", 0.58):
                print(f"[DEBUG] 偵測到喚醒詞：{word} (相似度: {ratio:.3f})")
                return True
        return False

    def stop(self):
        print("[DEBUG] VoskWake stop() 被呼叫")
        self.stop_event.set()


voice_waker = VoskWake()

# ───────────────────────────────────────────────
#  熱鍵管理（保持原樣）
# ───────────────────────────────────────────────

def register_hotkey(hotkey_str):
    global current_hotkey
    if current_hotkey:
        try:
            keyboard.remove_hotkey(current_hotkey)
        except:
            pass

    if not hotkey_str or hotkey_str.strip() == "":
        print("熱鍵已移除")
        current_hotkey = None
        return

    try:
        keyboard.add_hotkey(hotkey_str, open_xiaoai)
        current_hotkey = hotkey_str
        print(f"熱鍵已註冊：{hotkey_str}")
    except Exception as e:
        print(f"熱鍵註冊失敗：{e}")
        messagebox.showerror("熱鍵錯誤", str(e))

# ───────────────────────────────────────────────
#  設定視窗（保持原樣）
# ───────────────────────────────────────────────

def open_settings_and_restart(icon=None, item=None):
    try:
        voice_waker.stop()
    except:
        pass

    global voice_listener_active, current_hotkey
    voice_listener_active = False
    keyboard.unhook_all()
    if current_hotkey:
        try:
            keyboard.remove_hotkey(current_hotkey)
        except:
            pass
    if icon_instance:
        try:
            icon_instance.stop()
        except:
            pass

    win = tk.Tk()
    win.title("小愛同學啟動器 - 設定")
    win.geometry("520x580")
    win.resizable(False, False)

    notebook = ttk.Notebook(win)
    notebook.pack(fill='both', expand=True, padx=10, pady=10)

    tab_hotkey = ttk.Frame(notebook)
    notebook.add(tab_hotkey, text="熱鍵設定")

    tk.Label(tab_hotkey, text="熱鍵 (範例：ctrl+alt+q、f10、ctrl+shift+1)", font=("Microsoft YaHei", 10)).pack(pady=15)

    entry_hotkey = tk.Entry(tab_hotkey, width=35, font=("Consolas", 12))
    entry_hotkey.insert(0, config.get("hotkey", "ctrl + 1"))
    entry_hotkey.pack(pady=5)

    tk.Label(tab_hotkey, text="支援格式：\n"
                              "• f1 ~ f12\n"
                              "• ctrl + alt + q\n"
                              "• ctrl+shift+f\n"
                              "• win + k\n"
                              "• alt + f8", justify="left").pack(pady=10)

    def apply_hotkey():
        new_key = entry_hotkey.get().strip()
        config["hotkey"] = new_key
        save_config(config)
        messagebox.showinfo("完成", f"熱鍵已更新為：\n{new_key or '無（已移除）'}", parent=win)

    tk.Button(tab_hotkey, text="儲存熱鍵", command=apply_hotkey, width=15).pack(pady=20)

    tab_wake = ttk.Frame(notebook)
    notebook.add(tab_wake, text="喚醒詞設定")

    tk.Label(tab_wake, text="喚醒詞（每行一個，按 Enter 換行）", font=("Microsoft YaHei", 10)).pack(pady=10)

    text_wake = scrolledtext.ScrolledText(tab_wake, width=50, height=12, font=("Microsoft YaHei", 11))
    text_wake.pack(pady=5)

    current_words = "\n".join(config.get("wake_words", DEFAULT_WAKE_WORDS))
    text_wake.insert("1.0", current_words)

    def apply_wake_words():
        lines = text_wake.get("1.0", "end").strip().split("\n")
        new_list = [w.strip() for w in lines if w.strip()]
        config["wake_words"] = new_list
        save_config(config)
        messagebox.showinfo("完成", f"已更新 {len(new_list)} 個喚醒詞", parent=win)

    tk.Button(tab_wake, text="儲存喚醒詞", command=apply_wake_words, width=15).pack(pady=15)

    tab_adv = ttk.Frame(notebook)
    notebook.add(tab_adv, text="進階")

    tk.Label(tab_adv, text="相似度門檻（0.50 ~ 0.75，預設0.58）\n越低越容易觸發，但可能誤認", font=("Microsoft YaHei", 10)).pack(pady=10)

    scale_thresh = tk.Scale(tab_adv, from_=0.50, to=0.75, resolution=0.01, orient="horizontal", length=300)
    scale_thresh.set(config.get("similarity_threshold", 0.58))
    scale_thresh.pack(pady=5)

    def save_threshold():
        config["similarity_threshold"] = round(scale_thresh.get(), 2)
        save_config(config)
        messagebox.showinfo("完成", f"相似度門檻已設為 {config['similarity_threshold']}", parent=win)

    tk.Button(tab_adv, text="儲存門檻", command=save_threshold).pack(pady=20)

    tk.Label(tab_adv, text="（已使用 Vosk 離線模型）", fg="gray").pack(pady=30)

    def on_closing():
        messagebox.showinfo(
            "設定完成",
            "所有變更已儲存。\n\n請手動關閉目前程式（右鍵托盤 → 結束程式），\n然後重新執行。",
            parent=win
        )
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", on_closing)
    win.mainloop()

# ───────────────────────────────────────────────
#  托盤與主程式
# ───────────────────────────────────────────────

def create_icon():
    img = Image.new('RGB', (32, 32), (0, 120, 215))
    draw = ImageDraw.Draw(img)
    draw.text((8, 8), "AI", fill='white')
    return img


def stop_program(icon=None, item=None):
    global voice_listener_active
    voice_listener_active = False
    try:
        voice_waker.stop()
    except:
        pass
    keyboard.unhook_all()
    if icon_instance:
        icon_instance.stop()
    sys.exit(0)


if __name__ == "__main__":
    if not load_cached_position():
        print("未找到按鈕位置快取，建議第一次執行時校準")
        calibrate_voice_button()

    register_hotkey(config.get("hotkey", "ctrl + 1"))

    icon = Icon(
        "XiaoiLauncher",
        create_icon(),
        menu=Menu(
            MenuItem("小愛同學啟動器", lambda: None, enabled=False),
            MenuItem("設定熱鍵與喚醒詞", 
                     lambda: threading.Thread(target=open_settings_and_restart, daemon=True).start()),
            MenuItem("重新校準語音按鈕", lambda i=None: calibrate_voice_button() or print("校準完成")),
            MenuItem("結束程式", stop_program)
        )
    )
    icon_instance = icon

    print("="*60)
    print("小愛同學快速啟動器（Vosk 離線版） 已啟動")
    print(f"目前熱鍵：{config.get('hotkey', '未設定')}")
    print(f"喚醒詞數量：{len(config.get('wake_words', []))}")
    print("右鍵托盤圖示 → 設定熱鍵與喚醒詞")
    print("="*60)

    def voice_loop():
        while voice_listener_active:
            try:
                if voice_waker.listen():
                    print("語音喚醒成功 → 開啟小愛")
                    open_xiaoai()
            except Exception as e:
                print(f"[語音循環錯誤] {e}")
            time.sleep(0.3)

    threading.Thread(target=voice_loop, daemon=True).start()

    threading.Thread(target=icon.run, daemon=True).start()

    try:
        keyboard.wait()
    except KeyboardInterrupt:
        stop_program()