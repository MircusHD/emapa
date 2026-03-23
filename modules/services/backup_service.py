"""
backup_service.py — Serviciu backup/restore bază de date SQLite pentru eMapa.

Funcții principale:
  create_backup()              → copie consistentă a app.db în data/backups/
  list_backups()               → lista backup-urilor existente
  restore_from_file(filename)  → restaurare din backup existent (creează safety backup automat)
  restore_from_upload(bytes)   → restaurare din fișier uploadat
  get_backup_bytes(filename)   → citește bytes pentru descărcare
  delete_backup(filename)      → șterge un fișier de backup
"""
import os
import sqlite3
from datetime import datetime
from typing import Optional

from modules.config import BASE_DIR, DB_PATH

BACKUP_DIR = os.path.join(BASE_DIR, "data", "backups")
os.makedirs(BACKUP_DIR, exist_ok=True)


def create_backup() -> tuple[bool, str, str]:
    """Creează un backup consistent al bazei de date folosind sqlite3.backup().
    Returnează (ok, filename, msg)."""
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"app_backup_{ts}.db"
        backup_path = os.path.join(BACKUP_DIR, backup_filename)

        src = sqlite3.connect(DB_PATH)
        dst = sqlite3.connect(backup_path)
        src.backup(dst)
        dst.close()
        src.close()

        size_mb = round(os.path.getsize(backup_path) / (1024 * 1024), 2)
        return True, backup_filename, f"Backup creat: {backup_filename} ({size_mb} MB)"
    except Exception as e:
        return False, "", f"Eroare la creare backup: {e}"


def list_backups() -> list[dict]:
    """Returnează lista backup-urilor existente, sortat descrescător după dată."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    result = []
    try:
        for fname in sorted(os.listdir(BACKUP_DIR), reverse=True):
            if fname.endswith(".db"):
                fpath = os.path.join(BACKUP_DIR, fname)
                stat = os.stat(fpath)
                result.append({
                    "filename": fname,
                    "size_mb": round(stat.st_size / (1024 * 1024), 2),
                    "created_at": datetime.fromtimestamp(stat.st_mtime).strftime("%d.%m.%Y %H:%M:%S"),
                })
    except Exception:
        pass
    return result


def restore_from_file(backup_filename: str) -> tuple[bool, str]:
    """Restaurează BD din fișierul de backup specificat.
    Creează automat un backup de siguranță al BD curente înainte de restaurare.
    OPERAȚIE DISTRUCTIVĂ — returnează (ok, msg)."""
    backup_path = os.path.join(BACKUP_DIR, backup_filename)
    if not os.path.exists(backup_path):
        return False, f"Fișierul de backup nu există: {backup_filename}"
    try:
        # Backup de siguranță automat al BD curente
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safety_filename = f"pre_restore_{ts}.db"
        safety_path = os.path.join(BACKUP_DIR, safety_filename)
        src = sqlite3.connect(DB_PATH)
        dst = sqlite3.connect(safety_path)
        src.backup(dst)
        dst.close()
        src.close()

        # Restaurare
        src = sqlite3.connect(backup_path)
        dst = sqlite3.connect(DB_PATH)
        src.backup(dst)
        dst.close()
        src.close()

        return True, f"Restaurare reușită din '{backup_filename}'. Backup de siguranță salvat: {safety_filename}"
    except Exception as e:
        return False, f"Eroare la restaurare: {e}"


def restore_from_upload(file_bytes: bytes) -> tuple[bool, str]:
    """Salvează bytes uploadați ca fișier temporar, validează și restaurează.
    OPERAȚIE DISTRUCTIVĂ — returnează (ok, msg)."""
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        tmp_filename = f"upload_{ts}.db"
        tmp_path = os.path.join(BACKUP_DIR, tmp_filename)
        with open(tmp_path, "wb") as f:
            f.write(file_bytes)

        # Validare fișier SQLite
        try:
            test_con = sqlite3.connect(tmp_path)
            test_con.execute("SELECT name FROM sqlite_master LIMIT 1")
            test_con.close()
        except Exception:
            os.remove(tmp_path)
            return False, "Fișierul uploadat nu este o bază de date SQLite validă."

        return restore_from_file(tmp_filename)
    except Exception as e:
        return False, f"Eroare la upload și restaurare: {e}"


def get_backup_bytes(backup_filename: str) -> Optional[bytes]:
    """Citește și returnează conținutul unui fișier de backup pentru descărcare."""
    backup_path = os.path.join(BACKUP_DIR, backup_filename)
    if not os.path.exists(backup_path):
        return None
    try:
        with open(backup_path, "rb") as f:
            return f.read()
    except Exception:
        return None


def delete_backup(backup_filename: str) -> tuple[bool, str]:
    """Șterge definitiv un fișier de backup."""
    backup_path = os.path.join(BACKUP_DIR, backup_filename)
    if not os.path.exists(backup_path):
        return False, f"Fișierul nu există: {backup_filename}"
    try:
        os.remove(backup_path)
        return True, f"Backup șters: {backup_filename}"
    except Exception as e:
        return False, f"Eroare la ștergere: {e}"