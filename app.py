from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import sqlite3
from pathlib import Path
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'clave_secreta_para_desarrollo'

# Configuración de la base de datos
BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "database.db"

@app.before_request
def limpiar_redirecciones():
    """Evita bucles de redirección cuando el rol no coincide con la ruta"""
    if 'usuario_id' in session:
        rol = session.get('rol')
        if rol == 'admin' and request.path == '/tecnico':
            return redirect(url_for('admin'))
        if rol == 'jefe' and request.path in ['/tecnico', '/admin']:
            return redirect(url_for('jefe'))
        if rol == 'tecnico' and request.path in ['/admin', '/jefe']:
            return redirect(url_for('tecnico'))

def conectar_db():
    """Conecta a la base de datos"""
    return sqlite3.connect(str(DATABASE))

def get_db():
    """Obtiene una conexión a la base de datos con row_factory"""
    conexion = conectar_db()
    conexion.row_factory = sqlite3.Row
    return conexion

def crear_base_de_datos():
    """Crea las tablas si no existen"""
    conexion = conectar_db()
    cursor = conexion.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            usuario TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            rol TEXT NOT NULL,
            activo INTEGER DEFAULT 1
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS camionetas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patente TEXT UNIQUE NOT NULL,
            activa INTEGER DEFAULT 1
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS asignaciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            camioneta_id INTEGER,
            tecnico_id INTEGER NOT NULL,
            tecnico2_id INTEGER,
            fecha TEXT NOT NULL,
            jornada TEXT NOT NULL,
            estado TEXT DEFAULT 'PENDIENTE',
            zona TEXT,
            FOREIGN KEY (camioneta_id) REFERENCES camionetas(id),
            FOREIGN KEY (tecnico_id) REFERENCES usuarios(id),
            FOREIGN KEY (tecnico2_id) REFERENCES usuarios(id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS controles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asignacion_id INTEGER NOT NULL,
            retiro_fecha_hora TEXT,
            devolucion_fecha_hora TEXT,
            estado TEXT DEFAULT 'ABIERTO',
            observaciones TEXT,
            FOREIGN KEY (asignacion_id) REFERENCES asignaciones(id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS control_detalles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            control_id INTEGER NOT NULL,
            elemento TEXT NOT NULL,
            estado_retiro TEXT,
            estado_devolucion TEXT,
            FOREIGN KEY (control_id) REFERENCES controles(id)
        )
    ''')

    # ⚠️ CORREGIDO: Tabla reportes creada SOLO UNA VEZ (con fecha_resolucion)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reportes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            control_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            elemento TEXT NOT NULL,
            estado TEXT NOT NULL,
            descripcion TEXT,
            fecha_hora TEXT NOT NULL,
            fecha_resolucion TEXT,
            FOREIGN KEY (control_id) REFERENCES controles(id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS fotos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            control_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            ruta TEXT NOT NULL,
            fecha_hora TEXT NOT NULL,
            FOREIGN KEY (control_id) REFERENCES controles(id)
        )
    ''')
    
    conexion.commit()
    insertar_datos_prueba(conexion)
    conexion.close()

def insertar_datos_prueba(conexion):
    """Inserta datos de prueba si no existen"""
    cursor = conexion.cursor()
    
    cursor.execute('SELECT COUNT(*) as count FROM usuarios')
    count = cursor.fetchone()[0]
    
    if count == 0:
        cursor.execute('''
            INSERT INTO usuarios (nombre, usuario, password, rol, activo)
            VALUES (?, ?, ?, ?, ?)
        ''', ('Administrador', 'admin', 'admin123', 'admin', 1))
        
        cursor.execute('''
            INSERT INTO usuarios (nombre, usuario, password, rol, activo)
            VALUES (?, ?, ?, ?, ?)
        ''', ('Jefe de Flota', 'jefe', 'jefe123', 'jefe', 1))
        
        tecnicos = [
            ('Ana Martínez', 'ana', 'ana123'),
            ('Carlos Gómez', 'carlos', 'carlos123'),
            ('Diego Morales', 'diego', 'diego123')
        ]
        for nombre, usuario, password in tecnicos:
            cursor.execute('''
                INSERT INTO usuarios (nombre, usuario, password, rol, activo)
                VALUES (?, ?, ?, ?, ?)
            ''', (nombre, usuario, password, 'tecnico', 1))
    
    cursor.execute('SELECT COUNT(*) as count FROM camionetas')
    count = cursor.fetchone()[0]
    
    if count == 0:
        patentes = ['AA123BB', 'AB456CD', 'AC789EF', 'AD012GH', 'AE345IJ', 'AF678KL', 'AG901MN', 'AH234OP', 'AI567QR']
        for patente in patentes:
            cursor.execute('''
                INSERT INTO camionetas (patente, activa)
                VALUES (?, ?)
            ''', (patente, 1))
    
    conexion.commit()

def obtener_tecnicos():
    conexion = get_db()
    tecnicos = conexion.execute('''
        SELECT id, nombre FROM usuarios 
        WHERE rol = 'tecnico' AND activo = 1 ORDER BY nombre
    ''').fetchall()
    conexion.close()
    return tecnicos

def obtener_camionetas():
    conexion = get_db()
    camionetas = conexion.execute('''
        SELECT id, patente FROM camionetas 
        WHERE activa = 1 ORDER BY patente
    ''').fetchall()
    conexion.close()
    return camionetas

@app.route('/')
def login():
    if 'usuario_id' in session:
        if session.get('rol') == 'admin': return redirect(url_for('admin'))
        if session.get('rol') == 'jefe': return redirect(url_for('jefe'))
        return redirect(url_for('tecnico'))
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def procesar_login():
    usuario = request.form.get('usuario')
    password = request.form.get('password')
    
    if not usuario or not password:
        return render_template('login.html', error='Usuario y contraseña son requeridos')
    
    conexion = get_db()
    user = conexion.execute('''
        SELECT * FROM usuarios 
        WHERE usuario = ? AND password = ? AND activo = 1
    ''', (usuario, password)).fetchone()
    conexion.close()
    
    if user:
        session['usuario_id'] = user['id']
        session['nombre'] = user['nombre']
        session['rol'] = user['rol']
        
        if user['rol'] == 'admin': return redirect(url_for('admin'))
        elif user['rol'] == 'jefe': return redirect(url_for('jefe'))
        else: return redirect(url_for('tecnico'))
    else:
        return render_template('login.html', error='Usuario o contraseña incorrectos')

@app.route('/admin')
def admin():
    if 'usuario_id' not in session or session.get('rol') != 'admin':
        return redirect(url_for('login'))
    
    fecha_seleccionada = request.args.get('fecha', datetime.now().strftime('%Y-%m-%d'))
    jornada_seleccionada = request.args.get('jornada', 'mañana')
    fecha_actual = datetime.now().strftime('%d/%m/%Y')
    
    conexion = get_db()
    
    try:
        tecnicos = obtener_tecnicos()
        camionetas = obtener_camionetas()
        
        # Obtener asignaciones actuales
        asignaciones_actuales = conexion.execute('''
            SELECT a.id as asignacion_id, a.camioneta_id, a.tecnico_id, a.tecnico2_id, a.zona,
                   c.patente as camioneta_patente
            FROM asignaciones a
            LEFT JOIN camionetas c ON a.camioneta_id = c.id
            WHERE a.fecha = ? AND a.jornada = ?
        ''', (fecha_seleccionada, jornada_seleccionada)).fetchall()
        
        # Diccionario para fácil acceso
        asignaciones_por_tecnico = {}
        for a in asignaciones_actuales:
            asignaciones_por_tecnico[a['tecnico_id']] = {
                'asignacion_id': a['asignacion_id'],
                'camioneta_id': a['camioneta_id'],
                'zona': a['zona'] or '',
                'tecnico2_id': a['tecnico2_id']
            }
        
        # Camionetas ocupadas para ese día/jornada (para no duplicar)
        camionetas_ocupadas = conexion.execute('''
            SELECT DISTINCT camioneta_id 
            FROM asignaciones 
            WHERE fecha = ? AND jornada = ? AND camioneta_id IS NOT NULL
        ''', (fecha_seleccionada, jornada_seleccionada)).fetchall()
        
        camionetas_ocupadas_ids = [row['camioneta_id'] for row in camionetas_ocupadas]
        
        # Reportes
        try:
            reportes = conexion.execute('''
                SELECT 
                    r.id, r.tipo, r.elemento, r.estado, r.descripcion, r.fecha_hora, r.fecha_resolucion,
                    COALESCE(cam.patente, 'SIN ASIGNAR') as patente,
                    COALESCE(u.nombre, 'TÉCNICO DESCONOCIDO') as tecnico_nombre
                FROM reportes r
                LEFT JOIN controles co ON r.control_id = co.id
                LEFT JOIN asignaciones a ON co.asignacion_id = a.id
                LEFT JOIN camionetas cam ON a.camioneta_id = cam.id
                LEFT JOIN usuarios u ON a.tecnico_id = u.id
                ORDER BY r.fecha_hora DESC
            ''').fetchall()
            
            reportes_por_patente = {}
            for reporte in reportes:
                patente = reporte['patente']
                if patente not in reportes_por_patente:
                    reportes_por_patente[patente] = []
                reportes_por_patente[patente].append(dict(reporte))
                
            patentes_con_reportes = sorted(reportes_por_patente.keys())
            
            faltantes_por_patente = {}
            for patente, registros in reportes_por_patente.items():
                dedupe = {}
                for r in registros:
                    if r['estado'] in ['FALLA', 'FALTANTE', 'OBSERVACION']:
                        if r['elemento'] not in dedupe:
                            dedupe[r['elemento']] = r
                faltantes_por_patente[patente] = list(dedupe.values())
                
        except sqlite3.OperationalError:
            reportes_por_patente = {}
            patentes_con_reportes = []
            faltantes_por_patente = {}
        
    finally:
        conexion.close()
    
    mensaje = request.args.get('mensaje', '')
    error = request.args.get('error', '')
    
    # Generar la lista de filas de la planilla (una por técnico)
    planilla = []
    for tecnico in tecnicos:
        info = asignaciones_por_tecnico.get(tecnico['id'], {
            'asignacion_id': None,
            'camioneta_id': None,
            'zona': '',
            'tecnico2_id': None
        })
        planilla.append({
            'tecnico_id': tecnico['id'],
            'tecnico_nombre': tecnico['nombre'],
            'asignacion_id': info['asignacion_id'],
            'camioneta_id': info['camioneta_id'],
            'zona': info['zona'],
            'tecnico2_id': info['tecnico2_id']
        })
    
    return render_template('admin.html', 
                         camionetas=camionetas,
                         tecnicos=tecnicos,
                         planilla=planilla,
                         camionetas_ocupadas=camionetas_ocupadas_ids,
                         reportes=reportes, 
                         reportes_por_patente=reportes_por_patente,
                         faltantes_por_patente=faltantes_por_patente,
                         patentes_con_reportes=patentes_con_reportes,
                         fecha_seleccionada=fecha_seleccionada,
                         jornada_seleccionada=jornada_seleccionada,
                         fecha_actual=fecha_actual,
                         mensaje=mensaje,
                         error=error)

@app.route('/guardar-planilla', methods=['POST'])
def guardar_planilla():
    """Guarda todas las asignaciones de la planilla"""
    if 'usuario_id' not in session or session.get('rol') != 'admin':
        return redirect(url_for('login'))
    
    fecha = request.form.get('fecha')
    jornada = request.form.get('jornada')
    
    if not fecha or not jornada:
        return redirect(url_for('admin', error='Fecha y jornada son requeridas'))
    
    conexion = get_db()
    
    try:
        # Procesar cada técnico
        for tecnico_id in request.form.getlist('tecnico_ids'):
            tecnico_id = int(tecnico_id)
            camioneta_id = request.form.get(f'camioneta_{tecnico_id}') or None
            zona = request.form.get(f'zona_{tecnico_id}') or ''
            tecnico2_id = request.form.get(f'tecnico2_{tecnico_id}') or None
            
            # Verificar si ya existe una asignación para ese técnico en esa fecha/jornada
            existe_asignacion = conexion.execute('''
                SELECT id FROM asignaciones 
                WHERE tecnico_id = ? AND fecha = ? AND jornada = ?
            ''', (tecnico_id, fecha, jornada)).fetchone()
            
            if existe_asignacion:
                # Actualizar la existente
                conexion.execute('''
                    UPDATE asignaciones 
                    SET camioneta_id = ?, zona = ?, tecnico2_id = ?, estado = 'PENDIENTE'
                    WHERE tecnico_id = ? AND fecha = ? AND jornada = ?
                ''', (camioneta_id, zona, tecnico2_id, tecnico_id, fecha, jornada))
            else:
                # Crear nueva
                conexion.execute('''
                    INSERT INTO asignaciones (camioneta_id, tecnico_id, tecnico2_id, fecha, jornada, estado, zona)
                    VALUES (?, ?, ?, ?, ?, 'PENDIENTE', ?)
                ''', (camioneta_id, tecnico_id, tecnico2_id, fecha, jornada, zona))
        
        # Actualizar estado a 'ASIGNADA' solo para los que tienen camioneta
        conexion.execute('''
            UPDATE asignaciones 
            SET estado = 'ASIGNADA' 
            WHERE fecha = ? AND jornada = ? AND camioneta_id IS NOT NULL
        ''', (fecha, jornada))
        
        conexion.commit()
        mensaje = f'✅ Asignaciones guardadas correctamente para {fecha} ({jornada})'
        
    except Exception as e:
        conexion.rollback()
        return redirect(url_for('admin', error=f'Error al guardar: {str(e)}'))
    finally:
        conexion.close()
    
    return redirect(url_for('admin', fecha=fecha, jornada=jornada, mensaje=mensaje))

@app.route('/tecnico')
def tecnico():
    if 'usuario_id' not in session or session.get('rol') != 'tecnico':
        return redirect(url_for('login'))
    
    usuario_id = session['usuario_id']
    fecha_actual = datetime.now().strftime('%Y-%m-%d')
    
    conexion = get_db()
    
    asignacion = conexion.execute('''
        SELECT a.id, a.fecha, a.jornada, a.estado,
               c.patente as camioneta_patente,
               c.id as camioneta_id,
               u2.nombre as tecnico2_nombre
        FROM asignaciones a
        JOIN camionetas c ON a.camioneta_id = c.id
        LEFT JOIN usuarios u2 ON a.tecnico2_id = u2.id
        WHERE a.tecnico_id = ? 
        AND a.fecha = ? 
        AND a.estado = 'ASIGNADA'
    ''', (usuario_id, fecha_actual)).fetchone()
    
    conexion.close()
    
    return render_template('tecnico.html', 
                         nombre=session['nombre'],
                         asignacion=asignacion,
                         fecha_actual=fecha_actual)

@app.route('/jefe')
def jefe():
    if 'usuario_id' not in session or session.get('rol') != 'jefe':
        return redirect(url_for('login'))
    
    fecha_actual = datetime.now().strftime('%d/%m/%Y')
    conexion = get_db()
    
    try:
        camionetas = conexion.execute('''
            SELECT id, patente FROM camionetas WHERE activa = 1 ORDER BY patente
        ''').fetchall()
        
        # Obtener TODOS los reportes (incluyendo los RESUELTOS)
        reportes = conexion.execute('''
            SELECT r.estado, r.elemento, r.descripcion, r.fecha_hora, r.fecha_resolucion,
                   COALESCE(cam.patente, 'SIN ASIGNAR') as patente,
                   COALESCE(u.nombre, 'TÉCNICO DESCONOCIDO') as tecnico_nombre
            FROM reportes r
            LEFT JOIN controles co ON r.control_id = co.id
            LEFT JOIN asignaciones a ON co.asignacion_id = a.id
            LEFT JOIN camionetas cam ON a.camioneta_id = cam.id
            LEFT JOIN usuarios u ON a.tecnico_id = u.id
            ORDER BY r.fecha_hora DESC
        ''').fetchall()
        
        # Estructura de datos
        resumen_flota = {}
        for camioneta in camionetas:
            patente = camioneta['patente']
            # Inicializar todas las camionetas como OK
            resumen_flota[patente] = {
                'estado_general': 'OK', 
                'historial': [],  # Solo historial para el clic
                'ultimo_registro': 'Sin registros'
            }
        
        for r in reportes:
            patente = r['patente']
            if patente in resumen_flota:
                # Actualizar el último registro
                resumen_flota[patente]['ultimo_registro'] = r['fecha_hora'][:16].replace('T', ' ')
                
                # Guardar TODO en el historial
                resumen_flota[patente]['historial'].append({
                    'fecha': r['fecha_hora'][:16].replace('T', ' '),
                    'elemento': r['elemento'],
                    'estado': r['estado'],
                    'descripcion': r['descripcion'],
                    'tecnico': r['tecnico_nombre'],
                    'fecha_resolucion': r['fecha_resolucion'] or '-'
                })
                
                # Solo definir el estado general basado en las FALLAS y FALTANTES (NO resueltos)
                if r['estado'] == 'FALLA':
                    resumen_flota[patente]['estado_general'] = 'FALLA'
                elif r['estado'] == 'FALTANTE' and resumen_flota[patente]['estado_general'] != 'FALLA':
                    resumen_flota[patente]['estado_general'] = 'ALERTA'
                elif r['estado'] == 'OBSERVACION' and resumen_flota[patente]['estado_general'] == 'OK':
                    resumen_flota[patente]['estado_general'] = 'ALERTA'
        
    finally:
        conexion.close()
    
    return render_template('jefe.html', 
                         resumen_flota=resumen_flota,
                         fecha_actual=fecha_actual)

@app.route('/iniciar-retiro')
def iniciar_retiro():
    if 'usuario_id' not in session or session.get('rol') != 'tecnico':
        return redirect(url_for('login'))
    return "Aquí comenzará el control de RETIRO."

@app.route('/resolver-reporte/<int:reporte_id>', methods=['POST'])
def resolver_reporte(reporte_id):
    """Cambia el estado de un reporte a 'RESUELTO'"""
    if 'usuario_id' not in session or session.get('rol') != 'admin':
        return jsonify({'success': False, 'error': 'No autorizado'}), 401
    
    conexion = get_db()
    try:
        # Obtener la fecha y hora actuales
        ahora = datetime.now().strftime('%Y-%m-%d %H:%M')
        
        # Actualizar el estado del reporte y la fecha de resolución
        conexion.execute('''
            UPDATE reportes 
            SET estado = 'RESUELTO', fecha_resolucion = ?
            WHERE id = ?
        ''', (ahora, reporte_id))
        conexion.commit()
        return jsonify({'success': True, 'fecha_resolucion': ahora})
    except Exception as e:
        conexion.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conexion.close()


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    try:
        if DATABASE.exists():
            try:
                conexion = conectar_db()
                cursor = conexion.cursor()
                cursor.execute('SELECT name FROM sqlite_master WHERE type="table" AND name="usuarios"')
                if cursor.fetchone() is None:
                    conexion.close()
                    DATABASE.unlink()
                    crear_base_de_datos()
                else:
                    conexion.close()
            except sqlite3.OperationalError:
                if DATABASE.exists():
                    try:
                        DATABASE.unlink()
                    except PermissionError:
                        print("❌ Error: No se puede eliminar database.db porque está en uso.")
                        exit(1)
                crear_base_de_datos()
        else:
            crear_base_de_datos()
        
        print("✅ Base de datos inicializada correctamente")
        print("🚀 Iniciando servidor en http://localhost:5000")
        print("📝 Credenciales: Admin: admin / admin123 | Jefe: jefe / jefe123 | Técnico: ana / ana123")
        app.run(debug=True, host='0.0.0.0', port=5000)
        
    except Exception as e:
        print(f"❌ Error inesperado: {e}")