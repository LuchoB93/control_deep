import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "database.db"

def agregar_tabla_reportes():
    conexion = sqlite3.connect(DATABASE)
    cursor = conexion.cursor()
    
    try:
        # Verificar si la tabla ya existe
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='reportes'")
        if cursor.fetchone() is None:
            print("📦 Creando tabla reportes...")
            
            # Crear tabla reportes
            cursor.execute('''
                CREATE TABLE reportes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    control_id INTEGER NOT NULL,
                    tipo TEXT NOT NULL,
                    elemento TEXT NOT NULL,
                    estado TEXT NOT NULL,
                    descripcion TEXT,
                    fecha_hora TEXT NOT NULL,
                    FOREIGN KEY (control_id) REFERENCES controles(id)
                )
            ''')
            
            # Crear tabla fotos (opcional, para el futuro)
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='fotos'")
            if cursor.fetchone() is None:
                print("📸 Creando tabla fotos...")
                cursor.execute('''
                    CREATE TABLE fotos (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        control_id INTEGER NOT NULL,
                        tipo TEXT NOT NULL,
                        ruta TEXT NOT NULL,
                        fecha_hora TEXT NOT NULL,
                        FOREIGN KEY (control_id) REFERENCES controles(id)
                    )
                ''')
            
            conexion.commit()
            print("✅ Tablas creadas exitosamente!")
        else:
            print("ℹ️ La tabla reportes ya existe")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        conexion.rollback()
    finally:
        conexion.close()

if __name__ == '__main__':
    agregar_tabla_reportes()
    print("🎯 Proceso completado")