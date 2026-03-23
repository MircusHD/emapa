import os
import random
import string

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
SIGNATURE_DIR = os.path.join(DATA_DIR, "signatures")
DEFAULT_SIG_DIR = os.path.join(SIGNATURE_DIR, "defaults")
FINAL_DIR = os.path.join(DATA_DIR, "final")
DB_PATH = os.path.join(DATA_DIR, "app.db")
DB_URL = f"sqlite:///{DB_PATH}"

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(SIGNATURE_DIR, exist_ok=True)
os.makedirs(DEFAULT_SIG_DIR, exist_ok=True)
os.makedirs(FINAL_DIR, exist_ok=True)

DG_DEPT = "GENERAL"

# Public document code (short, human-friendly)
PUBLIC_PREFIX = "EM"  # format: EM-A9K3X7

ORG_DEPARTMENTS = [
    "GENERAL",
    "SRV_UIP",
    "SRV_ACHIZITII_ADMINISTRATIV",
    "COMP_AUDIT_INTERN",
    "COMP_JURIDIC",
    "COMP_RESURSE_UMANE",
    "COMP_PREVENIRE_PROTECTIE",
    "DEP_ECONOMIC",
    "DEP_EXPLOATARE",
    "DEP_TEHNIC",
    "DEP_CALITATE",
    "SERV_FINANCIAR_CONTABILITATE",
    "COMP_CONTACT_CENTER",
    "SERV_COMERCIAL",
    "SECTIA_APA_CANAL",
    "SERV_DISPECERAT",
    "SECTIE_MENTENANTA",
    "SECTIE_AUTOMATIZARE_SCADA",
    "SECTIE_TRATARE_APA_ORLEA",
    "ADUCTIUNE_APA_ORLEA_DEVA",
    "SERV_TEHNIC_INVESTITII",
    "LAB_METROLOGIE",
    "SERV_MONITORIZARE_PIERDERI",
    "SERV_LABORATOARE",
    "SERV_MEDIU_PROCEDURI",
    "SECTOR_IT",
]

DEFAULT_PARENTS = {
    "SERV_LABORATOARE": "DEP_CALITATE",
    "SERV_MEDIU_PROCEDURI": "DEP_CALITATE",
    "SERV_FINANCIAR_CONTABILITATE": "DEP_ECONOMIC",
    "SECTOR_IT": "DEP_EXPLOATARE",
}


# Path helpers
def rel_upload_path(stored_filename: str, dt) -> str:
    yyyy = dt.strftime("%Y")
    mm = dt.strftime("%m")
    folder = os.path.join(UPLOAD_DIR, yyyy, mm)
    os.makedirs(folder, exist_ok=True)
    return os.path.join(yyyy, mm, stored_filename)


def abs_upload_path(rel_path: str) -> str:
    return os.path.join(UPLOAD_DIR, rel_path)


def sig_abs_path(rel: str) -> str:
    return os.path.join(SIGNATURE_DIR, rel)


def final_abs_path(rel: str) -> str:
    return os.path.join(FINAL_DIR, rel)
