from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = 'clave_secreta_para_desarrollo'

# Configuración de la base de datos
BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "database.db"

# Constantes para los elementos de la camioneta
EXPECTED_CAMIONETA = [
    "Aceite",
    "Agua Limpiavidrios",
    "Agua Refrigerante",
    "Balizas",
    "Cubierta Auxiliar",
    "Estado de Cubiertas",
    "Gato Hidráulico",
    "Juego de Llaves de Oficina",
    "Kit Primeros Auxilios",
    "Linga",
    "Llave Cruz",
    "Luces Altas",
    "Luces Bajas",
    "Luces de Posición",
    "Matafuegos",
    "Seguro",
    "Tarjeta Verde",
]

EXPECTED_HERRAMIENTAS = [
    "Conos",
    "Escaleras de Aluminio",
    "Escaleras de Madera",
    "Pasacables",
    "Pertiga",
    "Porta Bobina",
]

EXPECTED_CAJA = [
    "GUANTES",
    "DIGITALIZADOR",
    "TESTER/BUSCA POLO",
    "LINTERNA MINERO",
    "PERCUTOR/TALADRO",
    "MECHA CORTA",
    "MECHA LARGA",
    "DESTORNILLADOR PLANO",
    "DESTORNILLADOR PHILIPS",
    "MARTILLO",
    "GRIPIADORA",
    "PELACABLE",
    "PULSIANA",
    "VFL",
    "SACA TRAMPA",
    "PROLONGACION",
    "GUANTES DIELECTRICOS",
    "MULTIMETRO",
]

# Combinar todas las categorías para facilitar el uso
TODOS_ELEMENTOS = {
    'CAMIONETA': EXPECTED_CAMIONETA,
    'HERRAMIENTA': EXPECTED_HERRAMIENTAS,
    'CAJA': EXPECTED_CAJA
}

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
    #Tabla estadisticas para tecnicos
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS estadisticas_tecnicos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tecnico_id INTEGER NOT NULL,
        elemento TEXT NOT NULL,
        categoria TEXT NOT NULL,
        tipo_reporte TEXT NOT NULL,  -- 'FALTANTE', 'FALLA', 'OBSERVACION'
        fecha_reporte TEXT NOT NULL,
        fecha_resolucion TEXT,
        resuelto INTEGER DEFAULT 0,
        FOREIGN KEY (tecnico_id) REFERENCES usuarios(id)
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

     # Tabla para los controles diarios del técnico
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS controles_tecnicos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asignacion_id INTEGER NOT NULL,
            fecha TEXT NOT NULL,
            jornada TEXT NOT NULL,  -- 'mañana' o 'tarde'
            tipo_control TEXT NOT NULL,  -- 'RETIRO' o 'DEVOLUCION'
            finalizado INTEGER DEFAULT 0,
            fecha_hora_inicio TEXT NOT NULL,
            fecha_hora_fin TEXT,
            FOREIGN KEY (asignacion_id) REFERENCES asignaciones(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS items_control_tecnico (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            control_tecnico_id INTEGER NOT NULL,
            elemento TEXT NOT NULL,
            categoria TEXT NOT NULL,
            estado TEXT NOT NULL,
            observacion TEXT,
            fecha_hora TEXT NOT NULL,
            FOREIGN KEY (control_tecnico_id) REFERENCES controles_tecnicos(id)
        )
    ''')


     # Tabla para el estado de elementos (bloqueados por fallas)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS elementos_bloqueados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            elemento TEXT NOT NULL,
            camioneta_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,  -- 'CAMIONETA', 'HERRAMIENTA', 'CAJA'
            fecha_bloqueo TEXT NOT NULL,
            motivo TEXT,
            resuelto INTEGER DEFAULT 0,  -- 0=pendiente, 1=resuelto
            fecha_resolucion TEXT,
            FOREIGN KEY (camioneta_id) REFERENCES camionetas(id)
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

        # En crear_base_de_datos(), modifica la tabla reportes
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
        entregado_por TEXT,          -- NUEVO: quien entregó el material
        recibido_por TEXT,           -- NUEVO: quien recibió el material
        fecha_entrega TEXT,          -- NUEVO: fecha de entrega
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


@app.route('/jefe/estadisticas')
def jefe_estadisticas():
    """Obtiene estadísticas para el panel del jefe"""
    if 'usuario_id' not in session or session.get('rol') != 'jefe':
        return redirect(url_for('login'))
    
    conexion = get_db()
    
    # 1. Estadísticas generales
    stats_generales = conexion.execute('''
        SELECT 
            COUNT(DISTINCT r.elemento) as total_elementos_reportados,
            COUNT(CASE WHEN r.estado = 'FALTANTE' THEN 1 END) as total_faltantes,
            COUNT(CASE WHEN r.estado = 'FALLA' THEN 1 END) as total_fallas,
            COUNT(CASE WHEN r.estado = 'OBSERVACION' THEN 1 END) as total_observaciones,
            COUNT(CASE WHEN r.estado = 'RESUELTO' THEN 1 END) as total_resueltos,
            COUNT(DISTINCT a.tecnico_id) as tecnicos_activos
        FROM reportes r
        LEFT JOIN controles co ON r.control_id = co.id
        LEFT JOIN asignaciones a ON co.asignacion_id = a.id
        WHERE r.fecha_hora >= date('now', '-30 days')
    ''').fetchone()
    
    # 2. Elementos más reportados como FALTANTE
    elementos_mas_faltantes = conexion.execute('''
        SELECT 
            r.elemento,
            COUNT(*) as total,
            COUNT(DISTINCT a.tecnico_id) as tecnicos_diferentes
        FROM reportes r
        LEFT JOIN controles co ON r.control_id = co.id
        LEFT JOIN asignaciones a ON co.asignacion_id = a.id
        WHERE r.estado = 'FALTANTE' 
        AND r.fecha_hora >= date('now', '-30 days')
        GROUP BY r.elemento
        ORDER BY total DESC
        LIMIT 10
    ''').fetchall()
    
    # 3. Técnicos que más reportan
    tecnicos_mas_reportan = conexion.execute('''
        SELECT 
            u.nombre as tecnico,
            u.usuario,
            COUNT(r.id) as total_reportes,
            COUNT(CASE WHEN r.estado = 'FALTANTE' THEN 1 END) as faltantes,
            COUNT(CASE WHEN r.estado = 'FALLA' THEN 1 END) as fallas,
            COUNT(CASE WHEN r.estado = 'OBSERVACION' THEN 1 END) as observaciones,
            COUNT(CASE WHEN r.estado = 'RESUELTO' THEN 1 END) as resueltos
        FROM usuarios u
        LEFT JOIN asignaciones a ON u.id = a.tecnico_id
        LEFT JOIN controles co ON a.id = co.asignacion_id
        LEFT JOIN reportes r ON co.id = r.control_id
        WHERE u.rol = 'tecnico'
        AND r.fecha_hora >= date('now', '-30 days')
        GROUP BY u.id
        ORDER BY total_reportes DESC
        LIMIT 10
    ''').fetchall()
    
    # 4. Historial por elemento (para el rastreo individual)
    historial_elementos = conexion.execute('''
        SELECT 
            r.elemento,
            r.estado,
            r.descripcion,
            r.fecha_hora,
            r.fecha_resolucion,
            r.resuelto_por,
            u.nombre as tecnico_nombre,
            c.patente
        FROM reportes r
        LEFT JOIN controles co ON r.control_id = co.id
        LEFT JOIN asignaciones a ON co.asignacion_id = a.id
        LEFT JOIN usuarios u ON a.tecnico_id = u.id
        LEFT JOIN camionetas c ON a.camioneta_id = c.id
        WHERE r.fecha_hora >= date('now', '-90 days')
        ORDER BY r.elemento, r.fecha_hora DESC
    ''').fetchall()
    
    # 5. Agrupar historial por elemento
    historial_por_elemento = {}
    for item in historial_elementos:
        elemento = item['elemento']
        if elemento not in historial_por_elemento:
            historial_por_elemento[elemento] = []
        historial_por_elemento[elemento].append(dict(item))
    
    conexion.close()
    
    return render_template('jefe_estadisticas.html',
                         stats_generales=stats_generales,
                         elementos_mas_faltantes=elementos_mas_faltantes,
                         tecnicos_mas_reportan=tecnicos_mas_reportan,
                         historial_por_elemento=historial_por_elemento)


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


@app.route('/guardar-control-rapido', methods=['POST'])
def guardar_control_rapido():
    """Guarda todos los problemas de una categoría de una vez"""
    if 'usuario_id' not in session or session.get('rol') != 'tecnico':
        return jsonify({'error': 'No autorizado'}), 401
    
    data = request.get_json()
    control_id = data.get('control_id')
    problemas = data.get('problemas', [])
    
    if not control_id:
        return jsonify({'error': 'ID de control requerido'}), 400
    
    conexion = get_db()
    cursor = conexion.cursor()
    
    try:
        fecha_hora = datetime.now().isoformat()
        fecha_legible = datetime.now().strftime('%Y-%m-%d %H:%M')
        
        # Obtener la camioneta y el control
        info = cursor.execute('''
            SELECT a.camioneta_id, ct.asignacion_id, ct.tipo_control, 
                   a.tecnico_id, u.nombre as tecnico_nombre, c.patente
            FROM controles_tecnicos ct
            JOIN asignaciones a ON ct.asignacion_id = a.id
            JOIN camionetas c ON a.camioneta_id = c.id
            JOIN usuarios u ON a.tecnico_id = u.id
            WHERE ct.id = ?
        ''', (control_id,)).fetchone()
        
        if not info:
            return jsonify({'error': 'Control no encontrado'}), 404
        
        camioneta_id = info['camioneta_id']
        asignacion_id = info['asignacion_id']
        tipo_control = info['tipo_control']
        tecnico_nombre = info['tecnico_nombre']
        patente = info['patente']
        
        # Obtener o crear el control en la tabla `controles`
        control_existente = cursor.execute('''
            SELECT id FROM controles WHERE asignacion_id = ? AND estado = 'ABIERTO'
        ''', (asignacion_id,)).fetchone()
        
        if control_existente:
            control_id_old = control_existente['id']
        else:
            fecha_hora_control = datetime.now().isoformat()
            cursor.execute('''
                INSERT INTO controles (asignacion_id, retiro_fecha_hora, estado)
                VALUES (?, ?, 'ABIERTO')
            ''', (asignacion_id, fecha_hora_control))
            control_id_old = cursor.lastrowid
        
        # ==========================================
        # GUARDAR TODOS LOS ELEMENTOS (OK Y PROBLEMAS)
        # ==========================================
        
        # 1. Crear un diccionario de problemas con su observación
        problemas_dict = {}
        for p in problemas:
            problemas_dict[p['elemento']] = {
                'observacion': p.get('observacion', ''),
                'categoria': p.get('categoria', 'GENERAL')
            }
        
        # 2. Recorrer TODOS los elementos de todas las categorías
        for categoria, lista in TODOS_ELEMENTOS.items():
            for elemento in lista:
                if elemento in problemas_dict:
                    # Es un problema
                    estado = 'FALTANTE'
                    # ✅ LA OBSERVACIÓN VA AQUÍ
                    descripcion = problemas_dict[elemento]['observacion'] if problemas_dict[elemento]['observacion'] else 'Elemento faltante'
                    categoria_elemento = problemas_dict[elemento]['categoria']
                else:
                    # Está OK
                    estado = 'OK'
                    descripcion = 'Elemento en buen estado'
                    categoria_elemento = categoria
                
                # Guardar en items_control_tecnico
                cursor.execute('''
                    INSERT INTO items_control_tecnico 
                    (control_tecnico_id, elemento, categoria, estado, observacion, fecha_hora)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (control_id, elemento, categoria_elemento, 
                      estado, descripcion, fecha_hora))
                
                # ✅ Guardar en reportes con la descripción correcta
                cursor.execute('''
                    INSERT INTO reportes 
                    (control_id, tipo, elemento, estado, descripcion, fecha_hora)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (control_id_old, tipo_control, elemento, 
                      estado, descripcion, fecha_hora))
        
        # 3. Bloquear SOLO los elementos con problemas
        for elemento, data in problemas_dict.items():
            ya_bloqueado = cursor.execute('''
                SELECT id FROM elementos_bloqueados 
                WHERE elemento = ? AND camioneta_id = ? AND resuelto = 0
            ''', (elemento, camioneta_id)).fetchone()
            
            if not ya_bloqueado:
                cursor.execute('''
                    INSERT INTO elementos_bloqueados 
                    (elemento, camioneta_id, tipo, fecha_bloqueo, motivo, resuelto)
                    VALUES (?, ?, ?, ?, ?, 0)
                ''', (elemento, camioneta_id, data['categoria'], 
                      fecha_hora, data['observacion']))
        
        # 4. Actualizar el estado del control
        if tipo_control == 'RETIRO':
            cursor.execute('''
                UPDATE controles 
                SET retiro_fecha_hora = ? 
                WHERE id = ?
            ''', (fecha_hora, control_id_old))
        else:
            cursor.execute('''
                UPDATE controles 
                SET devolucion_fecha_hora = ? 
                WHERE id = ?
            ''', (fecha_hora, control_id_old))
        
        conexion.commit()
        
        total_ok = sum(1 for cat in TODOS_ELEMENTOS.values() for e in cat if e not in problemas_dict)
        total_problemas = len(problemas_dict)
        
        print(f"✅ Control guardado: {total_ok} OK, {total_problemas} problemas")
        for elemento, data in problemas_dict.items():
            print(f"   - {elemento}: {data['observacion']}")
        
        return jsonify({
            'success': True, 
            'message': f'Control guardado: {total_ok} OK, {total_problemas} problemas',
            'total_ok': total_ok,
            'total_problemas': total_problemas
        })
        
    except Exception as e:
        conexion.rollback()
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        conexion.close()


@app.route('/guardar-estado-elemento', methods=['POST'])
def guardar_estado_elemento():
    """Guarda el estado de un elemento durante el control"""
    if 'usuario_id' not in session or session.get('rol') != 'tecnico':
        return jsonify({'error': 'No autorizado'}), 401
    
    control_id = request.form.get('control_id')
    elemento = request.form.get('elemento')
    categoria = request.form.get('categoria')
    estado = request.form.get('estado')
    observacion = request.form.get('observacion', '')
    
    # Validar datos requeridos
    if not all([control_id, elemento, categoria, estado]):
        return jsonify({'error': 'Datos incompletos'}), 400
    
    fecha_hora = datetime.now().isoformat()
    
    conexion = get_db()
    cursor = conexion.cursor()
    
    try:
        # Verificar si el elemento ya fue registrado en este control
        existe = cursor.execute('''
            SELECT id FROM items_control_tecnico 
            WHERE control_tecnico_id = ? AND elemento = ?
        ''', (control_id, elemento)).fetchone()
        
        if existe:
            # Actualizar estado
            cursor.execute('''
                UPDATE items_control_tecnico 
                SET estado = ?, observacion = ?, fecha_hora = ?
                WHERE control_tecnico_id = ? AND elemento = ?
            ''', (estado, observacion, fecha_hora, control_id, elemento))
        else:
            # Insertar nuevo registro
            cursor.execute('''
                INSERT INTO items_control_tecnico 
                (control_tecnico_id, elemento, categoria, estado, observacion, fecha_hora)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (control_id, elemento, categoria, estado, observacion, fecha_hora))
        
        # Si el estado es FALLA o FALTANTE, bloquear el elemento
        if estado in ['FALLA', 'FALTANTE']:
            # Obtener la camioneta asociada al control
            camioneta = cursor.execute('''
                SELECT a.camioneta_id 
                FROM controles_tecnicos ct
                JOIN asignaciones a ON ct.asignacion_id = a.id
                WHERE ct.id = ?
            ''', (control_id,)).fetchone()
            
            if camioneta:
                # Verificar si ya está bloqueado
                ya_bloqueado = cursor.execute('''
                    SELECT id FROM elementos_bloqueados 
                    WHERE elemento = ? AND camioneta_id = ? AND resuelto = 0
                ''', (elemento, camioneta['camioneta_id'])).fetchone()
                
                if not ya_bloqueado:
                    cursor.execute('''
                        INSERT INTO elementos_bloqueados 
                        (elemento, camioneta_id, tipo, fecha_bloqueo, motivo, resuelto)
                        VALUES (?, ?, ?, ?, ?, 0)
                    ''', (elemento, camioneta['camioneta_id'], categoria, 
                          fecha_hora, observacion))
        
        conexion.commit()
        return jsonify({'success': True, 'message': 'Elemento guardado correctamente'})
        
    except Exception as e:
        conexion.rollback()
        print(f"❌ Error al guardar estado: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        conexion.close()

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
    """Panel principal del técnico"""
    if 'usuario_id' not in session or session.get('rol') != 'tecnico':
        return redirect(url_for('login'))
    
    usuario_id = session['usuario_id']
    fecha_actual = datetime.now().strftime('%Y-%m-%d')
    hora_actual = datetime.now().hour
    
    # Determinar jornada
    if 6 <= hora_actual < 14:
        jornada_actual = 'mañana'
    elif 14 <= hora_actual < 22:
        jornada_actual = 'tarde'
    else:
        jornada_actual = 'mañana'
    
    conexion = get_db()
    
    # Buscar asignación del técnico para hoy
    asignacion = conexion.execute('''
        SELECT a.id, a.fecha, a.jornada, a.estado,
               c.patente as camioneta_patente,
               c.id as camioneta_id
        FROM asignaciones a
        JOIN camionetas c ON a.camioneta_id = c.id
        WHERE a.tecnico_id = ? 
        AND a.fecha = ? 
        AND a.estado = 'ASIGNADA'
    ''', (usuario_id, fecha_actual)).fetchone()
    
    # Variables para el estado de los controles
    control_retiro_activo = None
    control_devolucion_activo = None
    retiro_completado = False
    devolucion_completada = False
    
    if asignacion:
        # Buscar controles de RETIRO
        control_retiro_activo = conexion.execute('''
            SELECT * FROM controles_tecnicos 
            WHERE asignacion_id = ? 
            AND fecha = ? 
            AND jornada = ? 
            AND tipo_control = 'RETIRO'
            AND finalizado = 0
        ''', (asignacion['id'], fecha_actual, jornada_actual)).fetchone()
        
        # Buscar controles de DEVOLUCION
        control_devolucion_activo = conexion.execute('''
            SELECT * FROM controles_tecnicos 
            WHERE asignacion_id = ? 
            AND fecha = ? 
            AND jornada = ? 
            AND tipo_control = 'DEVOLUCION'
            AND finalizado = 0
        ''', (asignacion['id'], fecha_actual, jornada_actual)).fetchone()
        
        # Verificar si el RETIRO ya fue completado
        retiro_finalizado = conexion.execute('''
            SELECT id FROM controles_tecnicos 
            WHERE asignacion_id = ? 
            AND fecha = ? 
            AND jornada = ? 
            AND tipo_control = 'RETIRO'
            AND finalizado = 1
        ''', (asignacion['id'], fecha_actual, jornada_actual)).fetchone()
        retiro_completado = retiro_finalizado is not None
        
        # Verificar si la DEVOLUCION ya fue completada
        devolucion_finalizada = conexion.execute('''
            SELECT id FROM controles_tecnicos 
            WHERE asignacion_id = ? 
            AND fecha = ? 
            AND jornada = ? 
            AND tipo_control = 'DEVOLUCION'
            AND finalizado = 1
        ''', (asignacion['id'], fecha_actual, jornada_actual)).fetchone()
        devolucion_completada = devolucion_finalizada is not None
    
    # Verificar elementos bloqueados
    elementos_bloqueados = []
    if asignacion:
        bloqueados = conexion.execute('''
            SELECT elemento, tipo, motivo 
            FROM elementos_bloqueados 
            WHERE camioneta_id = ? AND resuelto = 0
        ''', (asignacion['camioneta_id'],)).fetchall()
        elementos_bloqueados = [dict(b) for b in bloqueados]
    
    conexion.close()
    
    return render_template('tecnico.html', 
                         nombre=session['nombre'],
                         asignacion=asignacion,
                         control_retiro_activo=control_retiro_activo,
                         control_devolucion_activo=control_devolucion_activo,
                         retiro_completado=retiro_completado,
                         devolucion_completada=devolucion_completada,
                         elementos_bloqueados=elementos_bloqueados,
                         fecha_actual=fecha_actual,
                         jornada_actual=jornada_actual)

@app.route('/iniciar-control', methods=['POST'])
def iniciar_control():
    """Inicia un nuevo control para el técnico"""
    if 'usuario_id' not in session or session.get('rol') != 'tecnico':
        return redirect(url_for('login'))
    
    asignacion_id = request.form.get('asignacion_id')
    jornada = request.form.get('jornada')
    tipo_control = request.form.get('tipo_control')
    
    if not all([asignacion_id, jornada, tipo_control]):
        return redirect(url_for('tecnico', error='Datos incompletos'))
    
    fecha_actual = datetime.now().strftime('%Y-%m-%d')
    fecha_hora = datetime.now().isoformat()
    
    conexion = get_db()
    
    # ==========================================
    # VALIDACIONES DEL FLUJO
    # ==========================================
    
    # 1. Verificar si ya hay un control activo del mismo tipo
    existe = conexion.execute('''
        SELECT id FROM controles_tecnicos 
        WHERE asignacion_id = ? AND fecha = ? AND jornada = ? 
        AND tipo_control = ? AND finalizado = 0
    ''', (asignacion_id, fecha_actual, jornada, tipo_control)).fetchone()
    
    if existe:
        conexion.close()
        return redirect(url_for('tecnico', error=f'Ya hay un control de {tipo_control} activo'))
    
    # 2. Si es DEVOLUCION, verificar que el RETIRO esté completado
    if tipo_control == 'DEVOLUCION':
        retiro_completado = conexion.execute('''
            SELECT id FROM controles_tecnicos 
            WHERE asignacion_id = ? AND fecha = ? AND jornada = ? 
            AND tipo_control = 'RETIRO' AND finalizado = 1
        ''', (asignacion_id, fecha_actual, jornada)).fetchone()
        
        if not retiro_completado:
            conexion.close()
            return redirect(url_for('tecnico', 
                error='⚠️ No puedes iniciar una devolución sin haber completado el retiro primero.'))
    
    # 3. Si es RETIRO, verificar que no haya una devolución ya completada (caso borde)
    if tipo_control == 'RETIRO':
        devolucion_completada = conexion.execute('''
            SELECT id FROM controles_tecnicos 
            WHERE asignacion_id = ? AND fecha = ? AND jornada = ? 
            AND tipo_control = 'DEVOLUCION' AND finalizado = 1
        ''', (asignacion_id, fecha_actual, jornada)).fetchone()
        
        if devolucion_completada:
            conexion.close()
            return redirect(url_for('tecnico', 
                error='⚠️ La devolución ya fue completada. No puedes iniciar un nuevo retiro.'))
    
    # Crear nuevo control
    cursor = conexion.cursor()
    cursor.execute('''
        INSERT INTO controles_tecnicos 
        (asignacion_id, fecha, jornada, tipo_control, finalizado, fecha_hora_inicio)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (asignacion_id, fecha_actual, jornada, tipo_control, 0, fecha_hora))
    
    control_id = cursor.lastrowid
    conexion.commit()
    conexion.close()
    
    return redirect(url_for('realizar_control', control_id=control_id))

@app.route('/realizar-control/<int:control_id>')
def realizar_control(control_id):
    """Muestra el formulario para realizar el control"""
    if 'usuario_id' not in session or session.get('rol') != 'tecnico':
        return redirect(url_for('login'))
    
    conexion = get_db()
    
    # Obtener el control
    control = conexion.execute('''
        SELECT ct.*, a.camioneta_id, c.patente, u.nombre as tecnico_nombre
        FROM controles_tecnicos ct
        JOIN asignaciones a ON ct.asignacion_id = a.id
        JOIN camionetas c ON a.camioneta_id = c.id
        JOIN usuarios u ON a.tecnico_id = u.id
        WHERE ct.id = ? AND ct.finalizado = 0
    ''', (control_id,)).fetchone()
    
    if not control:
        conexion.close()
        return redirect(url_for('tecnico', error='Control no encontrado o ya finalizado'))
    
    # Obtener elementos ya registrados en este control
    items_registrados = conexion.execute('''
        SELECT elemento, estado FROM items_control_tecnico 
        WHERE control_tecnico_id = ?
    ''', (control_id,)).fetchall()
    
    items_registrados_lista = [item['elemento'] for item in items_registrados]
    
    # Obtener elementos bloqueados
    elementos_bloqueados = conexion.execute('''
        SELECT elemento FROM elementos_bloqueados 
        WHERE camioneta_id = ? AND resuelto = 0
    ''', (control['camioneta_id'],)).fetchall()
    
    elementos_bloqueados_lista = [eb['elemento'] for eb in elementos_bloqueados]
    
    # Preparar los elementos para mostrar
    elementos_por_categoria = {
        'CAMIONETA': [],
        'HERRAMIENTA': [],
        'CAJA': []
    }
    
    for categoria, lista in TODOS_ELEMENTOS.items():
        for elemento in lista:
            estado = 'PENDIENTE'
            if elemento in items_registrados_lista:
                for item in items_registrados:
                    if item['elemento'] == elemento:
                        # ✅ MANEJAR None - Si es None, mostrar 'PENDIENTE'
                        estado = item['estado'] if item['estado'] is not None else 'PENDIENTE'
                        break
            elif elemento in elementos_bloqueados_lista:
                estado = 'BLOQUEADO'
            
            elementos_por_categoria[categoria].append({
                'nombre': elemento,
                'estado': estado,
                'bloqueado': elemento in elementos_bloqueados_lista,
                'registrado': elemento in items_registrados_lista
            })
    
    conexion.close()
    
    return render_template('realizar_control.html',
                         control=control,
                         elementos_por_categoria=elementos_por_categoria,
                         elementos_bloqueados=elementos_bloqueados_lista)

@app.route('/finalizar-control/<int:control_id>', methods=['POST'])
def finalizar_control(control_id):
    """Finaliza un control y verifica elementos pendientes"""
    if 'usuario_id' not in session or session.get('rol') != 'tecnico':
        return redirect(url_for('login'))
    
    conexion = get_db()
    
    try:
        # Verificar si el control ya fue finalizado
        control = conexion.execute('''
            SELECT finalizado FROM controles_tecnicos WHERE id = ?
        ''', (control_id,)).fetchone()
        
        if not control:
            conexion.close()
            return redirect(url_for('tecnico', error='Control no encontrado'))
        
        if control['finalizado'] == 1:
            conexion.close()
            return redirect(url_for('tecnico', error='Este control ya fue finalizado'))
        
        # Finalizar el control
        fecha_hora = datetime.now().isoformat()
        conexion.execute('''
            UPDATE controles_tecnicos 
            SET finalizado = 1, fecha_hora_fin = ?
            WHERE id = ?
        ''', (fecha_hora, control_id))
        
        conexion.commit()
        conexion.close()
        
        return redirect(url_for('tecnico', mensaje='✅ Control finalizado correctamente'))
        
    except Exception as e:
        conexion.rollback()
        conexion.close()
        print(f"❌ Error al finalizar: {e}")
        return redirect(url_for('tecnico', error=f'Error al finalizar: {str(e)}'))
    
    return redirect(url_for('tecnico', mensaje='✅ Control finalizado correctamente'))
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
            WHERE r.fecha_hora >= date('now', '-30 days')
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
                resumen_flota[patente]['ultimo_registro'] = r['fecha_hora'][:16].replace('T', ' ') if r['fecha_hora'] else 'Sin registros'
                
                resumen_flota[patente]['historial'].append({
                    'fecha': r['fecha_hora'][:16].replace('T', ' ') if r['fecha_hora'] else '-',
                    'elemento': r['elemento'],
                    'estado': r['estado'],
                    'descripcion': r['descripcion'] or '-',
                    'tecnico': r['tecnico_nombre'] or '-',
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


@app.route('/historial-camioneta/<string:patente>')
def historial_camioneta(patente):
    """Vista detallada del historial de una camioneta"""
    if 'usuario_id' not in session or session.get('rol') not in ['admin', 'jefe']:
        return redirect(url_for('login'))
    
    conexion = get_db()
    
    camioneta = conexion.execute('''
        SELECT id, patente FROM camionetas WHERE patente = ? AND activa = 1
    ''', (patente,)).fetchone()
    
    if not camioneta:
        conexion.close()
        return redirect(url_for('admin', error='Camioneta no encontrada'))
    
    # 1. Controles agrupados por fecha
    controles = conexion.execute('''
        SELECT DISTINCT 
            ct.fecha,
            ct.jornada,
            ct.tipo_control,
            ct.fecha_hora_inicio,
            ct.fecha_hora_fin,
            ct.finalizado,
            u.nombre as tecnico_nombre
        FROM controles_tecnicos ct
        JOIN asignaciones a ON ct.asignacion_id = a.id
        JOIN usuarios u ON a.tecnico_id = u.id
        WHERE a.camioneta_id = ?
        ORDER BY ct.fecha DESC, ct.fecha_hora_inicio DESC
    ''', (camioneta['id'],)).fetchall()
    
    historial_detallado = []
    for control in controles:
        elementos = conexion.execute('''
            SELECT 
                ic.elemento, 
                ic.categoria, 
                ic.estado, 
                ic.observacion, 
                ic.fecha_hora,
                r.entregado_por,
                r.recibido_por,
                r.fecha_entrega
            FROM items_control_tecnico ic
            LEFT JOIN reportes r ON r.elemento = ic.elemento 
                AND r.control_id = (
                    SELECT id FROM controles 
                    WHERE asignacion_id = (
                        SELECT id FROM asignaciones 
                        WHERE camioneta_id = ? AND fecha = ? AND jornada = ?
                    )
                )
            WHERE ic.control_tecnico_id IN (
                SELECT id FROM controles_tecnicos 
                WHERE asignacion_id IN (
                    SELECT id FROM asignaciones WHERE camioneta_id = ?
                )
                AND fecha = ? AND jornada = ? AND tipo_control = ?
            )
        ''', (camioneta['id'], control['fecha'], control['jornada'],
              camioneta['id'], control['fecha'], control['jornada'], control['tipo_control'])).fetchall()
        
        historial_detallado.append({
            'control': dict(control),
            'elementos': [dict(e) for e in elementos]
        })
    
    # 2. Historial por elemento con técnico y fecha
    historial_elementos = conexion.execute('''
    SELECT 
        r.elemento,
        r.estado,
        r.descripcion,
        r.fecha_hora,
        r.fecha_resolucion,
        r.resuelto_por,
        r.comentario_resolucion,
        r.entregado_por,
        r.recibido_por,
        r.fecha_entrega,
        c.patente,
        u.nombre as tecnico_nombre,
        r.tipo as tipo_control
    FROM reportes r
    JOIN controles co ON r.control_id = co.id
    JOIN asignaciones a ON co.asignacion_id = a.id
    JOIN camionetas c ON a.camioneta_id = c.id
    JOIN usuarios u ON a.tecnico_id = u.id
    WHERE c.patente = ?
    ORDER BY r.elemento, r.fecha_hora DESC
''', (patente,)).fetchall()
    
    historial_por_elemento = {}
    for item in historial_elementos:
        elemento = item['elemento']
        if elemento not in historial_por_elemento:
            historial_por_elemento[elemento] = []
        historial_por_elemento[elemento].append(dict(item))
    
    conexion.close()
    
    return render_template('historial_camioneta.html',
                         patente=patente,
                         historial_detallado=historial_detallado,
                         historial_por_elemento=historial_por_elemento)

@app.route('/iniciar-retiro')
def iniciar_retiro():
    if 'usuario_id' not in session or session.get('rol') != 'tecnico':
        return redirect(url_for('login'))
    return "Aquí comenzará el control de RETIRO."

@app.route('/resolver-reporte/<int:reporte_id>', methods=['POST'])
def resolver_reporte(reporte_id):
    """Cambia el estado de un reporte a 'RESUELTO' y desbloquea el elemento"""
    if 'usuario_id' not in session or session.get('rol') != 'admin':
        return jsonify({'success': False, 'error': 'No autorizado'}), 401
    
    nombre_admin = session.get('nombre', 'Administrador')
    
    # Obtener el comentario del cuerpo de la solicitud
    try:
        data = request.get_json()
        comentario = data.get('comentario', '').strip() if data else ''
    except Exception as e:
        comentario = ''
        print(f"⚠️ Error al leer JSON: {e}")
    
    # DEBUG - Ver en consola del servidor
    print(f"📝 Resolviendo reporte ID: {reporte_id}")
    print(f"💬 Comentario recibido: '{comentario}'")
    print(f"👤 Admin: {nombre_admin}")
    
    conexion = get_db()
    try:
        ahora = datetime.now().strftime('%Y-%m-%d %H:%M')
        ahora_iso = datetime.now().isoformat()
        
        # 1. Obtener el elemento y la camioneta del reporte
        reporte = conexion.execute('''
            SELECT r.id, r.elemento, r.control_id, r.tipo, 
                   a.camioneta_id
            FROM reportes r
            JOIN controles co ON r.control_id = co.id
            JOIN asignaciones a ON co.asignacion_id = a.id
            WHERE r.id = ?
        ''', (reporte_id,)).fetchone()
        
        if not reporte:
            return jsonify({'success': False, 'error': 'Reporte no encontrado'}), 404
        
        # 2. Actualizar el reporte con el comentario
        cursor = conexion.cursor()
        cursor.execute('''
            UPDATE reportes 
            SET estado = 'RESUELTO', 
                fecha_resolucion = ?, 
                resuelto_por = ?, 
                comentario_resolucion = ?
            WHERE id = ?
        ''', (ahora, nombre_admin, comentario, reporte_id))
        
        print(f"✅ Reporte {reporte_id} actualizado")
        
        # 3. Desbloquear el elemento en elementos_bloqueados
        elemento_bloqueado = cursor.execute('''
            SELECT id FROM elementos_bloqueados 
            WHERE elemento = ? AND camioneta_id = ? AND resuelto = 0
        ''', (reporte['elemento'], reporte['camioneta_id'])).fetchone()
        
        if elemento_bloqueado:
            cursor.execute('''
                UPDATE elementos_bloqueados 
                SET resuelto = 1, fecha_resolucion = ?
                WHERE id = ?
            ''', (ahora_iso, elemento_bloqueado['id']))
            print(f"✅ Elemento '{reporte['elemento']}' desbloqueado")
        else:
            print(f"⚠️ No se encontró elemento bloqueado para '{reporte['elemento']}'")
        
        conexion.commit()
        
        # Verificar que se guardó el comentario
        verificar = cursor.execute('''
            SELECT comentario_resolucion FROM reportes WHERE id = ?
        ''', (reporte_id,)).fetchone()
        print(f"🔍 Comentario guardado: '{verificar[0] if verificar and verificar[0] else 'VACÍO'}'")
        
        return jsonify({
            'success': True, 
            'fecha_resolucion': ahora,
            'mensaje': f'✅ Reporte resuelto y elemento "{reporte["elemento"]}" desbloqueado'
        })
        
    except Exception as e:
        conexion.rollback()
        print(f"❌ Error al resolver reporte: {e}")
        import traceback
        traceback.print_exc()
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