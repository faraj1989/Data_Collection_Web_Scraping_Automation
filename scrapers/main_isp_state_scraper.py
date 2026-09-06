"""Continuous Main ISP State exporter (NCE U2000 Performance Instance).

Same NCE portal (10.171.69.101) and login form as scrapers/nce_active_alarms_scraper.py,
but a completely different app within it: opening "U2000" from the portal
launcher loads Huawei's network manager as a Webswing-streamed Java desktop
application - the UI is a live bitmap painted onto a <canvas> element, not a
normal web page. Most of it has no DOM to select against, so navigating it
means real mouse events at pixel coordinates instead of clicking named
elements. This flow was captured with Chrome DevTools Recorder (two passes,
walked through live with the user) rather than read off existing code, since
this app had no scraper before.

Flow: login -> dismiss post-login warning dialog -> open U2000 -> Performance
Instance -> Group Management tab -> select "ISP" in the tree (pixel clicks) ->
select all -> right-click -> View Historical Data -> Table tab -> More ->
Save All -> CSV -> OK -> file lands in DOWNLOAD_DIR via Chrome's normal
download mechanism, same as every other scraper here.

FRAGILITY WARNING: the tree-selection step (find_isp_canvas, the click/
double-click/focus/select-all/right-click sequence) has no stable selector -
there is no search/filter field in this app (confirmed with the user). It
replays fixed pixel coordinates against a locked window size. If Huawei ever
reorders the "Group Management" tree (a new group added above ISP, etc.) or
the window size drifts, this breaks silently - a wrong/empty export, not an
exception. If that happens, re-record the flow with Chrome DevTools Recorder
(F12 -> Recorder) the same way this file was built, and update
ISP_TREE_CLICKS/ISP_LIST_FOCUS/ISP_CONTEXT_MENU_ITEM below.

There is no deep link into a Webswing app session - unlike the alarm
scrapers, which just refresh their page and re-click Export, every cycle
here must repeat the full click sequence from the portal loading page.
"""
import os
import sys
import shutil
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from project_config import env_int, env_path_str, env_str

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ================== USER CONFIG =====================
USERNAME = env_str("NCE_USERNAME")
PASSWORD = env_str("NCE_PASSWORD")
DEFAULT_URL = (
    "https://10.171.69.101:31943/unisso/login.action?service=%2Funisess%2Fv1%2Fauth%3Fservice"
    "%3D%252Fncecommonwebsite%252Fv1%252Fnewportal%252Fportal%252Floading%252Floading.html&decision=1"
)
URL = env_str("MAIN_ISP_URL", DEFAULT_URL)
DOWNLOAD_DIR = env_path_str(
    "MAIN_ISP_DOWNLOAD_DIR",
    os.path.join(os.path.expanduser("~"), "Downloads", "Main_ISP_State"),
)
EXPORT_BASE_DIR = env_path_str("MAIN_ISP_EXPORT_BASE_DIR", r"C:\Main_ISP_State")
WAIT_TIMEOUT = env_int("MAIN_ISP_WAIT_TIMEOUT", 45)
DOWNLOAD_TIMEOUT = env_int("MAIN_ISP_DOWNLOAD_TIMEOUT", 600)
# This flow is far heavier per cycle than the alarm scrapers (full login +
# ~15 sequential UI steps vs. one Export click) - default interval is longer.
INTERVAL_SECONDS = env_int("MAIN_ISP_INTERVAL_SECONDS", 900)
# Recommended non-headless until a few real cycles have been watched succeed
# (see module docstring / project plan) - flip once trusted.
HEADLESS = env_str("MAIN_ISP_HEADLESS", "false").strip().lower() == "true"

# Locked to the viewport the flow was recorded at - every pixel coordinate
# below is only valid at this exact window size. 1437x877 matches the
# recording of a confirmed, verified-successful manual run (2026-08-30) -
# earlier recordings used 1365x911 and are superseded.
WINDOW_WIDTH, WINDOW_HEIGHT = 1437, 877

# Direct deep link into U2000's Webswing session - previously used in place
# of the portal launcher tile click below, but confirmed live on 2026-09-06
# to no longer reliably reach U2000 (it silently falls back to the portal's
# own default view instead). Kept only as a fallback attempt in
# open_u2000_app(); the tile click is primary now. The fragment after
# "#page=" is base64 for
# "Action=com.huawei.u2000.unitedmgr.topo.action.DoWebTopoAction" - U2000's
# topology view. No session token embedded, so it's safe to hardcode/reuse
# across logins.
DEFAULT_U2000_TOPO_URL = (
    "https://10.171.69.101:31943/nmsnetworkmgrwebsite/v1/webswing/indexforwebswing.html"
    "#page=QWN0aW9uJTNEY29tLmh1YXdlaS51MjAwMC51bml0ZWRtZ3IudG9wby5hY3Rpb24uRG9XZWJUb3BvQWN0aW9u"
)
U2000_TOPO_URL = env_str("MAIN_ISP_TOPO_URL", DEFAULT_U2000_TOPO_URL)

# Portal home page with the app-tile launcher. Re-confirmed working via a
# fresh Chrome DevTools Recorder pass on 2026-09-06: navigate here, then
# click the "Network Management" (U2000) tile.
DEFAULT_PORTAL_HOME_URL = (
    "https://10.171.69.101:31943/ncecommonwebsite/v1/newportal/index.html?refr-flags=e"
)
PORTAL_HOME_URL = env_str("MAIN_ISP_PORTAL_URL", DEFAULT_PORTAL_HOME_URL)

DATA_ROOT = os.environ.get("DATA_ROOT", r"C:\Users\user\Desktop\Libyana_Data")


def ensure_dir(path):
    if not path:
        return path
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)
        print(f"Created directory: {path}")
    return path


DOWNLOAD_DIR = ensure_dir(DOWNLOAD_DIR)
EXPORT_BASE_DIR = ensure_dir(EXPORT_BASE_DIR)
ERROR_SCREENSHOT_DIR = ensure_dir(os.path.join(DATA_ROOT, "Errors"))

if not USERNAME or not PASSWORD:
    raise RuntimeError("NCE_USERNAME and NCE_PASSWORD must be configured in .env or environment variables.")


def wait_for_file(download_dir, before_files, timeout):
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


def print_driver_versions():
    caps = driver.capabilities
    browser_version = caps.get("browserVersion") or caps.get("version")
    chromedriver_version = None
    if isinstance(caps.get("chrome"), dict):
        chromedriver_version = caps["chrome"].get("chromedriverVersion")
    chromedriver_version = chromedriver_version or caps.get("chromedriverVersion")
    if chromedriver_version:
        chromedriver_version = chromedriver_version.split(" ")[0]
    print(f"Browser version: {browser_version}")
    print(f"ChromeDriver version: {chromedriver_version}")


chrome_options = Options()
chrome_options.add_argument("--ignore-certificate-errors")
if HEADLESS:
    chrome_options.add_argument("--headless=new")
chrome_options.add_argument(f"--window-size={WINDOW_WIDTH},{WINDOW_HEIGHT}")
chrome_options.add_experimental_option("prefs", {
    "download.default_directory": DOWNLOAD_DIR,
    "download.prompt_for_download": False,
})

print("Initializing ChromeDriver...")
service = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=service, options=chrome_options)
driver.set_window_size(WINDOW_WIDTH, WINDOW_HEIGHT)
print(f"Using ChromeDriver at: {service.path}")
print_driver_versions()


def login():
    print("Logging in...")
    driver.get(URL)
    wait_for_ready_state()

    has_login_form = len(driver.find_elements(By.ID, "username")) > 0
    if has_login_form:
        print("Filling login credentials...")
        try:
            username_field = wait_and_fill((By.ID, "username"), USERNAME)
        except Exception:
            username_field = WebDriverWait(driver, WAIT_TIMEOUT).until(
                EC.presence_of_element_located((By.ID, "username"))
            )
            driver.execute_script(
                "arguments[0].value = arguments[1]; arguments[0].dispatchEvent(new Event('input'));",
                username_field, USERNAME,
            )
        try:
            password_field = wait_and_fill((By.ID, "value"), PASSWORD)
        except Exception:
            password_field = WebDriverWait(driver, WAIT_TIMEOUT).until(
                EC.presence_of_element_located((By.ID, "value"))
            )
            driver.execute_script(
                "arguments[0].value = arguments[1]; arguments[0].dispatchEvent(new Event('input'));",
                password_field, PASSWORD,
            )

        print("Attempting login click...")
        try:
            login_span = WebDriverWait(driver, WAIT_TIMEOUT).until(
                EC.element_to_be_clickable((By.ID, "submitDataverify"))
            )
            driver.execute_script("arguments[0].click();", login_span)
        except Exception as e_click:
            print(f"Login click failed: {e_click}")

        print("Waiting for login to complete...")
        time.sleep(8)

        if len(driver.find_elements(By.ID, "username")) > 0:
            page_text = driver.page_source.lower()
            login_error_keywords = [
                "invalid username", "invalid password", "incorrect username", "incorrect password",
                "wrong username", "wrong password", "password expired", "expired password",
                "credentials", "login failed", "account locked",
            ]
            if any(keyword in page_text for keyword in login_error_keywords):
                raise RuntimeError("Login failed: invalid credentials or expired password detected.")
            raise RuntimeError("Login appears to have failed; login form still visible.")
    else:
        print("Login form not present; assuming session is already authenticated.")

    # Post-login warning/disclaimer dialog - not present on every login (e.g.
    # only once per day on some sessions), so this is best-effort, not a hard
    # requirement.
    try:
        ok_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, "login_warn_confirm"))
        )
        driver.execute_script("arguments[0].click();", ok_button)
        print("Dismissed post-login warning dialog.")
    except Exception:
        print("No post-login warning dialog appeared (or already dismissed).")

    time.sleep(3)


def _u2000_loaded(timeout=20):
    """True once a real Webswing canvas is present - the only reliable
    signal that U2000 actually loaded. Earlier this checked for the Monitor
    ribbon button's DOM id instead, but that id turned out to be present
    (and clickable) even on the portal's own default page, which is
    presumably a shared id in the portal's menu-registration markup - so it
    passed the check while still being on the wrong page entirely (confirmed
    live 2026-09-06). A canvas can't lie the same way."""
    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[id^='wrapper-'] canvas"))
        )
        return True
    except Exception:
        return False


def open_u2000_app():
    """Navigate to the portal home page and click the "Network Management"
    (U2000) app tile. A direct deep link into U2000's Webswing session
    (U2000_TOPO_URL) was used here previously and was more deterministic
    when it worked, but was confirmed live on 2026-09-06 to no longer
    reliably reach U2000 - it silently falls back to the portal's default
    view instead, and clicking pixel coordinates meant for U2000 against
    that wrong page is what produced a confusing low-level chromedriver
    error rather than an obvious one. The tile click below was re-confirmed
    working the same day via a fresh Chrome DevTools Recorder pass. The old
    deep link is kept as a fallback attempt in case the tile ever becomes
    unreliable again (see module docstring's FRAGILITY WARNING)."""
    print("Opening U2000 app (portal tile)...")
    driver.get(PORTAL_HOME_URL)
    wait_for_ready_state()
    time.sleep(2)

    tile_selectors = [
        (By.CSS_SELECTOR, "div.brick_container_U2020-F_U2000_App div.appComNameContainer"),
        (By.XPATH, '//*[@id="appComContainer_U2020-F_U2000_App"]/div[2]'),
    ]
    clicked = False
    for by, selector in tile_selectors:
        try:
            elem = WebDriverWait(driver, 15).until(EC.element_to_be_clickable((by, selector)))
            driver.execute_script("arguments[0].click();", elem)
            clicked = True
            break
        except Exception:
            continue

    if clicked:
        time.sleep(10)  # Webswing session needs time to establish and paint the canvas

    if not clicked or not _u2000_loaded():
        print("Tile click didn't reach U2000 - falling back to the direct deep link...")
        driver.get(U2000_TOPO_URL)
        wait_for_ready_state()
        time.sleep(10)

    if not _u2000_loaded():
        save_error_screenshot("u2000_not_loaded")
        raise RuntimeError(
            "U2000 app did not load (neither the portal tile nor the direct deep "
            "link produced a Webswing canvas). See the u2000_not_loaded screenshot."
        )


def find_webswing_canvas():
    """The main Webswing viewport canvas. Its wrapper id (wrapper-<number>)
    looked session-generated across recordings, so match structurally
    instead of hardcoding the exact id."""
    return WebDriverWait(driver, WAIT_TIMEOUT).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "[id^='wrapper-'] canvas:nth-of-type(2)"))
    )


def find_context_menu_canvas():
    return WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "#webswing-root-container canvas:nth-of-type(3)"))
    )


def canvas_action(canvas, x, y, kind="click"):
    """Real mouse events at a pixel offset from the canvas's top-left corner
    - matches DOM offsetX/offsetY semantics, which is what Chrome DevTools
    Recorder captured. No JS click here: the remote Java app behind Webswing
    needs genuine mouse coordinates, not a synthetic DOM click."""
    actions = ActionChains(driver).move_to_element_with_offset(canvas, x, y)
    if kind == "double":
        actions.double_click().perform()
    elif kind == "right":
        actions.context_click().perform()
    else:
        actions.click().perform()


def find_frame_containing(by, value, timeout=WAIT_TIMEOUT, max_depth=4):
    """Recursively search every iframe for one containing the given element
    - same defensive approach as scrapers/nce_active_alarms_scraper.py's
    find_frame_with_export(), needed because the "Table" view and everything
    after it (More, Save All, format dropdowns, OK) live inside a nested
    iframe whose depth/position isn't safe to hardcode."""

    def search(depth=0):
        if driver.find_elements(by, value):
            return True
        if depth >= max_depth:
            return False
        for frame in driver.find_elements(By.TAG_NAME, "iframe"):
            try:
                driver.switch_to.frame(frame)
            except Exception:
                continue
            if search(depth + 1):
                return True
            driver.switch_to.parent_frame()
        return False

    end = time.time() + timeout
    while time.time() < end:
        driver.switch_to.default_content()
        if search():
            return True
        time.sleep(1)
    driver.switch_to.default_content()
    return False


def click_by_id(element_id, timeout=WAIT_TIMEOUT):
    elem = WebDriverWait(driver, timeout).until(EC.element_to_be_clickable((By.ID, element_id)))
    driver.execute_script("arguments[0].click();", elem)
    return elem


def click_by_xpath(xpath, timeout=WAIT_TIMEOUT):
    elem = WebDriverWait(driver, timeout).until(EC.element_to_be_clickable((By.XPATH, xpath)))
    driver.execute_script("arguments[0].click();", elem)
    return elem


def navigate_to_isp_table():
    """Performance Instance -> select ISP -> View Historical Data -> Table
    tab. Matches a confirmed, verified-successful manual run recorded on
    2026-08-30 at the locked 1437x877 window size - simpler than earlier
    attempts (no separate Group Management tab click or tree drill-down
    turned out to be needed; a single click on the canvas plus Ctrl+A is
    enough). Everything up to and including the right-click is pixel-
    coordinate against the canvas (see module docstring); everything from
    the Table tab onward has real element ids."""
    driver.switch_to.default_content()

    print("Clicking Monitor menu...")
    # Defensive: in one earlier run the topology landing page did NOT have
    # Performance Instance directly clickable via action-0-2 without this
    # (it silently opened an unrelated feature instead - see git history/
    # conversation), while in the verified run below it wasn't needed
    # (Monitor was apparently already the active ribbon). Clicking an
    # already-active top-level menu item is a no-op, so this is kept as a
    # no-cost safety net rather than removed.
    try:
        click_by_id("refr.mm.U2020-F_U2000_App.U2020-F_Monitor", timeout=10)
        time.sleep(2)
    except Exception:
        print("Monitor menu item not found/clickable - assuming it's already active.")

    print("Clicking Performance Instance...")
    click_by_xpath('//*[@id="action-0-2"]')
    time.sleep(3)

    print("Selecting ISP and all its objects...")
    canvas = find_webswing_canvas()
    canvas_action(canvas, 418, 199, "click")
    time.sleep(1)
    ActionChains(driver).key_down(Keys.CONTROL).send_keys("a").key_up(Keys.CONTROL).perform()
    time.sleep(1)

    # Screenshot right before the riskiest step - if ISP wasn't actually
    # selected, this is the evidence needed to diagnose a wrong/empty export
    # after the fact rather than just seeing a bad CSV with no explanation.
    save_error_screenshot("before_right_click", is_error=False)

    print("Right-clicking to open context menu...")
    canvas = find_webswing_canvas()
    canvas_action(canvas, 408, 206, "right")
    time.sleep(1.5)

    print("Clicking 'View Historical Data'...")
    context_canvas = find_context_menu_canvas()
    canvas_action(context_canvas, 164, 119, "click")
    time.sleep(4)  # new tab/panel needs time to load inside its iframe

    print("Switching into the report frame and clicking Table tab...")
    if not find_frame_containing(By.ID, "ev_tabItem_10011"):
        raise RuntimeError("Could not find the frame containing the Table tab.")
    click_by_id("ev_tabItem_10011")
    time.sleep(2)


def export_csv():
    """More -> Save All -> CSV -> OK. All real, stable element ids - the
    reliable half of this flow. Assumes the current frame (set by
    navigate_to_isp_table) is still active."""
    print("Opening More menu...")
    click_by_xpath('//*[@id="MoreDropDownDropDownButton"]')
    time.sleep(1)

    print("Clicking Save All...")
    click_by_xpath('//*[@id="ev_popup_10000"]/div/div/span[5]')
    time.sleep(2)

    print("Selecting CSV file type...")
    click_by_id("ev_slt_10002")
    time.sleep(1)
    try:
        click_by_xpath('//*[@id="ev_slt_10002_pop"]/div/div/span[1]')
    except Exception:
        # Fall back to matching by visible text if the popup's item order/ids shift.
        click_by_xpath('//span[contains(text(), "CSV files")]')
    time.sleep(1)

    # Present in the verified working recording (clicking the encoding
    # dropdown without changing its value, already UTF-8 by default) -
    # purpose not fully understood, kept as a non-fatal best-effort step to
    # match that recording exactly rather than risk deviating from it.
    try:
        click_by_id("ev_slt_10003", timeout=5)
        time.sleep(1)
    except Exception:
        print("UTF-8 encoding dropdown not found/clickable - continuing (default is already UTF-8).")

    print("Clicking OK...")
    # Dialog button ids vary by instance (ev_bt_1006/ev_bt_1007 both seen
    # across recordings) - try the ids seen so far, then fall back to
    # matching by visible text.
    for button_id in ("ev_bt_1006", "ev_bt_1007"):
        try:
            click_by_id(button_id, timeout=5)
            break
        except Exception:
            continue
    else:
        click_by_xpath("//span[text()='OK']/ancestor::button")


def save_error_screenshot(label, is_error=True):
    try:
        prefix = "main_isp" if is_error else "main_isp_debug"
        screenshot_path = os.path.join(
            ERROR_SCREENSHOT_DIR, f"{prefix}_{label}_{time.strftime('%Y%m%d_%H%M%S')}.png"
        )
        driver.save_screenshot(screenshot_path)
        print(f"Screenshot saved as: {screenshot_path}")
    except Exception as screenshot_error:
        print(f"Screenshot failed: {screenshot_error}")


def run_export_cycle():
    """Full cycle: fresh login through file download. There is no deep link
    or "just re-click Export" shortcut for a Webswing session, so every
    cycle repeats the whole sequence from the portal loading page."""
    login()
    open_u2000_app()
    navigate_to_isp_table()

    before_files = set(os.listdir(DOWNLOAD_DIR))
    export_csv()

    downloaded_file = wait_for_file(DOWNLOAD_DIR, before_files, DOWNLOAD_TIMEOUT)
    if not downloaded_file:
        raise RuntimeError("Download timed out.")

    date_folder = time.strftime("%Y-%m-%d")
    dest_dir = ensure_dir(os.path.join(EXPORT_BASE_DIR, date_folder))
    ext = os.path.splitext(downloaded_file)[1]
    new_filename = f"MainISPState_{time.strftime('%Y%m%d_%H%M%S')}{ext}"
    dest_path = os.path.join(dest_dir, new_filename)
    shutil.move(downloaded_file, dest_path)
    return dest_path


def main():
    print(f"Main ISP State exporter starting. Window locked to {WINDOW_WIDTH}x{WINDOW_HEIGHT}. "
          f"Headless={HEADLESS}. Exporting every {INTERVAL_SECONDS} seconds.")
    try:
        while True:
            try:
                dest_path = run_export_cycle()
                print(f"[{time.strftime('%H:%M:%S')}] Export success: {dest_path}")
            except Exception as e:
                print(f"[{time.strftime('%H:%M:%S')}] Export cycle failed: {e}")
                save_error_screenshot("cycle_error")

            time.sleep(INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("Stopped by user.")
    except Exception as e:
        print(f"Main ISP State exporter failed: {e}")
        save_error_screenshot("fatal_error")
        raise
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
