"""Backup de la base y de los archivos generados (remitos, firmas, fotos).

Uso:
    python backup.py            # un backup y termina
    python backup.py --loop     # uno por día, a la hora CONTROL_BACKUP_HORA (Docker)

La base se copia con la API de backup de SQLite: es segura aunque la app
esté escribiendo en ese momento (copiar el archivo a mano no lo es con WAL).
Se conservan los últimos CONTROL_BACKUP_DIAS backups.
"""
import os
import sqlite3
import sys
import tarfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent
TZ = ZoneInfo(os.environ.get('CONTROL_TZ') or 'America/Argentina/Buenos_Aires')

DATA_DIR = Path(os.environ.get('CONTROL_DATA_DIR') or BASE_DIR)
CARPETAS = {
    'remitos': Path(os.environ.get('CONTROL_REMITOS_DIR') or (BASE_DIR / 'remitos')),
    'firmas': Path(os.environ.get('CONTROL_FIRMAS_DIR') or (BASE_DIR / 'static' / 'firmas')),
    'fotos': Path(os.environ.get('CONTROL_FOTOS_DIR') or (BASE_DIR / 'fotos')),
}
DESTINO = Path(os.environ.get('CONTROL_BACKUP_DIR') or (BASE_DIR / 'backups'))
DIAS = int(os.environ.get('CONTROL_BACKUP_DIAS', '30'))
HORA = int(os.environ.get('CONTROL_BACKUP_HORA', '3'))


def hacer_backup():
    marca = datetime.now(TZ).strftime('%Y-%m-%d_%H%M')
    DESTINO.mkdir(parents=True, exist_ok=True)

    base = DATA_DIR / 'database.db'
    if base.exists():
        origen = sqlite3.connect(base)
        copia = sqlite3.connect(DESTINO / f'database_{marca}.db')
        with copia:
            origen.backup(copia)
        copia.close()
        origen.close()

    with tarfile.open(DESTINO / f'archivos_{marca}.tar.gz', 'w:gz') as tar:
        for nombre, carpeta in CARPETAS.items():
            if carpeta.exists():
                tar.add(carpeta, arcname=nombre)

    print(f'OK: backup {marca} en {DESTINO}', flush=True)
    limpiar_viejos()


def limpiar_viejos():
    limite = time.time() - DIAS * 86400
    # Solo los que genera este script: los backups manuales no se tocan.
    for patron in ('database_*.db', 'archivos_*.tar.gz'):
        for archivo in DESTINO.glob(patron):
            if archivo.stat().st_mtime < limite:
                archivo.unlink()


def segundos_hasta_proximo():
    ahora = datetime.now(TZ)
    proximo = ahora.replace(hour=HORA, minute=0, second=0, microsecond=0)
    if proximo <= ahora:
        proximo += timedelta(days=1)
    return (proximo - ahora).total_seconds()


if __name__ == '__main__':
    if '--loop' not in sys.argv:
        hacer_backup()
        raise SystemExit(0)
    print(f'Backup diario a las {HORA:02d}:00, se conservan {DIAS} días.', flush=True)
    while True:
        time.sleep(segundos_hasta_proximo())
        try:
            hacer_backup()
        except Exception as e:  # un backup fallido no debe matar el servicio
            print(f'ERROR: backup falló: {e}', flush=True)
