"""Export both NetEco Current Alarms views in two tabs of one authenticated browser."""
import importlib.util
import os
import shutil
import sys
import time
import traceback
from pathlib import Path

from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from project_config import env_int, env_path_str, env_str, load_env_file


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent
SOURCE_SCRIPT = PROJECT_ROOT / "neteco_continuous 15-5-2026.py"


def load_base_scraper():
    """Load the existing scraper helpers without starting its main loop."""
    spec = importlib.util.spec_from_file_location("neteco_base_scraper", SOURCE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


load_env_file()
BASE_SCRAPER = load_base_scraper()
ALL_CURRENT_ALARMS_URL = env_str(
    "NETECO_ALL_CURRENT_ALARMS_URL",
    "https://10.171.68.2:31943/eviewwebsite/index.html#path=/fmAlarmApp/fmAlarmView&templateId=120&fmPage=true&_t=1787017955421",
)
DOWNLOAD_DIR = env_path_str("NETECO_DOWNLOAD_DIR", str(Path.home() / "Downloads"))
EXPORT_BASE_DIR = env_path_str("NETECO_EXPORT_BASE_DIR", r"C:\Current_Alarms")
WAIT_TIMEOUT = env_int("NETECO_WAIT_TIMEOUT", 60)
INTERVAL_SECONDS = env_int("NETECO_INTERVAL_SECONDS", 300)
RETRY_DELAY_SECONDS = env_int("NETECO_RETRY_DELAY_SECONDS", 60)
MAX_CONSECUTIVE_FAILURES = env_int("NETECO_MAX_CONSECUTIVE_FAILURES", 5)


def log(message):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)


def ensure_dir(path):
    Path(path).mkdir(parents=True, exist_ok=True)
    return str(path)


def switch_to_alarm_frame(driver):
    """Put the browser in the iframe that contains the common NetEco export controls."""
    driver.switch_to.default_content()
    for frame in driver.find_elements(By.TAG_NAME, "iframe"):
        driver.switch_to.default_content()
        driver.switch_to.frame(frame)
        try:
            driver.find_element(By.ID, "exportBtn")
            return
        except WebDriverException:
            continue
    driver.switch_to.default_content()


def export_all_current_alarm(driver):
    """Export the second-tab view without changing the original NetEco CSV naming."""
    before_files = set(os.listdir(DOWNLOAD_DIR))
    switch_to_alarm_frame(driver)

    export_container = WebDriverWait(driver, WAIT_TIMEOUT).until(
        EC.element_to_be_clickable((By.ID, "exportBtn"))
    )
    export_button = export_container.find_element(By.TAG_NAME, "button")
    driver.execute_script("arguments[0].click();", export_button)

    all_option = WebDriverWait(driver, WAIT_TIMEOUT).until(
        EC.element_to_be_clickable((By.ID, "allExport"))
    )
    driver.execute_script("arguments[0].click();", all_option)
    confirm = WebDriverWait(driver, WAIT_TIMEOUT).until(
        EC.element_to_be_clickable((By.ID, "confirmBtn"))
    )
    driver.execute_script("arguments[0].click();", confirm)

    downloaded_file = BASE_SCRAPER.wait_for_download(DOWNLOAD_DIR, before_files)
    if not downloaded_file:
        raise TimeoutError("All Current Alarms download timed out")

    destination_dir = Path(ensure_dir(Path(EXPORT_BASE_DIR) / time.strftime("%Y-%m-%d")))
    extension = Path(downloaded_file).suffix or ".csv"
    destination = destination_dir / f"NetEco_All_Current_Alarm_{time.strftime('%Y%m%d_%H%M%S')}{extension}"
    shutil.move(downloaded_file, destination)
    log(f"Saved All Current Alarms export: {destination}")
    return destination


def open_all_alarms_tab(driver):
    driver.switch_to.new_window("tab")
    all_handle = driver.current_window_handle
    driver.get(ALL_CURRENT_ALARMS_URL)
    WebDriverWait(driver, WAIT_TIMEOUT).until(
        lambda browser: browser.execute_script("return document.readyState") in {"interactive", "complete"}
    )
    time.sleep(5)
    return all_handle


def main():
    ensure_dir(DOWNLOAD_DIR)
    ensure_dir(EXPORT_BASE_DIR)
    driver = None
    original_handle = None
    all_handle = None
    failures = 0

    while True:
        try:
            if driver is None:
                if not BASE_SCRAPER.wait_until_url_port_is_open(BASE_SCRAPER.URL):
                    raise ConnectionError(f"NetEco is unavailable: {BASE_SCRAPER.URL}")
                driver = BASE_SCRAPER.create_driver()
                BASE_SCRAPER.login_and_navigate(driver)
                original_handle = driver.current_window_handle
                all_handle = open_all_alarms_tab(driver)
                log("Opened second authenticated tab for All Current Alarms.")

            driver.switch_to.window(original_handle)
            BASE_SCRAPER.run_export_sequence(driver)
            log("Saved original Current Alarms export.")

            driver.switch_to.window(all_handle)
            driver.get(ALL_CURRENT_ALARMS_URL)
            WebDriverWait(driver, WAIT_TIMEOUT).until(
                lambda browser: browser.execute_script("return document.readyState") in {"interactive", "complete"}
            )
            time.sleep(3)
            export_all_current_alarm(driver)
            failures = 0
            log(f"Both exports complete; waiting {INTERVAL_SECONDS / 60:.1f} minutes.")
            time.sleep(INTERVAL_SECONDS)

        except KeyboardInterrupt:
            log("Stopped by user.")
            break
        except Exception as exc:
            failures += 1
            error_detail = f"{type(exc).__name__}: {str(exc)}" if str(exc) else f"{type(exc).__name__} (no message)"
            log(f"Dual export cycle failed ({failures}/{MAX_CONSECUTIVE_FAILURES}): {error_detail}")
            log(f"Traceback: {traceback.format_exc()}")
            BASE_SCRAPER.close_driver(driver)
            driver = None
            original_handle = None
            all_handle = None
            if failures >= MAX_CONSECUTIVE_FAILURES:
                raise SystemExit("Stopped after repeated NetEco dual-export failures.")
            time.sleep(RETRY_DELAY_SECONDS)
    BASE_SCRAPER.close_driver(driver)


if __name__ == "__main__":
    main()
