import os
import re
import sys
import requests
import threading
import subprocess
from urllib.parse import urlparse
from tkinter import filedialog, messagebox, ttk
import tkinter as tk
import webbrowser
import base64

# PIL and cv2 for image/video preview
from PIL import Image, ImageTk
import io
try:
    import cv2
except ImportError:
    cv2 = None


# Worker settings constants
DEFAULT_WORKERS = 5
MIN_WORKERS = 1
MAX_WORKERS = 100

def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', '_', name).strip()

def get_file_type_folder(filename):
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".bin":
        return None
    if ext in [".mp4", ".webm", ".mov", ".avi", ".mkv"]:
        return "Videos"
    elif ext in [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"]:
        return "Pictures"
    elif ext in [".zip", ".rar", ".7z"]:
        return "Zips"
    return "Other"

def extract_domain_service_id(url):
    parsed = urlparse(url)
    domain = parsed.netloc
    parts = parsed.path.strip("/").split("/")
    if len(parts) < 3 or parts[1] != "user":
        raise ValueError(f"Invalid URL: {url}")
    return domain, parts[0], parts[2]

def get_creator_name(domain, service, creator_id):
    try:
        r = requests.get(f"https://{domain}/api/v1/{service}/user/{creator_id}/profile")
        if r.ok:
            data = r.json()
            return sanitize_filename(data.get("name") or creator_id)
    except:
        pass
    return creator_id

def get_creator_posts(domain, service, creator_id):
    r = requests.get(f"https://{domain}/api/v1/{service}/user/{creator_id}")
    r.raise_for_status()
    return r.json()

def download_file(url, save_dir, file_label, artist_bar, file_bar, log_box):
    try:
        file_name = os.path.basename(urlparse(url).path)
        file_label.set(f"Downloading: {file_name}")
        subfolder = get_file_type_folder(file_name)
        if subfolder is None:
            log_box.insert(tk.END, f"[SKIP] {file_name} (unsupported type)\n")
            return
        target_folder = os.path.join(save_dir, subfolder)
        os.makedirs(target_folder, exist_ok=True)
        path = os.path.join(target_folder, file_name)

        if os.path.exists(path):
            log_box.insert(tk.END, f"[SKIP] {file_name}\n")
            return

        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, stream=True, headers=headers)
        total = int(r.headers.get("content-length", 0))
        downloaded = 0

        def update_progress(value):
            file_bar["value"] = value

        with open(path, 'wb') as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    percent = int(downloaded * 100 / total)
                    file_bar.after_idle(update_progress, percent)

        log_box.insert(tk.END, f"[OK] {file_name}\n")
        file_bar["value"] = 0
    except Exception as e:
        log_box.insert(tk.END, f"[ERROR] {file_name} — {e}\n")

def start_gui():
    root = tk.Tk()
    root.title("KemonoDrive")
    root.geometry("780x600")
    root.configure(bg="#111111")

    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("TLabel", background="#000000", foreground="white", font=("Segoe UI", 10))
    style.configure("TButton", font=("Segoe UI", 10), padding=6)
    style.configure("TEntry", fieldbackground="#111111", foreground="white")
    style.configure("TFrame", background="#000000")
    style.configure("TText", background="#000000", foreground="white")

    output_dir = tk.StringVar(value=os.path.abspath("Output"))
    file_status = tk.StringVar()
    artist_bar = None
    file_bar = None
    log_box = None
    url_box = None

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True)

    # Settings Tab
    settings_tab = ttk.Frame(notebook)
    notebook.add(settings_tab, text="Settings")

    # Worker settings variable (single value)
    worker_count = tk.IntVar(value=DEFAULT_WORKERS)

    ttk.Label(settings_tab, text="Number of Workers:").pack(anchor="w", padx=10, pady=(10, 0))
    ttk.Spinbox(settings_tab, from_=MIN_WORKERS, to=MAX_WORKERS, textvariable=worker_count, width=5).pack(anchor="w", padx=10)

    dl_tab = ttk.Frame(notebook)
    notebook.add(dl_tab, text="Download")

    ttk.Label(dl_tab, text="Profile URLs (one per line):").pack(anchor="w", padx=10, pady=(10, 0))
    url_box = tk.Text(dl_tab, height=6, bg="#2e2e2e", fg="white", insertbackground="white")
    url_box.pack(fill="x", padx=10)
    url_count_label = ttk.Label(dl_tab, text="URLs: 0")
    url_count_label.pack(anchor="w", padx=10, pady=(0, 5))

    folder_frame = ttk.Frame(dl_tab)
    folder_frame.pack(fill="x", padx=10, pady=(5, 5))
    ttk.Label(folder_frame, text="Output Folder:").pack(side="left")
    ttk.Entry(folder_frame, textvariable=output_dir, width=60).pack(side="left", padx=5)
    ttk.Button(folder_frame, text="Browse", command=lambda: output_dir.set(filedialog.askdirectory())).pack(side="left", padx=5)

    ttk.Label(dl_tab, textvariable=file_status).pack(anchor="w", padx=10, pady=(5, 0))
    artist_bar = ttk.Progressbar(dl_tab, mode="determinate")
    artist_bar.pack(fill="x", padx=10, pady=(2, 2))
    file_bar = ttk.Progressbar(dl_tab, mode="determinate")
    file_bar.pack(fill="x", padx=10)

    # Preview label for image/video preview
    preview_label = ttk.Label(dl_tab)
    preview_label.pack(anchor="center", pady=(5, 5))

    ttk.Label(dl_tab, text="Download Log:").pack(anchor="w", padx=10, pady=(10, 2))
    log_box = tk.Text(dl_tab, height=10, bg="#2e2e2e", fg="lightgray", insertbackground="white")
    log_box.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def start_download():
        urls = url_box.get("1.0", "end").strip().splitlines()
        out = output_dir.get()
        if not urls:
            messagebox.showerror("Error", "Please enter profile URLs.")
            return
        os.makedirs(out, exist_ok=True)
        log_box.delete("1.0", tk.END)

        def update_preview(path):
            try:
                # Clear text if previously set
                preview_label.config(text="")
                if path.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif')):
                    img = Image.open(path)
                    img.thumbnail((200, 200))
                    preview_img = ImageTk.PhotoImage(img)
                    preview_label.config(image=preview_img)
                    preview_label.image = preview_img
                elif cv2 and path.lower().endswith(('.mp4', '.webm', '.mov', '.avi', '.mkv')):
                    cap = cv2.VideoCapture(path)
                    success, frame = cap.read()
                    if success:
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        img = Image.fromarray(frame)
                        img.thumbnail((200, 200))
                        preview_img = ImageTk.PhotoImage(img)
                        preview_label.config(image=preview_img)
                        preview_label.image = preview_img
                    else:
                        preview_label.config(image='', text='[No Preview]')
                    cap.release()
                else:
                    preview_label.config(image='', text='[No Preview]')
            except Exception as e:
                preview_label.config(image='', text='[Preview Error]')

        def worker():
            from concurrent.futures import ThreadPoolExecutor, as_completed
            for url in urls:
                try:
                    domain, service, cid = extract_domain_service_id(url)
                    creator = get_creator_name(domain, service, cid)
                    save_dir = os.path.join(out, creator)
                    os.makedirs(save_dir, exist_ok=True)
                    posts = get_creator_posts(domain, service, cid)
                    files = []
                    for post in posts:
                        files += [f"https://{domain}/data{a['path']}" for a in post.get("attachments", []) if "path" in a]
                        if post.get("file") and "path" in post["file"]:
                            files.append(f"https://{domain}/data{post['file']['path']}")

                    artist_bar["value"] = 0
                    artist_bar["maximum"] = len(files)
                    log_box.insert(tk.END, f"== {creator} ({len(files)} files) ==\n")

                    def task(url):
                        # call download_file with preview update after download
                        file_path = None
                        try:
                            file_name = os.path.basename(urlparse(url).path)
                            subfolder = get_file_type_folder(file_name)
                            if subfolder is None:
                                log_box.insert(tk.END, f"[SKIP] {file_name} (unsupported type)\n")
                                return None
                            target_folder = os.path.join(save_dir, subfolder)
                            os.makedirs(target_folder, exist_ok=True)
                            path = os.path.join(target_folder, file_name)
                            file_path = path
                            if os.path.exists(path):
                                log_box.insert(tk.END, f"[SKIP] {file_name}\n")
                                return path
                            headers = {"User-Agent": "Mozilla/5.0"}
                            r = requests.get(url, stream=True, headers=headers)
                            total = int(r.headers.get("content-length", 0))
                            downloaded = 0

                            def update_progress(value):
                                file_bar["value"] = value
                            with open(path, 'wb') as f:
                                for chunk in r.iter_content(8192):
                                    f.write(chunk)
                                    downloaded += len(chunk)
                                    if total:
                                        percent = int(downloaded * 100 / total)
                                        root.after_idle(update_progress, percent)
                            log_box.insert(tk.END, f"[OK] {file_name}\n")
                            # After download, reset file_bar using after_idle in main thread
                            root.after_idle(lambda: file_bar.config(value=0))
                            return path
                        except Exception as e:
                            log_box.insert(tk.END, f"[ERROR] {os.path.basename(urlparse(url).path)} — {e}\n")
                            return None

                    # Use the value from the settings tab for max_workers
                    with ThreadPoolExecutor(max_workers=worker_count.get()) as executor:
                        futures = [executor.submit(task, file_url) for file_url in files]
                        for i, future in enumerate(as_completed(futures)):
                            result_path = future.result()
                            # Update artist_bar in main thread using after_idle
                            root.after_idle(lambda i=i: artist_bar.config(value=i + 1))
                            # Only update preview if file was successfully downloaded or exists
                            if result_path and os.path.exists(result_path):
                                # Use after_idle to update preview in main thread
                                root.after_idle(update_preview, result_path)

                except Exception as e:
                    log_box.insert(tk.END, f"[ERROR] {url} — {e}\n")

            file_status.set("Done.")

        threading.Thread(target=worker).start()

    ttk.Button(dl_tab, text="Start Download", command=start_download).pack(pady=(5, 10))

    browse_tab = ttk.Frame(notebook)
    notebook.add(browse_tab, text="Browse")

    # Set the active tab to the Download tab on startup
    notebook.select(dl_tab)

    search_mode = tk.StringVar(value="kemono")
    search_entry = tk.StringVar()
    selected_artists = {}
    artist_lookup = {}

    COOMER_PLATFORMS = ["onlyfans", "fansly", "candfans"]
    KEMONO_PLATFORMS = ["patreon", "fanbox", "discord", "fantia", "afdian", "boosty", "gumroad", "subscribestar", "dlsite"]

    mode_frame = ttk.Frame(browse_tab)
    mode_frame.pack(pady=10, padx=10, anchor="w")
    ttk.Label(mode_frame, text="Mode:").pack(side="left")
    ttk.Radiobutton(mode_frame, text="Kemono", variable=search_mode, value="kemono").pack(side="left", padx=5)
    ttk.Radiobutton(mode_frame, text="Coomer", variable=search_mode, value="coomer").pack(side="left", padx=5)

    search_platform = tk.StringVar(value="Any")
    platform_menu = ttk.OptionMenu(mode_frame, search_platform, "Any", *["Any"])
    platform_menu.pack(side="left", padx=10)

    search_frame = ttk.Frame(browse_tab)
    search_frame.pack(padx=10, pady=(0, 10), fill="x")
    search_entry_box = ttk.Entry(search_frame, textvariable=search_entry, width=40)
    search_entry_box.pack(side="left", fill="x", expand=True)
    search_entry_box.bind("<Return>", lambda e: threading.Thread(target=lambda: search_artists(search_entry.get(), search_mode.get())).start())
    ttk.Button(
        search_frame,
        text="Search",
        command=lambda: threading.Thread(target=lambda: search_artists(search_entry.get(), search_mode.get())).start()
    ).pack(side="left", padx=5)

    results_canvas = tk.Canvas(browse_tab, bg="#2e2e2e", highlightthickness=0)
    results_scrollbar = ttk.Scrollbar(browse_tab, orient="vertical", command=results_canvas.yview)
    results_frame = ttk.Frame(results_canvas)

    results_frame.bind(
        "<Configure>",
        lambda e: results_canvas.configure(
            scrollregion=results_canvas.bbox("all")
        )
    )

    results_canvas.create_window((0, 0), window=results_frame, anchor="nw")
    results_canvas.configure(yscrollcommand=results_scrollbar.set)

    results_canvas.pack(side="left", fill="both", expand=True, padx=(10,0), pady=(0,10))
    results_scrollbar.pack(side="right", fill="y", pady=(0,10))

    def update_url_box():
        existing_urls = set(url_box.get("1.0", "end").strip().splitlines())
        new_urls = set()
        domain = "kemono.su" if search_mode.get() == "kemono" else "coomer.su"
        for display, (var, service, uid) in selected_artists.items():
            if var.get():
                url = f"https://{domain}/{service}/user/{uid}"
                new_urls.add(url)
        # Fix unchecked URLs domain logic
        unchecked_urls = {
            f"https://{domain}/{s}/user/{u}"
            for display, (var, s, u) in selected_artists.items()
            if not var.get()
        }
        final_urls = (existing_urls - unchecked_urls) | new_urls
        url_box.delete("1.0", tk.END)
        for url in sorted(final_urls):
            url_box.insert(tk.END, url + "\n")
        url_count_label.config(text=f"URLs: {len(final_urls)}")

    def on_checkbutton_toggle():
        update_url_box()

    def search_artists(term, mode):
        for widget in results_frame.winfo_children():
            widget.destroy()
        selected_artists.clear()
        artist_lookup.clear()
        term = term.strip().lower()
        log_box.insert(tk.END, f"Searching '{term}' on {mode}...\n")
        selected_mode = search_mode.get()
        selected_platform = search_platform.get().lower()
        try:
            resp = requests.get(f"https://{selected_mode}.su/api/v1/creators.txt")
            resp.raise_for_status()
            all_creators = resp.json()
        except Exception as e:
            label = tk.Label(results_frame, text=f"[ERROR] Failed to fetch creators.txt — {e}", background="#2e2e2e", foreground="red")
            label.pack(anchor="w", padx=5, pady=2)
            return

        filtered = []
        for artist in all_creators:
            if selected_platform != "any" and artist["service"] != selected_platform:
                continue
            if not term or term in artist.get("name", "").lower():
                filtered.append(artist)

        filtered.sort(key=lambda a: a.get("favorited", 0), reverse=True)

        domain = f"https://{search_mode.get()}.su"
        for artist in filtered:
            try:
                r = requests.get(f"{domain}/api/v1/{artist['service']}/user/{artist['id']}")
                post_count = len(r.json()) if r.ok else "?"
            except:
                post_count = "?"
            display = f"{artist['name']} ({artist['service']}) - {artist.get('favorited', 0)}★ | {post_count} files"
            var = tk.BooleanVar()
            cb = ttk.Checkbutton(results_frame, text=display, variable=var, style="TCheckbutton", command=on_checkbutton_toggle)
            cb.pack(anchor="w", padx=5, pady=2)
            selected_artists[display] = (var, artist["service"], artist["id"])
            artist_lookup[display] = (artist["service"], artist["id"])

    footer = ttk.Frame(root, padding=5)
    footer.pack(side="bottom", fill="x")


    github_base64 = (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAACXBIWXMAAAsTAAALEwEAmpwYAAAFfUlEQVR4nO2Z20sjVxzHR0tLu/QG7fZp2z9ACoVOHDNJdJI4mcxkotgWr9UnFQQv9cFL8RbxwY24also26UPImjFiu2DVBHRBx/ESx+sbkFQtGIsqHW90EQTSU75HXZCms3EyWXcF7/wgzAz0e/n/H5zzvmdEMSd7nSnhJWfn/9KdnY2bTabW8xm84TJZPrTZDI9MxqNPgiGYZ5lZWU9zczMnDAYDC16vV5LEEQq8bLFcdyHFovFybKsKzs7G0GYzWYcJpMJGY1GHAzD4MjKykKZmZk49Hr9vsFgeEhR1INbN87z/H2O456wLOu1WCyIZVkUK4DBYMCh1+u9NE0/Zhjm/Vsxz3FcicViOeE4DoH5JAAgnU4H8Q9N00WqGSdJ8lWe53+0Wq0IzKsAgGiahvgB/ldSzdvt9ntWq3WK53l0CwBIq9X+RpLkvWSOPDZ/iwCIoqjZtLS01xIGgLIRBAGbhwDjklkIMJ8IgE6nQxkZGThCAZ5fe5yo+S/BfCgAjHhPTw+amZlB/f39KDc3F5sF0xKAZD7UeDgAGBUEAfX29qKpqSnU1taGjYcBII1GUxiX+by8vPcEQTgOBwCD29vbSNLl5SUaGRnBpSUZLioqQpWVlai+vh5HRUUFKigoCJYLZGx0dBR5vd7g31lbW4OyeQEgPT39hCTJ2KdYURSf2Gw2FA4A4ff7UbgODw/R+vo6BpKTx+PBRo+Pj1+4d3V1FREArlEU9X1M5nmef2Cz2byRAHJycpBaouQBvCRJfhTL6DtFUUSRAOAljjbK8er8/BzKRQ4A3oWHisw7HI5UURT35QDgHdjY2Eg6wPLycrQMAIALNo03AtjtdhrMRwKA0W9tbUWBQCDpAIFAANXV1WHzkQAgOyRJUkrKp0UOAKbQ/f19pJb29vaw6SgAXyvJwC+RAGCabG5uRmqruro6aD4cQKPRjCvJwNNIAFA+Y2NjqgMMDQ1hwzIA60oycBIJAMpnYWFBdYDZ2VlsVgbgWEkGvJEAYPVcWVlRHWBxcTEawJUSALdcBubn51UHmJ6ejgbwr5IS+kvuHRgfH1cdYHh4WPYdIElyVwnA73KzUGdnp+oAjY2N0WahZSUA43LrAGyd3W63aubdbjde6aOsA2NKAOqiLWSQYrU0ODgYdSHTaDTVNwKIoviJHIDUTsK2Odna3NwMNjpRAD6OazMnmZf2Q1BKS0tLSd3IcRwXsSMLAdgjCCKFUCKbzdYqAYBp6LBqamqCTTwE1KrD4UBbW1txG9/Z2UEdHR1B4xF64lCAm/dBoSdvoiheAgCM/MDAAO7CoHRqa2vxoiY199D7lpSU4GcmJyfR6emprGG4B89AL11YWIiNSicS4acSYQBXNE1/QMQiURS/k0oIRryhoSHYEpaWlv4vGwACjTxch9ZQTj6fD5WVleHe+KZjlYwQgPT09G9iMv88C28LguAKXcicTic6OjrCWwooMciEBACZgFX0Js3NzWGzMQD8TZLkO0Q8EgThi0j9wMHBAYaA+i0uLsbR1dWFLi4ubgQ4OzvDBmMAyIvLfEgmHoV2ZO3t7bh7glhdXUW7u7vI5XLhXaQSwfeUAlAU5SSSoBRBEH6SemIol+7u7oRWZIUAPyftR5D8/Pw3eJ6fkNYDgIDPTU1NqK+vD5+uQbemtFdWADDOMMzrRJKVYrVaO0MPd0PPReHYMBkAWq32W1V/frJarZ9zHOcKP51OAsC+Vqv9jLgN5ebmvsVxXD/LsleJAuh0ukudTveIYZg3idsWwzDvsiz7ldls3q2qqkJKVV5eDuVyoNfrOw0Gw33iZQshlHp0dPTp6elpg8fj+dXn861fX18f+P1+DwR89vl8f8A9eAaehe8Qd7rTnYhE9R+kV7M+FoRFRQAAAABJRU5ErkJggg=="
    )
    github_img_data = base64.b64decode(github_base64)
    github_img = ImageTk.PhotoImage(Image.open(io.BytesIO(github_img_data)).resize((20, 20)))
    github_label = tk.Label(footer, image=github_img, text=" AlexSpaces", compound="left", cursor="hand2", bg="#000000", fg="white")
    github_label.image = github_img
    github_label.pack(side="left", padx=(10, 20))
    github_label.bind("<Button-1>", lambda e: webbrowser.open_new("https://github.com/alexspaces"))

    github_label2 = tk.Label(footer, image=github_img, text=" RandomSideProjects", compound="left", cursor="hand2", bg="#000000", fg="white")
    github_label2.image = github_img
    github_label2.pack(side="left", padx=(10, 20))
    github_label2.bind("<Button-1>", lambda e: webbrowser.open_new("https://github.com/RandomSideProjects"))

    discord_base64 = (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAACXBIWXMAAAsTAAALEwEAmpwYAAADt0lEQVR4nO1ZTWhdRRR+rb+tvwvBP9CF6FZRpOpCFyK4SJPcM7lIbSG7J757znumWhFEX7XahRtFF+IP1rpSEHEhgjtFQbAVtPhDUWusWJq2WjEqNfbrJ/MS08TcuZmbPHuzuAfO5jHfnO87c2buzHmNRm211VZbbVXZcMZrRowbxfB4mvK0WJwf6wzbJOPd0ubVjVNl3S5XJxnvEMVLzrDf2QnOunJD7Dxe9FysKH4Qw4uuzdt9jL4TlxavdIatzjA+j/Q8AfhKjOudMXOKJ5zhGad4Ycaf9r8lypYfI4ovC+b5XoyPpm1e0RfyzviAKBAM+D+5KCDGzcvOvCh+P9Xk3UkRfw4br1pG9vFOVeTdSRHvLZE8h6om7/71jAMl6XOVKHZXTtxmVsGwp9TpJMrhqkm7BaXEu0qUDz5deQKwO458h+uqJutC3uG6iPLxX9kVQNZyVsGws5B82uK5YphcwQIm0zGuCQpI2kyqJukW8STjYLh8/IUqPhtTong1MZoYnvR3mHgiGHeK7R7rDDtE8VcJ7I7wBlb8GEn+l7TNG+ZiR0d5tijejsC+O9Dk2nkrr7xWFIciBewvuHFGZkG5KbSHnOJAkLzicNrkBbnlaxyJjZ+O8fKl17/i6G1dnh5cRcNTBdhnQ7hul6udYSKqAjK6vMDbIgV8HCLRm6fN0RB2RHlPEVYU70dyeCwP/EZkDX5WSMJ4b0HmOoXiFZ9ECngtbwU+igT/vWEzLwqSMLxegH0rhBvq8EKnOBZVQooPczKHfdGb2PBcHom0w+u8wGBgw/GkzRtL7x1bMM++PAG/xgvoZXO7Pzpn8S3e6gw/RYif8I/3WdFdnunfwM5wokQCJ/Iy8EcpAdMijjrFB86wtyxWDN94rCh+XkLc3/JWYKr0RBW5GKYWCij1Oa9cwGSegMNVE3PxJXRg4R5QfBupfo8Yvuh7VhWfFza85jn25m3irTENLFE+2GzyjDTjzc7wslMcXEYmD/oHVGK8aeY0ejgigced8pFQK+WWqBNF8Z0odXALz/MdjCTj9b0OnmGnGHY5w5FeoLlBp3/b1Ruj3OIxjQZXbTSe75TtuO8QvvaJyyU/ey6PcY2/a8R05BZr/W26n+d4Lxojyocisj7psz73u7OoJffxUt+YDZ9OGC81YcAGmlwbfIcojonh+fVtXrzkAIMZL+u9uAxHop92Jc0p5T8b+lDvP4cWL+lXjMadxrOm3wx4069Mo88mhlemb8Qc8hu63/PXVltttdXWyLN/AMt75SkILj0bAAAAAElFTkSuQmCC"
    )
    discord_img_data = base64.b64decode(discord_base64)
    discord_img = ImageTk.PhotoImage(Image.open(io.BytesIO(discord_img_data)).resize((20, 20)))
    discord_label = tk.Label(footer, image=discord_img, text=" Alexspaces", compound="left", cursor="hand2", bg="#000000", fg="white")
    discord_label.image = discord_img
    discord_label.pack(side="left", padx=(10, 0))
    discord_label.bind("<Button-1>", lambda e: webbrowser.open_new("https://discord.com/users/536633946344259614"))

    root.mainloop()

if __name__ == "__main__":
    start_gui()
    def update_platform_options(*args):
        options = COOMER_PLATFORMS if search_mode.get() == "coomer" else KEMONO_PLATFORMS
        menu = platform_menu["menu"]
        menu.delete(0, "end")
        menu.add_command(label="Any", command=lambda: search_platform.set("Any"))
        for opt in options:
            menu.add_command(label=opt.capitalize(), command=lambda value=opt: search_platform.set(value))

    search_mode.trace_add("write", update_platform_options)
    update_platform_options()