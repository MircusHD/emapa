
import shutil, os, datetime

def backup_database(db_path, backup_dir):
    os.makedirs(backup_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(backup_dir, f"app_backup_{ts}.db")
    shutil.copy(db_path, dst)
    return dst
