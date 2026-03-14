
import shutil, datetime, os

DATA = "data"
BACKUP = "data/backups"

def run_backup():

    os.makedirs(BACKUP, exist_ok=True)

    name = datetime.datetime.now().strftime("backup_%Y%m%d_%H%M")

    shutil.copytree(DATA, os.path.join(BACKUP, name))
