import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import os
import time
import re
import subprocess
import tempfile
import json
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
import msoffcrypto
from PyPDF2 import PdfReader, PdfWriter
from platform import system
import traceback  # Für detailliertere Fehlermeldungen

CREDENTIALS_PATH = os.path.expanduser("~/.imedcampus_config.json")
LIBREOFFICE_PATH = "/Applications/LibreOffice.app/Contents/MacOS/soffice"  # Pfad anpassen, falls notwendig

# --- Farbdefinitionen ---
COLOR_DARK_BLUE = "#004992"
COLOR_WHITE = "#FFFFFF"
COLOR_LIGHT_BLUE_ACCENT = "#E6F0FA"
COLOR_BUTTON_ACTIVE_BG = "#CCE0FF"
COLOR_SCROLLBAR_SLIDER = COLOR_WHITE
COLOR_SCROLLBAR_TROUGH = COLOR_DARK_BLUE
COLOR_SCROLLBAR_ACTIVE_SLIDER = "#DDDDDD"
COPYRIGHT_FG_COLOR = "#A0A0A0"

USERNAME = ""
PASSWORD = ""

root = tk.Tk()
root.title("ImedCampus Downloader")
root.config(bg=COLOR_DARK_BLUE)
root.withdraw()

style = ttk.Style(root)
try:
    style.theme_use("clam")
except tk.TclError:
    try:
        style.theme_use("alt")
    except tk.TclError:
        style.theme_use("default")
style.configure("Horizontal.TProgressbar", troughcolor=COLOR_DARK_BLUE, background=COLOR_WHITE, bordercolor=COLOR_WHITE)

# Explicitly pass master=root to Tkinter variables defined globally
download_path_var = tk.StringVar(master=root, value=os.path.expanduser("~/Downloads/ImedCampus"))
week_choice_var = tk.StringVar(master=root, value="aktuell")
convert_var = tk.BooleanVar(master=root, value=True)
event_links = []
checkbox_vars = []
select_all_var = tk.BooleanVar(master=root, value=False)


# --- Globale Variablen für das Log-Fenster und Puffer ---
log_window_instance = None
log_text_widget_external = None
log_buffer = []
MAX_LOG_BUFFER_SIZE = 500  # Maximale Anzahl von Nachrichten im Puffer/Fenster


def _on_mousewheel(event, canvas_widget):
    scroll_factor = 60
    if system() == "Darwin":
        canvas_widget.yview_scroll(-1 * event.delta, "units")
    elif event.num == 4:
        canvas_widget.yview_scroll(-1, "units")
    elif event.num == 5:
        canvas_widget.yview_scroll(1, "units")
    else:
        canvas_widget.yview_scroll(int(-1 * (event.delta / scroll_factor)), "units")


def browse_folder():
    path = filedialog.askdirectory(initialdir=download_path_var.get())
    if path:
        download_path_var.set(path)
        BASE_DOWNLOAD_PATH_LABEL.config(text=download_path_var.get())


folder_frame = tk.LabelFrame(root, text="Speicherort auswählen", bg=COLOR_DARK_BLUE, fg=COLOR_WHITE, padx=5, pady=5)
folder_frame.pack(fill="x", padx=10, pady=(10, 0))
tk.Label(folder_frame, text="Zielordner:", bg=COLOR_DARK_BLUE, fg=COLOR_WHITE).pack(side="left", padx=(5, 0), pady=5)
BASE_DOWNLOAD_PATH_LABEL = tk.Label(
    folder_frame, text=download_path_var.get(), anchor="w", bg=COLOR_DARK_BLUE, fg=COLOR_WHITE
)
BASE_DOWNLOAD_PATH_LABEL.pack(side="left", fill="x", expand=True, padx=(5, 0))
tk.Button(
    folder_frame,
    text="Auswählen …",
    command=browse_folder,
    bg=COLOR_WHITE,
    fg=COLOR_DARK_BLUE,
    activebackground=COLOR_BUTTON_ACTIVE_BG,
    relief=tk.FLAT,
    borderwidth=1,
    highlightthickness=1,
    highlightbackground=COLOR_WHITE,
).pack(side="right", padx=5, pady=5)

week_frame = tk.LabelFrame(root, text="Woche auswählen", bg=COLOR_DARK_BLUE, fg=COLOR_WHITE, padx=5, pady=5)
week_frame.pack(fill="x", padx=10, pady=(5, 0))
tk.Radiobutton(
    week_frame,
    text="Aktuelle Woche",
    variable=week_choice_var,
    value="aktuell",
    bg=COLOR_DARK_BLUE,
    fg=COLOR_WHITE,
    selectcolor=COLOR_DARK_BLUE,
    activebackground=COLOR_DARK_BLUE,
    activeforeground=COLOR_WHITE,
    highlightthickness=0,
).pack(side="left", padx=10, pady=5)
tk.Radiobutton(
    week_frame,
    text="Nächste Woche",
    variable=week_choice_var,
    value="naechste",
    bg=COLOR_DARK_BLUE,
    fg=COLOR_WHITE,
    selectcolor=COLOR_DARK_BLUE,
    activebackground=COLOR_DARK_BLUE,
    activeforeground=COLOR_WHITE,
    highlightthickness=0,
).pack(side="left", padx=10, pady=5)

convert_cb = tk.Checkbutton(
    root,
    text="In PDF konvertieren / PDF-Passwort entfernen",
    variable=convert_var,
    bg=COLOR_DARK_BLUE,
    fg=COLOR_WHITE,
    selectcolor=COLOR_DARK_BLUE,
    activebackground=COLOR_DARK_BLUE,
    activeforeground=COLOR_WHITE,
    highlightthickness=0,
)
convert_cb.pack(anchor="w", padx=10, pady=(5, 0))

load_events_button = tk.Button(
    root,
    text="Ereignisse laden",
    state="normal",
    width=20,
    bg=COLOR_WHITE,
    fg=COLOR_DARK_BLUE,
    activebackground=COLOR_BUTTON_ACTIVE_BG,
    relief=tk.FLAT,
    borderwidth=1,
    highlightthickness=1,
    highlightbackground=COLOR_WHITE,
)
load_events_button.pack(pady=(5, 10))

progress_frame = tk.Frame(root, bg=COLOR_DARK_BLUE)
progress_frame.pack(fill="x", padx=10, pady=(0, 0))
progress_label = tk.Label(
    progress_frame,
    text="Bitte Zielordner und Woche wählen, danach ‚Ereignisse laden' klicken.",
    anchor="w",
    bg=COLOR_DARK_BLUE,
    fg=COLOR_WHITE,
)
progress_label.pack(fill="x")
progress_bar = ttk.Progressbar(
    progress_frame, orient="horizontal", length=300, mode="determinate", style="Horizontal.TProgressbar"
)
progress_bar.pack(pady=(5, 10))

selection_frame = tk.LabelFrame(
    root, text="Wähle Ereignisse zum Download", bg=COLOR_DARK_BLUE, fg=COLOR_WHITE, padx=5, pady=5
)
selection_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
canvas = tk.Canvas(selection_frame, bg=COLOR_DARK_BLUE, highlightthickness=0)
scrollbar = tk.Scrollbar(
    selection_frame,
    orient="vertical",
    command=canvas.yview,
    bg=COLOR_SCROLLBAR_SLIDER,
    troughcolor=COLOR_SCROLLBAR_TROUGH,
    activebackground=COLOR_SCROLLBAR_ACTIVE_SLIDER,
    relief=tk.FLAT,
    width=12,
)
scrollable_frame = tk.Frame(canvas, bg=COLOR_DARK_BLUE)
scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
canvas.configure(yscrollcommand=scrollbar.set)
canvas.pack(side="left", fill="both", expand=True)
scrollbar.pack(side="right", fill="y")
canvas.bind("<MouseWheel>", lambda e, cw=canvas: _on_mousewheel(e, cw))
canvas.bind("<Button-4>", lambda e, cw=canvas: _on_mousewheel(e, cw))
canvas.bind("<Button-5>", lambda e, cw=canvas: _on_mousewheel(e, cw))
scrollable_frame.bind("<MouseWheel>", lambda e, cw=canvas: _on_mousewheel(e, cw))
scrollable_frame.bind("<Button-4>", lambda e, cw=canvas: _on_mousewheel(e, cw))
scrollable_frame.bind("<Button-5>", lambda e, cw=canvas: _on_mousewheel(e, cw))

download_button = tk.Button(
    root,
    text="Download Selected",
    state="disabled",
    width=20,
    bg=COLOR_WHITE,
    fg=COLOR_DARK_BLUE,
    activebackground=COLOR_BUTTON_ACTIVE_BG,
    relief=tk.FLAT,
    borderwidth=1,
    highlightthickness=1,
    highlightbackground=COLOR_WHITE,
)
download_button.pack(pady=(0, 5))


def show_log_window():
    global log_window_instance, log_text_widget_external, log_buffer
    if log_window_instance and log_window_instance.winfo_exists():
        log_window_instance.lift()
        log_window_instance.focus_set()
        return
    log_window_instance = tk.Toplevel(root)
    log_window_instance.title("Anwendungs-Logs")
    try:
        geom = root.geometry()
        size_part = geom.split("+")[0]
        log_win_width, log_win_height = map(int, size_part.split("x"))
        if log_win_width < 200 or log_win_height < 150:
            raise ValueError("Root window too small")
    except:
        log_win_width, log_win_height = 700, 450
    log_window_instance.geometry(f"{log_win_width}x{log_win_height}")
    log_window_instance.config(bg=COLOR_DARK_BLUE)
    ext_log_frame = tk.Frame(log_window_instance, bg=COLOR_DARK_BLUE)
    ext_log_frame.pack(fill="both", expand=True, padx=10, pady=10)
    log_text_widget_external = tk.Text(
        ext_log_frame,
        state="normal",
        bg=COLOR_WHITE,
        fg=COLOR_DARK_BLUE,
        relief=tk.FLAT,
        insertbackground=COLOR_DARK_BLUE,
        wrap=tk.WORD,
    )
    log_scrollbar_ext = tk.Scrollbar(
        ext_log_frame,
        orient="vertical",
        command=log_text_widget_external.yview,
        bg=COLOR_SCROLLBAR_SLIDER,
        troughcolor=COLOR_SCROLLBAR_TROUGH,
        activebackground=COLOR_SCROLLBAR_ACTIVE_SLIDER,
        relief=tk.FLAT,
        width=12,
    )
    log_text_widget_external.configure(yscrollcommand=log_scrollbar_ext.set)
    log_text_widget_external.pack(side="left", fill="both", expand=True)
    log_scrollbar_ext.pack(side="right", fill="y")
    for timestamp_str, message_text in log_buffer:
        log_text_widget_external.insert(tk.END, f"{timestamp_str} - {message_text}\n")
    log_text_widget_external.see(tk.END)
    log_text_widget_external.config(state="disabled")

    def on_log_window_close():
        global log_window_instance, log_text_widget_external
        if log_window_instance:
            log_window_instance.destroy()
        log_window_instance = None
        log_text_widget_external = None

    log_window_instance.protocol("WM_DELETE_WINDOW", on_log_window_close)


show_logs_button = tk.Button(
    root,
    text="Logs anzeigen",
    command=show_log_window,
    width=20,
    bg=COLOR_WHITE,
    fg=COLOR_DARK_BLUE,
    activebackground=COLOR_BUTTON_ACTIVE_BG,
    relief=tk.FLAT,
    borderwidth=1,
    highlightthickness=1,
    highlightbackground=COLOR_WHITE,
)
show_logs_button.pack(pady=(0, 10))
lle_label = tk.Label(root, text="LLE©", font=("Helvetica", 8), fg=COPYRIGHT_FG_COLOR, bg=COLOR_DARK_BLUE)
lle_label.place(relx=1.0, rely=1.0, anchor="se", x=-5, y=-5)
BASE_DOWNLOAD_PATH = download_path_var.get()


def log_message(message):
    root.after(0, lambda: _log_message_thread_safe(message))


def _log_message_thread_safe(message):
    global log_text_widget_external, log_buffer, log_window_instance
    timestamp_str = time.strftime("%H:%M:%S")
    log_buffer.append((timestamp_str, message))
    if len(log_buffer) > MAX_LOG_BUFFER_SIZE:
        log_buffer.pop(0)
    if log_text_widget_external and log_window_instance and log_window_instance.winfo_exists():
        log_text_widget_external.config(state="normal")
        num_lines_in_widget = int(log_text_widget_external.index("end-1c").split(".")[0])
        if num_lines_in_widget > MAX_LOG_BUFFER_SIZE + 20:
            lines_to_delete = num_lines_in_widget - MAX_LOG_BUFFER_SIZE
            log_text_widget_external.delete("1.0", f"{lines_to_delete + 1}.0")
        log_text_widget_external.insert(tk.END, f"{timestamp_str} - {message}\n")
        log_text_widget_external.see(tk.END)
        log_text_widget_external.config(state="disabled")
    print(f"{timestamp_str} - {message}")


def load_saved_credentials():
    global USERNAME, PASSWORD
    if os.path.exists(CREDENTIALS_PATH):
        try:
            with open(CREDENTIALS_PATH, "r") as f:
                data = json.load(f)
            USERNAME = data.get("username", "")
            PASSWORD = data.get("password", "")
        except Exception:
            pass


def save_credentials(username, password):
    try:
        with open(CREDENTIALS_PATH, "w") as f:
            json.dump({"username": username, "password": password}, f)
    except Exception as e:
        log_message(f"Fehler beim Speichern der Anmeldedaten: {e}")


def delete_saved_credentials():
    if os.path.exists(CREDENTIALS_PATH):
        try:
            os.remove(CREDENTIALS_PATH)
        except Exception as e:
            log_message(f"Fehler beim Löschen der Anmeldedaten: {e}")


def show_login_dialog():
    login_win = tk.Toplevel(root)
    login_win.title("Login")
    login_win.geometry("300x240")
    login_win.resizable(False, False)
    login_win.grab_set()
    login_win.config(bg=COLOR_DARK_BLUE)
    tk.Label(login_win, text="Benutzername:", bg=COLOR_DARK_BLUE, fg=COLOR_WHITE).pack(pady=(15, 0))
    username_entry = tk.Entry(
        login_win, bg=COLOR_WHITE, fg=COLOR_DARK_BLUE, insertbackground=COLOR_DARK_BLUE, relief=tk.FLAT, width=30
    )
    username_entry.pack(pady=(0, 10), padx=20, fill="x")
    tk.Label(login_win, text="Passwort:", bg=COLOR_DARK_BLUE, fg=COLOR_WHITE).pack()
    password_entry = tk.Entry(
        login_win,
        show="*",
        bg=COLOR_WHITE,
        fg=COLOR_DARK_BLUE,
        insertbackground=COLOR_DARK_BLUE,
        relief=tk.FLAT,
        width=30,
    )
    password_entry.pack(pady=(0, 10), padx=20, fill="x")
    save_var = tk.BooleanVar(value=False)  # This variable is local to the function and generally fine
    tk.Checkbutton(
        login_win,
        text="Anmeldedaten speichern",
        variable=save_var,
        bg=COLOR_DARK_BLUE,
        fg=COLOR_WHITE,
        selectcolor=COLOR_DARK_BLUE,
        activebackground=COLOR_DARK_BLUE,
        activeforeground=COLOR_WHITE,
        highlightthickness=0,
    ).pack(pady=5)

    def attempt_login():
        nonlocal login_win, username_entry, password_entry, save_var
        uname = username_entry.get().strip()
        pwd = password_entry.get().strip()
        if not uname or not pwd:
            messagebox.showerror("Fehler", "Benutzername und Passwort dürfen nicht leer sein.", parent=login_win)
            return
        chrome_opts = Options()
        chrome_opts.add_argument("--headless=new")
        chrome_opts.add_argument("--window-size=1920,1080")
        chrome_opts.add_argument("--disable-gpu")
        chrome_opts.add_argument("--no-sandbox")
        driver = None
        try:
            log_message("Login-Versuch gestartet...")
            driver = webdriver.Chrome(options=chrome_opts)
            driver.get("https://imed-campus.uke.uni-hamburg.de/")
            driver.find_element(By.NAME, "username").send_keys(uname)
            driver.find_element(By.NAME, "password").send_keys(pwd + Keys.RETURN)
            time.sleep(3.5)
            page_src_lower = driver.page_source.lower()
            current_url_lower = driver.current_url.lower()
            login_error_indicators = [
                "falsche anmeldedaten",
                "benutzername oder passwort ungültig",
                "login.php",
                "melde mich an",
                "anmeldung fehlgeschlagen",
            ]
            still_on_login_page = (
                'name="username"' in page_src_lower and 'name="password"' in page_src_lower
            ) or "loginform" in page_src_lower
            successful_landing_page = (
                "stundenplan" in current_url_lower
                or "dashboard" in current_url_lower
                or "persönliche übersicht" in page_src_lower
            )
            login_failed_check = (
                any(indicator in page_src_lower for indicator in login_error_indicators)
                or any(
                    indicator in current_url_lower for indicator in ["login.php", "login=failed", "credentials/failed"]
                )
                or (still_on_login_page and not successful_landing_page)
            )
            if login_failed_check and not successful_landing_page:
                raise Exception(f"Ungültige Anmeldedaten oder Login-Seite nicht verlassen. URL: {current_url_lower}")
            log_message(f"Login erfolgreich verifiziert. Aktuelle URL: {current_url_lower}")
        except Exception as e:
            log_message(f"Login fehlgeschlagen: {e}")
            messagebox.showerror(
                "Login fehlgeschlagen",
                f"Benutzername oder Passwort ungültig oder Seite nicht erreichbar.\nDetails: {e}",
                parent=login_win,
            )
            if driver:
                driver.quit()
                return
        finally:
            if driver:
                driver.quit()
        if save_var.get():
            save_credentials(uname, pwd)
        else:
            delete_saved_credentials()
        global USERNAME, PASSWORD
        USERNAME, PASSWORD = uname, pwd
        login_win.destroy()
        root.deiconify()

    btn_frame = tk.Frame(login_win, bg=COLOR_DARK_BLUE)
    btn_frame.pack(pady=15)
    tk.Button(
        btn_frame,
        text="Abbrechen",
        command=lambda: root.destroy(),
        bg=COLOR_WHITE,
        fg=COLOR_DARK_BLUE,
        activebackground=COLOR_BUTTON_ACTIVE_BG,
        relief=tk.FLAT,
        borderwidth=1,
        highlightthickness=1,
        highlightbackground=COLOR_WHITE,
        width=10,
    ).pack(side="left", padx=10)
    tk.Button(
        btn_frame,
        text="Login",
        command=attempt_login,
        bg=COLOR_WHITE,
        fg=COLOR_DARK_BLUE,
        activebackground=COLOR_BUTTON_ACTIVE_BG,
        relief=tk.FLAT,
        borderwidth=1,
        highlightthickness=1,
        highlightbackground=COLOR_WHITE,
        width=10,
    ).pack(side="right", padx=10)
    username_entry.insert(0, USERNAME)
    password_entry.insert(0, PASSWORD)
    if USERNAME and PASSWORD:
        save_var.set(True)
    login_win.protocol("WM_DELETE_WINDOW", lambda: root.destroy())
    username_entry.focus_set()


def decrypt_office_file(input_path: str, password: str) -> tuple[str | None, str | None]:
    _, ext = os.path.splitext(input_path)
    created_temp_file = None
    try:
        with open(input_path, "rb") as f_in:
            office_file = msoffcrypto.OfficeFile(f_in)
            if not office_file.is_encrypted():
                log_message(f"Datei {os.path.basename(input_path)} ist nicht verschlüsselt.")
                return input_path, None
            tmp_fd, tmp_path = tempfile.mkstemp(suffix=ext.lower())
            os.close(tmp_fd)
            created_temp_file = tmp_path
            decryption_success = False
            passwords_to_try = [password, "", None]
            for pwd_attempt in passwords_to_try:
                try:
                    if pwd_attempt is None and password == "":
                        continue
                    office_file.load_key(password=pwd_attempt)
                    decryption_success = True
                    log_message(
                        f"Entschlüsselung für {os.path.basename(input_path)} mit Pwd '{str(pwd_attempt)[:5]}...' OK."
                    )
                    break
                except Exception:
                    log_message(f"Pwd '{str(pwd_attempt)[:5]}...' für {os.path.basename(input_path)} falsch.")
            if not decryption_success:
                raise Exception("Alle Entschlüsselungsversuche fehlgeschlagen.")
            with open(tmp_path, "wb") as f_out:
                office_file.decrypt(f_out)
            log_message(f"✅ {os.path.basename(input_path)} -> {os.path.basename(tmp_path)}")
            return tmp_path, tmp_path
    except Exception as e:
        log_message(f"❌ Entschlüsselung {os.path.basename(input_path)}: {e}")
        if created_temp_file and os.path.exists(created_temp_file):
            try:
                os.remove(created_temp_file)
            except Exception:
                pass
        return None, None


def handle_password_protected_pdf(pdf_path: str, password: str) -> bool:
    try:
        with open(pdf_path, "rb") as file:
            reader = PdfReader(file)
            if not reader.is_encrypted:
                log_message(f"PDF {os.path.basename(pdf_path)} nicht verschlüsselt.")
                return True
            passwords_to_try = [password, "", None]
            decrypted = False
            for pwd_attempt in passwords_to_try:
                try:
                    if reader.decrypt(pwd_attempt):
                        decrypted = True
                        log_message(
                            f"PDF {os.path.basename(pdf_path)} mit Pwd '{str(pwd_attempt)[:5]}...' entschlüsselt."
                        )
                        break
                except NotImplementedError as nie:
                    log_message(
                        f"❌ AES-Entschlüsselung für PDF {os.path.basename(pdf_path)} fehlgeschlagen: {nie}. PyCryptodome fehlt möglicherweise."
                    )
                    return False
                except Exception as e_decrypt:
                    log_message(
                        f"Fehler bei Entschlüsselungsversuch für {os.path.basename(pdf_path)} mit Pwd '{str(pwd_attempt)[:5]}...': {e_decrypt}"
                    )
            if not decrypted:
                log_message(f"❌ Passwort für PDF {os.path.basename(pdf_path)} nicht gefunden.")
                return False
            writer = PdfWriter()
            for page in reader.pages:
                writer.add_page(page)
            with open(pdf_path, "wb") as output_file:
                writer.write(output_file)
            log_message(f"✅ PDF-Passwort von {os.path.basename(pdf_path)} entfernt.")
            return True
    except Exception as e:
        log_message(f"❌ PDF-Passwort-Entfernung {os.path.basename(pdf_path)}: {e}")
        return False


def convert_with_libreoffice(input_path: str, output_dir: str) -> str | None:
    cmd = [LIBREOFFICE_PATH, "--headless", "--convert-to", "pdf", "--outdir", output_dir, input_path]
    base_input_filename = os.path.splitext(os.path.basename(input_path))[0]
    expected_pdf_path = os.path.join(output_dir, f"{base_input_filename}.pdf")
    try:
        if os.path.exists(expected_pdf_path):
            log_message(f"Entferne existierende Datei: {os.path.basename(expected_pdf_path)}.")
            os.remove(expected_pdf_path)
        log_message(f"Starte LO-Konv.: {os.path.basename(input_path)} -> {os.path.basename(expected_pdf_path)}")
        result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=90)
        if result.returncode != 0:
            log_message(f"❌ LO-Konv. {os.path.basename(input_path)} (Exit: {result.returncode}).")
            if result.stdout:
                log_message(f"LO stdout: {result.stdout.strip()[:200]}")
            if result.stderr:
                log_message(f"LO stderr: {result.stderr.strip()[:200]}")
            if os.path.exists(expected_pdf_path):
                log_message(f"⚠️ Fehlerhafte PDF {os.path.basename(expected_pdf_path)} wird gelöscht.")
                os.remove(expected_pdf_path)
            return None
        if os.path.exists(expected_pdf_path):
            log_message(f"✅ LO hat PDF erstellt: {os.path.basename(expected_pdf_path)}")
            return expected_pdf_path
        else:
            log_message(f"❌ LO-Konv.: {os.path.basename(expected_pdf_path)} nicht gefunden (Exit 0).")
            if result.stdout:
                log_message(f"LO stdout: {result.stdout.strip()[:200]}")
            if result.stderr:
                log_message(f"LO stderr: {result.stderr.strip()[:200]}")
            return None
    except subprocess.TimeoutExpired:
        log_message(f"❌ LO-Konv. Timeout: {os.path.basename(input_path)}")
        return None
    except Exception as e:
        log_message(f"❌ LO-Konv. Fehler {os.path.basename(input_path)}: {e}")
        return None


def convert_to_pdf(input_path: str, password: str = "ukestudi", pdf_target_base_name: str | None = None) -> bool:
    dirname, original_fn_ext = os.path.split(input_path)
    original_base_from_input, original_ext_str = os.path.splitext(original_fn_ext)

    actual_final_base_name = pdf_target_base_name if pdf_target_base_name else original_base_from_input
    if not actual_final_base_name.strip():  # Zusätzlicher Check für leeren Basisnamen
        actual_final_base_name = f"konvertiert_{int(time.time())}"  # Fallback Name
        log_message(f"Warnung: PDF-Zielbasisname war leer, Fallback zu {actual_final_base_name}")

    final_pdf_path = os.path.join(dirname, f"{actual_final_base_name}.pdf")
    temp_decrypted_del = None

    try:
        if original_ext_str.lower() == ".pdf":
            log_message(f"Verarbeite PDF: {original_fn_ext} -> Ziel: {os.path.basename(final_pdf_path)}")

            password_handled_on_original = handle_password_protected_pdf(input_path, password)
            if not password_handled_on_original:
                log_message(f"Passwortbehandlung für {original_fn_ext} fehlgeschlagen.")
                return False

            if input_path != final_pdf_path:
                try:
                    if os.path.exists(final_pdf_path):
                        log_message(f"Überschreibe existierende PDF: {os.path.basename(final_pdf_path)}.")
                        os.remove(final_pdf_path)
                    os.rename(input_path, final_pdf_path)
                    log_message(
                        f"PDF {original_fn_ext} erfolgreich Pwd-behandelt und umbenannt zu {os.path.basename(final_pdf_path)}."
                    )
                except Exception as e_rename:
                    log_message(
                        f"❌ Fehler beim Umbenennen von {original_fn_ext} zu {os.path.basename(final_pdf_path)}: {e_rename}"
                    )
                    return False
            else:
                log_message(f"PDF {original_fn_ext} erfolgreich Pwd-behandelt (Name beibehalten).")
            return True

        conv_input_path = input_path
        if original_ext_str.lower() in (".pptx", ".ppsx", ".docx", ".xlsx", ".ppt", ".doc", ".xls", ".rtf"):
            log_message(f"Entschlüssele Office-Datei: {original_fn_ext}...")
            path_to_conv, temp_created = decrypt_office_file(input_path, password)
            if not path_to_conv:
                log_message(f"Entschlüsselung von {original_fn_ext} fehlgeschlagen.")
                return False
            conv_input_path = path_to_conv
            if temp_created and temp_created != input_path:
                temp_decrypted_del = temp_created

        log_message(
            f"Konvertiere {os.path.basename(conv_input_path)} (aus {original_fn_ext}) zu PDF -> {os.path.basename(final_pdf_path)}..."
        )
        created_pdf_lo = convert_with_libreoffice(conv_input_path, dirname)

        if created_pdf_lo:
            if created_pdf_lo != final_pdf_path:
                if os.path.exists(final_pdf_path):
                    log_message(f"Überschreibe Ziel-PDF: {os.path.basename(final_pdf_path)}.")
                    os.remove(final_pdf_path)
                try:
                    os.rename(created_pdf_lo, final_pdf_path)
                    log_message(f"✅ Erfolgreich konvertiert und umbenannt zu: {os.path.basename(final_pdf_path)}")
                except Exception as er:
                    log_message(
                        f"❌ Umbenennen von konvertierter PDF fehlgeschlagen: {os.path.basename(created_pdf_lo)} -> {os.path.basename(final_pdf_path)}: {er}"
                    )
                    # SyntaxError fix: Correctly indent try-except for removing created_pdf_lo
                    if os.path.exists(created_pdf_lo):
                        try:
                            os.remove(created_pdf_lo)
                        except Exception as e_del_lo:
                            log_message(
                                f"Konnte fehlerhafte LO PDF nicht löschen: {os.path.basename(created_pdf_lo)} - {e_del_lo}"
                            )
                    return False
            else:
                log_message(f"✅ PDF erstellt mit korrektem Namen: {os.path.basename(final_pdf_path)}")
            return True
        else:
            log_message(
                f"❌ PDF-Erstellung (LibreOffice) für {original_fn_ext} (aus {os.path.basename(conv_input_path)}) fehlgeschlagen."
            )
            return False
    except Exception as e:
        log_message(f"❌ Kritischer Fehler in convert_to_pdf für {original_fn_ext}: {e}")
        log_message(traceback.format_exc())
        return False
    finally:
        if temp_decrypted_del and os.path.exists(temp_decrypted_del):
            try:
                os.remove(temp_decrypted_del)
                log_message(f"Temporäre entschlüsselte Datei {os.path.basename(temp_decrypted_del)} entfernt.")
            except Exception as et:
                log_message(f"⚠️ Fehler beim Löschen der temporären Datei {os.path.basename(temp_decrypted_del)}: {et}")


def fetch_events_wrapper():
    root.after(0, lambda: load_events_button.config(state="disabled"))
    root.after(0, lambda: download_button.config(state="disabled"))
    fetch_events()
    root.after(0, lambda: load_events_button.config(state="normal"))


def start_fetch_thread():
    for widget in scrollable_frame.winfo_children():
        widget.destroy()
    checkbox_vars.clear()
    progress_label.config(text="Ereignisse werden geladen...")
    progress_bar.config(value=0, mode="indeterminate")
    progress_bar.start()
    root.update_idletasks()
    threading.Thread(target=fetch_events_wrapper, daemon=True).start()


def fetch_events():
    log_message("Lade Ereignisse...")
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    driver = None
    try:
        driver = webdriver.Chrome(options=chrome_options)
        driver.get("https://imed-campus.uke.uni-hamburg.de/")
        driver.find_element(By.NAME, "username").send_keys(USERNAME)
        driver.find_element(By.NAME, "password").send_keys(PASSWORD + Keys.RETURN)
        time.sleep(3.5)
        if any(
            indicator in driver.current_url.lower() for indicator in ["login.php", "login=failed", "credentials/failed"]
        ):
            log_message("Login fehlgeschlagen (fetch_events).")
            root.after(0, lambda: progress_label.config(text="Login fehlgeschlagen."))
            driver.quit()
            return
        driver.get("https://imed-campus.uke.uni-hamburg.de/stundenplan")
        time.sleep(3.5)
        if week_choice_var.get() == "naechste":
            try:
                driver.execute_script(
                    "arguments[0].click();", driver.find_element(By.XPATH, "//input[@name='next_w' and @type='image']")
                )
                time.sleep(3.5)
            except Exception as enw:
                log_message(f"Nächste Woche nicht geklickt: {enw}")
        events = driver.find_elements(By.CSS_SELECTOR, "a.vatitle")
        global event_links
        event_links.clear()
        for e in events:
            title = e.text.strip()
            href = e.get_attribute("href")
            if not href or not title:
                continue
            try:
                weekday = e.find_element(By.XPATH, "./ancestor::tr/td[@class='tday']/b").text.strip()
            except Exception:
                weekday = ""
            event_links.append((f"{title} ({weekday})" if weekday else title, href))
    except Exception as e:
        log_message(f"Ereignisse laden fehlgeschlagen: {e}")
        root.after(0, lambda: progress_label.config(text=f"Ereignisse laden fehlgeschlagen: {e}"))
    finally:
        if driver:
            driver.quit()
        root.after(0, lambda: progress_bar.stop())
        root.after(0, lambda: progress_bar.config(mode="determinate", value=0))
    if not event_links:
        log_message("Keine Ereignisse gefunden.")
        root.after(0, lambda: progress_label.config(text="Keine Ereignisse gefunden."))
        return
    log_message(f"{len(event_links)} Ereignisse gefunden")
    root.after(0, populate_checkboxes)


def populate_checkboxes():
    for widget in scrollable_frame.winfo_children():
        widget.destroy()
    checkbox_vars.clear()
    # select_all_var is global and already has master=root
    if not event_links:
        progress_label.config(text="Keine Ereignisse zum Anzeigen.")
        download_button.config(state="disabled")
        return
    progress_label.config(
        text=f"{len(event_links)} Ereignisse gefunden. Wähle aus.", bg=COLOR_DARK_BLUE, fg=COLOR_WHITE
    )
    day_button_frame = tk.Frame(scrollable_frame, bg=COLOR_DARK_BLUE)
    day_button_frame.pack(fill="x", padx=5, pady=(5, 0))

    def create_cmd(wd):
        return lambda: select_by_weekday(wd)

    for wd_short in ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]:
        day_btn = tk.Button(
            day_button_frame,
            text=wd_short,
            width=3,
            command=create_cmd(wd_short),
            bg=COLOR_WHITE,
            fg=COLOR_DARK_BLUE,
            activebackground=COLOR_BUTTON_ACTIVE_BG,
            relief=tk.FLAT,
        )
        day_btn.pack(side="left", padx=2)
        day_btn.bind("<MouseWheel>", lambda e, cw=canvas: _on_mousewheel(e, cw))
        day_btn.bind("<Button-4>", lambda e, cw=canvas: _on_mousewheel(e, cw))
        day_btn.bind("<Button-5>", lambda e, cw=canvas: _on_mousewheel(e, cw))
    # select_all_var is used by this Checkbutton
    select_all_cb = tk.Checkbutton(
        scrollable_frame,
        text="Alle auswählen",
        variable=select_all_var,
        anchor="w",
        command=lambda: [var.set(select_all_var.get()) for var in checkbox_vars],
        bg=COLOR_DARK_BLUE,
        fg=COLOR_WHITE,
        selectcolor=COLOR_DARK_BLUE,
        activebackground=COLOR_DARK_BLUE,
        activeforeground=COLOR_WHITE,
        highlightthickness=0,
    )
    select_all_cb.pack(fill="x", padx=5, pady=(5, 10))
    select_all_cb.bind("<MouseWheel>", lambda e, cw=canvas: _on_mousewheel(e, cw))
    select_all_cb.bind("<Button-4>", lambda e, cw=canvas: _on_mousewheel(e, cw))
    select_all_cb.bind("<Button-5>", lambda e, cw=canvas: _on_mousewheel(e, cw))
    current_canvas_width = canvas.winfo_width()
    wraplen = current_canvas_width - 45 if current_canvas_width > 60 else 400
    for idx, (title, _) in enumerate(event_links):
        var = tk.BooleanVar(master=root, value=False)  # Also set master for these dynamically created vars
        cb = tk.Checkbutton(
            scrollable_frame,
            text=title,
            variable=var,
            anchor="w",
            wraplength=wraplen,
            justify="left",
            bg=COLOR_DARK_BLUE,
            fg=COLOR_WHITE,
            selectcolor=COLOR_DARK_BLUE,
            activebackground=COLOR_DARK_BLUE,
            activeforeground=COLOR_WHITE,
            highlightthickness=0,
        )
        cb.pack(fill="x", padx=5, pady=2)
        checkbox_vars.append(var)
        cb.bind("<MouseWheel>", lambda e, cw=canvas: _on_mousewheel(e, cw))
        cb.bind("<Button-4>", lambda e, cw=canvas: _on_mousewheel(e, cw))
        cb.bind("<Button-5>", lambda e, cw=canvas: _on_mousewheel(e, cw))
    download_button.config(state="normal")
    canvas.update_idletasks()
    canvas.config(scrollregion=canvas.bbox("all"))
    canvas.itemconfig(canvas_window, width=canvas.winfo_width())


def select_by_weekday(weekday_short):
    found = False
    for idx, (title, _) in enumerate(event_links):
        if f"({weekday_short})" in title:
            checkbox_vars[idx].set(True)
            found = True
    if not found:
        log_message(f"Keine Ereignisse für '{weekday_short}' gefunden.")


def start_download_thread():
    progress_bar.config(value=0, mode="determinate")
    threading.Thread(target=download_selected_wrapper, daemon=True).start()


def download_selected_wrapper():
    root.after(0, lambda: download_button.config(state="disabled"))
    root.after(0, lambda: load_events_button.config(state="disabled"))
    try:
        download_selected()
    except Exception as e:
        log_message(f"🚫 Kritischer Fehler im Download-Thread: {e}")
        log_message(traceback.format_exc())
        root.after(0, lambda: progress_label.config(text=f"Kritischer Fehler: {e}"))
    finally:
        root.after(0, lambda: download_button.config(state="normal"))
        root.after(0, lambda: load_events_button.config(state="normal"))
        root.after(0, lambda: progress_bar.config(value=0))


def download_selected():
    selected_indices = [i for i, var in enumerate(checkbox_vars) if var.get()]
    if not selected_indices:
        log_message("Keine Ereignisse ausgewählt.")
        root.after(0, lambda: progress_label.config(text="Keine Ereignisse ausgewählt."))
        return
    log_message(f"Starte Download von {len(selected_indices)} Ereignissen...")
    root.after(0, lambda: progress_label.config(text="Starte Download..."))
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    driver = None
    try:
        driver = webdriver.Chrome(options=chrome_options)
        driver.get("https://imed-campus.uke.uni-hamburg.de/")
        driver.find_element(By.NAME, "username").send_keys(USERNAME)
        driver.find_element(By.NAME, "password").send_keys(PASSWORD + Keys.RETURN)
        time.sleep(3.5)
        if any(
            indicator in driver.current_url.lower() for indicator in ["login.php", "login=failed", "credentials/failed"]
        ):
            log_message("Login fehlgeschlagen (Download).")
            root.after(0, lambda: progress_label.config(text="Login fehlgeschlagen (Download)."))
            driver.quit()
            return
        driver.get("https://imed-campus.uke.uni-hamburg.de/stundenplan")
        time.sleep(3.5)
        if week_choice_var.get() == "naechste":
            try:
                driver.execute_script(
                    "arguments[0].click();", driver.find_element(By.XPATH, "//input[@name='next_w' and @type='image']")
                )
                time.sleep(3.5)
            except Exception:
                log_message("Warnung: Nächste Woche nicht geklickt (Download).")
        total_selected = len(selected_indices)
        root.after(0, lambda: progress_bar.config(maximum=total_selected, value=0))
        global BASE_DOWNLOAD_PATH
        BASE_DOWNLOAD_PATH = download_path_var.get()
        os.makedirs(BASE_DOWNLOAD_PATH, exist_ok=True)
        dl_count, conv_count, fail_conv_count = 0, 0, 0
        for count, idx in enumerate(selected_indices, start=1):
            full_title, event_page_link = event_links[idx]
            safe_title_temp = re.sub(r"[^\w\s\-_.()]", "_", full_title)
            display_title = safe_title_temp[:60] + "..." if len(safe_title_temp) > 60 else safe_title_temp
            log_message(f"Bearbeite ({count}/{total_selected}): {safe_title_temp}")
            root.after(
                0, lambda t=display_title, c=count: progress_label.config(text=f"({c}/{total_selected}) Lade: {t}")
            )
            root.after(0, lambda v=count: progress_bar.config(value=v))
            root.update_idletasks()
            wd_match = re.search(r"\((Mo|Di|Mi|Do|Fr|Sa|So)\)", safe_title_temp)
            wd_folder = wd_match.group(1) if wd_match else "Unbekannt"
            event_folder = os.path.join(BASE_DOWNLOAD_PATH, wd_folder)
            os.makedirs(event_folder, exist_ok=True)
            driver.execute_script("window.open(arguments[0], '_blank');", event_page_link)
            time.sleep(1.5)
            driver.switch_to.window(driver.window_handles[-1])
            time.sleep(4.5)
            fn_title_event = safe_title_temp.replace(wd_match.group(0), "").strip() if wd_match else safe_title_temp
            fn_title_event = re.sub(r"\s+", "_", fn_title_event)
            fn_title_event = re.sub(r"[^\w\-_.]", "", fn_title_event)[:100]

            page_dl_links = driver.find_elements(
                By.XPATH,
                "//a[contains(@href, '/dl.php?') or contains(@href, 'download.php') or contains(@class, 'download') or contains(@href, '.pdf') or contains(@href, '.pptx') or contains(@href, '.docx') or contains(@href, '.xlsx')]",
            )
            if not page_dl_links:
                log_message(f"Keine Download-Links für {safe_title_temp} gefunden.")
            sel_cookies = driver.get_cookies()
            session = requests.Session()
            for c_sel in sel_cookies:
                session.cookies.set(c_sel["name"], c_sel["value"])

            for link_idx, link_el in enumerate(page_dl_links):
                file_url = link_el.get_attribute("href")
                if not file_url or not file_url.startswith("http"):
                    if file_url and not file_url.startswith("http"):
                        file_url = requests.compat.urljoin(driver.current_url, file_url)
                    else:
                        continue
                link_text = link_el.text.strip()
                server_fn = ""
                try:
                    head_r = session.head(file_url, allow_redirects=True, timeout=20)
                    if "Content-Disposition" in head_r.headers:
                        disp = head_r.headers["Content-Disposition"]
                        fn_m = re.search(r'filename\*?=(?:UTF-\d{1,2}\'\')?([^";]+)', disp, re.IGNORECASE)
                        if fn_m:
                            server_fn = requests.utils.unquote(fn_m.group(1)).strip('"')
                except requests.exceptions.RequestException as eh:
                    log_message(f"HEAD-Req. Fehler {file_url}: {eh}")

                base_fn_dl = server_fn or link_text or f"datei_{link_idx + 1}"
                _, server_file_ext_only = os.path.splitext(base_fn_dl)
                if not server_file_ext_only and file_url:
                    _, server_file_ext_only = os.path.splitext(file_url.split("?")[0].split("#")[0])

                file_ext = server_file_ext_only.lower()

                pdf_target_clean_base = re.sub(r"[^\w\-_.,() ]", "_", os.path.splitext(base_fn_dl)[0])[:80].strip()
                if not pdf_target_clean_base:
                    pdf_target_clean_base = f"unbenannte_datei_{link_idx + 1}"

                ts = time.strftime("%Y%m%d-%H%M%S")
                original_download_fn = f"{fn_title_event}_{ts}_{pdf_target_clean_base}{file_ext}"
                original_download_fn = re.sub(r"_+", "_", original_download_fn).strip("_")[:200]
                save_path = os.path.join(event_folder, original_download_fn)

                try:
                    log_message(f"Lade herunter: {original_download_fn} von {file_url[:70]}...")
                    resp = session.get(file_url, timeout=180)
                    resp.raise_for_status()
                    with open(save_path, "wb") as f:
                        f.write(resp.content)
                    dl_count += 1
                    log_message(f"✅ Heruntergeladen: {original_download_fn}")
                except requests.exceptions.RequestException as er:
                    log_message(f"❌ Download {original_download_fn}: {er}")
                    continue
                except Exception as ew:
                    log_message(f"❌ Speichern {original_download_fn}: {ew}")
                    continue

                if (
                    convert_var.get()
                    and file_ext
                    and file_ext.lower() not in [".zip", ".rar", ".7z", ".gz", ".tar", ".tgz"]
                ):
                    log_message(
                        f"Verarbeite: {original_download_fn} -> Ziel-Basisname für PDF: {pdf_target_clean_base}"
                    )
                    conv_ok = convert_to_pdf(save_path, "ukestudi", pdf_target_base_name=pdf_target_clean_base)
                    if conv_ok:
                        conv_count += 1
                        if file_ext.lower() != ".pdf":
                            try:
                                os.remove(save_path)
                                log_message(
                                    f"Originaldatei ({os.path.basename(save_path)}) entfernt nach Konvertierung."
                                )
                            except OSError as erem:
                                log_message(
                                    f"⚠️ Originaldatei ({os.path.basename(save_path)}) konnte nicht entfernt werden: {erem}"
                                )
                    else:
                        fail_conv_count += 1
                        log_message(
                            f"Verarbeitung von {original_download_fn} fehlgeschlagen. Originaldatei bleibt (oder ist fehlerhaft)."
                        )

            if len(driver.window_handles) > 1:
                driver.close()
                driver.switch_to.window(driver.window_handles[0])
                time.sleep(0.5)
    except Exception as edl:
        log_message(f"🚫 Fehler im Download: {edl}")
        log_message(traceback.format_exc())
    finally:
        if driver:
            driver.quit()
    summary = f"✅ Download beendet! {dl_count} Dateien heruntergeladen."
    if convert_var.get():
        summary += f" {conv_count} verarbeitet/konvertiert, {fail_conv_count} Verarbeitungsfehler."
    log_message(summary)
    root.after(0, lambda: progress_label.config(text=summary))
    root.after(0, lambda: root.bell())


load_events_button.config(command=start_fetch_thread)
download_button.config(command=start_download_thread)

if __name__ == "__main__":
    load_saved_credentials()
    show_login_dialog()
    root.mainloop()
