import os
import shutil
import socket
import time
from urllib.parse import urlparse

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

from project_config import env_int, env_path_str, env_str

# ================== USER CONFIGURATION =====================
USERNAME = env_str("NETECO_USERNAME")
PASSWORD = env_str("NETECO_PASSWORD")
URL = env_str("NETECO_URL")

DOWNLOAD_DIR = env_path_str("NETECO_DOWNLOAD_DIR", os.path.join(os.path.expanduser("~"), "Downloads"))
EXPORT_BASE_DIR = env_path_str("NETECO_EXPORT_BASE_DIR", r"C:\Current_Alarms")

WAIT_TIMEOUT = env_int("NETECO_WAIT_TIMEOUT", 60)
INTERVAL_SECONDS = env_int("NETECO_INTERVAL_SECONDS", 300)
DOWNLOAD_TIMEOUT_SECONDS = env_int("NETECO_DOWNLOAD_TIMEOUT_SECONDS", 180)
DOWNLOAD_STABLE_SECONDS = env_int("NETECO_DOWNLOAD_STABLE_SECONDS", 5)
RETRY_DELAY_SECONDS = env_int("NETECO_RETRY_DELAY_SECONDS", 60)
MAX_CONSECUTIVE_FAILURES = env_int("NETECO_MAX_CONSECUTIVE_FAILURES", 5)
PORT_CHECK_TIMEOUT = env_int("NETECO_PORT_CHECK_TIMEOUT", 5)

TEMP_DOWNLOAD_EXTENSIONS = (".crdownload", ".tmp", ".partial")

if not USERNAME or not PASSWORD or not URL:
    raise RuntimeError(
        "NETECO_USERNAME, NETECO_PASSWORD, and NETECO_URL must be configured in .env or environment variables."
    )


def log(message):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)


def wait_for_ready_state(driver, timeout=WAIT_TIMEOUT):
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )


def wait_and_fill(driver, locator, text, timeout=WAIT_TIMEOUT):
    elem = WebDriverWait(driver, timeout).until(EC.visibility_of_element_located(locator))
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", elem)
    try:
        elem.clear()
        elem.send_keys(text)
    except WebDriverException:
        driver.execute_script(
            "arguments[0].value = arguments[1]; arguments[0].dispatchEvent(new Event('input')); arguments[0].dispatchEvent(new Event('change'));",
            elem,
            text,
        )
    return elem


def wait_and_click(driver, locator, timeout=WAIT_TIMEOUT):
    elem = WebDriverWait(driver, timeout).until(EC.element_to_be_clickable(locator))
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", elem)
    try:
        elem.click()
    except WebDriverException:
        driver.execute_script("arguments[0].click();", elem)
    return elem


def print_driver_versions(driver):
    caps = driver.capabilities
    browser_version = caps.get("browserVersion") or caps.get("version")
    chromedriver_version = None
    if isinstance(caps.get("chrome"), dict):
        chromedriver_version = caps["chrome"].get("chromedriverVersion")
    chromedriver_version = chromedriver_version or caps.get("chromedriverVersion")
    if chromedriver_version:
        chromedriver_version = chromedriver_version.split(" ")[0]
    log(f"Browser version: {browser_version}")
    log(f"ChromeDriver version: {chromedriver_version}")


def wait_until_url_port_is_open(url, timeout=PORT_CHECK_TIMEOUT):
    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError as exc:
        log(f"Cannot connect to {host}:{port}: {exc}")
        return False


def is_complete_download(path):
    if path.lower().endswith(TEMP_DOWNLOAD_EXTENSIONS):
        return False

    try:
        first_size = os.path.getsize(path)
        time.sleep(DOWNLOAD_STABLE_SECONDS)
        second_size = os.path.getsize(path)
    except OSError:
        return False

    return first_size > 0 and first_size == second_size


def wait_for_download(download_dir, before_files, timeout=DOWNLOAD_TIMEOUT_SECONDS):
    end_time = time.time() + timeout

    while time.time() < end_time:
        current_files = set(os.listdir(download_dir))
        new_files = [
            name
            for name in current_files - before_files
            if not name.lower().endswith(TEMP_DOWNLOAD_EXTENSIONS)
        ]

        newest_first = sorted(
            (os.path.join(download_dir, name) for name in new_files),
            key=os.path.getmtime,
            reverse=True,
        )

        for path in newest_first:
            if os.path.isfile(path) and is_complete_download(path):
                return path

        time.sleep(2)

    return None


def init_driver():
    chrome_options = Options()
    chrome_options.set_capability("acceptInsecureCerts", True)
    chrome_options.page_load_strategy = "eager"

    chrome_options.add_argument("--ignore-certificate-errors")
    chrome_options.add_argument("--allow-insecure-localhost")
    chrome_options.add_argument("--allow-running-insecure-content")
    chrome_options.add_argument("--allow-legacy-insecure-renegotiation")
    chrome_options.add_argument("--start-maximized")

    chrome_options.add_experimental_option(
        "prefs",
        {
            "download.default_directory": DOWNLOAD_DIR,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "profile.default_content_setting_values.automatic_downloads": 1,
            "profile.default_content_settings.popups": 0,
            "safebrowsing.enabled": True,
            "safebrowsing.disable_download_protection": False,
        },
    )

    log("Starting Chrome...")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    log(f"Using ChromeDriver at: {service.path}")
    print_driver_versions(driver)
    driver.execute_cdp_cmd(
        "Page.setDownloadBehavior",
        {
            "behavior": "allow",
            "downloadPath": DOWNLOAD_DIR,
        },
    )
    driver.set_page_load_timeout(WAIT_TIMEOUT)
    return driver


def login_and_navigate(driver):
    log(f"Navigating to: {URL}")
    driver.get(URL)
    wait_for_ready_state(driver)

    if driver.find_elements(By.ID, "username"):
        log("Filling login form...")
        wait_and_fill(driver, (By.ID, "username"), USERNAME)
        wait_and_fill(driver, (By.ID, "value"), PASSWORD)

        try:
            wait_and_click(driver, (By.ID, "submitDataverify"))
            log("Login submitted via submitDataverify.")
        except Exception:
            try:
                wait_and_click(driver, (By.ID, "btn_outerverify"))
                log("Login submitted via btn_outerverify.")
            except Exception as exc:
                log(f"Login click failed: {exc}")
    else:
        log("Login form not present; assuming an active session.")

    time.sleep(5)

    try:
        dev_mgmt = WebDriverWait(driver, WAIT_TIMEOUT).until(
            EC.visibility_of_element_located((By.XPATH, "//span[@title='Device Management']"))
        )
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", dev_mgmt)
        time.sleep(2)
        driver.execute_script("arguments[0].click();", dev_mgmt)
    except Exception as exc:
        log(f"Device Management link not found: {exc}")

    try:
        current_alarms_xpath = (
            "//span[normalize-space()='Current Alarms'] | "
            "//a[normalize-space()='Current Alarms'] | "
            "//*[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'current alarms')]"
        )
        current_alarms_btn = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.XPATH, current_alarms_xpath))
        )
        driver.execute_script("arguments[0].click();", current_alarms_btn)
        log("Reached Current Alarms.")
    except Exception as exc:
        log(f"Could not open Current Alarms: {exc}")

    time.sleep(10)


def click_export_button(driver):
    driver.switch_to.default_content()
    iframes = driver.find_elements(By.TAG_NAME, "iframe")

    for frame in iframes:
        driver.switch_to.default_content()
        driver.switch_to.frame(frame)
        try:
            export_container = driver.find_element(By.ID, "exportBtn")
            export_button = export_container.find_element(By.TAG_NAME, "button")
            driver.execute_script("arguments[0].click();", export_button)
            return
        except WebDriverException:
            continue

    driver.switch_to.default_content()
    export_container = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.ID, "exportBtn"))
    )
    export_button = export_container.find_element(By.TAG_NAME, "button")
    driver.execute_script("arguments[0].click();", export_button)


def run_export_sequence(driver):
    before_files = set(os.listdir(DOWNLOAD_DIR))

    click_export_button(driver)

    all_option = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.ID, "allExport"))
    )
    driver.execute_script("arguments[0].click();", all_option)

    ok_confirm = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.ID, "confirmBtn"))
    )
    driver.execute_script("arguments[0].click();", ok_confirm)

    downloaded_file = wait_for_download(DOWNLOAD_DIR, before_files)
    if not downloaded_file:
        log("Download timed out. Next export will wait for the normal interval.")
        return False

    dest_dir = os.path.join(EXPORT_BASE_DIR, time.strftime("%Y-%m-%d"))
    os.makedirs(dest_dir, exist_ok=True)

    extension = os.path.splitext(downloaded_file)[1]
    new_name = f"CurrentAlarms_NetEco_{time.strftime('%Y%m%d_%H%M%S')}{extension}"
    new_path = os.path.join(dest_dir, new_name)

    shutil.move(downloaded_file, new_path)
    log(f"Saved: {new_path}")
    return True


def close_driver(driver):
    if driver:
        try:
            driver.quit()
        except WebDriverException:
            pass


def main():
    driver = None
    consecutive_failures = 0

    try:
        while True:
            try:
                if not wait_until_url_port_is_open(URL):
                    raise ConnectionError("Target URL is not reachable before opening Chrome")

                if driver is None:
                    driver = init_driver()

                login_and_navigate(driver)
                success = run_export_sequence(driver)
                consecutive_failures = 0 if success else consecutive_failures + 1

                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    log("Stopped after consecutive failures. Check NetEco service, HTTPS/TLS compatibility, VPN/routing, and credentials.")
                    break

                log(f"Waiting {INTERVAL_SECONDS} seconds before next export attempt...")
                time.sleep(INTERVAL_SECONDS)

            except Exception as exc:
                consecutive_failures += 1
                log(f"Error occurred: {exc}")
                if driver:
                    try:
                        driver.save_screenshot(f"error_{time.strftime('%Y%m%d_%H%M%S')}.png")
                    except Exception:
                        pass
                    close_driver(driver)
                    driver = None

                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    log("Stopped after consecutive failures. Check NetEco service, HTTPS/TLS compatibility, VPN/routing, and credentials.")
                    break

                log(f"Restarting browser session in {RETRY_DELAY_SECONDS} seconds...")
                time.sleep(RETRY_DELAY_SECONDS)

    finally:
        close_driver(driver)


if __name__ == "__main__":
    main()
