from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
import os
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from werkzeug.utils import secure_filename
from PIL import Image as PILImage

app = Flask(__name__)
app.secret_key = 'clave_secreta_para_desarrollo'

# Configuración de la base de datos
BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "database.db"

# Configuración de la carpeta de remitos
REMITOS_DIR = BASE_DIR / "remitos"

# Configuración para subida de firmas
UPLOAD_FOLDER = BASE_DIR / "static" / "firmas"
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# Crear carpetas necesarias
if not REMITOS_DIR.exists():
    REMITOS_DIR.mkdir()
if not UPLOAD_FOLDER.exists():
    UPLOAD_FOLDER.mkdir(parents=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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

TODOS_ELEMENTOS = {
    'CAMIONETA': EXPECTED_CAMIONETA,
    'HERRAMIENTA': EXPECTED_HERRAMIENTAS,
    'CAJA': EXPECTED_CAJA
}

# ============================================
# FUNCIONES AUXILIARES PARA REMITOS CON FIRMA
# ============================================

def crear_carpeta_remitos(patente, fecha):
    """Crea la estructura de carpetas para remitos"""
    if not REMITOS_DIR.exists():
        REMITOS_DIR.mkdir()
    
    carpeta_patente = REMITOS_DIR / patente
    if not carpeta_patente.exists():
        carpeta_patente.mkdir()
    
    year_month = fecha[:7]
    carpeta_fecha = carpeta_patente / year_month
    if not carpeta_fecha.exists():
        carpeta_fecha.mkdir()
    
    return carpeta_fecha





def generar_pdf_remito(reporte, admin_nombre, admin_firma, fecha_hora, ruta_pdf):
    """Genera el PDF del remito usando ReportLab con firma"""
    doc = SimpleDocTemplate(str(ruta_pdf), pagesize=A4,
                           rightMargin=1.5*cm, leftMargin=1.5*cm,
                           topMargin=1.5*cm, bottomMargin=1.5*cm)
    
    styles = getSampleStyleSheet()
    
    titulo_style = ParagraphStyle(
        'Titulo',
        parent=styles['Heading1'],
        alignment=TA_CENTER,
        fontSize=18,
        textColor=colors.HexColor('#1a1a2e'),
        spaceAfter=10
    )
    
    subtitulo_style = ParagraphStyle(
        'Subtitulo',
        parent=styles['Heading2'],
        alignment=TA_CENTER,
        fontSize=14,
        textColor=colors.HexColor('#555'),
        spaceAfter=20
    )
    
    campo_label_style = ParagraphStyle(
        'CampoLabel',
        parent=styles['Normal'],
        fontSize=11,
        textColor=colors.HexColor('#333'),
        fontName='Helvetica-Bold',
        alignment=TA_LEFT
    )
    
    campo_valor_style = ParagraphStyle(
        'CampoValor',
        parent=styles['Normal'],
        fontSize=11,
        textColor=colors.HexColor('#555'),
        alignment=TA_LEFT
    )
    
    firma_style = ParagraphStyle(
        'Firma',
        parent=styles['Normal'],
        fontSize=11,
        alignment=TA_CENTER,
        spaceAfter=30
    )
    
    elements = []
    
    elements.append(Paragraph("CONTROL DE CAMIONETAS", titulo_style))
    elements.append(Paragraph("REMITO DE ENTREGA DE MATERIAL", subtitulo_style))
    elements.append(Spacer(1, 0.5*cm))
    
    data = [
        ['N° REMITO:', f"REM-{fecha_hora.strftime('%Y%m%d')}-{reporte['id']}"],
        ['FECHA:', fecha_hora.strftime('%d/%m/%Y %H:%M')],
        ['PATENTE:', reporte['patente']],
        ['ZONA:', reporte['zona'] or 'No especificada'],
        ['TÉCNICO RESPONSABLE:', reporte['tecnico_nombre'] or 'No asignado'],
        ['MATERIAL:', reporte['elemento']],
        ['ESTADO:', 'FALTANTE'],
        ['DESCRIPCIÓN:', reporte['descripcion'] or 'Sin descripción'],
    ]
    
    tabla_data = []
    for label, value in data:
        tabla_data.append([
            Paragraph(label, campo_label_style),
            Paragraph(str(value), campo_valor_style)
        ])
    
    tabla = Table(tabla_data, colWidths=[4*cm, 10*cm])
    tabla.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e0e0e0')),
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f5f5f5')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    
    elements.append(tabla)
    elements.append(Spacer(1, 0.8*cm))
    
    # ==========================================
    # SECCIÓN DE FIRMA
    # ==========================================
    elements.append(Paragraph("FIRMA DEL ADMINISTRADOR", firma_style))
    elements.append(Spacer(1, 0.2*cm))
    
    # Si hay firma cargada, mostrarla
    if admin_firma and Path(admin_firma).exists():
        try:
            img_path = Path(admin_firma)
            if img_path.exists():
                with PILImage.open(img_path) as img:
                    img_width, img_height = img.size
                    target_width = 4 * cm
                    target_height = 2 * cm
                    scale = min(target_width / img_width, target_height / img_height)
                    final_width = img_width * scale
                    final_height = img_height * scale
                
                img = Image(str(img_path), width=final_width, height=final_height)
                img.hAlign = 'CENTER'
                elements.append(img)
                elements.append(Spacer(1, 0.2*cm))
                elements.append(Paragraph(admin_nombre, ParagraphStyle(
                    'FirmaNombreImg',
                    parent=styles['Normal'],
                    alignment=TA_CENTER,
                    fontSize=10,
                    textColor=colors.HexColor('#666')
                )))
            else:
                raise Exception("Archivo no encontrado")
        except Exception as e:
            print(f"Error al cargar firma: {e}")
            elements.append(Paragraph(admin_nombre, ParagraphStyle(
                'FirmaNombreFallback',
                parent=styles['Normal'],
                alignment=TA_CENTER,
                fontSize=12,
                fontName='Helvetica-Bold',
                textColor=colors.HexColor('#333')
            )))
            elements.append(Paragraph("_________________________", ParagraphStyle(
                'FirmaLineaFallback',
                parent=styles['Normal'],
                alignment=TA_CENTER,
                fontSize=11
            )))
    else:
        elements.append(Paragraph(admin_nombre, ParagraphStyle(
            'FirmaNombre',
            parent=styles['Normal'],
            alignment=TA_CENTER,
            fontSize=12,
            fontName='Helvetica-Bold',
            textColor=colors.HexColor('#333'),
            spaceAfter=5
        )))
        elements.append(Paragraph("_________________________", ParagraphStyle(
            'FirmaLinea',
            parent=styles['Normal'],
            alignment=TA_CENTER,
            fontSize=11,
            spaceAfter=5
        )))
    
    elements.append(Paragraph(f"{admin_nombre} (Administrador)", ParagraphStyle(
        'FirmaCargo',
        parent=styles['Normal'],
        alignment=TA_CENTER,
        fontSize=9,
        textColor=colors.HexColor('#666'),
        spaceAfter=20
    )))
    
    # Pie de página
    pie_style = ParagraphStyle(
        'Pie',
        parent=styles['Normal'],
        alignment=TA_CENTER,
        fontSize=8,
        textColor=colors.HexColor('#999')
    )
    elements.append(Paragraph("Documento generado por el Sistema de Control de Camionetas", pie_style))
    elements.append(Paragraph(f"Remito generado el {fecha_hora.strftime('%d/%m/%Y a las %H:%M')}", pie_style))
    
    doc.build(elements)
    return ruta_pdf


# ============================================
# FUNCIONES DE NOTIFICACIONES Y SEGUIMIENTO
# ============================================

def crear_notificacion(tipo, mensaje, patente=None, elemento=None, destinatario_rol='todos', enlace=None):
    """Crea una notificación en el sistema"""
    conexion = get_db()
    try:
        fecha = datetime.now().isoformat()
        conexion.execute('''
            INSERT INTO notificaciones (tipo, mensaje, patente, elemento, fecha, destinatario_rol, enlace)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (tipo, mensaje, patente, elemento, fecha, destinatario_rol, enlace))
        conexion.commit()
        return True
    except Exception as e:
        print(f"Error al crear notificación: {e}")
        return False
    finally:
        conexion.close()

def crear_seguimiento_remito(reporte_id, patente, elemento, ruta_pdf):
    """Crea un seguimiento para un remito generado"""
    conexion = get_db()
    try:
        fecha = datetime.now().isoformat()
        conexion.execute('''
            INSERT INTO seguimiento_remitos 
            (reporte_id, patente, elemento, fecha_generacion, estado, ruta_pdf)
            VALUES (?, ?, ?, ?, 'PENDIENTE_FIRMA', ?)
        ''', (reporte_id, patente, elemento, fecha, ruta_pdf))
        conexion.commit()
        return True
    except Exception as e:
        print(f"Error al crear seguimiento: {e}")
        return False
    finally:
        conexion.close()

def firmar_remito(reporte_id, tecnico_nombre):
    """Marca un remito como firmado por el técnico"""
    conexion = get_db()
    try:
        fecha = datetime.now().isoformat()
        conexion.execute('''
            UPDATE reportes 
            SET remito_firmado = 1, firma_tecnico = ?, fecha_firma = ?
            WHERE id = ?
        ''', (tecnico_nombre, fecha, reporte_id))
        conexion.commit()
        return True
    except Exception as e:
        print(f"Error al firmar remito: {e}")
        return False
    finally:
        conexion.close()

def revisar_remito(reporte_id, admin_nombre):
    """Marca un remito como revisado por el administrador"""
    conexion = get_db()
    try:
        fecha = datetime.now().isoformat()
        conexion.execute('''
            UPDATE reportes 
            SET remito_revisado = 1
            WHERE id = ?
        ''', (reporte_id,))
        conexion.commit()
        return True
    except Exception as e:
        print(f"Error al revisar remito: {e}")
        return False
    finally:
        conexion.close()

def obtener_notificaciones(rol=None):
    """Obtiene notificaciones para un rol específico"""
    conexion = get_db()
    try:
        if rol:
            query = '''
                SELECT * FROM notificaciones 
                WHERE (destinatario_rol = ? OR destinatario_rol = 'todos') 
                AND leido = 0
                ORDER BY fecha DESC
            '''
            notificaciones = conexion.execute(query, (rol,)).fetchall()
        else:
            query = '''
                SELECT * FROM notificaciones 
                WHERE leido = 0
                ORDER BY fecha DESC
            '''
            notificaciones = conexion.execute(query).fetchall()
        return [dict(n) for n in notificaciones]
    finally:
        conexion.close()

def marcar_notificacion_leida(notificacion_id):
    """Marca una notificación como leída"""
    conexion = get_db()
    try:
        fecha = datetime.now().isoformat()
        conexion.execute('''
            UPDATE notificaciones 
            SET leido = 1, fecha_lectura = ?
            WHERE id = ?
        ''', (fecha, notificacion_id))
        conexion.commit()
        return True
    except Exception as e:
        print(f"Error al marcar notificación: {e}")
        return False
    finally:
        conexion.close()



# ============================================
# FILTROS PARA JINJA2
# ============================================

@app.template_filter('timestamp_to_datetime')
def timestamp_to_datetime(timestamp):
    if timestamp:
        return datetime.fromtimestamp(timestamp).strftime('%d/%m/%Y %H:%M')
    return '-'

# ============================================
# FUNCIONES DE BASE DE DATOS
# ============================================

@app.before_request
def limpiar_redirecciones():
    if 'usuario_id' in session:
        rol = session.get('rol')
        if rol == 'admin' and request.path == '/tecnico':
            return redirect(url_for('admin'))
        if rol == 'jefe' and request.path in ['/tecnico', '/admin']:
            return redirect(url_for('jefe'))
        if rol == 'tecnico' and request.path in ['/admin', '/jefe']:
            return redirect(url_for('tecnico'))

def conectar_db():
    return sqlite3.connect(str(DATABASE))

def get_db():
    conexion = conectar_db()
    conexion.row_factory = sqlite3.Row
    return conexion

def crear_base_de_datos():
    conexion = conectar_db()
    cursor = conexion.cursor()


    # En crear_base_de_datos(), agregar estas tablas:

# Tabla para el seguimiento de remitos
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS seguimiento_remitos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reporte_id INTEGER NOT NULL,
        patente TEXT NOT NULL,
        elemento TEXT NOT NULL,
        fecha_generacion TEXT NOT NULL,
        fecha_firma TEXT,
        fecha_revision TEXT,
        estado TEXT DEFAULT 'PENDIENTE_FIRMA',  -- 'PENDIENTE_FIRMA', 'FIRMADO', 'REVISADO', 'CERRADO'
        tecnico_firma TEXT,
        admin_revision TEXT,
        observaciones TEXT,
        ruta_pdf TEXT,
        FOREIGN KEY (reporte_id) REFERENCES reportes(id)
    )
''')

# Tabla para notificaciones del sistema
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS notificaciones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tipo TEXT NOT NULL,  -- 'REMITO_PENDIENTE', 'REMITO_FIRMADO', 'REMITO_REVISADO'
        mensaje TEXT NOT NULL,
        patente TEXT,
        elemento TEXT,
        fecha TEXT NOT NULL,
        leido INTEGER DEFAULT 0,
        destinatario_rol TEXT,  -- 'admin', 'tecnico', 'todos'
        enlace TEXT,
        fecha_lectura TEXT
    )
''')



    
    # Tabla Usuarios (con columna firma)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            usuario TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            rol TEXT NOT NULL,
            activo INTEGER DEFAULT 1,
            firma TEXT
        )
    ''')
    
    # Tabla estadisticas_tecnicos
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS estadisticas_tecnicos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tecnico_id INTEGER NOT NULL,
            elemento TEXT NOT NULL,
            categoria TEXT NOT NULL,
            tipo_reporte TEXT NOT NULL,
            fecha_reporte TEXT NOT NULL,
            fecha_resolucion TEXT,
            resuelto INTEGER DEFAULT 0,
            FOREIGN KEY (tecnico_id) REFERENCES usuarios(id)
        )
    ''')
    
    # Tabla camionetas
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS camionetas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patente TEXT UNIQUE NOT NULL,
            activa INTEGER DEFAULT 1
        )
    ''')
    
    # Tabla controles_tecnicos
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS controles_tecnicos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asignacion_id INTEGER NOT NULL,
            fecha TEXT NOT NULL,
            jornada TEXT NOT NULL,
            tipo_control TEXT NOT NULL,
            finalizado INTEGER DEFAULT 0,
            fecha_hora_inicio TEXT NOT NULL,
            fecha_hora_fin TEXT,
            FOREIGN KEY (asignacion_id) REFERENCES asignaciones(id)
        )
    ''')
    
    # Tabla items_control_tecnico
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
    
    # Tabla elementos_bloqueados
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS elementos_bloqueados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            elemento TEXT NOT NULL,
            camioneta_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            fecha_bloqueo TEXT NOT NULL,
            motivo TEXT,
            resuelto INTEGER DEFAULT 0,
            fecha_resolucion TEXT,
            FOREIGN KEY (camioneta_id) REFERENCES camionetas(id)
        )
    ''')
    
    # Tabla asignaciones
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
    
    # Tabla Controles
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
    
    # Tabla control_detalles
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
    # En crear_base_de_datos(), modificar la tabla reportes
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
        entregado_por TEXT,
        recibido_por TEXT,
        fecha_entrega TEXT,
        ruta_remito TEXT,
        remito_firmado INTEGER DEFAULT 0,
        remito_revisado INTEGER DEFAULT 0,
        firma_tecnico TEXT,
        fecha_firma TEXT,
        FOREIGN KEY (control_id) REFERENCES controles(id)
    )
''')
    
    # Tabla Fotos
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
    cursor = conexion.cursor()
    
    cursor.execute('SELECT COUNT(*) as count FROM usuarios')
    count = cursor.fetchone()[0]
    
    if count == 0:
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

# ============================================
# RUTAS DE FIRMA
# ============================================

@app.route('/admin/firma', methods=['GET', 'POST'])
def admin_firma():
    if 'usuario_id' not in session or session.get('rol') != 'admin':
        return redirect(url_for('login'))
    
    usuario_id = session['usuario_id']
    mensaje = None
    error = None
    
    conexion = get_db()
    usuario = conexion.execute('SELECT id, nombre, usuario, firma FROM usuarios WHERE id = ?', (usuario_id,)).fetchone()
    
    if request.method == 'POST':
        if 'firma' not in request.files:
            error = 'No se seleccionó ningún archivo'
        else:
            archivo = request.files['firma']
            if archivo.filename == '':
                error = 'No se seleccionó ningún archivo'
            elif not allowed_file(archivo.filename):
                error = 'Formato no permitido. Usá PNG, JPG o GIF.'
            else:
                try:
                    filename = secure_filename(f"firma_{usuario_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.png")
                    ruta_completa = UPLOAD_FOLDER / filename
                    archivo.save(str(ruta_completa))
                    
                    conexion.execute('UPDATE usuarios SET firma = ? WHERE id = ?', (str(ruta_completa), usuario_id))
                    conexion.commit()
                    mensaje = '✅ Firma cargada exitosamente!'
                    usuario = conexion.execute('SELECT id, nombre, usuario, firma FROM usuarios WHERE id = ?', (usuario_id,)).fetchone()
                    
                except Exception as e:
                    error = f'Error al guardar la firma: {str(e)}'
    
    conexion.close()
    return render_template('admin_firma.html', usuario=usuario, mensaje=mensaje, error=error)

@app.route('/admin/firma/eliminar', methods=['POST'])
def eliminar_firma():
    if 'usuario_id' not in session or session.get('rol') != 'admin':
        return jsonify({'success': False, 'error': 'No autorizado'}), 401
    
    usuario_id = session['usuario_id']
    
    conexion = get_db()
    try:
        usuario = conexion.execute('SELECT firma FROM usuarios WHERE id = ?', (usuario_id,)).fetchone()
        
        if usuario and usuario['firma']:
            ruta_firma = Path(usuario['firma'])
            if ruta_firma.exists():
                ruta_firma.unlink()
            
            conexion.execute('UPDATE usuarios SET firma = NULL WHERE id = ?', (usuario_id,))
            conexion.commit()
            return jsonify({'success': True, 'mensaje': 'Firma eliminada correctamente'})
        
        return jsonify({'success': False, 'error': 'No hay firma para eliminar'})
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conexion.close()

# ============================================
# RUTAS DE ESTADÍSTICAS
# ============================================

@app.route('/jefe/estadisticas')
def jefe_estadisticas():
    if 'usuario_id' not in session or session.get('rol') != 'jefe':
        return redirect(url_for('login'))
    
    conexion = get_db()
    
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

# ============================================
# RUTAS DE LOGIN
# ============================================

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

# ============================================
# RUTAS DE ADMINISTRADOR
# ============================================

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
    if 'usuario_id' not in session or session.get('rol') != 'admin':
        return redirect(url_for('login'))
    
    fecha = request.form.get('fecha')
    jornada = request.form.get('jornada')
    
    if not fecha or not jornada:
        return redirect(url_for('admin', error='Fecha y jornada son requeridas'))
    
    conexion = get_db()
    
    try:
        for camioneta_id in request.form.getlist('camioneta_ids'):
            camioneta_id = int(camioneta_id)
            tecnico_id = request.form.get(f'tecnico_{camioneta_id}') or None
            tecnico2_id = request.form.get(f'tecnico2_{camioneta_id}') or None
            zona = request.form.get(f'zona_{camioneta_id}') or ''
            
            existe_asignacion = conexion.execute('''
                SELECT id FROM asignaciones 
                WHERE camioneta_id = ? AND fecha = ? AND jornada = ?
            ''', (camioneta_id, fecha, jornada)).fetchone()
            
            if existe_asignacion:
                conexion.execute('''
                    UPDATE asignaciones 
                    SET tecnico_id = ?, tecnico2_id = ?, zona = ?, estado = 'ASIGNADA'
                    WHERE camioneta_id = ? AND fecha = ? AND jornada = ?
                ''', (tecnico_id, tecnico2_id, zona, camioneta_id, fecha, jornada))
            else:
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
    if 'usuario_id' not in session or session.get('rol') != 'admin':
        return redirect(url_for('login'))
    
    jornada = request.args.get('jornada', 'mañana')
    fecha_inicio = request.args.get('fecha_inicio', datetime.now().strftime('%Y-%m-%d'))
    
    dias_semana = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
    
    fecha_dt = datetime.strptime(fecha_inicio, '%Y-%m-%d')
    inicio_semana = fecha_dt - timedelta(days=fecha_dt.weekday())
    fechas_semana = [inicio_semana + timedelta(days=i) for i in range(7)]
    
    conexion = get_db()
    
    try:
        tecnicos = obtener_tecnicos()
        camionetas = obtener_camionetas()
        
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
    if 'usuario_id' not in session or session.get('rol') != 'admin':
        return redirect(url_for('login'))
    
    fechas = request.form.getlist('fechas[]')
    jornada = request.form.get('jornada', 'mañana')
    
    conexion = get_db()
    
    try:
        for camioneta_id in request.form.getlist('camioneta_ids'):
            camioneta_id = int(camioneta_id)
            
            for fecha in fechas:
                tecnico_id = request.form.get(f'tecnico_{camioneta_id}_{fecha}') or None
                tecnico2_id = request.form.get(f'tecnico2_{camioneta_id}_{fecha}') or None
                zona = request.form.get(f'zona_{camioneta_id}_{fecha}') or ''
                
                existe_asignacion = conexion.execute('''
                    SELECT id FROM asignaciones 
                    WHERE camioneta_id = ? AND fecha = ? AND jornada = ?
                ''', (camioneta_id, fecha, jornada)).fetchone()
                
                if existe_asignacion:
                    conexion.execute('''
                        UPDATE asignaciones 
                        SET tecnico_id = ?, tecnico2_id = ?, zona = ?, estado = 'ASIGNADA'
                        WHERE camioneta_id = ? AND fecha = ? AND jornada = ?
                    ''', (tecnico_id, tecnico2_id, zona, camioneta_id, fecha, jornada))
                else:
                    conexion.execute('''
                        INSERT INTO asignaciones (camioneta_id, tecnico_id, tecnico2_id, fecha, jornada, estado, zona)
                        VALUES (?, ?, ?, ?, ?, 'ASIGNADA', ?)
                    ''', (camioneta_id, tecnico_id, tecnico2_id, fecha, jornada, zona))
        
        conexion.commit()
        mensaje = '✅ Asignaciones de la semana guardadas correctamente'
        
    except Exception as e:
        conexion.rollback()
        return redirect(url_for('asignacion_semanal', error=f'Error al guardar: {str(e)}'))
    finally:
        conexion.close()
    
    return redirect(url_for('asignacion_semanal', mensaje=mensaje))

# ============================================
# RUTAS DE TÉCNICO
# ============================================

@app.route('/tecnico')
def tecnico():
    if 'usuario_id' not in session or session.get('rol') != 'tecnico':
        return redirect(url_for('login'))
    
    usuario_id = session['usuario_id']
    fecha_actual = datetime.now().strftime('%Y-%m-%d')
    hora_actual = datetime.now().hour
    
    if 6 <= hora_actual < 14:
        jornada_actual = 'mañana'
    elif 14 <= hora_actual < 22:
        jornada_actual = 'tarde'
    else:
        jornada_actual = 'mañana'
    
    conexion = get_db()
    
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
    
    control_retiro_activo = None
    control_devolucion_activo = None
    retiro_completado = False
    devolucion_completada = False
    
    if asignacion:
        control_retiro_activo = conexion.execute('''
            SELECT * FROM controles_tecnicos 
            WHERE asignacion_id = ? 
            AND fecha = ? 
            AND jornada = ? 
            AND tipo_control = 'RETIRO'
            AND finalizado = 0
        ''', (asignacion['id'], fecha_actual, jornada_actual)).fetchone()
        
        control_devolucion_activo = conexion.execute('''
            SELECT * FROM controles_tecnicos 
            WHERE asignacion_id = ? 
            AND fecha = ? 
            AND jornada = ? 
            AND tipo_control = 'DEVOLUCION'
            AND finalizado = 0
        ''', (asignacion['id'], fecha_actual, jornada_actual)).fetchone()
        
        retiro_finalizado = conexion.execute('''
            SELECT id FROM controles_tecnicos 
            WHERE asignacion_id = ? 
            AND fecha = ? 
            AND jornada = ? 
            AND tipo_control = 'RETIRO'
            AND finalizado = 1
        ''', (asignacion['id'], fecha_actual, jornada_actual)).fetchone()
        retiro_completado = retiro_finalizado is not None
        
        devolucion_finalizada = conexion.execute('''
            SELECT id FROM controles_tecnicos 
            WHERE asignacion_id = ? 
            AND fecha = ? 
            AND jornada = ? 
            AND tipo_control = 'DEVOLUCION'
            AND finalizado = 1
        ''', (asignacion['id'], fecha_actual, jornada_actual)).fetchone()
        devolucion_completada = devolucion_finalizada is not None
    
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
    
    existe = conexion.execute('''
        SELECT id FROM controles_tecnicos 
        WHERE asignacion_id = ? AND fecha = ? AND jornada = ? 
        AND tipo_control = ? AND finalizado = 0
    ''', (asignacion_id, fecha_actual, jornada, tipo_control)).fetchone()
    
    if existe:
        conexion.close()
        return redirect(url_for('tecnico', error=f'Ya hay un control de {tipo_control} activo'))
    
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
    if 'usuario_id' not in session or session.get('rol') != 'tecnico':
        return redirect(url_for('login'))
    
    conexion = get_db()
    
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
    
    items_registrados = conexion.execute('''
        SELECT elemento, estado FROM items_control_tecnico 
        WHERE control_tecnico_id = ?
    ''', (control_id,)).fetchall()
    
    items_registrados_lista = [item['elemento'] for item in items_registrados]
    
    elementos_bloqueados = conexion.execute('''
        SELECT elemento FROM elementos_bloqueados 
        WHERE camioneta_id = ? AND resuelto = 0
    ''', (control['camioneta_id'],)).fetchall()
    
    elementos_bloqueados_lista = [eb['elemento'] for eb in elementos_bloqueados]
    
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
    if 'usuario_id' not in session or session.get('rol') != 'tecnico':
        return redirect(url_for('login'))
    
    conexion = get_db()
    
    try:
        control = conexion.execute('''
            SELECT finalizado FROM controles_tecnicos WHERE id = ?
        ''', (control_id,)).fetchone()
        
        if not control:
            conexion.close()
            return redirect(url_for('tecnico', error='Control no encontrado'))
        
        if control['finalizado'] == 1:
            conexion.close()
            return redirect(url_for('tecnico', error='Este control ya fue finalizado'))
        
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

@app.route('/guardar-control-rapido', methods=['POST'])
def guardar_control_rapido():
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
        
        info = cursor.execute('''
            SELECT a.camioneta_id, ct.asignacion_id, ct.tipo_control
            FROM controles_tecnicos ct
            JOIN asignaciones a ON ct.asignacion_id = a.id
            WHERE ct.id = ?
        ''', (control_id,)).fetchone()
        
        if not info:
            return jsonify({'error': 'Control no encontrado'}), 404
        
        camioneta_id = info['camioneta_id']
        asignacion_id = info['asignacion_id']
        tipo_control = info['tipo_control']
        
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
        
        problemas_dict = {}
        for p in problemas:
            problemas_dict[p['elemento']] = p.get('observacion', '')
        
        for categoria, lista in TODOS_ELEMENTOS.items():
            for elemento in lista:
                if elemento in problemas_dict:
                    estado = 'FALTANTE'
                    descripcion = problemas_dict[elemento] if problemas_dict[elemento] else 'Elemento faltante'
                    categoria_elemento = categoria
                else:
                    estado = 'OK'
                    descripcion = 'Elemento en buen estado'
                    categoria_elemento = categoria
                
                cursor.execute('''
                    INSERT INTO items_control_tecnico 
                    (control_tecnico_id, elemento, categoria, estado, observacion, fecha_hora)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (control_id, elemento, categoria_elemento, 
                      estado, descripcion, fecha_hora))
                
                cursor.execute('''
                    INSERT INTO reportes 
                    (control_id, tipo, elemento, estado, descripcion, fecha_hora)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (control_id_old, tipo_control, elemento, 
                      estado, descripcion, fecha_hora))
        
        for p in problemas:
            ya_bloqueado = cursor.execute('''
                SELECT id FROM elementos_bloqueados 
                WHERE elemento = ? AND camioneta_id = ? AND resuelto = 0
            ''', (p['elemento'], camioneta_id)).fetchone()
            
            if not ya_bloqueado:
                cursor.execute('''
                    INSERT INTO elementos_bloqueados 
                    (elemento, camioneta_id, tipo, fecha_bloqueo, motivo, resuelto)
                    VALUES (?, ?, ?, ?, ?, 0)
                ''', (p['elemento'], camioneta_id, p['categoria'], 
                      fecha_hora, p.get('observacion', '')))
        
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
        
        return jsonify({
            'success': True, 
            'message': f'Control guardado: {total_ok} OK, {total_problemas} problemas'
        })
        
    except Exception as e:
        conexion.rollback()
        print(f"❌ Error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        conexion.close()

@app.route('/guardar-estado-elemento', methods=['POST'])
def guardar_estado_elemento():
    if 'usuario_id' not in session or session.get('rol') != 'tecnico':
        return jsonify({'error': 'No autorizado'}), 401
    
    control_id = request.form.get('control_id')
    elemento = request.form.get('elemento')
    categoria = request.form.get('categoria')
    estado = request.form.get('estado')
    observacion = request.form.get('observacion', '')
    
    if not all([control_id, elemento, categoria, estado]):
        return jsonify({'error': 'Datos incompletos'}), 400
    
    fecha_hora = datetime.now().isoformat()
    
    conexion = get_db()
    cursor = conexion.cursor()
    
    try:
        existe = cursor.execute('''
            SELECT id FROM items_control_tecnico 
            WHERE control_tecnico_id = ? AND elemento = ?
        ''', (control_id, elemento)).fetchone()
        
        if existe:
            cursor.execute('''
                UPDATE items_control_tecnico 
                SET estado = ?, observacion = ?, fecha_hora = ?
                WHERE control_tecnico_id = ? AND elemento = ?
            ''', (estado, observacion, fecha_hora, control_id, elemento))
        else:
            cursor.execute('''
                INSERT INTO items_control_tecnico 
                (control_tecnico_id, elemento, categoria, estado, observacion, fecha_hora)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (control_id, elemento, categoria, estado, observacion, fecha_hora))
        
        if estado in ['FALLA', 'FALTANTE']:
            camioneta = cursor.execute('''
                SELECT a.camioneta_id 
                FROM controles_tecnicos ct
                JOIN asignaciones a ON ct.asignacion_id = a.id
                WHERE ct.id = ?
            ''', (control_id,)).fetchone()
            
            if camioneta:
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

# ============================================
# RUTAS DE JEFE
# ============================================

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

# ============================================
# RUTAS DE HISTORIAL
# ============================================

@app.route('/historial-camioneta/<string:patente>')
def historial_camioneta(patente):
    if 'usuario_id' not in session or session.get('rol') not in ['admin', 'jefe']:
        return redirect(url_for('login'))
    
    conexion = get_db()
    
    camioneta = conexion.execute('''
        SELECT id, patente FROM camionetas WHERE patente = ? AND activa = 1
    ''', (patente,)).fetchone()
    
    if not camioneta:
        conexion.close()
        return redirect(url_for('admin', error='Camioneta no encontrada'))
    
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

# ============================================
# RUTAS DE REPORTES Y REMITOS
# ============================================

@app.route('/iniciar-retiro')
def iniciar_retiro():
    if 'usuario_id' not in session or session.get('rol') != 'tecnico':
        return redirect(url_for('login'))
    return "Aquí comenzará el control de RETIRO."

@app.route('/resolver-reporte/<int:reporte_id>', methods=['POST'])
def resolver_reporte(reporte_id):
    if 'usuario_id' not in session or session.get('rol') != 'admin':
        return jsonify({'success': False, 'error': 'No autorizado'}), 401
    
    nombre_admin = session.get('nombre', 'Administrador')
    
    try:
        data = request.get_json()
        comentario = data.get('comentario', '').strip() if data else ''
    except Exception as e:
        comentario = ''
        print(f"⚠️ Error al leer JSON: {e}")
    
    print(f"📝 Resolviendo reporte ID: {reporte_id}")
    print(f"💬 Comentario recibido: '{comentario}'")
    
    conexion = get_db()
    try:
        ahora = datetime.now().strftime('%Y-%m-%d %H:%M')
        ahora_iso = datetime.now().isoformat()
        
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
        
        cursor = conexion.cursor()
        cursor.execute('''
            UPDATE reportes 
            SET estado = 'RESUELTO', 
                fecha_resolucion = ?, 
                resuelto_por = ?, 
                comentario_resolucion = ?
            WHERE id = ?
        ''', (ahora, nombre_admin, comentario, reporte_id))
        
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
        
        conexion.commit()
        
        return jsonify({
            'success': True, 
            'fecha_resolucion': ahora,
            'mensaje': f'✅ Reporte resuelto y elemento "{reporte["elemento"]}" desbloqueado'
        })
        
    except Exception as e:
        conexion.rollback()
        print(f"❌ Error al resolver reporte: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conexion.close()

@app.route('/comentar-reporte/<int:reporte_id>', methods=['POST'])
def comentar_reporte(reporte_id):
    if 'usuario_id' not in session or session.get('rol') != 'admin':
        return jsonify({'success': False, 'error': 'No autorizado'}), 401
    
    data = request.get_json()
    comentario = data.get('comentario', '').strip()
    
    if not comentario:
        return jsonify({'success': False, 'error': 'El comentario es requerido'}), 400
    
    conexion = get_db()
    try:
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

@app.route('/generar-remito/<int:reporte_id>', methods=['POST'])
def generar_remito_pdf(reporte_id):
    """Genera un remito en PDF con la firma del administrador"""
    if 'usuario_id' not in session or session.get('rol') not in ['admin', 'jefe']:
        return jsonify({'success': False, 'error': 'No autorizado'}), 401
    
    admin_nombre = session.get('nombre', 'Administrador')
    admin_id = session.get('usuario_id')
    
    conexion = get_db()
    try:
        reporte = conexion.execute('''
            SELECT r.id, r.elemento, r.descripcion, r.estado, r.fecha_hora,
                   c.patente, u.nombre as tecnico_nombre, a.zona
            FROM reportes r
            LEFT JOIN controles co ON r.control_id = co.id
            LEFT JOIN asignaciones a ON co.asignacion_id = a.id
            LEFT JOIN camionetas c ON a.camioneta_id = c.id
            LEFT JOIN usuarios u ON a.tecnico_id = u.id
            WHERE r.id = ? AND r.estado = 'FALTANTE'
        ''', (reporte_id,)).fetchone()
        
        if not reporte:
            return jsonify({'success': False, 'error': 'Reporte no encontrado o ya resuelto'}), 404
        
        # Verificar si ya tiene seguimiento
        seguimiento = conexion.execute('''
            SELECT id FROM seguimiento_remitos WHERE reporte_id = ?
        ''', (reporte_id,)).fetchone()
        
        if seguimiento:
            return jsonify({'success': False, 'error': 'Este remito ya fue generado'}), 400
        
        admin_info = conexion.execute('SELECT nombre, firma FROM usuarios WHERE id = ?', (admin_id,)).fetchone()
        admin_firma = admin_info['firma'] if admin_info else None
        
        fecha_hora = datetime.now()
        fecha_str = fecha_hora.strftime('%Y-%m-%d')
        hora_str = fecha_hora.strftime('%H-%M-%S')
        
        carpeta_destino = crear_carpeta_remitos(reporte['patente'], fecha_str)
        nombre_archivo = f"{reporte['patente']}_{fecha_str}_{hora_str}_{reporte['elemento'].replace(' ', '_')}.pdf"
        ruta_pdf = carpeta_destino / nombre_archivo
        
        generar_pdf_remito(reporte, admin_nombre, admin_firma, fecha_hora, ruta_pdf)
        
        cursor = conexion.cursor()
        cursor.execute('''
            UPDATE reportes SET ruta_remito = ? WHERE id = ?
        ''', (str(ruta_pdf), reporte_id))
        
        # Crear seguimiento de remito
        crear_seguimiento_remito(reporte_id, reporte['patente'], reporte['elemento'], str(ruta_pdf))
        
        # Crear notificación para técnicos
        crear_notificacion(
            'REMITO_PENDIENTE',
            f'📄 Remito pendiente de firma para la camioneta {reporte["patente"]} - Elemento: {reporte["elemento"]}',
            reporte['patente'],
            reporte['elemento'],
            'tecnico',
            f'/historial-camioneta/{reporte["patente"]}'
        )
        
        conexion.commit()
        
        url_pdf = f"/remitos/{reporte['patente']}/{fecha_str[:7]}/{nombre_archivo}"
        
        return jsonify({
            'success': True,
            'url': url_pdf,
            'ruta': str(ruta_pdf),
            'mensaje': 'Remito generado. Pendiente de firma del técnico.'
        })
        
    except Exception as e:
        conexion.rollback()
        print(f"❌ Error al generar remito: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conexion.close()


 # ============================================
# RUTAS DE SEGUIMIENTO DE REMITOS
# ============================================

@app.route('/api/notificaciones')
def api_notificaciones():
    """Obtiene notificaciones para el usuario actual"""
    if 'usuario_id' not in session:
        return jsonify({'error': 'No autorizado'}), 401
    
    rol = session.get('rol')
    notificaciones = obtener_notificaciones(rol)
    return jsonify(notificaciones)

@app.route('/api/notificaciones/marcar/<int:notificacion_id>', methods=['POST'])
def marcar_notificacion(notificacion_id):
    """Marca una notificación como leída"""
    if 'usuario_id' not in session:
        return jsonify({'error': 'No autorizado'}), 401
    
    if marcar_notificacion_leida(notificacion_id):
        return jsonify({'success': True})
    return jsonify({'success': False}), 500

@app.route('/firmar-remito/<int:reporte_id>', methods=['POST'])
def firmar_remito_tecnico(reporte_id):
    """El técnico firma el remito desde el panel"""
    if 'usuario_id' not in session or session.get('rol') != 'tecnico':
        return jsonify({'success': False, 'error': 'No autorizado'}), 401
    
    tecnico_nombre = session.get('nombre', 'Técnico')
    
    conexion = get_db()
    try:
        reporte = conexion.execute('''
            SELECT r.id, r.remito_firmado, r.estado, c.patente, r.elemento
            FROM reportes r
            JOIN controles co ON r.control_id = co.id
            JOIN asignaciones a ON co.asignacion_id = a.id
            JOIN camionetas c ON a.camioneta_id = c.id
            WHERE r.id = ? AND r.estado = 'FALTANTE'
        ''', (reporte_id,)).fetchone()
        
        if not reporte:
            return jsonify({'success': False, 'error': 'Reporte no encontrado'}), 404
        
        if reporte['remito_firmado'] == 1:
            return jsonify({'success': False, 'error': 'Este remito ya fue firmado'}), 400
        
        # Firmar el remito
        if firmar_remito(reporte_id, tecnico_nombre):
            # Crear notificación para administradores
            crear_notificacion(
                'REMITO_FIRMADO',
                f'✍️ Remito firmado para revisión - Patente: {reporte["patente"]} - Elemento: {reporte["elemento"]}',
                reporte['patente'],
                reporte['elemento'],
                'admin',
                f'/admin/remitos/seguimiento'
            )
            return jsonify({
                'success': True,
                'mensaje': '✅ Remito firmado correctamente. El administrador lo revisará.'
            })
        else:
            return jsonify({'success': False, 'error': 'Error al firmar el remito'}), 500
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conexion.close()

@app.route('/revisar-remito/<int:reporte_id>', methods=['POST'])
def revisar_remito_admin(reporte_id):
    """Administrador revisa y cierra el remito firmado"""
    if 'usuario_id' not in session or session.get('rol') != 'admin':
        return jsonify({'success': False, 'error': 'No autorizado'}), 401
    
    admin_nombre = session.get('nombre', 'Administrador')
    
    if revisar_remito(reporte_id, admin_nombre):
        crear_notificacion(
            'REMITO_REVISADO',
            f'✅ Remito revisado y cerrado por {admin_nombre}',
            None,
            None,
            'todos',
            None
        )
        return jsonify({'success': True, 'mensaje': 'Remito revisado y cerrado'})
    
    return jsonify({'success': False, 'error': 'Error al revisar el remito'}), 500       

@app.route('/remitos/<path:filename>')
def servir_remito(filename):
    if 'usuario_id' not in session or session.get('rol') not in ['admin', 'jefe']:
        return redirect(url_for('login'))
    
    ruta_completa = REMITOS_DIR / filename
    
    if not ruta_completa.exists():
        return "Archivo no encontrado", 404
    
    try:
        ruta_real = ruta_completa.resolve()
        remitos_real = REMITOS_DIR.resolve()
        if not str(ruta_real).startswith(str(remitos_real)):
            return "Acceso denegado", 403
    except Exception:
        return "Acceso denegado", 403
    
    return send_file(ruta_completa, as_attachment=False, mimetype='application/pdf')

@app.route('/admin/remitos')
def admin_remitos():
    if 'usuario_id' not in session or session.get('rol') != 'admin':
        return redirect(url_for('login'))
    
    remitos = []
    if REMITOS_DIR.exists():
        for patente_dir in REMITOS_DIR.iterdir():
            if patente_dir.is_dir():
                for mes_dir in patente_dir.iterdir():
                    if mes_dir.is_dir():
                        for archivo in mes_dir.glob('*.pdf'):
                            remitos.append({
                                'patente': patente_dir.name,
                                'mes': mes_dir.name,
                                'archivo': archivo.name,
                                'ruta': f"/remitos/{patente_dir.name}/{mes_dir.name}/{archivo.name}",
                                'fecha': archivo.stat().st_mtime
                            })
    
    remitos.sort(key=lambda x: x['fecha'], reverse=True)
    
    return render_template('admin_remitos.html', remitos=remitos)

# ============================================
# RUTAS DE LOGOUT
# ============================================

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ============================================
# MAIN
# ============================================

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