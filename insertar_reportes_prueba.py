import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "database.db"

def insertar_reportes_prueba():
    conexion = sqlite3.connect(DATABASE)
    conexion.row_factory = sqlite3.Row
    cursor = conexion.cursor()
    
    try:
        # Verificar si hay controles en la base de datos
        controles = cursor.execute('SELECT id FROM controles LIMIT 1').fetchone()
        
        if not controles:
            print("⚠️ No hay controles en la base de datos. Creando uno de prueba...")
            
            # Crear una asignación de prueba si no existe
            asignacion = cursor.execute('''
                SELECT id FROM asignaciones LIMIT 1
            ''').fetchone()
            
            if not asignacion:
                print("❌ No hay asignaciones. Creá una asignación primero desde el panel.")
                return
            
            # Crear un control de prueba
            ahora = datetime.now().isoformat()
            cursor.execute('''
                INSERT INTO controles (asignacion_id, retiro_fecha_hora, estado, observaciones)
                VALUES (?, ?, 'ABIERTO', 'Control de prueba')
            ''', (asignacion['id'], ahora))
            
            control_id = cursor.lastrowid
            print(f"✅ Control creado con ID: {control_id}")
        else:
            control_id = controles['id']
            print(f"📋 Usando control existente ID: {control_id}")
        
        # Verificar si ya hay reportes
        reportes_existentes = cursor.execute('SELECT COUNT(*) as count FROM reportes').fetchone()
        
        if reportes_existentes['count'] > 0:
            print(f"ℹ️ Ya existen {reportes_existentes['count']} reportes")
            respuesta = input("¿Querés agregar más reportes de prueba? (s/n): ")
            if respuesta.lower() != 's':
                return
        
        # Insertar reportes de prueba
        ahora = datetime.now()
        fecha_hora1 = (ahora - timedelta(hours=2)).isoformat()
        fecha_hora2 = (ahora - timedelta(hours=5)).isoformat()
        fecha_hora3 = (ahora - timedelta(hours=8)).isoformat()
        fecha_hora4 = (ahora - timedelta(hours=24)).isoformat()
        
        reportes = [
            (control_id, 'RETIRO', 'Aceite', 'FALLA', 'Nivel de aceite bajo - requiere revisión', fecha_hora1),
            (control_id, 'RETIRO', 'Llave cruz', 'FALTANTE', 'No se encuentra la llave cruz en el baúl', fecha_hora2),
            (control_id, 'DEVOLUCION', 'Matafuegos', 'OK', 'Matafuegos en correcto estado y presión', fecha_hora3),
            (control_id, 'RETIRO', 'Gato', 'OBSERVACION', 'El gato está oxidado pero funciona correctamente', fecha_hora4),
            (control_id, 'RETIRO', 'Agua', 'FALLA', 'No tiene agua el depósito - URGENTE', fecha_hora1),
            (control_id, 'DEVOLUCION', 'Kit de herramientas', 'FALTANTE', 'Falta un destornillador del kit', fecha_hora2),
            (control_id, 'RETIRO', 'Luces', 'OK', 'Todas las luces funcionan correctamente', fecha_hora3),
            (control_id, 'RETIRO', 'Neumáticos', 'OBSERVACION', 'El neumático trasero derecho tiene poco dibujo', fecha_hora4),
        ]
        
        for reporte in reportes:
            cursor.execute('''
                INSERT INTO reportes (control_id, tipo, elemento, estado, descripcion, fecha_hora)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', reporte)
        
        conexion.commit()
        print(f"✅ {len(reportes)} reportes de prueba insertados correctamente!")
        
        # Mostrar resumen
        print("\n📊 Resumen de reportes:")
        resumen = cursor.execute('''
            SELECT estado, COUNT(*) as cantidad
            FROM reportes
            GROUP BY estado
        ''').fetchall()
        
        for row in resumen:
            print(f"   {row['estado']}: {row['cantidad']}")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        conexion.rollback()
    finally:
        conexion.close()

if __name__ == '__main__':
    print("🔧 Insertando reportes de prueba...")
    insertar_reportes_prueba()
    print("\n🎯 Proceso completado")
    print("📝 Ahora actualizá la página del administrador para ver los reportes")