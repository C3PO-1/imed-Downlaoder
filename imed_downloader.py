from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass

import msoffcrypto
import requests
from PyPDF2 import PdfReader, PdfWriter
from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

CREDENTIALS_PATH = os.path.expanduser("~/.imedcampus_config.json")
LIBREOFFICE_PATH = "/Applications/LibreOffice.app/Contents/MacOS/soffice"
WAIT_SHORT = 2

COLOR_DARK_BLUE = "#0B1B3A"
COLOR_WHITE = "#FFFFFF"
COLOR_BUTTON_ACTIVE_BG = "#1E335C"
COLOR_LIGHT_BLUE_ACCENT = "#1C3D6E"
COLOR_ACCENT_ORANGE = "#FF8C42"
COPYRIGHT_FG_COLOR = "#9CAAC0"

MAX_LOG_BUFFER_SIZE = 500
BASE_DOWNLOAD_PATH = os.path.expanduser("~/Downloads/ImedCampus")
USERNAME = ""
PASSWORD = ""
MAIN_WINDOW: "MainWindow | None" = None


@dataclass
class EventItem:
    title: str
    link: str


def log_message(message: str) -> None:
    timestamp_str = time.strftime("%H:%M:%S")
    print(f"{timestamp_str} - {message}")
    if MAIN_WINDOW:
        MAIN_WINDOW.log_signal.emit(timestamp_str, message)


def create_driver() -> webdriver.Chrome:
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    driver = webdriver.Chrome(options=opts)
    driver.implicitly_wait(10)
    return driver


def login(driver: webdriver.Chrome, username: str, password: str) -> bool:
    driver.get("https://imed-campus.uke.uni-hamburg.de/")
    driver.find_element(By.NAME, "username").send_keys(username)
    driver.find_element(By.NAME, "password").send_keys(password + Keys.RETURN)
    time.sleep(WAIT_SHORT)
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
            indicator in current_url_lower
            for indicator in ["login.php", "login=failed", "credentials/failed"]
        )
        or (still_on_login_page and not successful_landing_page)
    )
    if login_failed_check and not successful_landing_page:
        log_message(
            f"Ungültige Anmeldedaten oder Login-Seite nicht verlassen. URL: {current_url_lower}"
        )
        return False
    log_message(f"Login erfolgreich verifiziert. Aktuelle URL: {current_url_lower}")
    return True


def open_schedule(driver: webdriver.Chrome, week_choice: str) -> None:
    wait = WebDriverWait(driver, 10)
    driver.get("https://imed-campus.uke.uni-hamburg.de/stundenplan")
    try:
        wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Stundenplan')]")))
        log_message("Stundenplan-Seite erfolgreich geladen.")
    except Exception as exc:
        log_message(f"Warten auf Stundenplan-Seite fehlgeschlagen: {exc}")
        return
    if week_choice == "naechste":
        try:
            next_week_button_xpath = "//input[@name='next_w' and @type='submit']"
            next_week_button = wait.until(EC.element_to_be_clickable((By.XPATH, next_week_button_xpath)))
            next_week_button.click()
            log_message("✅ Erfolgreich auf 'Nächste Woche' geklickt.")
            time.sleep(WAIT_SHORT)
        except Exception as exc:
            log_message(f"❌ Nächste Woche konnte nicht geklickt werden: {exc}")


def load_saved_credentials() -> None:
    global USERNAME, PASSWORD
    if os.path.exists(CREDENTIALS_PATH):
        try:
            with open(CREDENTIALS_PATH, "r", encoding="utf-8") as credentials_file:
                data = json.load(credentials_file)
            USERNAME = data.get("username", "")
            PASSWORD = data.get("password", "")
        except Exception:
            USERNAME, PASSWORD = "", ""


def save_credentials(username: str, password: str) -> None:
    try:
        with open(CREDENTIALS_PATH, "w", encoding="utf-8") as credentials_file:
            json.dump({"username": username, "password": password}, credentials_file)
    except Exception as exc:
        log_message(f"Fehler beim Speichern der Anmeldedaten: {exc}")


def delete_saved_credentials() -> None:
    if os.path.exists(CREDENTIALS_PATH):
        try:
            os.remove(CREDENTIALS_PATH)
        except Exception as exc:
            log_message(f"Fehler beim Löschen der Anmeldedaten: {exc}")


def decrypt_office_file(input_path: str, password: str) -> tuple[str | None, str | None]:
    _, ext = os.path.splitext(input_path)
    created_temp_file = None
    try:
        with open(input_path, "rb") as file_handle:
            office_file = msoffcrypto.OfficeFile(file_handle)
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
                    log_message(
                        f"Pwd '{str(pwd_attempt)[:5]}...' für {os.path.basename(input_path)} falsch."
                    )
            if not decryption_success:
                raise Exception("Alle Entschlüsselungsversuche fehlgeschlagen.")
            with open(tmp_path, "wb") as out_handle:
                office_file.decrypt(out_handle)
            log_message(f"✅ {os.path.basename(input_path)} -> {os.path.basename(tmp_path)}")
            return tmp_path, tmp_path
    except Exception as exc:
        log_message(f"❌ Entschlüsselung {os.path.basename(input_path)}: {exc}")
        if created_temp_file and os.path.exists(created_temp_file):
            try:
                os.remove(created_temp_file)
            except Exception:
                pass
        return None, None


def handle_password_protected_pdf(pdf_path: str, password: str) -> bool:
    try:
        with open(pdf_path, "rb") as file_handle:
            reader = PdfReader(file_handle)
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
                except NotImplementedError as not_impl:
                    log_message(
                        f"❌ AES-Entschlüsselung für PDF {os.path.basename(pdf_path)} fehlgeschlagen: {not_impl}. PyCryptodome fehlt möglicherweise."
                    )
                    return False
                except Exception as exc:
                    log_message(
                        f"Fehler bei Entschlüsselungsversuch für {os.path.basename(pdf_path)} mit Pwd '{str(pwd_attempt)[:5]}...': {exc}"
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
    except Exception as exc:
        log_message(f"❌ PDF-Passwort-Entfernung {os.path.basename(pdf_path)}: {exc}")
        return False


def convert_with_libreoffice(input_path: str, output_dir: str) -> str | None:
    cmd = [
        LIBREOFFICE_PATH,
        "--headless",
        "--convert-to",
        "pdf",
        "--outdir",
        output_dir,
        input_path,
    ]
    base_input_filename = os.path.splitext(os.path.basename(input_path))[0]
    expected_pdf_path = os.path.join(output_dir, f"{base_input_filename}.pdf")
    try:
        if os.path.exists(expected_pdf_path):
            log_message(f"Entferne existierende Datei: {os.path.basename(expected_pdf_path)}.")
            os.remove(expected_pdf_path)
        log_message(
            f"Starte LO-Konv.: {os.path.basename(input_path)} -> {os.path.basename(expected_pdf_path)}"
        )
        result = subprocess.run(
            cmd, check=False, capture_output=True, text=True, timeout=90
        )
        if result.returncode != 0:
            log_message(
                f"❌ LO-Konv. {os.path.basename(input_path)} (Exit: {result.returncode})."
            )
            if result.stdout:
                log_message(f"LO stdout: {result.stdout.strip()[:200]}")
            if result.stderr:
                log_message(f"LO stderr: {result.stderr.strip()[:200]}")
            if os.path.exists(expected_pdf_path):
                log_message(
                    f"⚠️ Fehlerhafte PDF {os.path.basename(expected_pdf_path)} wird gelöscht."
                )
                os.remove(expected_pdf_path)
            return None
        if os.path.exists(expected_pdf_path):
            log_message(
                f"✅ LO hat PDF erstellt: {os.path.basename(expected_pdf_path)}"
            )
            return expected_pdf_path
        log_message(
            f"❌ LO-Konv.: {os.path.basename(expected_pdf_path)} nicht gefunden (Exit 0)."
        )
        if result.stdout:
            log_message(f"LO stdout: {result.stdout.strip()[:200]}")
        if result.stderr:
            log_message(f"LO stderr: {result.stderr.strip()[:200]}")
        return None
    except subprocess.TimeoutExpired:
        log_message(f"❌ LO-Konv. Timeout: {os.path.basename(input_path)}")
        return None
    except Exception as exc:
        log_message(f"❌ LO-Konv. Fehler {os.path.basename(input_path)}: {exc}")
        return None


def convert_to_pdf(
    input_path: str,
    password: str = "ukestudi",
    pdf_target_base_name: str | None = None,
) -> bool:
    dirname, original_fn_ext = os.path.split(input_path)
    original_base_from_input, original_ext_str = os.path.splitext(original_fn_ext)
    actual_final_base_name = (
        pdf_target_base_name if pdf_target_base_name else original_base_from_input
    )
    if not actual_final_base_name.strip():
        actual_final_base_name = f"konvertiert_{int(time.time())}"
        log_message(
            f"⚠️ Basisname leer, verwende Fallback {actual_final_base_name} für {original_fn_ext}."
        )
    temp_decrypted_del = None
    try:
        conv_input_path = input_path
        if original_ext_str.lower() in [".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx"]:
            log_message(f"Entschlüssele Office-Datei: {original_fn_ext}...")
            conv_input_path, temp_decrypted_del = decrypt_office_file(
                input_path, password
            )
            if not conv_input_path:
                log_message(f"Entschlüsselung von {original_fn_ext} fehlgeschlagen.")
                return False
        if original_ext_str.lower() == ".pdf":
            log_message(
                f"Versuche Passwortentfernung für PDF {original_fn_ext} (Passwort: {password})."
            )
            return handle_password_protected_pdf(conv_input_path, password)
        created_pdf_lo = convert_with_libreoffice(conv_input_path, dirname)
        if not created_pdf_lo or not os.path.exists(created_pdf_lo):
            log_message(
                f"❌ PDF-Erstellung (LibreOffice) für {original_fn_ext} (aus {os.path.basename(conv_input_path)}) fehlgeschlagen."
            )
            return False
        final_pdf_path = os.path.join(dirname, f"{actual_final_base_name}.pdf")
        if os.path.exists(final_pdf_path):
            base_name_without_ext = os.path.splitext(actual_final_base_name)[0]
            final_pdf_path = os.path.join(
                dirname,
                f"{base_name_without_ext}_{int(time.time())}.pdf",
            )
        try:
            os.replace(created_pdf_lo, final_pdf_path)
        except Exception as exc:
            log_message(
                f"❌ Umbenennen von konvertierter PDF fehlgeschlagen: {os.path.basename(created_pdf_lo)} -> {os.path.basename(final_pdf_path)}: {exc}"
            )
            if os.path.exists(created_pdf_lo):
                try:
                    os.remove(created_pdf_lo)
                except Exception as cleanup_exc:
                    log_message(
                        f"Konnte fehlerhafte LO PDF nicht löschen: {os.path.basename(created_pdf_lo)} - {cleanup_exc}"
                    )
            return False
        log_message(
            f"✅ PDF erstellt mit korrektem Namen: {os.path.basename(final_pdf_path)}"
        )
        return True
    except Exception as exc:
        log_message(f"❌ Kritischer Fehler in convert_to_pdf für {original_fn_ext}: {exc}")
        log_message(traceback.format_exc())
        return False
    finally:
        if temp_decrypted_del and os.path.exists(temp_decrypted_del):
            try:
                os.remove(temp_decrypted_del)
                log_message(
                    f"Temporäre entschlüsselte Datei {os.path.basename(temp_decrypted_del)} entfernt."
                )
            except Exception as cleanup_exc:
                log_message(
                    f"⚠️ Fehler beim Löschen der temporären Datei {os.path.basename(temp_decrypted_del)}: {cleanup_exc}"
                )


class LoginDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Login")
        self.setModal(True)
        self.setFixedWidth(360)
        self.username = ""
        self.password = ""
        self.remember_credentials = False
        self._build_ui()

    def _build_ui(self) -> None:
        font = QFont("Segoe UI", 10)
        self.setFont(font)
        self.setStyleSheet(
            f"""
            QDialog {{
                background-color: {COLOR_DARK_BLUE};
                color: {COLOR_WHITE};
            }}
            QLineEdit {{
                background-color: {COLOR_WHITE};
                color: {COLOR_DARK_BLUE};
                border-radius: 6px;
                padding: 6px 8px;
            }}
            QLabel {{
                color: {COLOR_WHITE};
                font-weight: 600;
            }}
            QCheckBox {{
                color: {COLOR_WHITE};
            }}
            QPushButton {{
                background-color: {COLOR_WHITE};
                color: {COLOR_DARK_BLUE};
                border-radius: 6px;
                padding: 8px 14px;
                border: 2px solid transparent;
            }}
            QPushButton:hover {{
                border-color: {COLOR_ACCENT_ORANGE};
            }}
            QPushButton:pressed {{
                background-color: {COLOR_BUTTON_ACTIVE_BG};
                color: {COLOR_WHITE};
            }}
        """
        )
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(QLabel("Benutzername:"))
        self.username_edit = QLineEdit(self)
        self.username_edit.setPlaceholderText("imed\u2026")
        layout.addWidget(self.username_edit)
        layout.addWidget(QLabel("Passwort:"))
        self.password_edit = QLineEdit(self)
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.password_edit)
        self.save_checkbox = QCheckBox("Anmeldedaten speichern", self)
        layout.addWidget(self.save_checkbox)
        button_box = QDialogButtonBox(self)
        self.cancel_button = button_box.addButton(
            "Abbrechen", QDialogButtonBox.ButtonRole.RejectRole
        )
        self.login_button = button_box.addButton(
            "Login", QDialogButtonBox.ButtonRole.AcceptRole
        )
        layout.addWidget(button_box)
        self.cancel_button.clicked.connect(self.reject)
        self.login_button.clicked.connect(self._attempt_login)
        self.username_edit.setText(USERNAME)
        self.password_edit.setText(PASSWORD)
        if USERNAME and PASSWORD:
            self.save_checkbox.setChecked(True)
        self.username_edit.setFocus()

    def _attempt_login(self) -> None:
        uname = self.username_edit.text().strip()
        pwd = self.password_edit.text().strip()
        if not uname or not pwd:
            QMessageBox.critical(
                self,
                "Fehler",
                "Benutzername und Passwort dürfen nicht leer sein.",
            )
            return
        driver = None
        self.login_button.setEnabled(False)
        try:
            log_message("Login-Versuch gestartet...")
            driver = create_driver()
            if not login(driver, uname, pwd):
                raise Exception("Ungültige Anmeldedaten oder Seite nicht erreichbar")
        except Exception as exc:
            log_message(f"Login fehlgeschlagen: {exc}")
            QMessageBox.critical(
                self,
                "Login fehlgeschlagen",
                f"Benutzername oder Passwort ungültig oder Seite nicht erreichbar.\nDetails: {exc}",
            )
            self.login_button.setEnabled(True)
            if driver:
                driver.quit()
            return
        finally:
            if driver:
                driver.quit()
        self.username = uname
        self.password = pwd
        self.remember_credentials = self.save_checkbox.isChecked()
        self.accept()


class LogWindow(QDialog):
    def __init__(self, parent: QWidget, logs: list[tuple[str, str]]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Anwendungs-Logs")
        self.resize(parent.width(), parent.height())
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setStyleSheet(
            f"""
            QDialog {{
                background-color: {COLOR_DARK_BLUE};
            }}
            QTextEdit {{
                background-color: {COLOR_WHITE};
                color: {COLOR_DARK_BLUE};
                border-radius: 8px;
                padding: 10px;
                font-family: 'Consolas', 'Courier New', monospace;
            }}
        """
        )
        layout = QVBoxLayout(self)
        self.text_edit = QTextEdit(self)
        self.text_edit.setReadOnly(True)
        layout.addWidget(self.text_edit)
        self.set_logs(logs)

    def set_logs(self, logs: list[tuple[str, str]]) -> None:
        self.text_edit.clear()
        for timestamp_str, message_text in logs:
            self.text_edit.append(f"{timestamp_str} - {message_text}")
        self.text_edit.moveCursor(QTextCursor.MoveOperation.End)

    def append_log(self, timestamp_str: str, message_text: str) -> None:
        self.text_edit.append(f"{timestamp_str} - {message_text}")
        self.text_edit.moveCursor(QTextCursor.MoveOperation.End)


class FetchEventsWorker(QObject):
    finished = pyqtSignal()
    events_ready = pyqtSignal(list)
    progress_text = pyqtSignal(str)

    def __init__(self, username: str, password: str, week_choice: str) -> None:
        super().__init__()
        self.username = username
        self.password = password
        self.week_choice = week_choice

    def run(self) -> None:
        driver = None
        try:
            log_message("Lade Ereignisse...")
            driver = create_driver()
            if not login(driver, self.username, self.password):
                self.progress_text.emit("Login fehlgeschlagen.")
                return
            open_schedule(driver, self.week_choice)
            events = driver.find_elements(By.CSS_SELECTOR, "a.vatitle")
            event_links: list[tuple[str, str]] = []
            for event in events:
                title = event.text.strip()
                href = event.get_attribute("href")
                if not href or not title:
                    continue
                try:
                    weekday = event.find_element(
                        By.XPATH, "./ancestor::tr/td[@class='tday']/b"
                    ).text.strip()
                except Exception:
                    weekday = ""
                display = f"{title} ({weekday})" if weekday else title
                event_links.append((display, href))
            if not event_links:
                log_message("Keine Ereignisse gefunden.")
                self.progress_text.emit("Keine Ereignisse gefunden.")
                return
            log_message(f"{len(event_links)} Ereignisse gefunden")
            self.events_ready.emit(event_links)
            self.progress_text.emit(
                f"{len(event_links)} Ereignisse gefunden. Wähle aus."
            )
        except Exception as exc:
            log_message(f"Ereignisse laden fehlgeschlagen: {exc}")
            self.progress_text.emit(f"Ereignisse laden fehlgeschlagen: {exc}")
        finally:
            if driver:
                driver.quit()
            self.finished.emit()


class DownloadWorker(QObject):
    finished = pyqtSignal()
    progress_text = pyqtSignal(str)
    progress_range = pyqtSignal(int, int)
    progress_value = pyqtSignal(int)
    summary = pyqtSignal(str)

    def __init__(
        self,
        events: list[EventItem],
        download_path: str,
        convert_enabled: bool,
        username: str,
        password: str,
    ) -> None:
        super().__init__()
        self.events = events
        self.download_path = download_path
        self.convert_enabled = convert_enabled
        self.username = username
        self.password = password

    def run(self) -> None:
        if not self.events:
            self.finished.emit()
            return
        driver = None
        try:
            self.progress_text.emit("Starte Download...")
            self.progress_range.emit(0, len(self.events))
            self.progress_value.emit(0)
            log_message(f"Starte Download von {len(self.events)} Ereignissen...")
            driver = create_driver()
            if not login(driver, self.username, self.password):
                self.progress_text.emit("Login fehlgeschlagen (Download).")
                return
            dl_count = 0
            conv_count = 0
            fail_conv_count = 0
            os.makedirs(self.download_path, exist_ok=True)
            global BASE_DOWNLOAD_PATH
            BASE_DOWNLOAD_PATH = self.download_path
            for count, event in enumerate(self.events, start=1):
                full_title = event.title
                event_page_link = event.link
                safe_title_temp = re.sub(r"[^\w\s\-_.()]", "_", full_title)
                display_title = (
                    safe_title_temp[:60] + "..."
                    if len(safe_title_temp) > 60
                    else safe_title_temp
                )
                log_message(f"Bearbeite ({count}/{len(self.events)}): {safe_title_temp}")
                self.progress_text.emit(
                    f"({count}/{len(self.events)}) Lade: {display_title}"
                )
                wd_match = re.search(r"\((Mo|Di|Mi|Do|Fr|Sa|So)\)", safe_title_temp)
                wd_folder = wd_match.group(1) if wd_match else "Unbekannt"
                event_folder = os.path.join(self.download_path, wd_folder)
                os.makedirs(event_folder, exist_ok=True)
                driver.execute_script(
                    "window.open(arguments[0], '_blank');", event_page_link
                )
                time.sleep(WAIT_SHORT / 2)
                driver.switch_to.window(driver.window_handles[-1])
                time.sleep(WAIT_SHORT * 2)
                if wd_match:
                    fn_title_event = (
                        safe_title_temp.replace(wd_match.group(0), "").strip()
                    )
                else:
                    fn_title_event = safe_title_temp
                fn_title_event = re.sub(r"\s+", "_", fn_title_event)
                fn_title_event = re.sub(r"[^\w\-_.]", "", fn_title_event)[:100]
                page_dl_links = driver.find_elements(
                    By.XPATH,
                    "//a[contains(@href, '/dl.php?') or contains(@href, 'download.php') or contains(@class, 'download') or contains(@href, '.pdf') or contains(@href, '.pptx') or contains(@href, '.docx') or contains(@href, '.xlsx')]",
                )
                if not page_dl_links:
                    log_message(
                        f"Keine Download-Links für {safe_title_temp} gefunden."
                    )
                sel_cookies = driver.get_cookies()
                session = requests.Session()
                for cookie in sel_cookies:
                    session.cookies.set(cookie["name"], cookie["value"])
                for link_idx, link_el in enumerate(page_dl_links):
                    file_url = link_el.get_attribute("href")
                    if not file_url or not file_url.startswith("http"):
                        if file_url and not file_url.startswith("http"):
                            file_url = requests.compat.urljoin(
                                driver.current_url, file_url
                            )
                        else:
                            continue
                    link_text = link_el.text.strip()
                    server_fn = ""
                    try:
                        head_response = session.head(
                            file_url, allow_redirects=True, timeout=20
                        )
                        if "Content-Disposition" in head_response.headers:
                            disp = head_response.headers["Content-Disposition"]
                            filename_match = re.search(
                                r"filename\*?=(?:UTF-\d{1,2}'')?([^\";]+)",
                                disp,
                                re.IGNORECASE,
                            )
                            if filename_match:
                                server_fn = requests.utils.unquote(
                                    filename_match.group(1)
                                ).strip('"')
                    except requests.exceptions.RequestException as exc:
                        log_message(f"HEAD-Req. Fehler {file_url}: {exc}")
                    base_fn_dl = server_fn or link_text or f"datei_{link_idx + 1}"
                    _, server_file_ext_only = os.path.splitext(base_fn_dl)
                    if not server_file_ext_only and file_url:
                        _, server_file_ext_only = os.path.splitext(
                            file_url.split("?")[0].split("#")[0]
                        )
                    file_ext = server_file_ext_only.lower()
                    pdf_target_clean_base = re.sub(
                        r"[^\w\-_.,() ]",
                        "_",
                        os.path.splitext(base_fn_dl)[0],
                    )
                    pdf_target_clean_base = re.sub(
                        r"_+", "_", pdf_target_clean_base
                    ).strip(" _")[:80]
                    if not pdf_target_clean_base:
                        pdf_target_clean_base = (
                            f"unbenannte_datei_{link_idx + 1}"
                        )
                    timestamp_str = time.strftime("%Y%m%d-%H%M%S")
                    original_download_fn = (
                        f"{fn_title_event}_{timestamp_str}_{pdf_target_clean_base}{file_ext}"
                    )
                    original_download_fn = re.sub(
                        r"_+", "_", original_download_fn
                    ).strip("_")[:200]
                    save_path = os.path.join(event_folder, original_download_fn)
                    try:
                        log_message(
                            f"Lade herunter: {original_download_fn} von {file_url[:70]}..."
                        )
                        response = session.get(file_url, timeout=180)
                        response.raise_for_status()
                        with open(save_path, "wb") as out_file:
                            out_file.write(response.content)
                        dl_count += 1
                        log_message(
                            f"✅ Heruntergeladen: {original_download_fn}"
                        )
                    except requests.exceptions.RequestException as exc:
                        log_message(f"❌ Download {original_download_fn}: {exc}")
                        continue
                    except Exception as exc:
                        log_message(f"❌ Speichern {original_download_fn}: {exc}")
                        continue
                    if (
                        self.convert_enabled
                        and file_ext
                        and file_ext.lower()
                        not in [".zip", ".rar", ".7z", ".gz", ".tar", ".tgz"]
                    ):
                        log_message(
                            f"Verarbeite: {original_download_fn} -> Ziel-Basisname für PDF: {pdf_target_clean_base}"
                        )
                        conv_ok = convert_to_pdf(
                            save_path,
                            "ukestudi",
                            pdf_target_base_name=pdf_target_clean_base,
                        )
                        if conv_ok:
                            conv_count += 1
                            if file_ext.lower() != ".pdf":
                                try:
                                    os.remove(save_path)
                                    log_message(
                                        f"Originaldatei ({os.path.basename(save_path)}) entfernt nach Konvertierung."
                                    )
                                except OSError as exc:
                                    log_message(
                                        f"⚠️ Originaldatei ({os.path.basename(save_path)}) konnte nicht entfernt werden: {exc}"
                                    )
                        else:
                            fail_conv_count += 1
                            log_message(
                                f"Verarbeitung von {original_download_fn} fehlgeschlagen. Originaldatei bleibt (oder ist fehlerhaft)."
                            )
                if len(driver.window_handles) > 1:
                    driver.close()
                    driver.switch_to.window(driver.window_handles[0])
                    time.sleep(WAIT_SHORT / 4)
                self.progress_value.emit(count)
            summary = f"✅ Download beendet! {dl_count} Dateien heruntergeladen."
            if self.convert_enabled:
                summary += (
                    f" {conv_count} verarbeitet/konvertiert, {fail_conv_count} Verarbeitungsfehler."
                )
            log_message(summary)
            self.summary.emit(summary)
        except Exception as exc:
            log_message(f"🚫 Fehler im Download: {exc}")
            log_message(traceback.format_exc())
            self.progress_text.emit(f"Kritischer Fehler: {exc}")
        finally:
            if driver:
                driver.quit()
            self.finished.emit()


class MainWindow(QMainWindow):
    log_signal = pyqtSignal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ImedCampus Downloader")
        self.resize(1000, 720)
        self.setMinimumSize(820, 600)
        self.download_path = os.path.expanduser("~/Downloads/ImedCampus")
        self.week_choice = "aktuell"
        self.convert_enabled = True
        self.event_items: list[EventItem] = []
        self.checkbox_widgets: list[QCheckBox] = []
        self.select_all_checkbox: QCheckBox | None = None
        self.log_buffer: list[tuple[str, str]] = []
        self.log_window: LogWindow | None = None
        self.fetch_thread: QThread | None = None
        self.download_thread: QThread | None = None
        self._build_ui()
        self._connect_signals()

    def _build_ui(self) -> None:
        QApplication.setStyle("Fusion")
        central_widget = QWidget(self)
        central_widget.setObjectName("central")
        self.setCentralWidget(central_widget)
        central_layout = QVBoxLayout(central_widget)
        central_layout.setContentsMargins(20, 20, 20, 12)
        central_layout.setSpacing(16)
        central_widget.setStyleSheet(
            f"""
            QWidget#central {{
                background-color: {COLOR_DARK_BLUE};
                color: {COLOR_WHITE};
                font-family: 'Segoe UI', 'Helvetica Neue', Arial;
            }}
            QGroupBox {{
                border: 1px solid rgba(255, 255, 255, 0.18);
                border-radius: 14px;
                margin-top: 18px;
                padding: 18px;
                font-weight: 600;
                color: {COLOR_WHITE};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 8px;
                color: {COLOR_WHITE};
            }}
            QPushButton {{
                background-color: {COLOR_WHITE};
                color: {COLOR_DARK_BLUE};
                border-radius: 10px;
                padding: 10px 18px;
                border: 2px solid transparent;
                font-weight: 600;
                letter-spacing: 0.5px;
            }}
            QPushButton:hover {{
                border-color: {COLOR_ACCENT_ORANGE};
            }}
            QPushButton:pressed {{
                background-color: {COLOR_BUTTON_ACTIVE_BG};
                color: {COLOR_WHITE};
            }}
            QPushButton:disabled {{
                background-color: {COLOR_LIGHT_BLUE_ACCENT};
                color: rgba(255, 255, 255, 0.6);
            }}
            QLabel {{
                color: {COLOR_WHITE};
            }}
            QRadioButton, QCheckBox {{
                color: {COLOR_WHITE};
            }}
            QScrollArea {{
                border: none;
                background: transparent;
            }}
            QProgressBar {{
                background-color: rgba(18, 44, 87, 0.8);
                color: {COLOR_WHITE};
                border: 1px solid rgba(255, 255, 255, 0.3);
                border-radius: 12px;
                text-align: center;
                padding: 2px;
            }}
            QProgressBar::chunk {{
                background-color: {COLOR_WHITE};
                border-radius: 10px;
            }}
        """
        )
        # Speicherort
        path_group = QGroupBox("Speicherort auswählen", self)
        path_layout = QHBoxLayout(path_group)
        path_layout.setSpacing(12)
        self.path_label = QLabel(self.download_path, path_group)
        self.path_label.setWordWrap(True)
        self.path_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        browse_button = QPushButton("Auswählen …", path_group)
        browse_button.clicked.connect(self._choose_download_path)
        path_layout.addWidget(self.path_label)
        path_layout.addWidget(browse_button)
        central_layout.addWidget(path_group)
        # Woche
        week_group = QGroupBox("Woche auswählen", self)
        week_layout = QHBoxLayout(week_group)
        week_layout.setSpacing(20)
        self.radio_week_current = QRadioButton("Aktuelle Woche", week_group)
        self.radio_week_next = QRadioButton("Nächste Woche", week_group)
        self.radio_week_current.setChecked(True)
        week_layout.addWidget(self.radio_week_current)
        week_layout.addWidget(self.radio_week_next)
        week_layout.addStretch(1)
        central_layout.addWidget(week_group)
        # Optionen
        self.convert_checkbox = QCheckBox(
            "In PDF konvertieren / PDF-Passwort entfernen", self
        )
        self.convert_checkbox.setChecked(True)
        central_layout.addWidget(self.convert_checkbox)
        # Aktionen
        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(12)
        self.load_events_button = QPushButton("Ereignisse laden", self)
        self.download_button = QPushButton("Download Selected", self)
        self.download_button.setEnabled(False)
        self.logs_button = QPushButton("Logs anzeigen", self)
        actions_layout.addWidget(self.load_events_button)
        actions_layout.addWidget(self.download_button)
        actions_layout.addWidget(self.logs_button)
        actions_layout.addStretch(1)
        central_layout.addLayout(actions_layout)
        # Progress
        progress_container = QVBoxLayout()
        progress_container.setSpacing(6)
        self.progress_label = QLabel(
            "Bitte Zielordner und Woche wählen, danach ‚Ereignisse laden' klicken.",
            self,
        )
        self.progress_label.setWordWrap(True)
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        progress_container.addWidget(self.progress_label)
        progress_container.addWidget(self.progress_bar)
        central_layout.addLayout(progress_container)
        # Event Auswahl
        selection_group = QGroupBox("Wähle Ereignisse zum Download", self)
        selection_layout = QVBoxLayout(selection_group)
        selection_layout.setContentsMargins(0, 0, 0, 0)
        selection_layout.setSpacing(0)
        self.scroll_area = QScrollArea(selection_group)
        self.scroll_area.setWidgetResizable(True)
        self.events_container = QWidget()
        self.events_container.setStyleSheet("background: transparent;")
        self.events_layout = QVBoxLayout(self.events_container)
        self.events_layout.setContentsMargins(16, 20, 16, 16)
        self.events_layout.setSpacing(10)
        self.scroll_area.setWidget(self.events_container)
        selection_layout.addWidget(self.scroll_area)
        central_layout.addWidget(selection_group, stretch=1)
        # Footer
        footer_layout = QHBoxLayout()
        footer_layout.addStretch(1)
        copyright_label = QLabel("LLE©", self)
        copyright_label.setStyleSheet(
            f"color: {COPYRIGHT_FG_COLOR}; font-size: 11px;"
        )
        footer_layout.addWidget(copyright_label)
        central_layout.addLayout(footer_layout)

    def _connect_signals(self) -> None:
        self.log_signal.connect(self._handle_log_message)
        self.radio_week_current.toggled.connect(self._update_week_choice)
        self.convert_checkbox.toggled.connect(self._update_convert)
        self.load_events_button.clicked.connect(self.start_fetch_thread)
        self.download_button.clicked.connect(self.start_download_thread)
        self.logs_button.clicked.connect(self.show_log_window)

    def _choose_download_path(self) -> None:
        selected_dir = QFileDialog.getExistingDirectory(
            self,
            "Zielordner auswählen",
            self.download_path,
        )
        if selected_dir:
            self.download_path = selected_dir
            self.path_label.setText(self.download_path)

    def _update_week_choice(self, checked: bool) -> None:
        if checked:
            self.week_choice = "aktuell"
        else:
            self.week_choice = "naechste"

    def _update_convert(self, checked: bool) -> None:
        self.convert_enabled = checked

    def _handle_log_message(self, timestamp_str: str, message_text: str) -> None:
        self.log_buffer.append((timestamp_str, message_text))
        if len(self.log_buffer) > MAX_LOG_BUFFER_SIZE:
            self.log_buffer.pop(0)
        if self.log_window and self.log_window.isVisible():
            self.log_window.append_log(timestamp_str, message_text)

    def show_log_window(self) -> None:
        if self.log_window and self.log_window.isVisible():
            self.log_window.raise_()
            self.log_window.activateWindow()
            return
        self.log_window = LogWindow(self, self.log_buffer)
        self.log_window.finished.connect(self._close_log_window)
        self.log_window.show()

    def _close_log_window(self) -> None:
        self.log_window = None

    def clear_event_list(self) -> None:
        while self.events_layout.count():
            item = self.events_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.checkbox_widgets.clear()
        self.select_all_checkbox = None

    def populate_events(self) -> None:
        self.clear_event_list()
        if not self.event_items:
            self.progress_label.setText("Keine Ereignisse zum Anzeigen.")
            self.download_button.setEnabled(False)
            return
        day_widget = QWidget(self.events_container)
        day_layout = QHBoxLayout(day_widget)
        day_layout.setSpacing(6)
        day_layout.setContentsMargins(0, 0, 0, 0)
        weekdays = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
        for wd_short in weekdays:
            day_button = QPushButton(wd_short, day_widget)
            day_button.setFixedWidth(48)
            day_button.setStyleSheet(
                f"background-color: {COLOR_WHITE}; color: {COLOR_DARK_BLUE}; border-radius: 8px;"
                f"border: 2px solid transparent;"
                f"padding: 6px 0;"
            )
            day_button.clicked.connect(lambda _, w=wd_short: self.select_by_weekday(w))
            day_layout.addWidget(day_button)
        day_layout.addStretch(1)
        self.events_layout.addWidget(day_widget)
        self.select_all_checkbox = QCheckBox("Alle auswählen", self.events_container)
        self.select_all_checkbox.setTristate(True)
        self.select_all_checkbox.stateChanged.connect(self._select_all_changed)
        self.events_layout.addWidget(self.select_all_checkbox)
        for item in self.event_items:
            checkbox = QCheckBox(item.title, self.events_container)
            checkbox.setWordWrap(True)
            checkbox.stateChanged.connect(self._sync_select_all)
            checkbox.setStyleSheet("QCheckBox { font-size: 14px; }")
            self.events_layout.addWidget(checkbox)
            self.checkbox_widgets.append(checkbox)
        self.events_layout.addStretch(1)
        self.download_button.setEnabled(True)

    def _select_all_changed(self, state: int) -> None:
        checked = state == Qt.CheckState.Checked
        for checkbox in self.checkbox_widgets:
            checkbox.blockSignals(True)
            checkbox.setChecked(checked)
            checkbox.blockSignals(False)

    def _sync_select_all(self) -> None:
        if not self.select_all_checkbox:
            return
        all_checked = all(cb.isChecked() for cb in self.checkbox_widgets)
        any_checked = any(cb.isChecked() for cb in self.checkbox_widgets)
        if all_checked:
            self.select_all_checkbox.blockSignals(True)
            self.select_all_checkbox.setCheckState(Qt.CheckState.Checked)
            self.select_all_checkbox.blockSignals(False)
        elif any_checked:
            self.select_all_checkbox.blockSignals(True)
            self.select_all_checkbox.setCheckState(Qt.CheckState.PartiallyChecked)
            self.select_all_checkbox.blockSignals(False)
        else:
            self.select_all_checkbox.blockSignals(True)
            self.select_all_checkbox.setCheckState(Qt.CheckState.Unchecked)
            self.select_all_checkbox.blockSignals(False)

    def select_by_weekday(self, weekday_short: str) -> None:
        found = False
        for checkbox, item in zip(self.checkbox_widgets, self.event_items):
            if f"({weekday_short})" in item.title:
                checkbox.setChecked(True)
                found = True
        if not found:
            log_message(f"Keine Ereignisse für '{weekday_short}' gefunden.")
        self._sync_select_all()

    def start_fetch_thread(self) -> None:
        if not USERNAME or not PASSWORD:
            QMessageBox.information(
                self,
                "Login benötigt",
                "Bitte zuerst einloggen, bevor Ereignisse geladen werden.",
            )
            return
        self.load_events_button.setEnabled(False)
        self.download_button.setEnabled(False)
        self.progress_label.setText("Ereignisse werden geladen...")
        self.progress_bar.setRange(0, 0)
        self.clear_event_list()
        self.fetch_thread = QThread(self)
        self.fetch_worker = FetchEventsWorker(
            USERNAME, PASSWORD, self.week_choice
        )
        self.fetch_worker.moveToThread(self.fetch_thread)
        self.fetch_thread.started.connect(self.fetch_worker.run)
        self.fetch_worker.events_ready.connect(self._on_events_ready)
        self.fetch_worker.progress_text.connect(self.progress_label.setText)
        self.fetch_worker.finished.connect(self._on_fetch_finished)
        self.fetch_worker.finished.connect(self.fetch_worker.deleteLater)
        self.fetch_thread.finished.connect(self.fetch_thread.deleteLater)
        self.fetch_thread.start()

    def _on_events_ready(self, events: list[tuple[str, str]]) -> None:
        self.event_items = [EventItem(title, link) for title, link in events]
        self.populate_events()

    def _on_fetch_finished(self) -> None:
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.load_events_button.setEnabled(True)
        if self.fetch_thread:
            thread = self.fetch_thread
            self.fetch_thread = None
            thread.quit()

    def start_download_thread(self) -> None:
        selected_items = [
            item
            for item, checkbox in zip(self.event_items, self.checkbox_widgets)
            if checkbox.isChecked()
        ]
        if not selected_items:
            log_message("Keine Ereignisse ausgewählt.")
            self.progress_label.setText("Keine Ereignisse ausgewählt.")
            return
        self.load_events_button.setEnabled(False)
        self.download_button.setEnabled(False)
        self.progress_bar.setRange(0, len(selected_items))
        self.progress_bar.setValue(0)
        self.progress_label.setText("Starte Download...")
        self.download_thread = QThread(self)
        self.download_worker = DownloadWorker(
            events=selected_items,
            download_path=self.download_path,
            convert_enabled=self.convert_enabled,
            username=USERNAME,
            password=PASSWORD,
        )
        self.download_worker.moveToThread(self.download_thread)
        self.download_thread.started.connect(self.download_worker.run)
        self.download_worker.progress_text.connect(self.progress_label.setText)
        self.download_worker.progress_range.connect(self.progress_bar.setRange)
        self.download_worker.progress_value.connect(self.progress_bar.setValue)
        self.download_worker.summary.connect(self._on_download_summary)
        self.download_worker.finished.connect(self._on_download_finished)
        self.download_worker.finished.connect(self.download_worker.deleteLater)
        self.download_thread.finished.connect(self.download_thread.deleteLater)
        self.download_thread.start()

    def _on_download_summary(self, summary: str) -> None:
        self.progress_label.setText(summary)
        QApplication.beep()

    def _on_download_finished(self) -> None:
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.load_events_button.setEnabled(True)
        self.download_button.setEnabled(True)
        if self.download_thread:
            thread = self.download_thread
            self.download_thread = None
            thread.quit()


def show_login_dialog(parent: MainWindow) -> bool:
    dialog = LoginDialog(parent)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        global USERNAME, PASSWORD
        USERNAME, PASSWORD = dialog.username, dialog.password
        if dialog.remember_credentials:
            save_credentials(USERNAME, PASSWORD)
        else:
            delete_saved_credentials()
        return True
    return False


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    global MAIN_WINDOW
    MAIN_WINDOW = window
    load_saved_credentials()
    if not show_login_dialog(window):
        sys.exit(0)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
