"""Shared alarm classification taxonomy for MAE/NetEco alarm names.

Extracted from enhanced_noc_analysis.py so the same "what matters" definition
is used consistently by both the current-alarm triage report and the
historical-alarm analysis engine - a term added/fixed here benefits both.
"""
import pandas as pd

SERVICE_OUTAGE = (
    "NE Is Disconnected", "NodeB Unavailable", "GSM Cell out of Service", "UMTS Cell Unavailable",
    "Cell Unavailable", "Local Cell Unusable", "GSM Local Cell Unusable", "RF Out of Service",
)
TRANSPORT_TERMS = ("SCTP", "S1ap", "X2 Interface", "Link Down", "OML", "CSL", "Ping Failure",
                   "User Plane", "SDH/SONET", "VLAN", "ALD Maintenance Link")
POWER_TERMS = ("DC Input Power", "External Power Supply", "Power Failure")
RADIO_HARDWARE_TERMS = ("BBU", "CPRI", "RF Unit", "RHUB", "Board ", "Optical Module", "Inter-BBU")
RADIO_QUALITY_TERMS = ("VSWR", "RTWP", "RSSI", "RX Channel", "TX Channel", "Radio Link Failure",
                       "Interference Noise")
CAPACITY_TERMS = ("Overload", "congestion", "Resources Used", "Traffic Exceeding", "KPI entity")
LICENSE_TERMS = ("License", "Licensed Feature", "software service fee")
MAINTENANCE_TERMS = ("backup", "Maintenance", "Task execution", "Data Store", "Data Configuration")
SECURITY_TERMS = ("Attack", "Blacklist", "Security", "Insecure", "Weak Algorithms", "Login Attempts",
                  "Changes a User's Password")
CRITICAL_ENERGY_TERMS = (
    "LLVD", "BLVD", "Bus Bar Undervoltage", "DC Under Voltage", "DC Ultra Under Voltage",
    "DC Ultra Undervoltage", "DC Undervoltage", "Remaining Capacity Percent Under 30",
    "Remaining Capacity Percentage Under 30", "Overdischarge", "Lithium Battery Protection",
    "Battery Undervoltage", "Battery Undervoltage Protection",
)
# Site mains/AC-feed/rectifier/battery-condition alarms - distinct from CRITICAL_ENERGY_TERMS
# (imminent DC-bus/battery failure, P1) and from POWER_TERMS (RAN-equipment power, MAE-sourced):
# these come from NetEco's energy-plant historical feed and are common at volume, but represent
# power *risk* rather than a confirmed site-down condition.
SITE_POWER_TERMS = (
    "Mains", "Phase L1", "Phase L2", "Phase L3", "PSU Protection", "AC Failure",
    "Rectifier Protection", "Battery Discharge Overcurrent", "Battery Fuse Broken",
    "Remaining Capacity Percent Under 50", "Remaining Capacity Percentage Under 50",
)
ENVIRONMENTAL_TERMS = (
    "Air Conditioner", "Fan ", "Water Alarm", "High Ambient Humidity",
    "Frequent High Pressure", "Compressor",
)
COMMUNICATION_TERMS = ("Communication Between NMS And NE Is Abnormal", "Communication Failure")
SEVERITY_ORDER = {"Critical": 4, "Major": 3, "Minor": 2, "Warning": 1}


def has_term(names, terms) -> bool:
    return any(any(term.lower() in str(name).lower() for term in terms) for name in names)


def classify_mae_alarm(name: str) -> tuple[str, str]:
    text = str(name or "")
    if text in SERVICE_OUTAGE:
        return "Service Outage", "P1" if text in {"NE Is Disconnected", "NodeB Unavailable"} else "P2"
    if has_term([text], CRITICAL_ENERGY_TERMS):
        return "Critical Energy / Battery", "P1"
    if has_term([text], SECURITY_TERMS):
        return "Security / Core Protection", "P3"
    if has_term([text], LICENSE_TERMS):
        return "License / Entitlement", "P3"
    if has_term([text], POWER_TERMS):
        return "RAN Power", "P2"
    if has_term([text], SITE_POWER_TERMS):
        return "Site Power / Energy", "P2"
    if has_term([text], ENVIRONMENTAL_TERMS):
        return "Environmental / HVAC", "P3"
    if has_term([text], COMMUNICATION_TERMS):
        return "NMS Communication", "P2"
    if has_term([text], TRANSPORT_TERMS):
        return "Transport / Connectivity", "P2"
    if has_term([text], RADIO_HARDWARE_TERMS):
        return "RAN Hardware", "P2"
    if has_term([text], RADIO_QUALITY_TERMS):
        return "Radio Quality", "P3"
    if has_term([text], CAPACITY_TERMS):
        return "Capacity / Performance", "P3"
    if has_term([text], MAINTENANCE_TERMS):
        return "Maintenance / Management", "P3"
    if "Clock" in text:
        return "Synchronization", "P2"
    if any(term in text for term in ("OpenStack", "Server", "Pool", "S-CSCF", "ASBC", "DIMM")):
        return "Core / IT Platform", "P2"
    return "Other / Review", "P3"


def severity_max(values) -> str:
    values = [value for value in values if pd.notna(value)]
    return max(values, key=lambda value: SEVERITY_ORDER.get(str(value), 0), default="-")
