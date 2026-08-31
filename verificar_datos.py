import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "database.db"

def verificar_datos():
    conexion = sqlite3.connect(DATABASE)
    conexion.row_factory = sqlite3.Row
    cursor = conexion.cursor()
    
    print("🔍 VERIFICANDO DATOS:\n")
    
    # 1. Verificar reportes
    reportes = cursor.execute('SELECT * FROM reportes').fetchall()
    print(f"📊 Reportes totales: {len(reportes)}")
    
    if reportes:
        print("\n📋 Primer reporte:")
        # Convertir Row a dict para poder iterar
        primer_reporte = dict(reportes[0])
        for key, value in primer_reporte.items():
            print(f"   {key}: {value}")
    
    # 2. Verificar controles
    controles = cursor.execute('SELECT * FROM controles').fetchall()
    print(f"\n📋 Controles totales: {len(controles)}")
    
    if controles:
        print("\n📋 Primer control:")
        primer_control = dict(controles[0])
        for key, value in primer_control.items():
            print(f"   {key}: {value}")
    
    # 3. Verificar asignaciones
    asignaciones = cursor.execute('SELECT * FROM asignaciones').fetchall()
    print(f"\n📋 Asignaciones totales: {len(asignaciones)}")
    
    if asignaciones:
        print("\n📋 Primera asignación:")
        primer_asignacion = dict(asignaciones[0])
        for key, value in primer_asignacion.items():
            print(f"   {key}: {value}")
    
    # 4. Verificar camionetas
    camionetas = cursor.execute('SELECT * FROM camionetas').fetchall()
    print(f"\n🚗 Camionetas totales: {len(camionetas)}")
    
    if camionetas:
        print("\n🚗 Camionetas disponibles:")
        for camioneta in camionetas:
            print(f"   ID: {camioneta['id']} - Patente: {camioneta['patente']}")
    
    # 5. Verificar la relación reportes → controles
    print("\n🔗 Relación reportes → controles:")
    query = '''
        SELECT r.id, r.control_id, c.id as control_existe
        FROM reportes r
        LEFT JOIN controles c ON r.control_id = c.id
    '''
    resultados = cursor.execute(query).fetchall()
    
    for row in resultados:
        existe = '✅' if row['control_existe'] else '❌ NO EXISTE'
        print(f"   Reporte {row['id']} → control_id: {row['control_id']} {existe}")
    
    # 6. Verificar la relación completa
    print("\n🔗 Relación completa (reportes → controles → asignaciones → camionetas):")
    query_completa = '''
        SELECT 
            r.id as reporte_id,
            r.elemento,
            r.estado,
            r.control_id,
            c.id as control_id_existe,
            c.asignacion_id,
            a.id as asignacion_id_existe,
            a.camioneta_id,
            cam.id as camioneta_id_existe,
            cam.patente,
            u.nombre as tecnico_nombre
        FROM reportes r
        LEFT JOIN controles c ON r.control_id = c.id
        LEFT JOIN asignaciones a ON c.asignacion_id = a.id
        LEFT JOIN camionetas cam ON a.camioneta_id = cam.id
        LEFT JOIN usuarios u ON a.tecnico_id = u.id
        LIMIT 5
    '''
    
    resultados = cursor.execute(query_completa).fetchall()
    for row in resultados:
        print(f"\n   📌 Reporte ID: {row['reporte_id']}")
        print(f"      Elemento: {row['elemento']}")
        print(f"      Estado: {row['estado']}")
        print(f"      control_id: {row['control_id']} → {'✅' if row['control_id_existe'] else '❌ NO EXISTE'}")
        if row['control_id_existe']:
            print(f"      asignacion_id: {row['asignacion_id']} → {'✅' if row['asignacion_id_existe'] else '❌ NO EXISTE'}")
        if row['asignacion_id_existe']:
            print(f"      camioneta: {row['patente']} → {'✅' if row['camioneta_id_existe'] else '❌ NO EXISTE'}")
            print(f"      técnico: {row['tecnico_nombre']}")
    
    # 7. Resumen final
    print("\n" + "="*50)
    print("📊 RESUMEN FINAL:")
    
    # Contar reportes por estado
    resumen_estados = cursor.execute('''
        SELECT estado, COUNT(*) as cantidad
        FROM reportes
        GROUP BY estado
    ''').fetchall()
    
    print("\n📈 Reportes por estado:")
    for row in resumen_estados:
        print(f"   {row['estado']}: {row['cantidad']}")
    
    # Verificar cuántos reportes tienen todas las relaciones completas
    completos = cursor.execute('''
        SELECT COUNT(*) as cantidad
        FROM reportes r
        JOIN controles c ON r.control_id = c.id
        JOIN asignaciones a ON c.asignacion_id = a.id
        JOIN camionetas cam ON a.camioneta_id = cam.id
        JOIN usuarios u ON a.tecnico_id = u.id
    ''').fetchone()
    
    print(f"\n✅ Reportes con todas las relaciones completas: {completos['cantidad']} de {len(reportes)}")
    
    conexion.close()

if __name__ == '__main__':
    verificar_datos()