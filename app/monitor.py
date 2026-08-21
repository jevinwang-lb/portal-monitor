import json
import os
import ssl
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright


# ============================================================
# Configuration
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)

# ------------------------------------------------------------
# Files
# ------------------------------------------------------------

DOMAINS_FILE = os.environ.get(
    "DOMAINS_FILE",
    os.path.join(BASE_DIR, "domains.txt"),
)

STATE_FILE = os.environ.get(
    "STATE_FILE",
    os.path.join(BASE_DIR, "status.json"),
)


# ------------------------------------------------------------
# Google Transparency Report
# ------------------------------------------------------------

REPORT_BASE_URL = (
    "https://transparencyreport.google.com/"
    "safe-browsing/search"
)


# ------------------------------------------------------------
# Local Chrome
# ------------------------------------------------------------

CHROME_PATH = os.environ.get(
    "CHROME_PATH",
    "/Applications/Google Chrome.app/"
    "Contents/MacOS/Google Chrome",
)


# ------------------------------------------------------------
# Browser mode
#
# Local:
#   false
#
# Docker / Kubernetes:
#   true
# ------------------------------------------------------------

PLAYWRIGHT_HEADLESS = (
    os.environ.get(
        "PLAYWRIGHT_HEADLESS",
        "false",
    ).lower()
    == "true"
)


# ------------------------------------------------------------
# Browser HTTPS verification
#
# Local defaults to false? No.
# We keep normal verification locally.
#
# Docker POC currently defaults to true because your local
# Docker traffic is affected by Zero Trust TLS inspection.
#
# Production should ideally install the corporate CA instead.
# ------------------------------------------------------------

default_ignore_https = (
    "true"
    if PLAYWRIGHT_HEADLESS
    else "false"
)

IGNORE_HTTPS_ERRORS = (
    os.environ.get(
        "IGNORE_HTTPS_ERRORS",
        default_ignore_https,
    ).lower()
    == "true"
)


# ------------------------------------------------------------
# Teams / Power Automate Webhook
# ------------------------------------------------------------

ALERT_WEBHOOK_URL = os.environ.get(
    "ALERT_WEBHOOK_URL"
)

# Normal default:
#   true
#
# Local Zero Trust testing:
#   export WEBHOOK_VERIFY_TLS=false
#
# Kubernetes:
#   leave unset / true
WEBHOOK_VERIFY_TLS = (
    os.environ.get(
        "WEBHOOK_VERIFY_TLS",
        "true",
    ).lower()
    == "true"
)


# ------------------------------------------------------------
# Timeouts
# ------------------------------------------------------------

NAVIGATION_TIMEOUT_MS = int(
    os.environ.get(
        "NAVIGATION_TIMEOUT_MS",
        "30000",
    )
)

RESULT_TIMEOUT_MS = int(
    os.environ.get(
        "RESULT_TIMEOUT_MS",
        "20000",
    )
)

MAX_RETRIES = int(
    os.environ.get(
        "MAX_RETRIES",
        "3",
    )
)

RETRY_DELAY_SECONDS = int(
    os.environ.get(
        "RETRY_DELAY_SECONDS",
        "2",
    )
)


# ============================================================
# Helpers
# ============================================================

def now_iso():

    return datetime.now(
        timezone.utc
    ).isoformat()


def safe_filename(value):

    result = value

    for char in [
        "/",
        ":",
        "?",
        "&",
        "=",
        "\\",
    ]:

        result = result.replace(
            char,
            "_",
        )

    return result


# ============================================================
# Domains
# ============================================================

def load_domains():

    if not os.path.exists(
        DOMAINS_FILE
    ):

        print(
            "ERROR: domains file not found:"
        )

        print(
            DOMAINS_FILE
        )

        sys.exit(2)

    domains = []

    with open(
        DOMAINS_FILE,
        "r",
        encoding="utf-8",
    ) as f:

        for line in f:

            line = line.strip()

            if not line:
                continue

            if line.startswith("#"):
                continue

            domains.append(
                line
            )

    # Remove duplicates
    domains = list(
        dict.fromkeys(
            domains
        )
    )

    return domains


# ============================================================
# State
# ============================================================

def load_state():

    if not os.path.exists(
        STATE_FILE
    ):

        return {}

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8",
        ) as f:

            return json.load(
                f
            )

    except Exception as e:

        print(
            "WARNING: failed to load state:"
        )

        print(
            e
        )

        return {}


def save_state(state):

    state_dir = os.path.dirname(
        STATE_FILE
    )

    if state_dir:

        os.makedirs(
            state_dir,
            exist_ok=True,
        )

    temp_file = (
        STATE_FILE + ".tmp"
    )

    with open(
        temp_file,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            state,
            f,
            indent=2,
            ensure_ascii=False,
        )

    os.replace(
        temp_file,
        STATE_FILE,
    )


# ============================================================
# Google URL
# ============================================================

def build_report_url(domain):

    query = urllib.parse.urlencode(
        {
            "url": domain,
            "hl": "en",
        }
    )

    return (
        REPORT_BASE_URL
        + "?"
        + query
    )


# ============================================================
# Parse Google result
# ============================================================

# Transparency Report uses more than one unsafe phrasing.
# Whole-site:
#   "This site is unsafe"
# Partial / mixed site (testsafebrowsing etc.):
#   "Some pages on this site are unsafe"
#   "contains harmful content"

UNSAFE_PATTERNS = [
    "this site is unsafe",
    "site is unsafe",
    "some pages on this site are unsafe",
    "pages on this site are unsafe",
    "contains harmful content",
]

SAFE_PATTERNS = [
    "no unsafe content found",
    "no issues found",
    "this site is safe",
]

NO_DATA_PATTERNS = [
    "no available data",
]

UNKNOWN_PATTERNS = [
    "it's hard to provide a simple safety status",
    "it’s hard to provide a simple safety status",
]


def parse_status(body_text):

    body_lower = body_text.lower()

    for pattern in UNSAFE_PATTERNS:

        if pattern in body_lower:

            return "UNSAFE"

    for pattern in SAFE_PATTERNS:

        if pattern in body_lower:

            return "SAFE"

    for pattern in NO_DATA_PATTERNS:

        if pattern in body_lower:

            return "NO_DATA"

    for pattern in UNKNOWN_PATTERNS:

        if pattern in body_lower:

            return "UNKNOWN"

    return "UNKNOWN"


# ============================================================
# Debug output
# ============================================================

def save_debug(
    page,
    domain,
    body_text,
):

    debug_dir = os.path.dirname(
        STATE_FILE
    )

    if not debug_dir:

        debug_dir = BASE_DIR

    os.makedirs(
        debug_dir,
        exist_ok=True,
    )

    filename = safe_filename(
        domain
    )

    text_file = os.path.join(
        debug_dir,
        f"debug_{filename}.txt",
    )

    screenshot_file = os.path.join(
        debug_dir,
        f"debug_{filename}.png",
    )

    try:

        with open(
            text_file,
            "w",
            encoding="utf-8",
        ) as f:

            f.write(
                body_text
            )

        print(
            "Debug text:",
            text_file,
        )

    except Exception as e:

        print(
            "Failed to save debug text:",
            e,
        )

    try:

        page.screenshot(
            path=screenshot_file,
            full_page=True,
        )

        print(
            "Debug screenshot:",
            screenshot_file,
        )

    except Exception as e:

        print(
            "Failed to save screenshot:",
            e,
        )


# ============================================================
# Wait for Google result
# ============================================================

def wait_for_google_result(page):

    patterns = (
        UNSAFE_PATTERNS
        + SAFE_PATTERNS
        + NO_DATA_PATTERNS
        + UNKNOWN_PATTERNS
    )

    js_patterns = json.dumps(
        patterns
    )

    try:

        page.wait_for_function(
            f"""
            () => {{
                const body = document.body;

                if (!body) {{
                    return false;
                }}

                const text =
                    body.innerText.toLowerCase();

                const patterns = {js_patterns};

                return patterns.some(
                    (pattern) => text.includes(pattern)
                );
            }}
            """,
            timeout=RESULT_TIMEOUT_MS,
        )

        return True

    except Exception:

        return False


# ============================================================
# Single domain check
# ============================================================

def check_domain_once(
    page,
    domain,
):

    report_url = build_report_url(
        domain
    )

    print(
        "Google Report URL:",
        report_url,
    )

    page.goto(
        report_url,
        wait_until="domcontentloaded",
        timeout=NAVIGATION_TIMEOUT_MS,
    )

    result_loaded = (
        wait_for_google_result(
            page
        )
    )

    if not result_loaded:

        print(
            "WARNING: timed out waiting "
            "for Google result"
        )

    body_text = page.locator(
        "body"
    ).inner_text()

    status = parse_status(
        body_text
    )

    # Save debug only for truly unknown results
    if status == "UNKNOWN":

        save_debug(
            page,
            domain,
            body_text,
        )

    return status


# ============================================================
# Retry
# ============================================================

def check_domain(
    page,
    domain,
):

    last_status = None

    for attempt in range(
        1,
        MAX_RETRIES + 1,
    ):

        print(
            f"Attempt "
            f"{attempt}/{MAX_RETRIES}"
        )

        try:

            status = check_domain_once(
                page,
                domain,
            )

            last_status = status

            # Definitive / legitimate results
            if status in [
                "SAFE",
                "UNSAFE",
                "NO_DATA",
            ]:

                return status

            # UNKNOWN may be legitimate, but retry in case
            # Google simply had not finished rendering.
            if status == "UNKNOWN":

                if attempt < MAX_RETRIES:

                    print(
                        "UNKNOWN result, "
                        "retrying..."
                    )

                    time.sleep(
                        RETRY_DELAY_SECONDS
                    )

                    continue

                return "UNKNOWN"

        except Exception as e:

            print(
                f"CHECK ERROR "
                f"(attempt {attempt}):"
            )

            print(
                e
            )

            if attempt < MAX_RETRIES:

                time.sleep(
                    RETRY_DELAY_SECONDS
                )

                continue

    if last_status:

        return last_status

    return "CHECK_ERROR"


# ============================================================
# Teams / Power Automate Webhook
# ============================================================

def send_webhook(event):

    if not ALERT_WEBHOOK_URL:

        print(
            "INFO: ALERT_WEBHOOK_URL "
            "not configured"
        )

        return

    payload = json.dumps(
        event,
        ensure_ascii=False,
    ).encode(
        "utf-8"
    )

    request = urllib.request.Request(
        ALERT_WEBHOOK_URL,
        data=payload,
        headers={
            "Content-Type":
                "application/json",
        },
        method="POST",
    )

    # --------------------------------------------------------
    # Normal / Kubernetes
    # --------------------------------------------------------

    if WEBHOOK_VERIFY_TLS:

        with urllib.request.urlopen(
            request,
            timeout=15,
        ) as response:

            print(
                "Webhook HTTP:",
                response.status,
            )

        return


    # --------------------------------------------------------
    # Local POC behind Zero Trust TLS inspection
    #
    # Do NOT use this as the production default.
    # --------------------------------------------------------

    print(
        "WARNING: Webhook TLS verification "
        "is disabled"
    )

    ssl_context = (
        ssl._create_unverified_context()
    )

    with urllib.request.urlopen(
        request,
        timeout=15,
        context=ssl_context,
    ) as response:

        print(
            "Webhook HTTP:",
            response.status,
        )


# ============================================================
# Browser
# ============================================================

def launch_browser(playwright):

    # --------------------------------------------------------
    # Docker / Kubernetes
    # --------------------------------------------------------

    if PLAYWRIGHT_HEADLESS:

        print(
            "Browser: Playwright Chromium"
        )

        return (
            playwright.chromium.launch(
                headless=True,
            )
        )


    # --------------------------------------------------------
    # Local Mac
    # --------------------------------------------------------

    if not os.path.exists(
        CHROME_PATH
    ):

        print(
            "ERROR: Google Chrome not found:"
        )

        print(
            CHROME_PATH
        )

        sys.exit(2)

    print(
        "Browser: local Google Chrome"
    )

    return (
        playwright.chromium.launch(
            headless=False,
            executable_path=CHROME_PATH,
        )
    )


# ============================================================
# Main
# ============================================================

def main():

    print(
        "=" * 60
    )

    print(
        "Portal Safe Browsing Monitor"
    )

    print(
        "Time:",
        now_iso(),
    )

    print(
        "Domains file:",
        DOMAINS_FILE,
    )

    print(
        "State file:",
        STATE_FILE,
    )

    print(
        "Headless:",
        PLAYWRIGHT_HEADLESS,
    )

    print(
        "Ignore HTTPS errors:",
        IGNORE_HTTPS_ERRORS,
    )

    print(
        "Webhook configured:",
        bool(ALERT_WEBHOOK_URL),
    )

    print(
        "Webhook TLS verification:",
        WEBHOOK_VERIFY_TLS,
    )

    print(
        "=" * 60
    )


    # --------------------------------------------------------
    # Domains
    # --------------------------------------------------------

    domains = load_domains()

    if not domains:

        print(
            "ERROR: no domains configured"
        )

        sys.exit(2)

    print(
        f"Found {len(domains)} "
        "domain(s)"
    )


    # --------------------------------------------------------
    # State
    # --------------------------------------------------------

    old_state = load_state()

    new_state = {}

    notification_events = []

    monitor_errors = []


    # --------------------------------------------------------
    # Playwright
    # --------------------------------------------------------

    with sync_playwright() as p:

        browser = launch_browser(
            p
        )

        context = browser.new_context(
            ignore_https_errors=(
                IGNORE_HTTPS_ERRORS
            )
        )

        page = context.new_page()

        try:

            for domain in domains:

                print()

                print(
                    "-" * 60
                )

                print(
                    "Checking:",
                    domain,
                )


                # --------------------------------------------
                # Check
                # --------------------------------------------

                try:

                    status = check_domain(
                        page,
                        domain,
                    )

                except Exception as e:

                    print(
                        "Unexpected CHECK ERROR:"
                    )

                    print(
                        e
                    )

                    status = (
                        "CHECK_ERROR"
                    )


                # --------------------------------------------
                # Previous state
                # --------------------------------------------

                previous = old_state.get(
                    domain
                )


                # --------------------------------------------
                # Output
                # --------------------------------------------

                print(
                    "Previous:",
                    (
                        previous
                        if previous is not None
                        else "(first check)"
                    ),
                )

                print(
                    "Current :",
                    status,
                )


                # ============================================
                # Display current status
                # ============================================

                if status == "UNSAFE":

                    print()

                    print(
                        "🚨 UNSAFE:",
                        domain,
                    )

                elif status == "SAFE":

                    print()

                    print(
                        "✅ SAFE:",
                        domain,
                    )

                elif status == "NO_DATA":

                    print()

                    print(
                        "⚪ NO_DATA:",
                        domain,
                    )

                    print(
                        "Google currently has "
                        "no available status data."
                    )

                elif status == "UNKNOWN":

                    print()

                    print(
                        "🟡 UNKNOWN:",
                        domain,
                    )

                    print(
                        "Google did not provide "
                        "a clear SAFE/UNSAFE result."
                    )

                else:

                    print()

                    print(
                        "🔴 CHECK_ERROR:",
                        domain,
                    )


                # ============================================
                # CHECK_ERROR
                # ============================================

                if status == "CHECK_ERROR":

                    monitor_errors.append(
                        {
                            "event":
                                "monitor_error",
                            "domain":
                                domain,
                            "time":
                                now_iso(),
                        }
                    )

                    # Preserve previous valid state
                    if previous is not None:

                        new_state[
                            domain
                        ] = previous

                    continue


                # ============================================
                # UNKNOWN / NO_DATA
                #
                # Neither is considered a safety-state change.
                # Do not overwrite an existing valid state.
                # ============================================

                if status in [
                    "UNKNOWN",
                    "NO_DATA",
                ]:

                    if previous is not None:

                        new_state[
                            domain
                        ] = previous

                    continue


                # ============================================
                # First valid SAFE / UNSAFE check
                # ============================================

                if previous is None:

                    new_state[
                        domain
                    ] = status

                    # First check is already UNSAFE
                    if status == "UNSAFE":

                        event = {
                            "event":
                                "status_changed",
                            "domain":
                                domain,
                            "previous":
                                None,
                            "current":
                                "UNSAFE",
                            "time":
                                now_iso(),
                        }

                        notification_events.append(
                            event
                        )

                        print(
                            "🚨 FIRST CHECK "
                            "AND UNSAFE"
                        )

                    else:

                        print(
                            "First check: "
                            "no notification"
                        )

                    continue


                # ============================================
                # Save valid SAFE / UNSAFE state
                # ============================================

                new_state[
                    domain
                ] = status


                # ============================================
                # No state change
                # ============================================

                if previous == status:

                    print(
                        "No status change."
                    )

                    continue


                # ============================================
                # SAFE <-> UNSAFE
                # ============================================

                event = {
                    "event":
                        "status_changed",
                    "domain":
                        domain,
                    "previous":
                        previous,
                    "current":
                        status,
                    "time":
                        now_iso(),
                }

                notification_events.append(
                    event
                )

                print()

                print(
                    "🔔 STATUS CHANGED:"
                )

                print(
                    f"   {previous} "
                    f"-> {status}"
                )


        finally:

            context.close()

            browser.close()


    # ========================================================
    # Save state
    # ========================================================

    save_state(
        new_state
    )

    print()

    print(
        "=" * 60
    )

    print(
        "State saved:",
        STATE_FILE,
    )


    # ========================================================
    # Notifications
    # ========================================================

    if notification_events:

        print()

        print(
            "Notification events:",
            len(
                notification_events
            ),
        )

        for event in (
            notification_events
        ):

            print(
                "Event:",
                json.dumps(
                    event,
                    ensure_ascii=False,
                ),
            )

            try:

                send_webhook(
                    event
                )

            except Exception as e:

                print(
                    "Webhook failed:",
                    e,
                )

    else:

        print()

        print(
            "No notification events."
        )


    # ========================================================
    # Monitor errors
    # ========================================================

    if monitor_errors:

        print()

        print(
            "Monitor errors:",
            len(
                monitor_errors
            ),
        )

        for error in monitor_errors:

            print(
                json.dumps(
                    error,
                    ensure_ascii=False,
                )
            )


    print(
        "=" * 60
    )


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":

    main()