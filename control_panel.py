"""Streamlit control panel: settings editor + start/stop/status for every
script in script_registry.py. Thin UI only - all data and process/file logic
lives in app_settings.py and script_registry.py; this file must not redefine
SETTINGS or SCRIPT_REGISTRY, and must never touch chrome.exe/chromedriver.exe
directly (stopping a script always goes through script_registry.stop_process,
which kills the whole process tree, not just the parent).

Run via "Start Control Panel.bat", or directly:
    .venv\\Scripts\\python.exe -m streamlit run control_panel.py --server.port 8502
"""
from pathlib import Path

import streamlit as st

from app_settings import SETTINGS, read_env_file, validate_values, write_env_file
from script_registry import (
    CONTINUOUS_SCRIPTS,
    LOG_DIR,
    ON_DEMAND_SCRIPTS,
    SCRIPT_REGISTRY,
    is_process_running,
    launch_detached,
    stop_process,
)

st.set_page_config(page_title="Automation Control Panel", layout="wide")
st.title("Automation Control Panel")


def latest_log_for(entry):
    pattern = f"{entry['name'].replace(' ', '_')}_*.log"
    matches = sorted(LOG_DIR.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def tail_text(path, n_lines=40, tail_bytes=20000):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - tail_bytes))
            data = f.read()
        lines = data.decode("utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n_lines:]) or "(empty)"
    except OSError:
        return "(no log yet)"


def render_log_expander(entry):
    log_path = latest_log_for(entry)
    with st.expander("Recent log"):
        st.code(tail_text(log_path) if log_path else "(no log yet)", language=None)


def render_continuous_row(entry):
    pid = is_process_running(entry["file"])
    name_col, status_col, action_col = st.columns([3, 1.4, 1.4])

    with name_col:
        st.markdown(f"**{entry['name']}**")
        st.caption(entry["desc"])

    with status_col:
        st.markdown(f"🟢 Running (PID {pid})" if pid else "⚪ Stopped")

    with action_col:
        if pid:
            with st.popover("Stop", key=f"popover_stop_{entry['name']}"):
                st.write(
                    f"Stop **{entry['name']}**? "
                    "This affects live NOC monitoring if it's a scraper."
                )
                if st.button("Yes, stop it", key=f"confirm_stop_{entry['name']}"):
                    stop_process(pid)
                    st.rerun()
        else:
            if st.button("Start", key=f"start_{entry['name']}"):
                errors = validate_values(read_env_file(), required_keys=entry["required_env"])
                if errors:
                    for error in errors:
                        st.error(error)
                else:
                    proc = launch_detached(entry)
                    if proc:
                        st.success(f"Started (PID {proc.pid})")
                        st.rerun()
                    else:
                        st.error("Script file not found.")

    render_log_expander(entry)
    st.divider()


def render_on_demand_row(entry):
    pid = is_process_running(entry["file"])
    name_col, status_col = st.columns([3, 1.4])

    with name_col:
        st.markdown(f"**{entry['name']}**")
        st.caption(entry["desc"])

    with status_col:
        st.markdown(f"🟢 Running (PID {pid})" if pid else "⚪ Not running")

    render_log_expander(entry)
    st.divider()


def render_status_and_control_body():
    st.subheader("Continuous Scripts")
    for entry in CONTINUOUS_SCRIPTS:
        render_continuous_row(entry)

    st.subheader("On-Demand Scripts")
    st.caption("Status and recent log only - launch these from their own .bat file or on a schedule.")
    for entry in ON_DEMAND_SCRIPTS:
        render_on_demand_row(entry)


@st.fragment(run_every="5s")
def render_status_and_control_auto():
    render_status_and_control_body()


def render_status_tab():
    refresh_col, auto_col = st.columns([1, 4])
    with refresh_col:
        if st.button("Refresh status"):
            st.rerun()
    with auto_col:
        auto_refresh = st.toggle("Auto-refresh every 5s", value=False)

    if auto_refresh:
        render_status_and_control_auto()
    else:
        render_status_and_control_body()


def render_settings_tab():
    show_secrets = st.toggle("Show all secrets", value=False)
    st.caption(
        "Folders marked ❌ not found are created automatically the first time you Save. "
        "Editing a value here does not restart any already-running script - see the warning "
        "after Save for which ones need a manual restart from Status & Control."
    )

    filter_text = st.text_input("Filter settings", placeholder="e.g. mae, password, interval").strip().lower()

    all_values = read_env_file()

    for section in SETTINGS:
        section_name = section["section"]
        fields = section["fields"]

        if filter_text:
            haystack = (
                section_name + " " + " ".join(f"{key} {label}" for key, label, *_ in fields)
            ).lower()
            if filter_text not in haystack:
                continue

        with st.expander(section_name):
            with st.form(key=f"form_{section_name}"):
                edited = {}
                for key, label, default, field_type, is_secret in fields:
                    current = all_values.get(key, default)
                    if is_secret:
                        edited[key] = st.text_input(
                            label, value=current,
                            type="default" if show_secrets else "password",
                            key=f"field_{key}",
                        )
                    else:
                        edited[key] = st.text_input(label, value=current, key=f"field_{key}")
                        if field_type in ("dir", "file") and edited[key]:
                            exists = Path(edited[key]).exists()
                            if exists:
                                st.caption("✅ exists")
                            elif field_type == "file":
                                st.caption("ℹ️ not created yet")
                            else:
                                st.caption("❌ not found")

                submitted = st.form_submit_button("Save")
                if submitted:
                    full_values = read_env_file()
                    full_values.update(edited)
                    errors = validate_values(full_values)
                    if errors:
                        for error in errors:
                            st.error(error)
                    else:
                        write_env_file(full_values)
                        st.success("Saved.")
                        edited_keys = set(edited.keys())
                        affected = [
                            entry["name"] for entry in SCRIPT_REGISTRY
                            if set(entry["required_env"]) & edited_keys and is_process_running(entry["file"])
                        ]
                        if affected:
                            st.warning(
                                "Currently running with the old values: " + ", ".join(affected) +
                                ". Restart them from Status & Control to apply this change."
                            )


tab_status, tab_settings = st.tabs(["Status & Control", "Settings"])

with tab_status:
    render_status_tab()

with tab_settings:
    render_settings_tab()
