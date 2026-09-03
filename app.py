from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

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
    #Tabla Usuarios
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
    #Tabla camionetas
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS camionetas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patente TEXT UNIQUE NOT NULL,
            activa INTEGER DEFAULT 1
        )
    ''')
    #Tabla asignaciones
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS asignaciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            camioneta_id INTEGER,
            tecnico_id INTEGER,
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
    #Tabla Controles
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
    #Tabla control detalles
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

        # Tabla reportes
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
            comentario_resolucion TEXT,
            resuelto_por TEXT,
            FOREIGN KEY (control_id) REFERENCES controles(id)
        )
    ''')
    #Tabla Fotos. No implementado todavia 
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
        # Crear múltiples administradores
        admins = [
            ('Luciano', 'luciano', 'lucho123'),
            ('Juan', 'juan', 'juan123'),
            ('Mateo', 'mateo', 'mateo123')
        ]
        for nombre, usuario, password in admins:
            cursor.execute('''
                INSERT INTO usuarios (nombre, usuario, password, rol, activo)
                VALUES (?, ?, ?, 'admin', 1)
            ''', (nombre, usuario, password))
        
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
        patentes = ['AA123BB', 'AB456CD', 'AC789EF', 'AD012GH']
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
        
        # Obtener asignaciones por CAMIONETA
        asignaciones_actuales = conexion.execute('''
            SELECT a.id as asignacion_id, a.camioneta_id, a.tecnico_id, a.tecnico2_id, a.zona,
                   c.patente as camioneta_patente
            FROM asignaciones a
            LEFT JOIN camionetas c ON a.camioneta_id = c.id
            WHERE a.fecha = ? AND a.jornada = ?
        ''', (fecha_seleccionada, jornada_seleccionada)).fetchall()
        
        asignaciones_por_camioneta = {}
        for a in asignaciones_actuales:
            asignaciones_por_camioneta[a['camioneta_id']] = {
                'asignacion_id': a['asignacion_id'],
                'tecnico_id': a['tecnico_id'],
                'tecnico2_id': a['tecnico2_id'],
                'zona': a['zona'] or ''
            }
        
        # Reportes (se mantiene)
        try:
            reportes = conexion.execute('''
                SELECT 
                    r.id, r.tipo, r.elemento, r.estado, r.descripcion, r.fecha_hora, 
                    r.fecha_resolucion, r.comentario_resolucion, r.resuelto_por,
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
    
    planilla = []
    for camioneta in camionetas:
        info = asignaciones_por_camioneta.get(camioneta['id'], {
            'asignacion_id': None,
            'tecnico_id': None,
            'tecnico2_id': None,
            'zona': ''
        })
        planilla.append({
            'camioneta_id': camioneta['id'],
            'camioneta_patente': camioneta['patente'],
            'asignacion_id': info['asignacion_id'],
            'tecnico_id': info['tecnico_id'],
            'tecnico2_id': info['tecnico2_id'],
            'zona': info['zona']
        })
    
    return render_template('admin.html', 
                         camionetas=camionetas,
                         tecnicos=tecnicos,
                         planilla=planilla,
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
        # Procesar cada camioneta
        for camioneta_id in request.form.getlist('camioneta_ids'):
            camioneta_id = int(camioneta_id)
            tecnico_id = request.form.get(f'tecnico_{camioneta_id}') or None
            tecnico2_id = request.form.get(f'tecnico2_{camioneta_id}') or None
            zona = request.form.get(f'zona_{camioneta_id}') or ''
            
            # Verificar si ya existe una asignación para esa camioneta en esa fecha/jornada
            existe_asignacion = conexion.execute('''
                SELECT id FROM asignaciones 
                WHERE camioneta_id = ? AND fecha = ? AND jornada = ?
            ''', (camioneta_id, fecha, jornada)).fetchone()
            
            if existe_asignacion:
                # Actualizar
                conexion.execute('''
                    UPDATE asignaciones 
                    SET tecnico_id = ?, tecnico2_id = ?, zona = ?, estado = 'ASIGNADA'
                    WHERE camioneta_id = ? AND fecha = ? AND jornada = ?
                ''', (tecnico_id, tecnico2_id, zona, camioneta_id, fecha, jornada))
            else:
                # Crear nueva
                conexion.execute('''
                    INSERT INTO asignaciones (camioneta_id, tecnico_id, tecnico2_id, fecha, jornada, estado, zona)
                    VALUES (?, ?, ?, ?, ?, 'ASIGNADA', ?)
                ''', (camioneta_id, tecnico_id, tecnico2_id, fecha, jornada, zona))
        
        conexion.commit()
        mensaje = f'✅ Planilla guardada correctamente para {fecha} ({jornada})'
        
    except Exception as e:
        conexion.rollback()
        return redirect(url_for('admin', error=f'Error al guardar: {str(e)}'))
    finally:
        conexion.close()
    
    return redirect(url_for('admin', fecha=fecha, jornada=jornada, mensaje=mensaje))

@app.route('/admin/semana', methods=['GET', 'POST'])
def asignacion_semanal():
    """Asignación rápida para toda la semana"""
    if 'usuario_id' not in session or session.get('rol') != 'admin':
        return redirect(url_for('login'))
    
    # Obtener la jornada y la fecha de inicio de la semana
    jornada = request.args.get('jornada', 'mañana')
    fecha_inicio = request.args.get('fecha_inicio', datetime.now().strftime('%Y-%m-%d'))
    
    # ⚠️ DEFINIR LOS DÍAS DE LA SEMANA
    dias_semana = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
    
    # Calcular el lunes de la semana seleccionada
    fecha_dt = datetime.strptime(fecha_inicio, '%Y-%m-%d')
    inicio_semana = fecha_dt - timedelta(days=fecha_dt.weekday())
    fechas_semana = [inicio_semana + timedelta(days=i) for i in range(7)]
    
    conexion = get_db()
    
    try:
        tecnicos = obtener_tecnicos()
        camionetas = obtener_camionetas()
        
        # Obtener todas las asignaciones de la semana para la jornada
        fechas_str = [fecha.strftime('%Y-%m-%d') for fecha in fechas_semana]
        placeholders = ','.join('?' for _ in fechas_str)
        
        asignaciones_semana = conexion.execute(f'''
            SELECT a.camioneta_id, a.tecnico_id, a.tecnico2_id, a.zona, a.fecha
            FROM asignaciones a
            WHERE a.fecha IN ({placeholders}) AND a.jornada = ?
        ''', fechas_str + [jornada]).fetchall()
        
        asignaciones_por_dia = {}
        for asignacion in asignaciones_semana:
            camioneta_id = asignacion['camioneta_id']
            fecha = asignacion['fecha']
            if camioneta_id not in asignaciones_por_dia:
                asignaciones_por_dia[camioneta_id] = {}
            if fecha not in asignaciones_por_dia[camioneta_id]:
                asignaciones_por_dia[camioneta_id][fecha] = {
                    'tecnico_id': asignacion['tecnico_id'],
                    'tecnico2_id': asignacion['tecnico2_id'],
                    'zona': asignacion['zona'] or ''
                }
        
    finally:
        conexion.close()
    
    return render_template('semana.html', 
                         tecnicos=tecnicos,
                         camionetas=camionetas,
                         dias_semana=dias_semana,
                         fechas_semana=fechas_semana,
                         asignaciones_por_dia=asignaciones_por_dia,
                         jornada=jornada,
                         fecha_inicio=fecha_inicio)

@app.route('/guardar-semana', methods=['POST'])
def guardar_semana():
    """Guarda todas las asignaciones de la semana"""
    if 'usuario_id' not in session or session.get('rol') != 'admin':
        return redirect(url_for('login'))
    
    # Obtener los datos del formulario
    fechas = request.form.getlist('fechas[]')
    jornada = request.form.get('jornada', 'mañana')
    
    conexion = get_db()
    
    try:
        # Procesar cada camioneta
        for camioneta_id in request.form.getlist('camioneta_ids'):
            camioneta_id = int(camioneta_id)
            
            # Procesar cada día de la semana
            for fecha in fechas:
                tecnico_id = request.form.get(f'tecnico_{camioneta_id}_{fecha}') or None
                tecnico2_id = request.form.get(f'tecnico2_{camioneta_id}_{fecha}') or None
                zona = request.form.get(f'zona_{camioneta_id}_{fecha}') or ''
                
                # Verificar si ya existe una asignación para esa camioneta en esa fecha/jornada
                existe_asignacion = conexion.execute('''
                    SELECT id FROM asignaciones 
                    WHERE camioneta_id = ? AND fecha = ? AND jornada = ?
                ''', (camioneta_id, fecha, jornada)).fetchone()
                
                if existe_asignacion:
                    # Actualizar
                    conexion.execute('''
                        UPDATE asignaciones 
                        SET tecnico_id = ?, tecnico2_id = ?, zona = ?, estado = 'ASIGNADA'
                        WHERE camioneta_id = ? AND fecha = ? AND jornada = ?
                    ''', (tecnico_id, tecnico2_id, zona, camioneta_id, fecha, jornada))
                else:
                    # Crear nueva
                    conexion.execute('''
                        INSERT INTO asignaciones (camioneta_id, tecnico_id, tecnico2_id, fecha, jornada, estado, zona)
                        VALUES (?, ?, ?, ?, ?, 'ASIGNADA', ?)
                    ''', (camioneta_id, tecnico_id, tecnico2_id, fecha, jornada, zona))
        
        conexion.commit()
        mensaje = f'✅ Asignaciones de la semana guardadas correctamente'
        
    except Exception as e:
        conexion.rollback()
        return redirect(url_for('asignacion_semanal', error=f'Error al guardar: {str(e)}'))
    finally:
        conexion.close()
    
    return redirect(url_for('asignacion_semanal', mensaje=mensaje))

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
        #Consulta sql para camionetas
        camionetas = conexion.execute('''
            SELECT id, patente FROM camionetas WHERE activa = 1 ORDER BY patente
        ''').fetchall()
        #Consulta sql para reportes
        reportes = conexion.execute('''
            SELECT r.estado, r.elemento, r.descripcion, r.fecha_hora, r.fecha_resolucion, 
                   r.comentario_resolucion, r.resuelto_por,
                   COALESCE(cam.patente, 'SIN ASIGNAR') as patente,
                   COALESCE(u.nombre, 'TÉCNICO DESCONOCIDO') as tecnico_nombre
            FROM reportes r
            LEFT JOIN controles co ON r.control_id = co.id
            LEFT JOIN asignaciones a ON co.asignacion_id = a.id
            LEFT JOIN camionetas cam ON a.camioneta_id = cam.id
            LEFT JOIN usuarios u ON a.tecnico_id = u.id
            ORDER BY r.fecha_hora DESC
        ''').fetchall()
        
        resumen_flota = {}
        for camioneta in camionetas:
            patente = camioneta['patente']
            resumen_flota[patente] = {
                'estado_general': 'OK', 
                'historial': [],
                'ultimo_registro': 'Sin registros'
            }
        
        for r in reportes:
            patente = r['patente']
            if patente in resumen_flota:
                resumen_flota[patente]['ultimo_registro'] = r['fecha_hora'][:16].replace('T', ' ')
                
                resumen_flota[patente]['historial'].append({
                    'fecha': r['fecha_hora'][:16].replace('T', ' '),
                    'elemento': r['elemento'],
                    'estado': r['estado'],
                    'descripcion': r['descripcion'],
                    'tecnico': r['tecnico_nombre'],
                    'fecha_resolucion': r['fecha_resolucion'] or '-',
                    'resuelto_por': r['resuelto_por'] or '-',
                    'comentario_resolucion': r['comentario_resolucion'] or '-'
                })
                
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
    
    # Obtener el nombre del administrador
    nombre_admin = session.get('nombre', 'Administrador')
    
    conexion = get_db()
    try:
        # Obtener la fecha y hora actuales
        ahora = datetime.now().strftime('%Y-%m-%d %H:%M')
        
        # Actualizar el estado del reporte, la fecha y quién lo resolvió
        conexion.execute('''
            UPDATE reportes 
            SET estado = 'RESUELTO', fecha_resolucion = ?, resuelto_por = ?
            WHERE id = ?
        ''', (ahora, nombre_admin, reporte_id))
        conexion.commit()
        return jsonify({'success': True, 'fecha_resolucion': ahora})
    except Exception as e:
        conexion.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conexion.close()

@app.route('/comentar-reporte/<int:reporte_id>', methods=['POST'])
def comentar_reporte(reporte_id):
    """Agrega un comentario a un reporte ya resuelto"""
    if 'usuario_id' not in session or session.get('rol') != 'admin':
        return jsonify({'success': False, 'error': 'No autorizado'}), 401
    
    data = request.get_json()
    comentario = data.get('comentario', '').strip()
    
    if not comentario:
        return jsonify({'success': False, 'error': 'El comentario es requerido'}), 400
    
    conexion = get_db()
    try:
        # Actualizar el comentario del reporte
        conexion.execute('''
            UPDATE reportes 
            SET comentario_resolucion = ?
            WHERE id = ?
        ''', (comentario, reporte_id))
        conexion.commit()
        return jsonify({'success': True, 'comentario': comentario})
    except Exception as e:
        conexion.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conexion.close()       

@app.route('/remito/<int:reporte_id>')
def generar_remito(reporte_id):
    """Genera un remito específico para un reporte de tipo FALTANTE"""
    if 'usuario_id' not in session or session.get('rol') not in ('admin', 'jefe'):
        return redirect(url_for('login'))
    
    conexion = get_db()
    try:
        # Obtener el reporte y sus datos vinculados
        reporte = conexion.execute('''
            SELECT r.id, r.elemento, r.descripcion, r.estado, r.fecha_hora,
                   c.patente, u.nombre as tecnico_nombre
            FROM reportes r
            LEFT JOIN controles co ON r.control_id = co.id
            LEFT JOIN asignaciones a ON co.asignacion_id = a.id
            LEFT JOIN camionetas c ON a.camioneta_id = c.id
            LEFT JOIN usuarios u ON a.tecnico_id = u.id
            WHERE r.id = ?
        ''', (reporte_id,)).fetchone()
        
        if not reporte or reporte['estado'] != 'FALTANTE':
            return redirect(url_for('admin', error='Remito no disponible para este reporte'))
        
        # Obtener el nombre del admin que generó el remito
        admin_nombre = session.get('nombre', 'Administrador')
        
    finally:
        conexion.close()
    
    return render_template('remito.html', 
                         reporte=reporte,
                         admin_nombre=admin_nombre)       

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