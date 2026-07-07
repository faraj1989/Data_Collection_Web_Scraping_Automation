import os
import time
import shutil
import winreg
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from project_config import env_int, env_path_str, env_str

# ================== USER CONFIG =====================
USERNAME = env_str("MAE_USERNAME")
PASSWORD = env_str("MAE_PASSWORD")
URL = env_str("MAE_URL")
DOWNLOAD_DIR = env_path_str("MAE_DOWNLOAD_DIR", os.path.join(os.path.expanduser("~"), "Downloads"))
EXPORT_BASE_DIR = env_path_str("MAE_EXPORT_BASE_DIR", r"C:\Current_Alarms")
WAIT_TIMEOUT = env_int("MAE_WAIT_TIMEOUT", 45)
INTERVAL_SECONDS = env_int("MAE_INTERVAL_SECONDS", 300)

# =====================================================

if not USERNAME or not PASSWORD or not URL:
    raise RuntimeError("MAE_USERNAME, MAE_PASSWORD, and MAE_URL must be configured in .env or environment variables.")

def wait_for_file(download_dir, before_files, timeout=180):
    end = time.time() + timeout
    while time.time() < end:
        now = set(os.listdir(download_dir))
        new_files = [f for f in (now - before_files) if not any(x in f for x in [".crdownload", ".tmp", ".partial"])]
        if new_files:
            full = [os.path.join(download_dir, f) for f in new_files]
            return max(full, key=os.path.getmtime)
        time.sleep(2)
    return None

def wait_for_ready_state(timeout=WAIT_TIMEOUT):
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )

def wait_and_fill(locator, value):
    elem = WebDriverWait(driver, WAIT_TIMEOUT).until(EC.visibility_of_element_located(locator))
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", elem)
    elem.clear()
    elem.send_keys(value)
    return elem

def wait_and_click(locator):
    elem = WebDriverWait(driver, WAIT_TIMEOUT).until(EC.element_to_be_clickable(locator))
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", elem)
    driver.execute_script("arguments[0].click();", elem)
    return elem

def print_driver_versions():
    caps = driver.capabilities
    browser_version = caps.get("browserVersion") or caps.get("version")
    chromedriver_version = None
    if isinstance(caps.get("chrome"), dict):
        chromedriver_version = caps["chrome"].get("chromedriverVersion")
    chromedriver_version = chromedriver_version or caps.get("chromedriverVersion")
    if chromedriver_version:
        chromedriver_version = chromedriver_version.split(" ")[0]
    print(f"🔧 Browser version: {browser_version}")
    print(f"🔧 ChromeDriver version: {chromedriver_version}")

# ========== INITIALIZE BROWSER ==========
chrome_options = Options()
chrome_options.add_argument("--ignore-certificate-errors")
chrome_options.add_argument("--start-maximized")
chrome_options.add_experimental_option("prefs", {
    "download.default_directory": DOWNLOAD_DIR,
    "download.prompt_for_download": False,
})

print("🔧 Initializing ChromeDriver...")
service = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=service, options=chrome_options)
print(f"🔧 Using ChromeDriver at: {service.path}")
print_driver_versions()

def login_and_navigate():
    """Handles initial login and moving to the Current Alarms page."""
    print("🔐 Logging in...")
    driver.get(URL)
    try:
        wait_for_ready_state()

        # Check if login form is present
        has_login_form = len(driver.find_elements(By.ID, "username")) > 0
        
        if has_login_form:
            print("📝 Filling login credentials...")
            
            # Fill username using a visibility wait; fallback to JS assignment
            try:
                username_field = wait_and_fill((By.ID, "username"), USERNAME)
            except Exception:
                username_field = WebDriverWait(driver, WAIT_TIMEOUT).until(
                    EC.presence_of_element_located((By.ID, "username"))
                )
                driver.execute_script(
                    "arguments[0].value = arguments[1]; arguments[0].dispatchEvent(new Event('input'));",
                    username_field,
                    USERNAME,
                )

            # Fill password using a visibility wait; fallback to JS assignment
            try:
                password_field = wait_and_fill((By.ID, "value"), PASSWORD)
            except Exception:
                password_field = WebDriverWait(driver, WAIT_TIMEOUT).until(
                    EC.presence_of_element_located((By.ID, "value"))
                )
                driver.execute_script(
                    "arguments[0].value = arguments[1]; arguments[0].dispatchEvent(new Event('input'));",
                    password_field,
                    PASSWORD,
                )

            print("🔐 Attempting login click...")

            # Try clicking the actual trigger; prefer clickable wait and JS click,
            # but fall back to alternate container if needed.
            try:
                login_span = WebDriverWait(driver, WAIT_TIMEOUT).until(
                    EC.element_to_be_clickable((By.ID, "submitDataverify"))
                )
                driver.execute_script("arguments[0].click();", login_span)
                print("✅ Login clicked via span element")
            except Exception:
                try:
                    login_div = driver.find_element(By.ID, "btn_outerverify")
                    driver.execute_script("arguments[0].click();", login_div)
                    print("✅ Login clicked via btn_outerverify")
                except Exception as e_click:
                    print(f"⚠️ Login click failed: {e_click}")

            # Wait for login to process
            print("⏳ Waiting for login to complete...")
            time.sleep(8)
            
        else:
            print("ℹ️ Login form not present; assuming session is already authenticated.")

        # Navigate to Current Alarms
        print("📡 Navigating to Current Alarms...")
        current_alarms_xpath = (
            "//div[contains(text(), 'Current Alarms')] | "
            "//span[contains(text(), 'Current Alarms')] | "
            "//a[contains(text(), 'Current Alarms')] | "
            "//*[contains(text(), 'Current Alarms')]"
        )
        
        try:
            # Wait for Current Alarms to be present
            current_alarm = WebDriverWait(driver, WAIT_TIMEOUT).until(
                EC.presence_of_element_located((By.XPATH, current_alarms_xpath))
            )
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", current_alarm)
            time.sleep(0.5)
            driver.execute_script("arguments[0].click();", current_alarm)
            print("✅ Current Alarms clicked")
        except Exception as e:
            print(f"⚠️ Could not find Current Alarms: {e}")
            # Try alternative - look for any element with "Current Alarms" text using partial match
            try:
                elements = driver.find_elements(By.XPATH, "//*[contains(text(), 'Current Alarms')]")
                for elem in elements:
                    if elem.is_displayed():
                        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", elem)
                        time.sleep(0.5)
                        driver.execute_script("arguments[0].click();", elem)
                        print("✅ Current Alarms found and clicked via text search")
                        break
            except Exception as e2:
                print(f"⚠️ Alternative click failed: {e2}")
                # Take screenshot for debugging
                driver.save_screenshot("debug_current_alarms.png")
                print("📸 Screenshot saved as debug_current_alarms.png")

        time.sleep(10)
        return True
    except Exception as e:
        print(f"❌ Login/Navigation failed: {e}")
        return False

# ========== MAIN EXECUTION ==========
try:
    # Initial login
    if not login_and_navigate():
        print("❌ Initial login failed. Exiting...")
        driver.quit()
        exit(1)
    
    # Main loop
    while True:
        try:
            print(f"\n🔄 [{time.strftime('%H:%M:%S')}] Refreshing page for latest data...")
            driver.refresh()
            time.sleep(12)
            
            # Check if we were logged out
            if "login" in driver.current_url.lower() or len(driver.find_elements(By.ID, "username")) > 0:
                print("⚠️ Session expired during refresh. Re-logging in...")
                if not login_and_navigate():
                    print("❌ Re-login failed. Exiting...")
                    break
            
            # Switch to the Alarms Iframe
            driver.switch_to.default_content()
            iframe_xpath = "//iframe[contains(@id,'fmAlarmView')]"
            WebDriverWait(driver, WAIT_TIMEOUT).until(
                EC.presence_of_element_located((By.XPATH, iframe_xpath))
            )
            driver.switch_to.frame(driver.find_element(By.XPATH, iframe_xpath))
            
            # Find and Click Export
            print("🔍 Finding Export button...")
            export_xpath = "//button[normalize-space()='Export']"
            export_btn = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.XPATH, export_xpath))
            )
            
            before_files = set(os.listdir(DOWNLOAD_DIR))
            driver.execute_script("arguments[0].click();", export_btn)
            time.sleep(3)
            
            # Handle Export Dialog
            print("📦 Handling Export Dialog...")
            all_opt = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.XPATH, "//*[text()='All']"))
            )
            driver.execute_script("arguments[0].click();", all_opt)
            
            ok_btn = driver.find_element(By.XPATH, "//span[text()='OK']/ancestor::button")
            driver.execute_script("arguments[0].click();", ok_btn)
            
            # Wait for download and move file
            downloaded_file = wait_for_file(DOWNLOAD_DIR, before_files)
            if downloaded_file:
                date_folder = time.strftime("%Y-%m-%d")
                dest_dir = os.path.join(EXPORT_BASE_DIR, date_folder)
                os.makedirs(dest_dir, exist_ok=True)
                new_filename = f"CurrentAlarms_MAE_{time.strftime('%Y%m%d_%H%M%S')}.csv"
                shutil.move(downloaded_file, os.path.join(dest_dir, new_filename))
                print(f"✅ Export Success: {new_filename}")
            else:
                print("❌ Download timed out.")
                
        except Exception as e:
            print(f"⚠️ Cycle Error: {e}")
            driver.save_screenshot(f"error_{time.strftime('%Y%m%d_%H%M%S')}.png")
            driver.get(URL)
            time.sleep(5)
            login_and_navigate()
        
        # Countdown
        print(f"😴 Sleeping for {INTERVAL_SECONDS // 60} minutes...")
        for m in range(INTERVAL_SECONDS // 60, 0, -1):
            print(f"Next update in {m} minutes...", end="\r")
            time.sleep(60)
        remaining_seconds = INTERVAL_SECONDS % 60
        if remaining_seconds > 0:
            time.sleep(remaining_seconds)
            
except KeyboardInterrupt:
    print("\n🛑 Automation stopped by user.")
finally:
    print("Browser remains open. Close it manually when finished.")