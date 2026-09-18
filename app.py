from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file
import sqlite3
from pathlib import Path, PurePosixPath
from datetime import datetime, timedelta, time
import os
import sys
import secrets
import shutil
import re
import calendar as calendario_py
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from PIL import Image as PILImage
from zoneinfo import ZoneInfo

# La consola de Windows suele venir en cp1252 y no puede imprimir los emojis
# que usan los mensajes de este archivo: sin esto, un print de arranque corta
# la ejecución con UnicodeEncodeError.
for _flujo in (sys.stdout, sys.stderr):
    try:
        _flujo.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):
        pass

app = Flask(__name__)
# En producción definir CONTROL_SECRET_KEY. Sin esa variable se genera una clave
# al azar por arranque: el sistema funciona, pero las sesiones se cierran al
# reiniciar el servidor (mejor eso que una clave pública en el repositorio).
app.secret_key = os.environ.get('CONTROL_SECRET_KEY') or secrets.token_hex(32)

BASE_DIR = Path(__file__).resolve().parent

# El servidor puede correr en UTC (Docker, Codespaces). Sin esto los horarios se
# guardaban adelantados respecto de la hora real de la jornada y los controles
# vencían antes de tiempo.
TZ_LOCAL = ZoneInfo(os.environ.get('CONTROL_TZ') or 'America/Argentina/Buenos_Aires')


def ahora():
    """Hora local de la operación, sin tzinfo: el resto del código compara naive."""
    return datetime.now(TZ_LOCAL).replace(tzinfo=None)

# Dónde vive la base de datos. En Docker apunta a un volumen (CONTROL_DATA_DIR),
# para que reconstruir la imagen no borre el historial de la flota.
DATA_DIR = Path(os.environ.get('CONTROL_DATA_DIR') or BASE_DIR)
DATABASE = DATA_DIR / "database.db"

# Carpeta de remitos y de firmas: también deben ir a un volumen.
REMITOS_DIR = Path(os.environ.get('CONTROL_REMITOS_DIR') or (BASE_DIR / "remitos"))
UPLOAD_FOLDER = Path(os.environ.get('CONTROL_FIRMAS_DIR') or (BASE_DIR / "static" / "firmas"))
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# Crear carpetas necesarias
for _carpeta in (DATA_DIR, REMITOS_DIR, UPLOAD_FOLDER):
    _carpeta.mkdir(parents=True, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def ruta_firma(firma):
    """Ruta en disco de una firma a partir de lo guardado en la base.

    Acepta el formato nuevo (solo el nombre del archivo) y también las rutas
    absolutas que quedaron guardadas por la versión anterior.
    """
    if not firma:
        return None
    nombre = PurePosixPath(str(firma).replace(chr(92), '/')).name
    if not nombre:
        return None
    return UPLOAD_FOLDER / nombre


def borrar_firma(firma):
    ruta = ruta_firma(firma)
    if ruta and ruta.exists():
        try:
            ruta.unlink()
        except OSError as e:
            print(f"⚠️ No se pudo borrar la firma {ruta.name}: {e}")

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

# Contenido con el que se siembra el catálogo la primera vez. A partir de ahí
# la fuente de verdad es la tabla elementos_catalogo, que administra el admin.
CATALOGO_INICIAL = {
    'CAMIONETA': EXPECTED_CAMIONETA,
    'HERRAMIENTA': EXPECTED_HERRAMIENTAS,
    'CAJA': EXPECTED_CAJA
}

CATEGORIAS = ('CAMIONETA', 'HERRAMIENTA', 'CAJA')

ETIQUETA_CATEGORIA = {
    'CAMIONETA': 'Camioneta',
    'HERRAMIENTA': 'Herramientas',
    'CAJA': 'Caja de herramientas',
}


def obtener_catalogo(conexion, incluir_inactivos=False):
    """Elementos activos agrupados por categoría, en el orden configurado."""
    filtro = '' if incluir_inactivos else 'WHERE activo = 1'
    filas = conexion.execute(f'''
        SELECT id, nombre, categoria, activo, orden
        FROM elementos_catalogo {filtro}
        ORDER BY orden, nombre
    ''').fetchall()

    catalogo = {categoria: [] for categoria in CATEGORIAS}
    for fila in filas:
        catalogo.setdefault(fila['categoria'], []).append(dict(fila))
    return catalogo


def categoria_por_elemento(conexion):
    """{nombre del elemento: categoría} de los elementos activos.

    Se usa para no confiar en la categoría que manda el navegador, que se
    puede alterar desde el cliente.
    """
    return {
        fila['nombre']: fila['categoria']
        for fila in conexion.execute(
            'SELECT nombre, categoria FROM elementos_catalogo WHERE activo = 1')
    }


def zonas_activas(conexion):
    return [dict(f) for f in conexion.execute(
        'SELECT id, nombre, activa FROM zonas WHERE activa = 1 ORDER BY nombre')]

JORNADAS = ('mañana', 'tarde')

# Horario real de cada jornada, por día de la semana (0 = lunes ... 6 = domingo).
# Mañana: lunes a viernes 7:30 a 14:45.
# Tarde:  lunes a viernes 14:30 a 20:30, sábados 9:30 a 15:30.
# Domingo no se trabaja.
HORARIOS = {
    'mañana': {
        0: (time(7, 30), time(14, 45)),
        1: (time(7, 30), time(14, 45)),
        2: (time(7, 30), time(14, 45)),
        3: (time(7, 30), time(14, 45)),
        4: (time(7, 30), time(14, 45)),
    },
    'tarde': {
        0: (time(14, 30), time(20, 30)),
        1: (time(14, 30), time(20, 30)),
        2: (time(14, 30), time(20, 30)),
        3: (time(14, 30), time(20, 30)),
        4: (time(14, 30), time(20, 30)),
        5: (time(9, 30), time(15, 30)),
    },
}

# Margen para reclamar una devolución no realizada: una hora desde que termina
# el turno. El retiro no se reclama con este margen: ver vencimiento_retiro().
MARGEN_CONTROL = timedelta(hours=1)

# Zona con la que se identifica a quien está de guardia y se lleva la camioneta.
ZONA_GUARDIA = 'GUARDIA'

# Qué se le controla a cada camioneta por calendario, además del control diario
# de elementos. Los valores son los que se usan al crear un vencimiento nuevo:
# después cada camioneta puede tener los suyos (una puede lavarse cada 15 días
# y otra cada semana).
#
# El service es el único que vence por dos caminos a la vez, fecha y kilómetros:
# manda el que llegue primero, y por eso el kilometraje es obligatorio en cada
# control.
TIPOS_VENCIMIENTO = {
    'VTV': {
        'etiqueta': 'VTV',
        'icono': 'clipboard2-check',
        'color': '#0d6efd',
        'periodicidad_dias': 365,
        'periodicidad_km': None,
        'aviso_dias': 30,
        'aviso_km': None,
        'ayuda': 'Verificación técnica vehicular. Vence por fecha.',
    },
    'MATAFUEGO': {
        'etiqueta': 'Matafuego',
        'icono': 'fire',
        'color': '#dc3545',
        'periodicidad_dias': 365,
        'periodicidad_km': None,
        'aviso_dias': 30,
        'aviso_km': None,
        'ayuda': 'Carga y sellado del matafuego. Vence por fecha.',
    },
    'SERVICE': {
        'etiqueta': 'Service',
        'icono': 'wrench-adjustable',
        'color': '#fd7e14',
        'periodicidad_dias': 365,
        'periodicidad_km': 10000,
        'aviso_dias': 30,
        'aviso_km': 1000,
        'ayuda': 'Service de aceite y filtros: cada 10.000 km o una vez al año, '
                 'lo que ocurra primero.',
    },
    'LAVADO': {
        'etiqueta': 'Lavado',
        'icono': 'droplet',
        'color': '#0dcaf0',
        'periodicidad_dias': 15,
        'periodicidad_km': None,
        'aviso_dias': 3,
        'aviso_km': None,
        'ayuda': 'Lavado de la camioneta. Se programa por fecha.',
    },
}

ORDEN_ESTADO = {'VENCIDO': 0, 'POR_VENCER': 1, 'SIN_DATOS': 2, 'AL_DIA': 3}

MESES = ('enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio',
         'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre')

# Por qué se repone un elemento faltante. Va impreso en el remito.
MOTIVOS_REPOSICION = {
    'ROTURA': 'Rotura',
    'PERDIDA': 'Pérdida',
}


def horario_jornada(jornada, fecha):
    """(inicio, fin) de una jornada en una fecha, o None si ese día no se trabaja."""
    return HORARIOS.get(jornada, {}).get(fecha.weekday())


def jornada_laborable(jornada, fecha):
    return horario_jornada(jornada, fecha) is not None


def inicio_fin_jornada(jornada, fecha):
    """Los extremos de la jornada como datetime, o (None, None)."""
    horario = horario_jornada(jornada, fecha)
    if not horario:
        return None, None
    inicio, fin = horario
    base = datetime.combine(fecha.date() if isinstance(fecha, datetime) else fecha, time())
    return base + timedelta(hours=inicio.hour, minutes=inicio.minute), \
           base + timedelta(hours=fin.hour, minutes=fin.minute)


def jornadas_activas(momento=None):
    """Jornadas en curso, de mayor a menor prioridad.

    Mañana y tarde se solapan entre las 14:30 y las 14:45. En esa franja se
    prioriza la mañana, que es la que está cerrando.
    """
    momento = momento or ahora()
    activas = []
    for jornada in JORNADAS:
        inicio, fin = inicio_fin_jornada(jornada, momento)
        if inicio and inicio <= momento <= fin:
            activas.append(jornada)
    if activas:
        return activas

    # Fuera de horario: se ofrece la jornada del día que todavía no terminó, y
    # si ya terminaron todas, la última. Así el técnico que entra antes de hora
    # o después de cerrar igual encuentra su asignación.
    del_dia = [j for j in JORNADAS if jornada_laborable(j, momento)]
    if not del_dia:
        return []
    pendientes = [j for j in del_dia if inicio_fin_jornada(j, momento)[0] > momento]
    return pendientes or [del_dia[-1]]


def jornada_actual(momento=None):
    """Jornada de referencia para el momento dado."""
    activas = jornadas_activas(momento)
    return activas[0] if activas else 'mañana'


def jornada_valida(jornada):
    return jornada in JORNADAS


def orden_jornada(jornada):
    """Para ordenar turnos cronológicamente dentro de un mismo día."""
    return JORNADAS.index(jornada) if jornada in JORNADAS else len(JORNADAS)

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





def generar_pdf_remito(remito, ruta_pdf):
    """Genera el PDF del remito con los dos bloques de firma.

    Se regenera en cada paso del circuito: al crearlo las dos firmas figuran
    pendientes, y cada firma vuelve a escribir el archivo para que el PDF
    final tenga la del técnico que recibió y la de quien entregó el material.
    """
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
    
    fecha_hora = remito['fecha_generacion']
    data = [
        ['N° REMITO:', f"REM-{fecha_hora.strftime('%Y%m%d')}-{remito['id']}"],
        ['FECHA:', fecha_hora.strftime('%d/%m/%Y %H:%M')],
        ['CAMIONETA:', remito['patente']],
        ['MATERIAL ENTREGADO:', remito['material_entregado'] or remito['elemento']],
        ['MOTIVO DE REPOSICIÓN:', MOTIVOS_REPOSICION.get(remito['motivo'], 'No especificado')],
        ['CREADO POR:', remito['creador_nombre'] or 'Soporte'],
        ['ENTREGA EL MATERIAL:', remito['entrega_nombre'] or 'Pendiente de firma'],
        ['DESCRIPCIÓN:', remito['descripcion'] or 'Sin descripción'],
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
    # FIRMAS: quien recibe el material y quien lo entrega
    # ==========================================
    linea_style = ParagraphStyle(
        'FirmaLinea', parent=styles['Normal'], alignment=TA_CENTER, fontSize=11)

    pie_firma_style = ParagraphStyle(
        'FirmaPie', parent=styles['Normal'], alignment=TA_CENTER, fontSize=9,
        textColor=colors.HexColor('#666'))

    pendiente_style = ParagraphStyle(
        'FirmaPendiente', parent=styles['Normal'], alignment=TA_CENTER, fontSize=9,
        fontName='Helvetica-Bold', textColor=colors.HexColor('#b00020'))

    def bloque_firma(titulo, nombre, archivo_firma, fecha_firma, cargo):
        elements.append(Paragraph(titulo, firma_style))

        imagen = ruta_firma(archivo_firma) if fecha_firma else None
        dibujada = False
        if imagen and imagen.exists():
            try:
                with PILImage.open(imagen) as img:
                    ancho, alto = img.size
                escala = min(4 * cm / ancho, 2 * cm / alto)
                grafico = Image(str(imagen), width=ancho * escala, height=alto * escala)
                grafico.hAlign = 'CENTER'
                elements.append(grafico)
                dibujada = True
            except Exception as e:
                print(f"Error al cargar firma: {e}")
        if not dibujada:
            elements.append(Paragraph("_________________________", linea_style))

        elements.append(Paragraph(f"{nombre or 'Pendiente'} ({cargo})", pie_firma_style))
        if fecha_firma:
            elements.append(Paragraph(
                f"Firmado el {fecha_firma.strftime('%d/%m/%Y %H:%M')}", pie_firma_style))
        else:
            elements.append(Paragraph("PENDIENTE DE FIRMA", pendiente_style))
        elements.append(Spacer(1, 0.7 * cm))

    bloque_firma('RECIBE EL MATERIAL',
                 remito['tecnico_firma_nombre'], remito['tecnico_firma_archivo'],
                 remito['tecnico_fecha_firma'], 'Técnico')
    bloque_firma('ENTREGA EL MATERIAL',
                 remito['soporte_firma_nombre'], remito['soporte_firma_archivo'],
                 remito['soporte_fecha_firma'], 'Soporte')

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

def crear_notificacion(tipo, mensaje, patente=None, elemento=None, destinatario_rol='todos',
                       enlace=None, reporte_id=None, conexion=None):
    """Crea una notificación en el sistema.

    Si se pasa `conexion`, reutiliza la transacción del llamador (indispensable:
    abrir una segunda conexión mientras la ruta ya está escribiendo hace que
    SQLite responda 'database is locked' y la notificación se pierda en silencio).
    """
    propia = conexion is None
    if propia:
        conexion = get_db()
    try:
        fecha = ahora().isoformat()
        conexion.execute('''
            INSERT INTO notificaciones
                (tipo, mensaje, patente, elemento, fecha, destinatario_rol, enlace, reporte_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (tipo, mensaje, patente, elemento, fecha, destinatario_rol, enlace, reporte_id))
        if propia:
            conexion.commit()
        return True
    except Exception as e:
        print(f"Error al crear notificación: {e}")
        if propia:
            conexion.rollback()
        raise
    finally:
        if propia:
            conexion.close()

def datos_remito(conexion, reporte_id):
    """Fila con todo lo que necesitan el PDF y las pantallas de firma."""
    return conexion.execute('''
        SELECT r.id, r.elemento, r.descripcion, r.motivo_reposicion,
               r.material_entregado, r.creado_por, r.creado_por_id,
               r.entregado_por, r.entrega_id,
               r.firmado_por_id, r.ruta_remito,
               r.remito_firmado, r.remito_revisado,
               r.firma_tecnico, r.fecha_firma,
               r.firma_soporte, r.fecha_firma_soporte,
               c.patente, a.zona, a.camioneta_id,
               u.nombre AS tecnico_nombre,
               sr.fecha_generacion, sr.estado AS estado_remito,
               soporte.firma AS soporte_firma_archivo,
               firmante.firma AS tecnico_firma_archivo
        FROM reportes r
        LEFT JOIN controles co ON r.control_id = co.id
        LEFT JOIN asignaciones a ON co.asignacion_id = a.id
        LEFT JOIN camionetas c ON a.camioneta_id = c.id
        LEFT JOIN usuarios u ON a.tecnico_id = u.id
        LEFT JOIN usuarios soporte ON COALESCE(r.entrega_id, r.creado_por_id) = soporte.id
        LEFT JOIN usuarios firmante ON r.firmado_por_id = firmante.id
        LEFT JOIN seguimiento_remitos sr ON sr.reporte_id = r.id
        WHERE r.id = ?
    ''', (reporte_id,)).fetchone()


def _a_fecha(valor):
    try:
        return datetime.fromisoformat(valor) if valor else None
    except (ValueError, TypeError):
        return None


def escribir_pdf_remito(fila, ruta_pdf):
    """Vuelca la fila de datos_remito() al PDF, con el estado actual de firmas."""
    generar_pdf_remito({
        'id': fila['id'],
        'patente': fila['patente'],
        'elemento': fila['elemento'],
        'material_entregado': fila['material_entregado'],
        'motivo': fila['motivo_reposicion'],
        'descripcion': fila['descripcion'],
        'creador_nombre': fila['creado_por'],
        'entrega_nombre': fila['entregado_por'],
        'fecha_generacion': _a_fecha(fila['fecha_generacion']) or ahora(),
        'tecnico_firma_nombre': fila['firma_tecnico'],
        'tecnico_firma_archivo': fila['tecnico_firma_archivo'],
        'tecnico_fecha_firma': _a_fecha(fila['fecha_firma']),
        'soporte_firma_nombre': fila['firma_soporte'],
        'soporte_firma_archivo': fila['soporte_firma_archivo'],
        'soporte_fecha_firma': _a_fecha(fila['fecha_firma_soporte']),
    }, ruta_pdf)


def mudar_remitos_de_patente(conexion, camioneta_id, vieja, nueva):
    """Lleva los remitos ya emitidos a la patente nueva de la camioneta.

    Las carpetas, los nombres de archivo y el texto impreso en cada remito se
    arman con la patente del momento en que se generan. Si al corregir una
    patente no se arrastra todo esto, quedan documentos y rutas con un nombre
    que ya no existe en el sistema.

    El PDF se vuelve a escribir desde la base con el mismo código que usa la
    firma, así que las firmas y las fechas se conservan tal cual estaban.
    Devuelve (archivos_movidos, avisos).
    """
    avisos = []
    if not vieja or vieja == nueva:
        return 0, avisos

    origen = REMITOS_DIR / vieja
    destino_base = REMITOS_DIR / nueva
    movidos = {}

    if origen.is_dir():
        for pdf in sorted(origen.rglob('*.pdf')):
            relativo = pdf.relative_to(origen)
            destino = destino_base / relativo.parent / pdf.name.replace(vieja, nueva, 1)
            try:
                destino.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(pdf), str(destino))
                movidos[pdf.name] = str(destino)
            except OSError as e:
                avisos.append(f'No se pudo mover {pdf.name}: {e}')

        # Las carpetas vacías se sacan para no dejar el nombre viejo dando vueltas.
        for resto in sorted(origen.rglob('*'), reverse=True):
            if resto.is_dir() and not any(resto.iterdir()):
                resto.rmdir()
        if origen.is_dir() and not any(origen.iterdir()):
            origen.rmdir()

    def ruta_nueva(ruta):
        # Las rutas guardadas pueden venir de otra máquina (hay remitos con
        # rutas de Windows en bases viejas), así que se cortan por el nombre.
        if not ruta:
            return None
        return movidos.get(re.split(r'[\\/]', ruta)[-1])

    reportes = conexion.execute('''
        SELECT r.id, r.ruta_remito
        FROM reportes r
        JOIN controles co ON r.control_id = co.id
        JOIN asignaciones a ON co.asignacion_id = a.id
        WHERE a.camioneta_id = ? AND r.ruta_remito IS NOT NULL AND r.ruta_remito <> ''
    ''', (camioneta_id,)).fetchall()

    for fila in reportes:
        nueva_ruta = ruta_nueva(fila['ruta_remito'])
        if nueva_ruta:
            conexion.execute('UPDATE reportes SET ruta_remito = ? WHERE id = ?',
                             (nueva_ruta, fila['id']))

    for fila in conexion.execute(
            'SELECT id, ruta_pdf FROM seguimiento_remitos WHERE patente = ?', (vieja,)).fetchall():
        conexion.execute('UPDATE seguimiento_remitos SET patente = ?, ruta_pdf = ? WHERE id = ?',
                         (nueva, ruta_nueva(fila['ruta_pdf']) or fila['ruta_pdf'], fila['id']))

    conexion.execute('UPDATE notificaciones SET patente = ? WHERE patente = ?', (nueva, vieja))
    conexion.execute(
        'UPDATE notificaciones SET mensaje = REPLACE(mensaje, ?, ?) WHERE mensaje LIKE ?',
        (vieja, nueva, f'%{vieja}%'))

    # Recién ahora se reescriben los PDF: datos_remito() lee la patente por
    # join, así que necesita el UPDATE de camionetas ya aplicado.
    for fila in reportes:
        destino = ruta_nueva(fila['ruta_remito'])
        if not destino:
            continue
        try:
            escribir_pdf_remito(datos_remito(conexion, fila['id']), destino)
        except Exception as e:
            avisos.append(f'El remito {Path(destino).name} se movió pero no se pudo '
                          f'reescribir con la patente nueva: {e}')

    return len(movidos), avisos


def crear_seguimiento_remito(conexion, reporte_id, patente, elemento, ruta_pdf):
    """Arranca el circuito del remito: primero lo firma el técnico."""
    conexion.execute('''
        INSERT INTO seguimiento_remitos
        (reporte_id, patente, elemento, fecha_generacion, estado, ruta_pdf)
        VALUES (?, ?, ?, ?, 'PENDIENTE_FIRMA_TECNICO', ?)
    ''', (reporte_id, patente, elemento, ahora().isoformat(), str(ruta_pdf)))


def firmar_remito_tecnico_db(conexion, reporte_id, tecnico_id, tecnico_nombre):
    """El técnico que recibe el material firma; queda a la espera de soporte."""
    fecha = ahora().isoformat()
    conexion.execute('''
        UPDATE reportes
        SET remito_firmado = 1, firma_tecnico = ?, firmado_por_id = ?, fecha_firma = ?
        WHERE id = ?
    ''', (tecnico_nombre, tecnico_id, fecha, reporte_id))
    conexion.execute('''
        UPDATE seguimiento_remitos
        SET estado = 'PENDIENTE_FIRMA_SOPORTE', fecha_firma = ?, tecnico_firma = ?
        WHERE reporte_id = ?
    ''', (fecha, tecnico_nombre, reporte_id))


def firmar_remito_soporte_db(conexion, reporte_id, soporte_nombre, soporte_id=None):
    """Firma de quien entregó el material: cierra el remito.

    Quien entrega se registra recién acá, al firmar. No se elige al crear el
    remito porque en ese momento todavía no se sabe quién va a bajar a entregar
    la herramienta: firma el que efectivamente la entregó, y eso lo fija.
    """
    fecha = ahora().isoformat()
    conexion.execute('''
        UPDATE reportes
        SET remito_revisado = 1, firma_soporte = ?, fecha_firma_soporte = ?,
            entregado_por = ?, entrega_id = ?,
            estado = 'RESUELTO', fecha_resolucion = ?, resuelto_por = ?
        WHERE id = ?
    ''', (soporte_nombre, fecha, soporte_nombre, soporte_id,
          fecha, soporte_nombre, reporte_id))
    conexion.execute('''
        UPDATE seguimiento_remitos
        SET estado = 'FINALIZADO', fecha_revision = ?, admin_revision = ?
        WHERE reporte_id = ?
    ''', (fecha, soporte_nombre, reporte_id))


def desbloquear_elemento(conexion, camioneta_id, elemento):
    """Libera el elemento de la camioneta una vez cerrado el remito."""
    if camioneta_id is None:
        return
    conexion.execute('''
        UPDATE elementos_bloqueados
        SET resuelto = 1, fecha_resolucion = ?
        WHERE camioneta_id = ? AND elemento = ? AND resuelto = 0
    ''', (ahora().isoformat(), camioneta_id, elemento))


def obtener_notificaciones(rol=None, conexion=None):
    """Notificaciones sin leer de un rol, con el estado del remito asociado.

    `remito_cerrable` dice si la alerta se puede descartar: las de un remito
    quedan fijas hasta que el remito termina su circuito, para que nadie las
    haga desaparecer con material todavía sin firmar.
    """
    propia = conexion is None
    if propia:
        conexion = get_db()
    try:
        if rol:
            filas = conexion.execute('''
                SELECT n.*, sr.estado AS estado_remito
                FROM notificaciones n
                LEFT JOIN seguimiento_remitos sr ON sr.reporte_id = n.reporte_id
                WHERE (n.destinatario_rol = ? OR n.destinatario_rol = 'todos')
                  AND n.leido = 0
                ORDER BY n.fecha DESC
            ''', (rol,)).fetchall()
        else:
            filas = conexion.execute('''
                SELECT n.*, sr.estado AS estado_remito
                FROM notificaciones n
                LEFT JOIN seguimiento_remitos sr ON sr.reporte_id = n.reporte_id
                WHERE n.leido = 0
                ORDER BY n.fecha DESC
            ''').fetchall()

        notificaciones = []
        for f in filas:
            n = dict(f)
            n['remito_cerrable'] = (n['estado_remito'] in (None, 'FINALIZADO'))
            notificaciones.append(n)
        return notificaciones
    finally:
        if propia:
            conexion.close()

def marcar_notificacion_leida(notificacion_id):
    """Descarta una notificación. Devuelve (ok, motivo del rechazo)."""
    conexion = get_db()
    try:
        fila = conexion.execute('''
            SELECT n.id, sr.estado AS estado_remito
            FROM notificaciones n
            LEFT JOIN seguimiento_remitos sr ON sr.reporte_id = n.reporte_id
            WHERE n.id = ?
        ''', (notificacion_id,)).fetchone()

        if fila is None:
            return False, 'La alerta no existe'

        # Una alerta de remito no se puede sacar de la vista mientras el
        # circuito siga abierto: es el recordatorio de que falta una firma.
        if fila['estado_remito'] not in (None, 'FINALIZADO'):
            return False, 'No se puede cerrar: el remito todavía no está finalizado'

        conexion.execute('''
            UPDATE notificaciones
            SET leido = 1, fecha_lectura = ?
            WHERE id = ?
        ''', (ahora().isoformat(), notificacion_id))
        conexion.commit()
        return True, None
    except Exception as e:
        conexion.rollback()
        print(f"Error al marcar notificación: {e}")
        return False, str(e)
    finally:
        conexion.close()



# ============================================
# FILTROS PARA JINJA2
# ============================================

@app.template_filter('timestamp_to_datetime')
def timestamp_to_datetime(timestamp):
    if timestamp:
        return datetime.fromtimestamp(timestamp, TZ_LOCAL).strftime('%d/%m/%Y %H:%M')
    return '-'

@app.template_filter('miles')
def filtro_miles(valor):
    """Separador de miles en las pantallas: 148320 -> 148.320."""
    if valor in (None, ''):
        return '—'
    try:
        return miles(valor)
    except (TypeError, ValueError):
        return valor


@app.template_filter('nombre_firma')
def nombre_firma(firma):
    """Nombre del archivo de firma, sirva lo guardado como ruta o como nombre."""
    ruta = ruta_firma(firma)
    return ruta.name if ruta else ''

# ============================================
# FUNCIONES DE BASE DE DATOS
# ============================================

@app.before_request
def limpiar_redirecciones():
    if 'usuario_id' not in session:
        return
    rol = session.get('rol')
    propio = PANEL_POR_ROL.get(rol, 'tecnico')
    ajenos = {'/tecnico': 'tecnico', '/admin': 'admin', '/jefe': 'jefe'}
    destino = ajenos.get(request.path)
    if destino and destino != propio and rol != 'admin':
        return redirect(url_for(propio))


# Panel de inicio de cada rol.
PANEL_POR_ROL = {
    'admin': 'admin',
    'soporte': 'admin',
    'jefe': 'jefe',
    'tecnico': 'tecnico',
}


def autorizado(*roles):
    """True si el usuario logueado tiene alguno de esos roles.

    El admin es superusuario y entra a todo; además es el único que llega a
    Configuración y a los tiempos de control (se llama sin argumentos).
    """
    if 'usuario_id' not in session:
        return False
    rol = session.get('rol')
    return rol == 'admin' or rol in roles


@app.after_request
def no_guardar_en_cache(respuesta):
    """Evita que el botón "atrás" muestre una pantalla de una sesión cerrada.

    Sin esto el navegador reusaba la copia en caché y el usuario volvía a ver
    (y operar sobre) el panel después de hacer logout.
    """
    if request.endpoint != 'static':
        respuesta.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        respuesta.headers['Pragma'] = 'no-cache'
        respuesta.headers['Expires'] = '0'
    return respuesta


def conectar_db():
    # timeout: si otro proceso está escribiendo, espera en vez de fallar al instante.
    conexion = sqlite3.connect(str(DATABASE), timeout=15)
    conexion.execute('PRAGMA journal_mode = WAL')
    conexion.execute('PRAGMA foreign_keys = ON')
    return conexion

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
        estado TEXT DEFAULT 'PENDIENTE_FIRMA_TECNICO',
        -- PENDIENTE_FIRMA_TECNICO -> PENDIENTE_FIRMA_SOPORTE -> FINALIZADO
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
        reporte_id INTEGER,
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
    
    # Catálogo de elementos que se controlan en cada camioneta.
    # Antes estaba fijo en el código; ahora lo administra el admin.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS elementos_catalogo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            categoria TEXT NOT NULL,
            activo INTEGER DEFAULT 1,
            orden INTEGER DEFAULT 0,
            UNIQUE (nombre)
        )
    ''')

    # Zonas de trabajo. Reemplazan al texto libre de la planilla.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS zonas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            activa INTEGER DEFAULT 1,
            UNIQUE (nombre)
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
        motivo_reposicion TEXT,
        material_entregado TEXT,
        creado_por TEXT,
        creado_por_id INTEGER,
        entregado_por TEXT,
        entrega_id INTEGER,
        firmado_por_id INTEGER,
        ruta_remito TEXT,
        remito_firmado INTEGER DEFAULT 0,
        remito_revisado INTEGER DEFAULT 0,
        firma_tecnico TEXT,
        fecha_firma TEXT,
        firma_soporte TEXT,
        fecha_firma_soporte TEXT,
        FOREIGN KEY (control_id) REFERENCES controles(id)
    )
''')
    
    # Vencimientos programados de cada camioneta: VTV, matafuego, service,
    # lavado. Uno por camioneta y tipo; la fila guarda cuándo vence el próximo
    # y cada cuánto se repite.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS vencimientos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            camioneta_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            fecha_vencimiento TEXT,
            km_vencimiento INTEGER,
            periodicidad_dias INTEGER,
            periodicidad_km INTEGER,
            aviso_dias INTEGER,
            aviso_km INTEGER,
            observacion TEXT,
            activo INTEGER DEFAULT 1,
            FOREIGN KEY (camioneta_id) REFERENCES camionetas(id)
        )
    ''')
    cursor.execute('''
        CREATE UNIQUE INDEX IF NOT EXISTS idx_vencimiento_unico
        ON vencimientos (camioneta_id, tipo)
    ''')

    # Cada vez que algo se hace queda acá. Es el registro de "qué se hizo y
    # cuándo" que alimenta el calendario hacia atrás.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS vencimientos_historial (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            camioneta_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            fecha_realizado TEXT NOT NULL,
            km_realizado INTEGER,
            registrado_por TEXT,
            observacion TEXT,
            fecha_registro TEXT,
            FOREIGN KEY (camioneta_id) REFERENCES camionetas(id)
        )
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_vencimientos_historial
        ON vencimientos_historial (camioneta_id, tipo, fecha_realizado)
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
    aplicar_migraciones(conexion)
    insertar_datos_prueba(conexion)
    conexion.close()

def aplicar_migraciones(conexion):
    """Agrega columnas nuevas a bases de datos ya existentes, sin perder datos.

    Reemplaza al viejo comportamiento de borrar database.db ante cualquier
    error de esquema, que destruía el historial de la flota.
    """
    cursor = conexion.cursor()

    columnas_esperadas = {
        'notificaciones': [
            ('reporte_id', 'INTEGER'),
        ],
        'reportes': [
            ('motivo_reposicion', 'TEXT'),
            ('material_entregado', 'TEXT'),
            ('creado_por', 'TEXT'),
            ('creado_por_id', 'INTEGER'),
            ('firmado_por_id', 'INTEGER'),
            ('ruta_remito', 'TEXT'),
            ('remito_firmado', 'INTEGER DEFAULT 0'),
            ('remito_revisado', 'INTEGER DEFAULT 0'),
            ('firma_tecnico', 'TEXT'),
            ('fecha_firma', 'TEXT'),
            ('firma_soporte', 'TEXT'),
            ('fecha_firma_soporte', 'TEXT'),
            ('entregado_por', 'TEXT'),
            ('entrega_id', 'INTEGER'),
            ('recibido_por', 'TEXT'),
            ('fecha_entrega', 'TEXT'),
        ],
        'usuarios': [
            ('firma', 'TEXT'),
        ],
        'asignaciones': [
            ('tecnico2_id', 'INTEGER'),
            ('zona', 'TEXT'),
        ],
        'controles_tecnicos': [
            ('kilometraje', 'INTEGER'),
            ('fuera_de_termino', 'INTEGER DEFAULT 0'),
            ('forzado_por', 'TEXT'),
            ('observacion', 'TEXT'),
        ],
    }

    for tabla, columnas in columnas_esperadas.items():
        existentes = {fila[1] for fila in cursor.execute(f'PRAGMA table_info({tabla})')}
        if not existentes:
            continue
        for nombre, tipo in columnas:
            if nombre not in existentes:
                cursor.execute(f'ALTER TABLE {tabla} ADD COLUMN {nombre} {tipo}')
                print(f'🔧 Migración: {tabla}.{nombre} agregada')

    # Índices para las consultas que se hacen en cada pantalla.
    indices = [
        ('idx_asignaciones_fecha_jornada', 'asignaciones (fecha, jornada)'),
        ('idx_asignaciones_tecnico', 'asignaciones (tecnico_id, fecha)'),
        ('idx_asignaciones_tecnico2', 'asignaciones (tecnico2_id, fecha)'),
        ('idx_controles_tecnicos_asignacion', 'controles_tecnicos (asignacion_id, fecha, jornada, tipo_control)'),
        ('idx_items_control', 'items_control_tecnico (control_tecnico_id)'),
        ('idx_reportes_control', 'reportes (control_id)'),
        ('idx_reportes_fecha', 'reportes (fecha_hora)'),
        ('idx_bloqueados_camioneta', 'elementos_bloqueados (camioneta_id, resuelto)'),
        ('idx_seguimiento_reporte', 'seguimiento_remitos (reporte_id)'),
        ('idx_notificaciones_rol', 'notificaciones (destinatario_rol, leido)'),
        ('idx_controles_kilometraje', 'controles_tecnicos (asignacion_id, kilometraje)'),
    ]
    for nombre, definicion in indices:
        cursor.execute(f'CREATE INDEX IF NOT EXISTS {nombre} ON {definicion}')

    # El rol admin se dividió en dos: lo operativo (planillas, remitos) quedó
    # en soporte y admin pasó a ser solo configuración. Los usuarios que ya
    # existían eran todos operativos.
    hay_soporte = cursor.execute(
        "SELECT COUNT(*) FROM usuarios WHERE rol = 'soporte'").fetchone()[0]
    if not hay_soporte:
        movidos = cursor.execute(
            "UPDATE usuarios SET rol = 'soporte' WHERE rol = 'admin'").rowcount
        if movidos:
            print(f'🔧 Migración: {movidos} usuario(s) admin pasaron a soporte')

    # Solo sobre bases que ya tenían usuarios: en una instalación nueva los
    # crea insertar_datos_prueba(), que corre después de esta migración.
    hay_usuarios = cursor.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
    hay_admin = cursor.execute(
        "SELECT COUNT(*) FROM usuarios WHERE rol = 'admin'").fetchone()[0]
    existe_umber = cursor.execute(
        "SELECT COUNT(*) FROM usuarios WHERE usuario = 'umber'").fetchone()[0]
    if hay_usuarios and not hay_admin and not existe_umber:
        cursor.execute('''
            INSERT INTO usuarios (nombre, usuario, password, rol, activo)
            VALUES (?, ?, ?, 'admin', 1)
        ''', ('Umber', 'umber', hashear_password('umber123')))
        print('🔧 Migración: usuario admin "umber" creado')

    # Estados del seguimiento renombrados al ciclo de doble firma.
    cursor.execute('''
        UPDATE seguimiento_remitos SET estado = CASE estado
            WHEN 'PENDIENTE_FIRMA' THEN 'PENDIENTE_FIRMA_TECNICO'
            WHEN 'FIRMADO' THEN 'PENDIENTE_FIRMA_SOPORTE'
            WHEN 'REVISADO' THEN 'FINALIZADO'
            WHEN 'CERRADO' THEN 'FINALIZADO'
            ELSE estado END
        WHERE estado IN ('PENDIENTE_FIRMA', 'FIRMADO', 'REVISADO', 'CERRADO')
    ''')

    # Una asignación por camioneta/fecha/jornada: el código ya lo asume al hacer
    # "buscar y si existe actualizar", pero nada lo garantizaba a nivel base.
    try:
        cursor.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS idx_asignacion_unica
            ON asignaciones (camioneta_id, fecha, jornada)
        ''')
    except sqlite3.IntegrityError:
        print('⚠️ Hay asignaciones duplicadas (misma camioneta/fecha/jornada). '
              'No se pudo crear el índice único; revisar los datos.')

    conexion.commit()

def insertar_datos_prueba(conexion):
    cursor = conexion.cursor()
    
    cursor.execute('SELECT COUNT(*) as count FROM usuarios')
    count = cursor.fetchone()[0]
    
    if count == 0:
        cursor.execute('''
            INSERT INTO usuarios (nombre, usuario, password, rol, activo)
            VALUES (?, ?, ?, 'admin', 1)
        ''', ('Umber', 'umber', hashear_password('umber123')))

        soportes = [
            ('Luciano', 'luciano', 'lucho123'),
            ('Juan', 'juan', 'juan123'),
            ('Mateo', 'mateo', 'mateo123')
        ]
        for nombre, usuario, password in soportes:
            cursor.execute('''
                INSERT INTO usuarios (nombre, usuario, password, rol, activo)
                VALUES (?, ?, ?, 'soporte', 1)
            ''', (nombre, usuario, hashear_password(password)))
        
        cursor.execute('''
            INSERT INTO usuarios (nombre, usuario, password, rol, activo)
            VALUES (?, ?, ?, ?, ?)
        ''', ('Jefe de Flota', 'jefe', hashear_password('jefe123'), 'jefe', 1))
        
        tecnicos = [
            ('Ana Martínez', 'ana', 'ana123'),
            ('Carlos Gómez', 'carlos', 'carlos123'),
            ('Diego Morales', 'diego', 'diego123')
        ]
        for nombre, usuario, password in tecnicos:
            cursor.execute('''
                INSERT INTO usuarios (nombre, usuario, password, rol, activo)
                VALUES (?, ?, ?, ?, ?)
            ''', (nombre, usuario, hashear_password(password), 'tecnico', 1))
    
    # El catálogo arranca con los elementos que estaban fijos en el código.
    cursor.execute('SELECT COUNT(*) as count FROM elementos_catalogo')
    if cursor.fetchone()[0] == 0:
        orden = 0
        for categoria, elementos in CATALOGO_INICIAL.items():
            for nombre in elementos:
                cursor.execute('''
                    INSERT INTO elementos_catalogo (nombre, categoria, activo, orden)
                    VALUES (?, ?, 1, ?)
                ''', (nombre, categoria, orden))
                orden += 1

    cursor.execute('SELECT COUNT(*) as count FROM zonas')
    if cursor.fetchone()[0] == 0:
        # Se toman las zonas que ya se hayan usado en la planilla, más GUARDIA.
        usadas = [fila[0] for fila in cursor.execute('''
            SELECT DISTINCT TRIM(zona) FROM asignaciones
            WHERE zona IS NOT NULL AND TRIM(zona) <> ''
        ''')]
        for nombre in sorted(set(usadas) | {ZONA_GUARDIA}):
            cursor.execute('INSERT OR IGNORE INTO zonas (nombre, activa) VALUES (?, 1)', (nombre,))

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

def ultima_vez_ok(conexion, camioneta_id=None):
    """Última vez que cada elemento se registró OK, por camioneta.

    Se lee de items_control_tecnico, que guarda los 41 elementos de cada
    control. `reportes` solo almacena problemas, así que esta es la fuente
    para comparar "desde cuándo" un elemento dejó de estar en orden.

    Devuelve {(patente, elemento): {...}} o {elemento: {...}} si se pasa
    una camioneta concreta.

    Nota: SQLite garantiza que, con MAX() y GROUP BY, las columnas sueltas del
    SELECT provienen de la fila del máximo. Por eso el técnico y la fecha
    corresponden al mismo control.
    """
    filtro = 'AND a.camioneta_id = ?' if camioneta_id else ''
    parametros = (camioneta_id,) if camioneta_id else ()

    filas = conexion.execute(f'''
        SELECT
            cam.patente,
            ic.elemento,
            MAX(ic.fecha_hora) as fecha,
            ct.tipo_control,
            u.nombre as tecnico
        FROM items_control_tecnico ic
        JOIN controles_tecnicos ct ON ic.control_tecnico_id = ct.id
        JOIN asignaciones a ON ct.asignacion_id = a.id
        JOIN camionetas cam ON a.camioneta_id = cam.id
        LEFT JOIN usuarios u ON a.tecnico_id = u.id
        WHERE ic.estado = 'OK' {filtro}
        GROUP BY cam.patente, ic.elemento
    ''', parametros).fetchall()

    resultado = {}
    for fila in filas:
        datos = {
            'fecha': fila['fecha'],
            'tipo_control': fila['tipo_control'],
            'tecnico': fila['tecnico'],
        }
        clave = fila['elemento'] if camioneta_id else (fila['patente'], fila['elemento'])
        resultado[clave] = datos
    return resultado


def dias_desde(fecha_iso):
    """Días transcurridos desde una fecha ISO. None si no se puede interpretar."""
    if not fecha_iso:
        return None
    try:
        return (ahora() - datetime.fromisoformat(fecha_iso)).days
    except (ValueError, TypeError):
        return None


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
    if not autorizado('soporte', 'jefe', 'tecnico'):
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
                    extension = archivo.filename.rsplit('.', 1)[1].lower()
                    filename = secure_filename(
                        f"firma_{usuario_id}_{ahora().strftime('%Y%m%d%H%M%S')}.{extension}")
                    ruta_completa = UPLOAD_FOLDER / filename
                    archivo.save(str(ruta_completa))
                    
                    # Se guarda solo el nombre del archivo. Antes se guardaba la
                    # ruta absoluta de Windows, y la plantilla la partía con
                    # split('/') -> como la ruta usa "\", la imagen no cargaba.
                    # Además, así la base de datos se puede mover de máquina.
                    firma_anterior = usuario['firma'] if usuario else None
                    conexion.execute('UPDATE usuarios SET firma = ? WHERE id = ?',
                                     (filename, usuario_id))
                    conexion.commit()
                    
                    if firma_anterior:
                        borrar_firma(firma_anterior)
                    mensaje = '✅ Firma cargada exitosamente!'
                    usuario = conexion.execute('SELECT id, nombre, usuario, firma FROM usuarios WHERE id = ?', (usuario_id,)).fetchone()
                    
                except Exception as e:
                    error = f'Error al guardar la firma: {str(e)}'
    
    conexion.close()
    return render_template('admin_firma.html', usuario=usuario, mensaje=mensaje, error=error)

@app.route('/admin/firma/eliminar', methods=['POST'])
def eliminar_firma():
    if not autorizado('soporte', 'jefe', 'tecnico'):
        return jsonify({'success': False, 'error': 'No autorizado'}), 401
    
    usuario_id = session['usuario_id']
    
    conexion = get_db()
    try:
        usuario = conexion.execute('SELECT firma FROM usuarios WHERE id = ?', (usuario_id,)).fetchone()
        
        if usuario and usuario['firma']:
            borrar_firma(usuario['firma'])
            
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
    if not autorizado('jefe'):
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
    
    # elementos_por_categoria y etiqueta_categoria se pasaban acá pero la
    # plantilla no los usa, y el primero ni siquiera estaba definido: la página
    # entera respondía 500 por un NameError.
    return render_template('jefe_estadisticas.html',
                         stats_generales=stats_generales,
                         elementos_mas_faltantes=elementos_mas_faltantes,
                         tecnicos_mas_reportan=tecnicos_mas_reportan,
                         historial_por_elemento=historial_por_elemento)

# ============================================
# CAMBIO DE MANOS DE LA CAMIONETA
# ============================================
#
# El retiro y la devolución no dependen del turno sino de si la camioneta
# cambia de responsable:
#
#   - Hace falta RETIRO si en el turno anterior la tenía otra persona (o nadie).
#   - Hace falta DEVOLUCIÓN si en el turno siguiente la va a tener otra persona
#     (o nadie).
#
# Así, quien está de guardia y tiene la camioneta asignada mañana y tarde toda
# la semana la retira una vez al empezar y la devuelve al final, sin repetir el
# control en cada cambio de turno.

def _slot_vecino(fecha, jornada, hacia_adelante):
    """(fecha, jornada) del turno laborable inmediatamente anterior o siguiente."""
    paso = 1 if hacia_adelante else -1
    indice = orden_jornada(jornada)
    dia = fecha
    for _ in range(30):  # tope de seguridad: cubre feriados largos sin colgarse
        indice += paso
        if indice < 0:
            dia -= timedelta(days=1)
            indice = len(JORNADAS) - 1
        elif indice >= len(JORNADAS):
            dia += timedelta(days=1)
            indice = 0
        if jornada_laborable(JORNADAS[indice], dia):
            return dia, JORNADAS[indice]
    return None, None


def _asignacion_vecina(conexion, asignacion, hacia_adelante):
    """Asignación de la misma camioneta en el turno laborable contiguo.

    Devuelve None también cuando ese turno existe pero no tiene a nadie
    asignado. Ese hueco corta la cadena de responsabilidad: nadie garantiza
    quién usó la camioneta mientras tanto, así que hay que devolverla al
    terminar y volver a retirarla después.
    """
    try:
        fecha_dt = datetime.strptime(asignacion['fecha'], '%Y-%m-%d')
    except (ValueError, TypeError):
        return None

    fecha_vecina, jornada_vecina = _slot_vecino(
        fecha_dt, asignacion['jornada'], hacia_adelante)
    if fecha_vecina is None:
        return None

    return conexion.execute('''
        SELECT a.id, a.camioneta_id, a.fecha, a.jornada, a.tecnico_id, a.zona
        FROM asignaciones a
        WHERE a.camioneta_id = ? AND a.fecha = ? AND a.jornada = ?
          AND a.tecnico_id IS NOT NULL
    ''', (asignacion['camioneta_id'], fecha_vecina.strftime('%Y-%m-%d'),
          jornada_vecina)).fetchone()


def requiere_retiro(conexion, asignacion):
    """True si la camioneta llega desde otras manos y hay que revisarla."""
    anterior = _asignacion_vecina(conexion, asignacion, hacia_adelante=False)
    if anterior is None:
        return True
    return anterior['tecnico_id'] != asignacion['tecnico_id']


def requiere_devolucion(conexion, asignacion):
    """True si la camioneta pasa a otras manos y hay que entregarla revisada."""
    siguiente = _asignacion_vecina(conexion, asignacion, hacia_adelante=True)
    if siguiente is None:
        return True
    return siguiente['tecnico_id'] != asignacion['tecnico_id']


def turno_de_retiro(conexion, asignacion):
    """Asignación en la que esta camioneta fue retirada por el responsable actual.

    Cuando alguien conserva la camioneta varios turnos seguidos, el retiro se
    hizo en el primero de esa racha: es ahí donde hay que buscar el control.
    """
    actual = asignacion
    for _ in range(20):  # tope de seguridad
        anterior = _asignacion_vecina(conexion, actual, hacia_adelante=False)
        if anterior is None or anterior['tecnico_id'] != asignacion['tecnico_id']:
            return actual
        actual = anterior
    return actual


def retiro_abierto(conexion, camioneta_id):
    """Retiro hecho sobre esta camioneta que todavía no tiene su devolución.

    Mientras exista, la camioneta es responsabilidad de ese técnico: nadie más
    puede retirarla ni devolverla hasta que él la entregue revisada.
    """
    retiro = conexion.execute('''
        SELECT ct.fecha, ct.jornada, a.id AS asignacion_id, a.tecnico_id,
               u.nombre AS tecnico_nombre
        FROM controles_tecnicos ct
        JOIN asignaciones a ON ct.asignacion_id = a.id
        JOIN usuarios u ON a.tecnico_id = u.id
        WHERE a.camioneta_id = ? AND ct.tipo_control = 'RETIRO' AND ct.finalizado = 1
          AND COALESCE(ct.fuera_de_termino, 0) = 0
        ORDER BY ct.fecha DESC,
                 (CASE ct.jornada WHEN 'mañana' THEN 0 ELSE 1 END) DESC
        LIMIT 1
    ''', (camioneta_id,)).fetchone()

    if retiro is None:
        return None

    # La devolución se registra en el último turno de la racha, que no es el
    # mismo en el que se hizo el retiro: se busca por camioneta desde esa fecha.
    devuelta = conexion.execute('''
        SELECT ct.id
        FROM controles_tecnicos ct
        JOIN asignaciones a ON ct.asignacion_id = a.id
        WHERE a.camioneta_id = ? AND ct.tipo_control = 'DEVOLUCION' AND ct.finalizado = 1
          AND (ct.fecha > ?
               OR (ct.fecha = ?
                   AND (CASE ct.jornada WHEN 'mañana' THEN 0 ELSE 1 END) >= ?))
        LIMIT 1
    ''', (camioneta_id, retiro['fecha'], retiro['fecha'],
          orden_jornada(retiro['jornada']))).fetchone()

    return None if devuelta else retiro


def turno_de_devolucion(conexion, asignacion, momento=None):
    """Turno en el que corresponde registrar la devolución de esta racha.

    Simétrica de turno_de_retiro(), pero sin pasarse de los turnos que ya
    empezaron: la devolución se anota en el turno que se está cursando, no en
    el último que figure en la planilla. Eso es lo que permite que un técnico
    que conserva la camioneta toda la semana la devuelva igual al final de
    cada día si quiere controlarla más seguido, sin que el registro caiga en
    un turno del viernes que todavía no empezó.

    Con momento=None se recorre la racha completa, que es el turno donde la
    devolución vence si nadie la adelanta.
    """
    actual = asignacion
    for _ in range(40):  # tope de seguridad
        siguiente = _asignacion_vecina(conexion, actual, hacia_adelante=True)
        if siguiente is None or siguiente['tecnico_id'] != asignacion['tecnico_id']:
            return actual
        if momento is not None:
            try:
                fecha_dt = datetime.strptime(siguiente['fecha'], '%Y-%m-%d')
            except (ValueError, TypeError):
                return actual
            inicio, _ = inicio_fin_jornada(siguiente['jornada'], fecha_dt)
            if inicio is None or inicio > momento:
                return actual
        actual = siguiente
    return actual


def _detalle_custodia(conexion, camioneta, abierto, momento):
    """Datos de una camioneta retirada y no devuelta: dónde y cuándo cerrarla.

    La devolución no se registra en el turno del retiro sino en el último de la
    racha, así que hay que resolverlo acá: es el dato que le falta a la pantalla
    del técnico para poder ofrecerle el botón.
    """
    asignacion_retiro = conexion.execute('''
        SELECT id, camioneta_id, fecha, jornada, tecnico_id, zona
        FROM asignaciones WHERE id = ?
    ''', (abierto['asignacion_id'],)).fetchone()

    # Dónde se registra la devolución: el turno en curso de la racha.
    destino = (turno_de_devolucion(conexion, asignacion_retiro, momento)
               if asignacion_retiro else None)
    # Cuándo vence: el final de la racha completa, incluidos los turnos que
    # todavía no empezaron. Quien tiene la camioneta asignada toda la semana
    # no está en falta el martes.
    ultimo = (turno_de_devolucion(conexion, asignacion_retiro)
              if asignacion_retiro else None)

    vence = None
    if ultimo:
        try:
            fecha_dt = datetime.strptime(ultimo['fecha'], '%Y-%m-%d')
            _, fin = inicio_fin_jornada(ultimo['jornada'], fecha_dt)
            if fin:
                vence = fin + MARGEN_CONTROL
        except (ValueError, TypeError):
            pass

    # Una devolución empezada y no terminada: el técnico tiene que poder volver
    # a ella. Se busca por camioneta y técnico en vez de por la asignación que
    # calculamos arriba, porque el control pudo abrirse otro día de la racha y
    # entonces cuelga de otra asignación.
    activo = conexion.execute('''
        SELECT ct.id
        FROM controles_tecnicos ct
        JOIN asignaciones a ON ct.asignacion_id = a.id
        WHERE a.camioneta_id = ? AND a.tecnico_id = ?
          AND ct.tipo_control = 'DEVOLUCION' AND ct.finalizado = 0
          AND ct.fecha >= ?
        ORDER BY ct.id DESC LIMIT 1
    ''', (camioneta['id'], abierto['tecnico_id'], abierto['fecha'])).fetchone()

    vencida = bool(vence and momento > vence)
    return {
        'control_activo_id': activo['id'] if activo else None,
        'camioneta_id': camioneta['id'],
        'patente': camioneta['patente'],
        'tecnico_id': abierto['tecnico_id'],
        'tecnico': abierto['tecnico_nombre'],
        'retirada_fecha': abierto['fecha'],
        'retirada_jornada': abierto['jornada'],
        'asignacion_devolucion_id': destino['id'] if destino else abierto['asignacion_id'],
        'fecha_devolucion': destino['fecha'] if destino else abierto['fecha'],
        'jornada_devolucion': destino['jornada'] if destino else abierto['jornada'],
        'zona': (destino['zona'] if destino else '') or '',
        'vencido_desde': vence,
        'vencida': vencida,
        'horas': int((momento - vence).total_seconds() // 3600) if vencida else 0,
    }


def custodias_abiertas(conexion, momento=None, tecnico_id=None):
    """Camionetas retiradas que todavía nadie devolvió.

    Es el estado real de la flota, independiente de lo que diga la planilla de
    hoy. Mientras una custodia siga abierta la camioneta está bloqueada para
    todos, y el único que puede liberarla es el técnico que la retiró.
    """
    momento = momento or ahora()
    custodias = []
    for camioneta in conexion.execute(
            'SELECT id, patente FROM camionetas ORDER BY patente').fetchall():
        abierto = retiro_abierto(conexion, camioneta['id'])
        if abierto is None:
            continue
        if tecnico_id is not None and abierto['tecnico_id'] != tecnico_id:
            continue
        custodias.append(_detalle_custodia(conexion, camioneta, abierto, momento))
    return custodias


def custodia_de_camioneta(conexion, camioneta_id, momento=None):
    """La custodia abierta de una camioneta puntual, o None si está libre."""
    camioneta = conexion.execute(
        'SELECT id, patente FROM camionetas WHERE id = ?', (camioneta_id,)).fetchone()
    if camioneta is None:
        return None
    abierto = retiro_abierto(conexion, camioneta_id)
    if abierto is None:
        return None
    return _detalle_custodia(conexion, camioneta, abierto, momento or ahora())


# ============================================
# CONTROLES NO REALIZADOS
# ============================================

def controles_faltantes(conexion, momento=None, tecnico_id=None, camioneta_id=None):
    """Retiros que debían hacerse y nunca se completaron.

    No es lo mismo que una custodia abierta: acá la camioneta se usó sin
    revisarla, así que no hay constancia del estado en que estaba. Mientras el
    hueco siga abierto nadie más debería retirarla, porque si aparece algo roto
    no hay forma de saber de qué turno viene.

    Un control empezado y no terminado cuenta como faltante: lo que vale es el
    control completo, no haberlo abierto.

    Un hueco deja de contar cuando alguien controló la camioneta después: ahí
    volvió a haber constancia del estado, y seguir reclamando un turno viejo
    sería ruido. Lo que queda sin superar es lo que traba la camioneta.

    No lleva ventana de días a propósito. El hueco se cierra cuando el técnico
    hace el control tarde, cuando soporte lo libera, o cuando un control
    posterior lo supera; nunca por el simple paso del tiempo, porque entonces
    la camioneta quedaría trabada sin que nadie lo vea.
    """
    momento = momento or ahora()

    # Último control completo de cada camioneta, para saber hasta dónde hay
    # constancia del estado. Se compara por (fecha, orden de jornada).
    ultimo_control = {}
    for fila in conexion.execute('''
        SELECT a.camioneta_id, ct.fecha, ct.jornada
        FROM controles_tecnicos ct
        JOIN asignaciones a ON ct.asignacion_id = a.id
        WHERE ct.finalizado = 1
    '''):
        clave = (fila['fecha'], orden_jornada(fila['jornada']))
        actual = ultimo_control.get(fila['camioneta_id'])
        if actual is None or clave > actual:
            ultimo_control[fila['camioneta_id']] = clave

    sql = '''
        SELECT a.id, a.camioneta_id, a.fecha, a.jornada, a.tecnico_id, a.zona,
               c.patente, u.nombre AS tecnico
        FROM asignaciones a
        JOIN camionetas c ON a.camioneta_id = c.id
        JOIN usuarios u ON a.tecnico_id = u.id
        WHERE a.estado = 'ASIGNADA' AND a.tecnico_id IS NOT NULL
          AND a.fecha <= ?
          AND NOT EXISTS (
              SELECT 1 FROM controles_tecnicos ct
              WHERE ct.asignacion_id = a.id
                AND ct.tipo_control = 'RETIRO' AND ct.finalizado = 1
          )
    '''
    parametros = [momento.strftime('%Y-%m-%d')]
    if tecnico_id is not None:
        sql += ' AND a.tecnico_id = ?'
        parametros.append(tecnico_id)
    if camioneta_id is not None:
        sql += ' AND a.camioneta_id = ?'
        parametros.append(camioneta_id)
    sql += ' ORDER BY a.fecha DESC, a.jornada'

    faltantes = []
    for asignacion in conexion.execute(sql, parametros).fetchall():
        try:
            fecha = datetime.strptime(asignacion['fecha'], '%Y-%m-%d')
        except (ValueError, TypeError):
            continue

        inicio, fin = inicio_fin_jornada(asignacion['jornada'], fecha)
        if inicio is None:
            continue  # ese día no se trabaja en esa jornada

        vence = vencimiento_retiro(inicio, fin)
        if momento <= vence:
            continue  # todavía está en hora
        # Superado por un control posterior: la camioneta ya volvió a tener
        # constancia de su estado, así que este turno no traba nada. Va antes
        # que requiere_retiro() a propósito: esta comparación es de memoria y
        # aquella consulta la base por cada turno vecino.
        posterior = ultimo_control.get(asignacion['camioneta_id'])
        if posterior and posterior > (asignacion['fecha'],
                                      orden_jornada(asignacion['jornada'])):
            continue

        if not requiere_retiro(conexion, asignacion):
            continue  # venía con la camioneta del turno anterior

        # Si lo empezó y lo dejó por la mitad, se retoma ese mismo control.
        abierto = conexion.execute('''
            SELECT id FROM controles_tecnicos
            WHERE asignacion_id = ? AND tipo_control = 'RETIRO' AND finalizado = 0
            ORDER BY id DESC LIMIT 1
        ''', (asignacion['id'],)).fetchone()

        faltantes.append({
            'asignacion_id': asignacion['id'],
            'camioneta_id': asignacion['camioneta_id'],
            'patente': asignacion['patente'],
            'tecnico_id': asignacion['tecnico_id'],
            'tecnico': asignacion['tecnico'],
            'fecha': asignacion['fecha'],
            'jornada': asignacion['jornada'],
            'zona': asignacion['zona'] or '',
            'tipo': 'RETIRO',
            'control_activo_id': abierto['id'] if abierto else None,
            'vencido_desde': vence,
            'horas': int((momento - vence).total_seconds() // 3600),
        })

    faltantes.sort(key=lambda f: f['vencido_desde'], reverse=True)
    return faltantes


def falta_control_de(conexion, camioneta_id, momento=None, excepto_tecnico=None):
    """Huecos de control sobre una camioneta que impiden que otro la retire."""
    faltantes = controles_faltantes(conexion, momento, camioneta_id=camioneta_id)
    if excepto_tecnico is not None:
        faltantes = [f for f in faltantes if f['tecnico_id'] != excepto_tecnico]
    return faltantes

def vencimiento_retiro(inicio, fin):
    """Desde cuándo un retiro sin hacer cuenta como pendiente: media jornada.

    Arrancar el turno sin haber retirado la camioneta es normal (muchas veces
    el retiro se hace más tarde), así que recién se reclama pasada la mitad
    del turno.
    """
    return inicio + (fin - inicio) / 2


def controles_pendientes(conexion, momento=None):
    """Controles que deberían estar hechos y no lo están.

    Los RETIROS salen de controles_faltantes() y las DEVOLUCIONES de las
    custodias abiertas. Ninguno de los dos tiene ventana de días: antes los
    retiros se buscaban solo en la planilla de los últimos dos días y la alerta
    se borraba sola al tercero, mientras la camioneta seguía trabada sin que
    nadie se enterara.
    """
    momento = momento or ahora()

    # Quién tiene cada camioneta ahora mismo. Se calcula una sola vez porque
    # hace falta para cada hueco del recorrido.
    custodias = custodias_abiertas(conexion, momento)
    custodia_por_camioneta = {c['camioneta_id']: c for c in custodias}
    deuda_por_tecnico = {}
    for custodia in custodias:
        deuda_por_tecnico.setdefault(custodia['tecnico_id'], []).append(custodia)

    pendientes = []
    for falta in controles_faltantes(conexion, momento):
        # Si ya la tiene retirada, el retiro está hecho aunque sea de otro turno.
        custodia = custodia_por_camioneta.get(falta['camioneta_id'])
        if custodia is not None and custodia['tecnico_id'] == falta['tecnico_id']:
            continue

        # Un técnico que debe una devolución tiene el retiro bloqueado: no es
        # que no quiera hacerlo, es que el sistema no se lo permite. Soporte
        # necesita ver esa diferencia para saber a qué atender.
        deudas = [d for d in deuda_por_tecnico.get(falta['tecnico_id'], [])
                  if d['camioneta_id'] != falta['camioneta_id']]
        pendientes.append({**falta,
                           'bloqueado_por_deuda': ', '.join(d['patente'] for d in deudas)})

    # Las devoluciones salen de las custodias abiertas, no del recorrido de
    # arriba: así siguen reclamándose por más viejas que sean.
    for custodia in custodias:
        if not custodia['vencida']:
            continue
        pendientes.append({
            'asignacion_id': custodia['asignacion_devolucion_id'],
            'camioneta_id': custodia['camioneta_id'],
            'patente': custodia['patente'],
            'tecnico': custodia['tecnico'],
            'fecha': custodia['fecha_devolucion'],
            'jornada': custodia['jornada_devolucion'],
            'zona': custodia['zona'],
            'tipo': 'DEVOLUCION',
            'bloqueado_por_deuda': '',
            'vencido_desde': custodia['vencido_desde'],
            'horas': custodia['horas'],
        })

    pendientes.sort(key=lambda p: p['vencido_desde'], reverse=True)
    return pendientes


# ============================================
# CALENDARIO DE VENCIMIENTOS
# ============================================

def _fecha_iso(valor):
    """'2026-09-16' -> date, o None. Acepta también un datetime ISO completo."""
    if not valor:
        return None
    try:
        return datetime.strptime(str(valor)[:10], '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def estado_vencimiento(vencimiento, km_actual, hoy=None):
    """Cuánto le falta a un vencimiento y si hay que avisar.

    Un vencimiento puede tener plazo por fecha, por kilómetros o por los dos.
    Cuando tiene los dos (el service) manda el que llegue primero: si la
    camioneta hace 10.000 km en seis meses, el service es a los seis meses.

    Devuelve siempre las dos cuentas para poder mostrarlas, más el estado que
    resulta de la peor de las dos.
    """
    hoy = hoy or ahora().date()

    fecha = _fecha_iso(vencimiento['fecha_vencimiento'])
    dias = (fecha - hoy).days if fecha else None

    km_objetivo = vencimiento['km_vencimiento']
    km_faltantes = (km_objetivo - km_actual
                    if km_objetivo is not None and km_actual is not None else None)

    aviso_dias = vencimiento['aviso_dias']
    aviso_km = vencimiento['aviso_km']

    def clasificar(restante, aviso):
        if restante is None:
            return None
        if restante < 0:
            return 'VENCIDO'
        if aviso is not None and restante <= aviso:
            return 'POR_VENCER'
        return 'AL_DIA'

    por_fecha = clasificar(dias, aviso_dias)
    por_km = clasificar(km_faltantes, aviso_km)

    candidatos = [c for c in (por_fecha, por_km) if c]
    if not candidatos:
        estado = 'SIN_DATOS'
        motivo = None
    else:
        estado = min(candidatos, key=lambda c: ORDEN_ESTADO[c])
        motivo = 'fecha' if por_fecha == estado else 'km'

    if estado == 'SIN_DATOS':
        detalle = 'Sin cargar'
    elif motivo == 'fecha':
        if dias < 0:
            detalle = f'Vencido hace {abs(dias)} día{"s" if abs(dias) != 1 else ""}'
        elif dias == 0:
            detalle = 'Vence hoy'
        else:
            detalle = f'Faltan {dias} día{"s" if dias != 1 else ""}'
    else:
        if km_faltantes < 0:
            detalle = f'Pasado por {miles(abs(km_faltantes))} km'
        else:
            detalle = f'Faltan {miles(km_faltantes)} km'

    return {
        'estado': estado,
        'motivo': motivo,
        'dias': dias,
        'km_faltantes': km_faltantes,
        'detalle': detalle,
    }


def estado_flota(conexion, momento=None, camioneta_id=None):
    """Todos los vencimientos de la flota con su estado, ordenados por urgencia.

    Las camionetas a las que todavía no se les cargó un vencimiento aparecen
    igual, en SIN_DATOS: si se omitieran, el calendario diría que está todo al
    día cuando en realidad no se sabe nada.
    """
    momento = momento or ahora()
    hoy = momento.date()

    sql = 'SELECT id, patente FROM camionetas WHERE activa = 1'
    parametros = []
    if camioneta_id is not None:
        sql += ' AND id = ?'
        parametros.append(camioneta_id)
    camionetas = conexion.execute(sql + ' ORDER BY patente', parametros).fetchall()

    cargados = {}
    for fila in conexion.execute('SELECT * FROM vencimientos WHERE activo = 1'):
        cargados[(fila['camioneta_id'], fila['tipo'])] = fila

    filas = []
    for camioneta in camionetas:
        km_actual = ultimo_kilometraje(conexion, camioneta['id'])
        for tipo, config in TIPOS_VENCIMIENTO.items():
            guardado = cargados.get((camioneta['id'], tipo))
            vencimiento = guardado if guardado is not None else {
                'fecha_vencimiento': None, 'km_vencimiento': None,
                'aviso_dias': config['aviso_dias'], 'aviso_km': config['aviso_km'],
            }
            estado = estado_vencimiento(vencimiento, km_actual, hoy)

            ultimo = conexion.execute('''
                SELECT fecha_realizado, km_realizado, registrado_por, observacion
                FROM vencimientos_historial
                WHERE camioneta_id = ? AND tipo = ?
                ORDER BY fecha_realizado DESC, id DESC LIMIT 1
            ''', (camioneta['id'], tipo)).fetchone()

            filas.append({
                'camioneta_id': camioneta['id'],
                'patente': camioneta['patente'],
                'tipo': tipo,
                'etiqueta': config['etiqueta'],
                'icono': config['icono'],
                'color': config['color'],
                'ayuda': config['ayuda'],
                'km_actual': km_actual,
                'fecha_vencimiento': vencimiento['fecha_vencimiento'],
                'km_vencimiento': vencimiento['km_vencimiento'],
                'periodicidad_dias': (guardado['periodicidad_dias'] if guardado
                                      else config['periodicidad_dias']),
                'periodicidad_km': (guardado['periodicidad_km'] if guardado
                                    else config['periodicidad_km']),
                'aviso_dias': vencimiento['aviso_dias'] if guardado else config['aviso_dias'],
                'aviso_km': vencimiento['aviso_km'] if guardado else config['aviso_km'],
                'observacion': guardado['observacion'] if guardado else '',
                'configurado': guardado is not None,
                'ultimo': dict(ultimo) if ultimo else None,
                **estado,
            })

    filas.sort(key=lambda f: (ORDEN_ESTADO[f['estado']],
                              f['dias'] if f['dias'] is not None else 9999,
                              f['patente']))
    return filas


def vencimientos_alerta(conexion, momento=None):
    """Lo que hay que avisar hoy: vencido o a punto de vencer.

    SIN_DATOS queda afuera a propósito: que falte cargar la fecha de la VTV es
    un pendiente de carga, no una urgencia de la flota, y mezclarlos taparía
    las alertas reales.
    """
    return [f for f in estado_flota(conexion, momento)
            if f['estado'] in ('VENCIDO', 'POR_VENCER')]


def proximo_vencimiento(config_dias, config_km, desde_fecha, desde_km):
    """(fecha, km) del siguiente vencimiento después de hacer el trabajo."""
    fecha = None
    if config_dias:
        base = _fecha_iso(desde_fecha) or ahora().date()
        fecha = (base + timedelta(days=int(config_dias))).strftime('%Y-%m-%d')

    km = None
    if config_km and desde_km is not None:
        km = int(desde_km) + int(config_km)

    return fecha, km


def registrar_realizado(conexion, camioneta_id, tipo, fecha, km, quien, observacion):
    """Anota el trabajo hecho y corre el vencimiento al próximo período.

    Es un solo movimiento a propósito: si se registrara el lavado sin mover la
    fecha, la alerta seguiría sonando y alguien terminaría apagándola a mano.
    """
    config = TIPOS_VENCIMIENTO[tipo]
    actual = conexion.execute(
        'SELECT * FROM vencimientos WHERE camioneta_id = ? AND tipo = ?',
        (camioneta_id, tipo)).fetchone()

    periodicidad_dias = actual['periodicidad_dias'] if actual else config['periodicidad_dias']
    periodicidad_km = actual['periodicidad_km'] if actual else config['periodicidad_km']
    aviso_dias = actual['aviso_dias'] if actual else config['aviso_dias']
    aviso_km = actual['aviso_km'] if actual else config['aviso_km']

    conexion.execute('''
        INSERT INTO vencimientos_historial
            (camioneta_id, tipo, fecha_realizado, km_realizado, registrado_por,
             observacion, fecha_registro)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (camioneta_id, tipo, fecha, km, quien, observacion, ahora().isoformat()))

    nueva_fecha, nuevo_km = proximo_vencimiento(
        periodicidad_dias, periodicidad_km, fecha, km)

    if actual:
        conexion.execute('''
            UPDATE vencimientos
            SET fecha_vencimiento = ?, km_vencimiento = ?, activo = 1
            WHERE id = ?
        ''', (nueva_fecha, nuevo_km, actual['id']))
    else:
        conexion.execute('''
            INSERT INTO vencimientos
                (camioneta_id, tipo, fecha_vencimiento, km_vencimiento,
                 periodicidad_dias, periodicidad_km, aviso_dias, aviso_km, activo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
        ''', (camioneta_id, tipo, nueva_fecha, nuevo_km, periodicidad_dias,
              periodicidad_km, aviso_dias, aviso_km))

    return nueva_fecha, nuevo_km


def calendario_mes(conexion, anio, mes, momento=None):
    """Semanas del mes con lo que se hizo y lo que vence cada día.

    Se mezclan tres cosas en la misma grilla, que es lo que hace útil la vista:
    los trabajos ya hechos (lavado, service...), los vencimientos que caen ese
    día, y cuántos controles de camioneta se hicieron.
    """
    momento = momento or ahora()
    primero = datetime(anio, mes, 1).date()
    ultimo_dia = calendario_py.monthrange(anio, mes)[1]
    ultimo = datetime(anio, mes, ultimo_dia).date()
    desde, hasta = primero.strftime('%Y-%m-%d'), ultimo.strftime('%Y-%m-%d')

    eventos = {}

    def agregar(dia, evento):
        eventos.setdefault(dia, []).append(evento)

    for fila in conexion.execute('''
            SELECT h.tipo, h.fecha_realizado, h.km_realizado, h.registrado_por,
                   h.observacion, c.patente
            FROM vencimientos_historial h
            JOIN camionetas c ON h.camioneta_id = c.id
            WHERE h.fecha_realizado BETWEEN ? AND ?
            ORDER BY h.fecha_realizado, c.patente
        ''', (desde, hasta)):
        config = TIPOS_VENCIMIENTO.get(fila['tipo'], {})
        agregar(fila['fecha_realizado'][:10], {
            'clase': 'hecho',
            'tipo': fila['tipo'],
            'etiqueta': config.get('etiqueta', fila['tipo']),
            'icono': config.get('icono', 'check'),
            'color': config.get('color', '#6c757d'),
            'patente': fila['patente'],
            'detalle': (f"{miles(fila['km_realizado'])} km" if fila['km_realizado'] else ''),
            'texto': f"{config.get('etiqueta', fila['tipo'])} · {fila['patente']}",
            'observacion': fila['observacion'] or '',
            'quien': fila['registrado_por'] or '',
        })

    for fila in conexion.execute('''
            SELECT v.tipo, v.fecha_vencimiento, v.km_vencimiento, c.patente
            FROM vencimientos v
            JOIN camionetas c ON v.camioneta_id = c.id
            WHERE v.activo = 1 AND v.fecha_vencimiento BETWEEN ? AND ?
            ORDER BY v.fecha_vencimiento, c.patente
        ''', (desde, hasta)):
        config = TIPOS_VENCIMIENTO.get(fila['tipo'], {})
        vencido = _fecha_iso(fila['fecha_vencimiento']) < momento.date()
        agregar(fila['fecha_vencimiento'][:10], {
            'clase': 'vencido' if vencido else 'vence',
            'tipo': fila['tipo'],
            'etiqueta': config.get('etiqueta', fila['tipo']),
            'icono': config.get('icono', 'calendar'),
            'color': config.get('color', '#6c757d'),
            'patente': fila['patente'],
            'detalle': (f"a los {miles(fila['km_vencimiento'])} km"
                        if fila['km_vencimiento'] else ''),
            'texto': (f"{'Venció' if vencido else 'Vence'} "
                      f"{config.get('etiqueta', fila['tipo'])} · {fila['patente']}"),
            'observacion': '',
            'quien': '',
        })

    # Los controles diarios van aparte de los vencimientos: son muchos y de otra
    # naturaleza. En la grilla se muestran como un solo contador, y el detalle
    # queda para cuando se abre el día.
    controles = {}
    for fila in conexion.execute('''
            SELECT ct.fecha, ct.jornada, ct.tipo_control, ct.kilometraje,
                   ct.fecha_hora_fin, ct.forzado_por,
                   c.patente, u.nombre AS tecnico
            FROM controles_tecnicos ct
            JOIN asignaciones a ON ct.asignacion_id = a.id
            JOIN camionetas c ON a.camioneta_id = c.id
            JOIN usuarios u ON a.tecnico_id = u.id
            WHERE ct.finalizado = 1 AND ct.fecha BETWEEN ? AND ?
            ORDER BY ct.fecha, ct.fecha_hora_fin
        ''', (desde, hasta)):
        fin = _a_fecha(fila['fecha_hora_fin'])
        controles.setdefault(fila['fecha'][:10], []).append({
            'patente': fila['patente'],
            'tecnico': fila['tecnico'],
            'tipo': fila['tipo_control'],
            'jornada': fila['jornada'],
            'hora': fin.strftime('%H:%M') if fin else '',
            'km': miles(fila['kilometraje']) if fila['kilometraje'] is not None else '',
            'forzado_por': fila['forzado_por'] or '',
        })

    semanas = []
    hoy = momento.strftime('%Y-%m-%d')
    for semana in calendario_py.Calendar(firstweekday=0).monthdatescalendar(anio, mes):
        dias = []
        for dia in semana:
            clave = dia.strftime('%Y-%m-%d')
            del_dia = eventos.get(clave, [])
            dias.append({
                'fecha': clave,
                'numero': dia.day,
                'del_mes': dia.month == mes,
                'es_hoy': clave == hoy,
                'etiqueta_larga': f'{dia.day} de {MESES[dia.month - 1]} de {dia.year}',
                'eventos': del_dia,
                'controles': controles.get(clave, []),
                'tiene': sorted({e['clase'] for e in del_dia} |
                                ({'control'} if controles.get(clave) else set())),
            })
        semanas.append(dias)
    return semanas


# ============================================
# CONTRASEÑAS
# ============================================

def es_hash(valor):
    """True si el valor guardado ya es un hash de werkzeug y no texto plano."""
    return bool(valor) and str(valor).startswith(('pbkdf2:', 'scrypt:', 'argon2'))


def hashear_password(password):
    return generate_password_hash(password)


def verificar_password(conexion, usuario, password):
    """Valida la contraseña y migra al vuelo las que están en texto plano.

    Las contraseñas originales estaban guardadas sin cifrar. En el primer
    login de cada usuario se comprueba contra el texto plano y, si coincide,
    se reemplaza por su hash. Nadie tiene que cambiar su contraseña.
    """
    guardada = usuario['password']

    if es_hash(guardada):
        return check_password_hash(guardada, password)

    # Comparación en tiempo constante para no filtrar información por el tiempo
    # de respuesta mientras queden contraseñas sin migrar.
    if not secrets.compare_digest(str(guardada), password):
        return False

    try:
        conexion.execute('UPDATE usuarios SET password = ? WHERE id = ?',
                         (hashear_password(password), usuario['id']))
        conexion.commit()
        print(f"🔒 Contraseña de '{usuario['usuario']}' migrada a hash")
    except sqlite3.Error as e:
        # Si falla la migración el usuario igual entra; se reintenta la próxima.
        print(f"⚠️ No se pudo migrar la contraseña de '{usuario['usuario']}': {e}")

    return True


# ============================================
# RUTAS DE LOGIN
# ============================================

@app.route('/')
def login():
    if 'usuario_id' in session:
        return redirect(url_for(PANEL_POR_ROL.get(session.get('rol'), 'tecnico')))
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def procesar_login():
    usuario = request.form.get('usuario')
    password = request.form.get('password')
    
    if not usuario or not password:
        return render_template('login.html', error='Usuario y contraseña son requeridos')
    
    conexion = get_db()
    try:
        user = conexion.execute('''
            SELECT * FROM usuarios WHERE usuario = ? AND activo = 1
        ''', (usuario,)).fetchone()
        
        if not user or not verificar_password(conexion, user, password):
            return render_template('login.html', error='Usuario o contraseña incorrectos')
    finally:
        conexion.close()
    
    session.clear()
    session['usuario_id'] = user['id']
    session['nombre'] = user['nombre']
    session['rol'] = user['rol']
    
    return redirect(url_for(PANEL_POR_ROL.get(user['rol'], 'tecnico')))

def consultar_reportes(conexion):
    """Todos los reportes con su camioneta y su técnico."""
    return conexion.execute('''
        SELECT
            r.id, r.tipo, r.elemento, r.estado, r.descripcion, r.fecha_hora,
            r.fecha_resolucion, r.comentario_resolucion, r.resuelto_por,
            r.ruta_remito, r.material_entregado, r.motivo_reposicion,
            COALESCE(cam.patente, 'SIN ASIGNAR') as patente,
            COALESCE(u.nombre, 'TÉCNICO DESCONOCIDO') as tecnico_nombre
        FROM reportes r
        LEFT JOIN controles co ON r.control_id = co.id
        LEFT JOIN asignaciones a ON co.asignacion_id = a.id
        LEFT JOIN camionetas cam ON a.camioneta_id = cam.id
        LEFT JOIN usuarios u ON a.tecnico_id = u.id
        ORDER BY r.fecha_hora DESC
    ''').fetchall()


def agrupar_reportes(conexion, reportes):
    """Agrupa los reportes por patente y arma la lista de faltantes vigentes.

    Se usa tanto al renderizar el panel como al refrescarlo por API: el
    faltante tiene que desaparecer de la pantalla apenas se cierra su remito,
    sin obligar a cerrar sesión.
    """
    reportes_por_patente = {}
    for reporte in reportes:
        reportes_por_patente.setdefault(reporte['patente'], []).append(dict(reporte))

    # Última vez que cada elemento estuvo OK, para saber desde cuándo falta.
    ultima_ok = ultima_vez_ok(conexion)

    faltantes_por_patente = {}
    for patente, registros in reportes_por_patente.items():
        dedupe = {}
        for r in registros:
            if r['estado'] in ('FALLA', 'FALTANTE', 'OBSERVACION') and r['elemento'] not in dedupe:
                referencia = ultima_ok.get((patente, r['elemento']))
                r['ultima_ok'] = referencia['fecha'] if referencia else None
                r['ultima_ok_tecnico'] = referencia['tecnico'] if referencia else None
                r['dias_sin_ok'] = dias_desde(r['ultima_ok'])
                dedupe[r['elemento']] = r
        faltantes_por_patente[patente] = list(dedupe.values())

    return reportes_por_patente, sorted(reportes_por_patente.keys()), faltantes_por_patente


# ============================================
# RUTAS DE ADMINISTRADOR
# ============================================

@app.route('/admin')
def admin():
    if not autorizado('soporte'):
        return redirect(url_for('login'))
    
    fecha_seleccionada = request.args.get('fecha', ahora().strftime('%Y-%m-%d'))
    jornada_seleccionada = request.args.get('jornada', 'mañana')
    fecha_actual = ahora().strftime('%d/%m/%Y')
    
    conexion = get_db()
    
    try:
        tecnicos = obtener_tecnicos()
        camionetas = obtener_camionetas()
        zonas = zonas_activas(conexion)

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
            reportes = consultar_reportes(conexion)
            
            reportes_por_patente, patentes_con_reportes, faltantes_por_patente = \
                agrupar_reportes(conexion, reportes)
                
            # Controles que ya deberían estar hechos y no lo están.
            pendientes_control = controles_pendientes(conexion)
            # VTV, matafuego, service y lavado vencidos o por vencer.
            vencimientos = vencimientos_alerta(conexion)
            
        except sqlite3.OperationalError as e:
            # Antes faltaba inicializar `reportes`, y este except terminaba
            # rompiendo el render con un NameError en lugar de degradar.
            print(f"⚠️ No se pudieron leer los reportes: {e}")
            reportes = []
            reportes_por_patente = {}
            patentes_con_reportes = []
            faltantes_por_patente = {}
            pendientes_control = []
            vencimientos = []
        
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
                         pendientes_control=pendientes_control,
                         vencimientos=vencimientos,
                         zonas=zonas,
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
    if not autorizado('soporte'):
        return redirect(url_for('login'))
    
    fecha = request.form.get('fecha')
    jornada = request.form.get('jornada')
    
    if not fecha or not jornada:
        return redirect(url_for('admin', error='Fecha y jornada son requeridas'))
    
    if not jornada_valida(jornada):
        return redirect(url_for('admin', error='Jornada inválida'))
    
    try:
        datetime.strptime(fecha, '%Y-%m-%d')
    except ValueError:
        return redirect(url_for('admin', error='Fecha inválida'))
    
    conexion = get_db()
    
    try:
        # Un técnico no puede estar en dos camionetas en la misma jornada.
        # Esto ya se validaba en el navegador, pero no en el servidor.
        asignados = set()
        for camioneta_id in request.form.getlist('camioneta_ids'):
            for campo in (f'tecnico_{camioneta_id}', f'tecnico2_{camioneta_id}'):
                valor = request.form.get(campo)
                if not valor:
                    continue
                if valor in asignados:
                    return redirect(url_for('admin', fecha=fecha, jornada=jornada,
                        error='Un mismo técnico está asignado a más de una camioneta.'))
                asignados.add(valor)
        
        for camioneta_id in request.form.getlist('camioneta_ids'):
            camioneta_id = int(camioneta_id)
            tecnico_id = request.form.get(f'tecnico_{camioneta_id}') or None
            tecnico2_id = request.form.get(f'tecnico2_{camioneta_id}') or None
            zona = (request.form.get(f'zona_{camioneta_id}') or '').strip()
            
            if tecnico_id and tecnico_id == tecnico2_id:
                return redirect(url_for('admin', fecha=fecha, jornada=jornada,
                    error='El técnico responsable y el acompañante no pueden ser el mismo.'))
            
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
        return redirect(url_for('admin', fecha=fecha, jornada=jornada,
                                error=f'Error al guardar: {str(e)}'))
    finally:
        conexion.close()
    
    return redirect(url_for('admin', fecha=fecha, jornada=jornada, mensaje=mensaje))

@app.route('/admin/semana', methods=['GET', 'POST'])
def asignacion_semanal():
    if not autorizado('soporte'):
        return redirect(url_for('login'))
    
    jornada = request.args.get('jornada', 'mañana')
    if not jornada_valida(jornada):
        jornada = 'mañana'
    fecha_inicio = request.args.get('fecha_inicio', ahora().strftime('%Y-%m-%d'))
    
    dias_semana = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
    
    # Una fecha inválida en la URL rompía la pantalla con un ValueError.
    try:
        fecha_dt = datetime.strptime(fecha_inicio, '%Y-%m-%d')
    except ValueError:
        fecha_dt = ahora()
        fecha_inicio = fecha_dt.strftime('%Y-%m-%d')
    inicio_semana = fecha_dt - timedelta(days=fecha_dt.weekday())
    fechas_semana = [inicio_semana + timedelta(days=i) for i in range(7)]
    
    conexion = get_db()
    
    try:
        tecnicos = obtener_tecnicos()
        camionetas = obtener_camionetas()
        zonas = zonas_activas(conexion)

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
                         zonas=zonas,
                         camionetas=camionetas,
                         dias_semana=dias_semana,
                         fechas_semana=fechas_semana,
                         asignaciones_por_dia=asignaciones_por_dia,
                         jornada=jornada,
                         fecha_inicio=fecha_inicio,
                         mensaje=request.args.get('mensaje', ''),
                         error=request.args.get('error', ''))

@app.route('/guardar-semana', methods=['POST'])
def guardar_semana():
    if not autorizado('soporte'):
        return redirect(url_for('login'))
    
    fechas = request.form.getlist('fechas[]')
    jornada = request.form.get('jornada', 'mañana')
    fecha_inicio = fechas[0] if fechas else ahora().strftime('%Y-%m-%d')
    
    if not jornada_valida(jornada):
        return redirect(url_for('asignacion_semanal', error='Jornada inválida'))
    
    camioneta_ids = request.form.getlist('camioneta_ids')
    
    # Un técnico por camioneta y por día, igual que en la planilla diaria.
    for fecha in fechas:
        asignados = set()
        for camioneta_id in camioneta_ids:
            for campo in (f'tecnico_{camioneta_id}_{fecha}', f'tecnico2_{camioneta_id}_{fecha}'):
                valor = request.form.get(campo)
                if not valor:
                    continue
                if valor in asignados:
                    return redirect(url_for('asignacion_semanal', jornada=jornada,
                        fecha_inicio=fecha_inicio,
                        error=f'Un mismo técnico quedó en más de una camioneta el {fecha}.'))
                asignados.add(valor)
    
    conexion = get_db()
    
    try:
        for camioneta_id in camioneta_ids:
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
        return redirect(url_for('asignacion_semanal', jornada=jornada,
                                fecha_inicio=fecha_inicio,
                                error=f'Error al guardar: {str(e)}'))
    finally:
        conexion.close()
    
    # Se vuelve a la misma semana y jornada que se estaba editando.
    return redirect(url_for('asignacion_semanal', jornada=jornada,
                            fecha_inicio=fecha_inicio, mensaje=mensaje))

# ============================================
# RUTAS DE TÉCNICO
# ============================================

@app.route('/tecnico')
def tecnico():
    if 'usuario_id' not in session or session.get('rol') != 'tecnico':
        return redirect(url_for('login'))
    
    usuario_id = session['usuario_id']
    momento = ahora()
    fecha_actual = momento.strftime('%Y-%m-%d')
    
    conexion = get_db()
    
    # Se busca la asignación entre las jornadas activas, por orden de prioridad.
    # Si el técnico solo tiene una de las dos, se usa esa: en el solapamiento de
    # 14:30 a 14:45 no hay que hacerlo elegir.
    asignacion = None
    jornada_actual_tecnico = jornada_actual(momento)
    candidatas = jornadas_activas(momento) or [jornada_actual_tecnico]
    
    for jornada in candidatas:
        asignacion = conexion.execute('''
            SELECT a.id, a.fecha, a.jornada, a.estado, a.zona, a.camioneta_id,
                   a.tecnico_id, a.tecnico2_id,
                   c.patente as camioneta_patente,
                   u1.nombre as tecnico_nombre,
                   u2.nombre as tecnico2_nombre
            FROM asignaciones a
            JOIN camionetas c ON a.camioneta_id = c.id
            LEFT JOIN usuarios u1 ON a.tecnico_id = u1.id
            LEFT JOIN usuarios u2 ON a.tecnico2_id = u2.id
            WHERE (a.tecnico_id = ? OR a.tecnico2_id = ?)
            AND a.fecha = ? 
            AND a.jornada = ?
            AND a.estado = 'ASIGNADA'
        ''', (usuario_id, usuario_id, fecha_actual, jornada)).fetchone()
        if asignacion:
            jornada_actual_tecnico = jornada
            break
    
    # El técnico 1 es el responsable del control; el acompañante solo lo ve.
    es_responsable = bool(asignacion) and asignacion['tecnico_id'] == usuario_id

    # Camionetas que este técnico retiró y nunca devolvió. Se calcula siempre,
    # tenga o no asignación hoy: antes la pantalla solo miraba la asignación
    # del día, así que una devolución colgada de la semana pasada era invisible
    # para él mientras la camioneta quedaba bloqueada para todos los demás.
    custodias = custodias_abiertas(conexion, momento, tecnico_id=usuario_id)

    # Retiros que este técnico nunca completó. Igual que las deudas, se buscan
    # por técnico y no por la asignación de hoy: el control que falta casi
    # siempre es de otro día, y antes no tenía forma de llegar a él.
    faltantes = controles_faltantes(conexion, momento, tecnico_id=usuario_id)

    control_retiro_activo = None
    control_devolucion_activo = None
    tiene_camioneta = False
    devolucion_completada = False
    necesita_retiro = True
    necesita_devolucion = True
    es_guardia = False
    asignacion_devolucion_id = None
    jornada_devolucion = jornada_actual_tecnico
    devolucion_en_otro_turno = False
    retirada_fecha = None
    retirada_jornada = None

    bloqueada_por = None

    if asignacion:
        abierto = retiro_abierto(conexion, asignacion['camioneta_id'])
        if abierto is not None and abierto['tecnico_id'] != usuario_id:
            bloqueada_por = abierto['tecnico_nombre']

        es_guardia = (asignacion['zona'] or '').strip().upper() == ZONA_GUARDIA
        necesita_retiro = requiere_retiro(conexion, asignacion)
        necesita_devolucion = requiere_devolucion(conexion, asignacion)

        # Lo que decide qué botón va no es la planilla sino la custodia: tener
        # la camioneta en la mano. Así el técnico que la devolvió de más (por
        # control propio, al terminar el día) puede volver a retirarla al día
        # siguiente aunque la planilla diga que es la misma racha.
        mia = next((c for c in custodias
                    if c['camioneta_id'] == asignacion['camioneta_id']), None)
        tiene_camioneta = mia is not None

        if mia:
            asignacion_devolucion_id = mia['asignacion_devolucion_id']
            jornada_devolucion = mia['jornada_devolucion']
            devolucion_en_otro_turno = mia['asignacion_devolucion_id'] != asignacion['id']
            retirada_fecha = mia['retirada_fecha']
            retirada_jornada = mia['retirada_jornada']
        else:
            asignacion_devolucion_id = asignacion['id']

        def buscar_control(asignacion_id, tipo, finalizado):
            return conexion.execute('''
                SELECT * FROM controles_tecnicos
                WHERE asignacion_id = ? AND tipo_control = ? AND finalizado = ?
                ORDER BY id DESC LIMIT 1
            ''', (asignacion_id, tipo, finalizado)).fetchone()

        control_retiro_activo = buscar_control(asignacion['id'], 'RETIRO', 0)
        control_devolucion_activo = buscar_control(asignacion_devolucion_id, 'DEVOLUCION', 0)
        devolucion_completada = buscar_control(asignacion['id'], 'DEVOLUCION', 1) is not None

    # Deudas: custodias sobre otras camionetas. Mientras existan, este técnico
    # no puede retirar nada nuevo.
    deudas = [c for c in custodias
              if not asignacion or c['camioneta_id'] != asignacion['camioneta_id']]

    # El hueco de la camioneta de hoy se resuelve desde la tarjeta del día; el
    # resto va en su propio panel.
    faltantes_otros = [f for f in faltantes
                       if not asignacion or f['camioneta_id'] != asignacion['camioneta_id']]

    # Con la camioneta de hoy sin controlar de un turno anterior, el retiro
    # normal no corresponde: primero hay que cerrar ese hueco.
    falta_de_hoy = next((f for f in faltantes
                         if asignacion and f['camioneta_id'] == asignacion['camioneta_id']
                         and f['asignacion_id'] != asignacion['id']), None)

    # Y si el hueco lo dejó otro técnico, esta camioneta no se puede retirar.
    trabada_por_hueco = ''
    if asignacion:
        ajenos = falta_control_de(conexion, asignacion['camioneta_id'], momento,
                                  excepto_tecnico=usuario_id)
        if ajenos:
            trabada_por_hueco = ', '.join(sorted({f['tecnico'] for f in ajenos}))

    elementos_bloqueados = []
    if asignacion:
        bloqueados = conexion.execute('''
            SELECT elemento, tipo, motivo, fecha_bloqueo
            FROM elementos_bloqueados
            WHERE camioneta_id = ? AND resuelto = 0
            ORDER BY elemento
        ''', (asignacion['camioneta_id'],)).fetchall()
        elementos_bloqueados = [dict(b) for b in bloqueados]
    
    conexion.close()
    
    return render_template('tecnico.html', 
                         nombre=session['nombre'],
                         asignacion=asignacion,
                         es_responsable=es_responsable,
                         control_retiro_activo=control_retiro_activo,
                         control_devolucion_activo=control_devolucion_activo,
                         tiene_camioneta=tiene_camioneta,
                         devolucion_completada=devolucion_completada,
                         necesita_retiro=necesita_retiro,
                         necesita_devolucion=necesita_devolucion,
                         deudas=deudas,
                         faltantes=faltantes_otros,
                         falta_de_hoy=falta_de_hoy,
                         trabada_por_hueco=trabada_por_hueco,
                         asignacion_devolucion_id=asignacion_devolucion_id,
                         jornada_devolucion=jornada_devolucion,
                         devolucion_en_otro_turno=devolucion_en_otro_turno,
                         retirada_fecha=retirada_fecha,
                         retirada_jornada=retirada_jornada,
                         es_guardia=es_guardia,
                         bloqueada_por=bloqueada_por,
                         elementos_bloqueados=elementos_bloqueados,
                         fecha_actual=fecha_actual,
                         jornada_actual=jornada_actual_tecnico,
                         mensaje=request.args.get('mensaje', ''),
                         error=request.args.get('error', ''))

# Tope de cordura para el odómetro: más que esto es un error de tipeo, no un
# kilometraje. Y salto máximo razonable entre dos controles seguidos.
KM_MAXIMO = 2_000_000
KM_SALTO_MAXIMO = 5_000


def ultimo_kilometraje(conexion, camioneta_id, antes_de_control=None):
    """Último odómetro registrado para esta camioneta, o None si no hay ninguno.

    Sirve para dos cosas: validar que el número nuevo no vaya para atrás y
    calcular cuánto le falta a la camioneta para el próximo service.
    """
    sql = '''
        SELECT ct.kilometraje, ct.fecha, ct.fecha_hora_fin
        FROM controles_tecnicos ct
        JOIN asignaciones a ON ct.asignacion_id = a.id
        WHERE a.camioneta_id = ? AND ct.kilometraje IS NOT NULL
    '''
    parametros = [camioneta_id]
    if antes_de_control is not None:
        sql += ' AND ct.id != ?'
        parametros.append(antes_de_control)
    sql += ' ORDER BY ct.fecha DESC, ct.id DESC LIMIT 1'

    fila = conexion.execute(sql, parametros).fetchone()
    return fila['kilometraje'] if fila else None


def miles(numero):
    """12345 -> '12.345'. Los mensajes se leen en la pantalla del técnico."""
    return f'{int(numero):,}'.replace(',', '.')


def validar_kilometraje(valor, ultimo):
    """(kilometraje, error). El odómetro no vuelve para atrás ni salta de golpe."""
    if valor in (None, ''):
        return None, 'Falta cargar el kilometraje de la camioneta.'
    try:
        km = int(str(valor).strip().replace('.', '').replace(' ', ''))
    except (TypeError, ValueError):
        return None, 'El kilometraje tiene que ser un número entero.'

    if km < 0:
        return None, 'El kilometraje no puede ser negativo.'
    if km > KM_MAXIMO:
        return None, f'{miles(km)} km no parece un valor real. Revisá el odómetro.'
    if ultimo is not None:
        if km < ultimo:
            return None, (f'El último kilometraje registrado es {miles(ultimo)} km y el '
                          f'odómetro no vuelve para atrás. Si te equivocaste antes, '
                          f'avisá a soporte.')
        if km - ultimo > KM_SALTO_MAXIMO:
            return None, (f'De {miles(ultimo)} a {miles(km)} km hay '
                          f'{miles(km - ultimo)} km de diferencia. '
                          f'Revisá que no te haya sobrado un dígito.')
    return km, None


def deuda_que_bloquea(conexion, usuario_id, camioneta_id):
    """Patentes que este técnico debe devolver y le impiden tocar otra camioneta.

    Se consulta en cada paso del retiro y no solo al iniciarlo: si no, alcanzaba
    con tener la pantalla del control abierta, o pegar la URL, para saltearse el
    bloqueo.
    """
    deudas = [c for c in custodias_abiertas(conexion, tecnico_id=usuario_id)
              if c['camioneta_id'] != camioneta_id]
    return ', '.join(d['patente'] for d in deudas)


def control_del_tecnico(conexion, control_id, usuario_id):
    """Devuelve el control solo si el técnico es el responsable de esa asignación.

    Sin esta verificación, cualquier técnico logueado podía guardar o finalizar
    el control de otra camioneta cambiando el id en la URL.
    """
    return conexion.execute('''
        SELECT ct.*, a.camioneta_id, a.tecnico_id
        FROM controles_tecnicos ct
        JOIN asignaciones a ON ct.asignacion_id = a.id
        WHERE ct.id = ? AND a.tecnico_id = ?
    ''', (control_id, usuario_id)).fetchone()


@app.route('/iniciar-control', methods=['POST'])
def iniciar_control():
    if 'usuario_id' not in session or session.get('rol') != 'tecnico':
        return redirect(url_for('login'))
    
    usuario_id = session['usuario_id']
    asignacion_id = request.form.get('asignacion_id')
    jornada = request.form.get('jornada')
    tipo_control = request.form.get('tipo_control')
    
    if not all([asignacion_id, jornada, tipo_control]):
        return redirect(url_for('tecnico', error='Datos incompletos'))
    
    if tipo_control not in ('RETIRO', 'DEVOLUCION'):
        return redirect(url_for('tecnico', error='Tipo de control inválido'))
    
    if not jornada_valida(jornada):
        return redirect(url_for('tecnico', error='Jornada inválida'))
    
    fecha_hora = ahora().isoformat()
    
    conexion = get_db()
    
    try:
        # El control lo hace el técnico responsable, no el acompañante.
        asignacion = conexion.execute('''
            SELECT id, camioneta_id, tecnico_id, fecha, jornada
            FROM asignaciones WHERE id = ? AND tecnico_id = ?
        ''', (asignacion_id, usuario_id)).fetchone()
        
        if not asignacion:
            return redirect(url_for('tecnico',
                error='Esta asignación no es tuya o no sos el técnico responsable.'))
        
        fecha_control = asignacion['fecha']
        jornada = asignacion['jornada']
        
        # Una camioneta retirada queda a nombre de quien la retiró hasta que la
        # devuelva: ningún otro técnico puede retirarla ni devolverla.
        abierto = retiro_abierto(conexion, asignacion['camioneta_id'])
        if abierto is not None and abierto['tecnico_id'] != usuario_id:
            return redirect(url_for('tecnico',
                error=f'🔒 {abierto["tecnico_nombre"]} tiene esta camioneta retirada y '
                      'todavía no la devolvió. Hasta que haga la devolución es su '
                      'responsabilidad: avisá a soporte técnico.'))

        # Lo que habilita cada control es la custodia, no la planilla. El
        # técnico puede retirar y devolver todos los días aunque la camioneta
        # sea suya toda la semana: es un control de más, nunca de menos.
        if tipo_control == 'RETIRO':
            if abierto is not None:
                return redirect(url_for('tecnico',
                    error='⚠️ Ya tenés esta camioneta retirada. Lo que corresponde '
                          'ahora es la devolución.'))

            # Deber una devolución bloquea cualquier retiro nuevo: la camioneta
            # anterior sigue a su nombre y no puede hacerse cargo de otra.
            deudas = [c for c in custodias_abiertas(conexion, tecnico_id=usuario_id)
                      if c['camioneta_id'] != asignacion['camioneta_id']]
            if deudas:
                patentes = ', '.join(d['patente'] for d in deudas)
                return redirect(url_for('tecnico',
                    error=f'🔒 Tenés la devolución de {patentes} sin hacer. Cerrala '
                          'antes de retirar otra camioneta.'))

            # Un control propio sin hacer bloquea cualquier retiro nuevo, sea de
            # la camioneta que sea: mientras quede un turno sin constancia, el
            # técnico no puede hacerse cargo de otro vehículo. Es la misma regla
            # que para las devoluciones.
            propios = [f for f in controles_faltantes(conexion, tecnico_id=usuario_id)
                       if f['asignacion_id'] != asignacion['id']]
            if propios:
                falta = propios[0]
                return redirect(url_for('tecnico',
                    error=f'🔒 Te quedó sin hacer el control de {falta["patente"]} '
                          f'del {falta["fecha"]} ({falta["jornada"]}). Cerralo antes '
                          'de retirar otra camioneta.'))

            # Y si el hueco lo dejó otro, la camioneta queda sin constancia de
            # en qué estado está: si aparece algo roto, no habría forma de saber
            # de qué turno viene.
            ajenos = falta_control_de(conexion, asignacion['camioneta_id'],
                                      excepto_tecnico=usuario_id)
            if ajenos:
                quienes = ', '.join(sorted({f['tecnico'] for f in ajenos}))
                return redirect(url_for('tecnico',
                    error=f'🔒 Esta camioneta quedó sin control en un turno anterior '
                          f'({quienes}). No se puede retirar hasta que se resuelva: '
                          'avisá a soporte técnico.'))

        if tipo_control == 'DEVOLUCION':
            if abierto is None:
                return redirect(url_for('tecnico',
                    error='⚠️ No tenés esta camioneta retirada, así que no hay nada '
                          'que devolver. Primero hacé el retiro.'))

        existe = conexion.execute('''
            SELECT id FROM controles_tecnicos 
            WHERE asignacion_id = ? AND fecha = ? AND jornada = ? 
            AND tipo_control = ? AND finalizado = 0
        ''', (asignacion['id'], fecha_control, jornada, tipo_control)).fetchone()
        
        if existe:
            # Antes esto era un error sin salida: quien empezaba un control y
            # volvía atrás no tenía forma de retomarlo desde el panel. Volver a
            # pedirlo es justamente querer continuarlo.
            return redirect(url_for('realizar_control', control_id=existe['id']))
        
        ya_hecho = conexion.execute('''
            SELECT id FROM controles_tecnicos 
            WHERE asignacion_id = ? AND fecha = ? AND jornada = ? 
            AND tipo_control = ? AND finalizado = 1
        ''', (asignacion['id'], fecha_control, jornada, tipo_control)).fetchone()
        
        if ya_hecho:
            return redirect(url_for('tecnico',
                error=f'El control de {tipo_control.lower()} de este turno ya fue realizado.'))
        
        
        cursor = conexion.cursor()
        cursor.execute('''
            INSERT INTO controles_tecnicos 
            (asignacion_id, fecha, jornada, tipo_control, finalizado, fecha_hora_inicio)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (asignacion['id'], fecha_control, jornada, tipo_control, 0, fecha_hora))
        
        control_id = cursor.lastrowid
        conexion.commit()
    finally:
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
        WHERE ct.id = ? AND ct.finalizado = 0 AND a.tecnico_id = ?
    ''', (control_id, session['usuario_id'])).fetchone()
    
    if not control:
        conexion.close()
        return redirect(url_for('tecnico',
            error='Control no encontrado, ya finalizado, o no te corresponde.'))

    if control['tipo_control'] == 'RETIRO':
        patentes = deuda_que_bloquea(conexion, session['usuario_id'], control['camioneta_id'])
        if patentes:
            conexion.close()
            return redirect(url_for('tecnico',
                error=f'🔒 Tenés la devolución de {patentes} sin hacer. Cerrala antes '
                      'de seguir con este retiro.'))
    
    items_registrados = conexion.execute('''
        SELECT elemento, estado FROM items_control_tecnico 
        WHERE control_tecnico_id = ?
    ''', (control_id,)).fetchall()
    
    items_registrados_lista = [item['elemento'] for item in items_registrados]
    
    bloqueados = conexion.execute('''
        SELECT elemento, tipo, motivo, fecha_bloqueo FROM elementos_bloqueados 
        WHERE camioneta_id = ? AND resuelto = 0
        ORDER BY elemento
    ''', (control['camioneta_id'],)).fetchall()
    
    elementos_bloqueados_lista = [eb['elemento'] for eb in bloqueados]
    
    # Detalle para el desplegable de recuperación: el técnico puede marcar acá
    # que un elemento faltante apareció, con una explicación obligatoria.
    faltantes_recuperables = []
    for eb in bloqueados:
        faltantes_recuperables.append({
            'elemento': eb['elemento'],
            'categoria': eb['tipo'],
            'motivo': eb['motivo'] or '',
            'desde': (eb['fecha_bloqueo'] or '')[:10],
            'dias': dias_desde(eb['fecha_bloqueo']),
        })
    
    estado_registrado = {item['elemento']: item['estado'] for item in items_registrados}

    elementos_por_categoria = {categoria: [] for categoria in CATEGORIAS}

    for categoria, elementos in obtener_catalogo(conexion).items():
        for elemento in elementos:
            nombre = elemento['nombre']
            if nombre in estado_registrado:
                estado = estado_registrado[nombre] or 'PENDIENTE'
            elif nombre in elementos_bloqueados_lista:
                estado = 'BLOQUEADO'
            else:
                estado = 'PENDIENTE'

            elementos_por_categoria.setdefault(categoria, []).append({
                'nombre': nombre,
                'estado': estado,
                'bloqueado': nombre in elementos_bloqueados_lista,
                'registrado': nombre in estado_registrado
            })

    ultimo_km = ultimo_kilometraje(conexion, control['camioneta_id'],
                                   antes_de_control=control_id)

    conexion.close()

    return render_template('realizar_control.html',
                         control=control,
                         ultimo_km=ultimo_km,
                         elementos_por_categoria=elementos_por_categoria,
                         elementos_bloqueados=elementos_bloqueados_lista,
                         faltantes_recuperables=faltantes_recuperables)

@app.route('/finalizar-control/<int:control_id>', methods=['POST'])
def finalizar_control(control_id):
    if 'usuario_id' not in session or session.get('rol') != 'tecnico':
        return redirect(url_for('login'))
    
    conexion = get_db()
    
    try:
        control = control_del_tecnico(conexion, control_id, session['usuario_id'])
        
        if not control:
            conexion.close()
            return redirect(url_for('tecnico',
                error='Control no encontrado o no te corresponde'))
        
        if control['finalizado'] == 1:
            conexion.close()
            return redirect(url_for('tecnico', error='Este control ya fue finalizado'))

        # El kilometraje se carga junto con los ítems, en guardar-control-rapido.
        # Si acá falta es porque ese guardado falló o porque se llegó directo a
        # esta URL: en los dos casos el control no está hecho y cerrarlo dejaría
        # la camioneta sin lectura de odómetro, que es de donde sale el service.
        if control['kilometraje'] is None:
            conexion.close()
            return redirect(url_for('tecnico',
                error='No se puede cerrar el control sin el kilometraje. '
                      'Volvé a entrar al control, cargalo y finalizá desde ahí.'))
        
        momento = ahora()

        # Un control cerrado un día posterior al del turno es una puesta al día,
        # no el control del turno: sirve para dejar constancia y para destrabar
        # la camioneta, pero no puede poner el vehículo en manos de nadie (el
        # técnico ya no lo tiene). Por eso no abre custodia.
        tarde = int(momento.strftime('%Y-%m-%d') > (control['fecha'] or ''))

        conexion.execute('''
            UPDATE controles_tecnicos
            SET finalizado = 1, fecha_hora_fin = ?, fuera_de_termino = ?
            WHERE id = ?
        ''', (momento.isoformat(), tarde, control_id))
        
        conexion.commit()
        conexion.close()

        if tarde:
            return redirect(url_for('tecnico',
                mensaje='✅ Control registrado fuera de término. Queda la constancia '
                        'y la camioneta se destraba, pero figura como hecho tarde.'))
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
    
    data = request.get_json(silent=True) or {}
    control_id = data.get('control_id')
    kilometraje = data.get('kilometraje')
    problemas = data.get('problemas', [])
    recuperados = data.get('recuperados', [])
    revisados = data.get('revisados', [])

    try:
        control_id = int(control_id)
    except (TypeError, ValueError):
        return jsonify({'error': 'ID de control inválido'}), 400

    if not all(isinstance(x, list) for x in (problemas, recuperados, revisados)):
        return jsonify({'error': 'Formato de datos inválido'}), 400
    
    conexion = get_db()
    cursor = conexion.cursor()
    
    try:
        fecha_hora = ahora().isoformat()
        
        info = control_del_tecnico(conexion, control_id, session['usuario_id'])
        
        if not info:
            return jsonify({'error': 'Control no encontrado o no te corresponde'}), 404
        
        if info['finalizado']:
            return jsonify({'error': 'Este control ya fue finalizado'}), 400

        if info['tipo_control'] == 'RETIRO':
            patentes = deuda_que_bloquea(conexion, session['usuario_id'], info['camioneta_id'])
            if patentes:
                return jsonify({'error':
                    f'Tenés la devolución de {patentes} sin hacer. '
                    'Cerrala antes de completar este retiro.'}), 400

        # El kilometraje es obligatorio en todo control: de ahí sale el aviso de
        # service y el seguimiento de uso de cada camioneta.
        ultimo = ultimo_kilometraje(conexion, info['camioneta_id'],
                                    antes_de_control=control_id)
        km, error_km = validar_kilometraje(kilometraje, ultimo)
        if error_km:
            return jsonify({'error': error_km}), 400

        conexion.execute('UPDATE controles_tecnicos SET kilometraje = ? WHERE id = ?',
                         (km, control_id))
        
        # Guardar dos veces el mismo control (doble clic, reintento del navegador)
        # duplicaba los 41 ítems y los 41 reportes. Se corta acá.
        ya_guardado = cursor.execute('''
            SELECT 1 FROM items_control_tecnico WHERE control_tecnico_id = ? LIMIT 1
        ''', (control_id,)).fetchone()
        
        if ya_guardado:
            return jsonify({'error': 'Este control ya fue guardado'}), 409
        
        camioneta_id = info['camioneta_id']
        asignacion_id = info['asignacion_id']
        tipo_control = info['tipo_control']
        patente_camioneta = cursor.execute(
            'SELECT patente FROM camionetas WHERE id = ?', (camioneta_id,)).fetchone()['patente']
        
        # La categoría se resuelve en el servidor a partir del catálogo, y los
        # elementos que no figuran en el catálogo se descartan.
        catalogo = categoria_por_elemento(conexion)

        problemas_dict = {}
        for problema in problemas:
            if not isinstance(problema, dict):
                continue
            elemento = problema.get('elemento')
            if elemento in catalogo:
                problemas_dict[elemento] = (problema.get('observacion') or '').strip()

        # Elementos que estaban faltando y el técnico dice haber recuperado.
        # Solo valen los que hoy están efectivamente bloqueados en esta
        # camioneta, y la explicación es obligatoria.
        bloqueados_actuales = {
            fila['elemento'] for fila in cursor.execute('''
                SELECT elemento FROM elementos_bloqueados
                WHERE camioneta_id = ? AND resuelto = 0
            ''', (camioneta_id,))
        }

        # El control es por la positiva: cada elemento del catálogo tiene que
        # haber sido marcado, como presente o como problema. Los bloqueados no
        # se piden porque no están en la camioneta.
        marcados = {e for e in revisados if e in catalogo} | set(problemas_dict)
        pendientes = sorted(set(catalogo) - marcados - bloqueados_actuales)
        if pendientes:
            return jsonify({
                'error': 'Faltan revisar: ' + ', '.join(pendientes[:5])
                         + ('…' if len(pendientes) > 5 else '')
            }), 400

        recuperados_dict = {}
        for recuperado in recuperados:
            if not isinstance(recuperado, dict):
                continue
            elemento = recuperado.get('elemento')
            observacion = (recuperado.get('observacion') or '').strip()
            if elemento not in bloqueados_actuales:
                continue
            if not observacion:
                return jsonify({
                    'error': f'Falta la explicación de cómo se recuperó "{elemento}"'
                }), 400
            if elemento in problemas_dict:
                return jsonify({
                    'error': f'"{elemento}" no puede estar recuperado y faltante a la vez'
                }), 400
            recuperados_dict[elemento] = observacion
        
        # Un registro de `controles` por asignación y tipo de control. Antes se
        # reutilizaba cualquier fila 'ABIERTO' de la asignación, así que los
        # reportes del retiro y de la devolución compartían control_id y el
        # historial mostraba cada elemento duplicado.
        columna_fecha = 'retiro_fecha_hora' if tipo_control == 'RETIRO' else 'devolucion_fecha_hora'
        
        control_existente = cursor.execute(
            f'SELECT id FROM controles WHERE asignacion_id = ? AND {columna_fecha} IS NOT NULL',
            (asignacion_id,)).fetchone()
        
        if control_existente:
            control_id_old = control_existente['id']
        else:
            cursor.execute(
                f'INSERT INTO controles (asignacion_id, {columna_fecha}, estado) '
                f"VALUES (?, ?, 'ABIERTO')",
                (asignacion_id, fecha_hora))
            control_id_old = cursor.lastrowid
        
        # items_control_tecnico guarda SIEMPRE los 41 elementos: es la planilla
        # del control, sirve para demostrar que se revisó todo y es la fuente de
        # la consulta "última vez que este elemento estuvo OK".
        #
        # reportes guarda SOLO los problemas. Antes entraban los 41 (40 de ellos
        # con estado OK), lo que sumaba ~7.000 filas por mes de puro ruido en el
        # historial, el panel del admin y las estadísticas.
        filas_items = []
        filas_reportes = []
        for elemento, categoria in catalogo.items():
            if elemento in problemas_dict:
                estado = 'FALTANTE'
                descripcion = problemas_dict[elemento] or 'Elemento faltante'
                filas_reportes.append(
                    (control_id_old, tipo_control, elemento, estado, descripcion, fecha_hora))
            else:
                estado = 'OK'
                descripcion = 'Elemento en buen estado'
            
            filas_items.append(
                (control_id, elemento, categoria, estado, descripcion, fecha_hora))
        
        cursor.executemany('''
            INSERT INTO items_control_tecnico 
            (control_tecnico_id, elemento, categoria, estado, observacion, fecha_hora)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', filas_items)
        
        if filas_reportes:
            cursor.executemany('''
                INSERT INTO reportes 
                (control_id, tipo, elemento, estado, descripcion, fecha_hora)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', filas_reportes)
        
        for elemento, observacion in problemas_dict.items():
            ya_bloqueado = cursor.execute('''
                SELECT id FROM elementos_bloqueados 
                WHERE elemento = ? AND camioneta_id = ? AND resuelto = 0
            ''', (elemento, camioneta_id)).fetchone()
            
            if not ya_bloqueado:
                cursor.execute('''
                    INSERT INTO elementos_bloqueados 
                    (elemento, camioneta_id, tipo, fecha_bloqueo, motivo, resuelto)
                    VALUES (?, ?, ?, ?, ?, 0)
                ''', (elemento, camioneta_id, catalogo.get(elemento, 'CAJA'),
                      fecha_hora, observacion))
        
        cursor.execute(
            f'UPDATE controles SET {columna_fecha} = ? WHERE id = ?',
            (fecha_hora, control_id_old))

        # Cada recuperación desbloquea el elemento, cierra su reporte de
        # faltante y deja constancia de quién lo encontró y qué explicó.
        tecnico_nombre = session.get('nombre', 'Técnico')
        for elemento, observacion in recuperados_dict.items():
            cursor.execute('''
                UPDATE elementos_bloqueados
                SET resuelto = 1, fecha_resolucion = ?
                WHERE elemento = ? AND camioneta_id = ? AND resuelto = 0
            ''', (fecha_hora, elemento, camioneta_id))

            cursor.execute('''
                UPDATE reportes
                SET estado = 'RESUELTO',
                    fecha_resolucion = ?,
                    resuelto_por = ?,
                    comentario_resolucion = ?
                WHERE elemento = ?
                  AND estado = 'FALTANTE'
                  AND control_id IN (
                        SELECT c.id FROM controles c
                        JOIN asignaciones a ON c.asignacion_id = a.id
                        WHERE a.camioneta_id = ?
                      )
            ''', (ahora().strftime('%Y-%m-%d %H:%M'),
                  f'{tecnico_nombre} (técnico)', observacion, elemento, camioneta_id))

            crear_notificacion(
                'ELEMENTO_RECUPERADO',
                f'🔁 {tecnico_nombre} recuperó "{elemento}" en {patente_camioneta}: {observacion}',
                patente_camioneta,
                elemento,
                'admin',
                f'/historial-camioneta/{patente_camioneta}',
                conexion=conexion
            )

        conexion.commit()
        
        total_problemas = len(problemas_dict)
        total_ok = len(catalogo) - total_problemas
        mensaje = f'Control guardado: {total_ok} OK, {total_problemas} problemas'
        if recuperados_dict:
            mensaje += f', {len(recuperados_dict)} recuperados'

        return jsonify({'success': True, 'message': mensaje})
        
    except Exception as e:
        conexion.rollback()
        print(f"❌ Error al guardar el control: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        conexion.close()

# ============================================
# RUTAS DE JEFE
# ============================================

@app.route('/jefe')
def jefe():
    if not autorizado('jefe'):
        return redirect(url_for('login'))
    
    fecha_actual = ahora().strftime('%d/%m/%Y')
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
        
        # `reportes` viene ordenado de más nuevo a más viejo.
        for r in reportes:
            patente = r['patente']
            if patente in resumen_flota:
                # Solo el primero es el último registro: antes se pisaba en cada
                # vuelta y terminaba mostrando la fecha del reporte más ANTIGUO.
                if not resumen_flota[patente]['historial'] and r['fecha_hora']:
                    resumen_flota[patente]['ultimo_registro'] = r['fecha_hora'][:16].replace('T', ' ')
                
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
    if not autorizado('soporte', 'jefe'):
        return redirect(url_for('login'))
    
    conexion = get_db()
    
    camioneta = conexion.execute('''
        SELECT id, patente FROM camionetas WHERE patente = ? AND activa = 1
    ''', (patente,)).fetchone()
    
    if not camioneta:
        conexion.close()
        destino = 'jefe' if session.get('rol') == 'jefe' else 'admin'
        return redirect(url_for(destino, error='Camioneta no encontrada'))
    
    controles = conexion.execute('''
        SELECT 
            ct.id,
            ct.asignacion_id,
            ct.fecha,
            ct.jornada,
            ct.tipo_control,
            ct.fecha_hora_inicio,
            ct.fecha_hora_fin,
            ct.finalizado,
            ct.kilometraje,
            ct.forzado_por,
            ct.observacion,
            u.nombre as tecnico_nombre
        FROM controles_tecnicos ct
        JOIN asignaciones a ON ct.asignacion_id = a.id
        JOIN usuarios u ON a.tecnico_id = u.id
        WHERE a.camioneta_id = ?
        ORDER BY ct.fecha DESC, ct.fecha_hora_inicio DESC
    ''', (camioneta['id'],)).fetchall()
    
    historial_detallado = []
    for control in controles:
        # Se consulta por el id del control en vez de reconstruirlo desde
        # camioneta+fecha+jornada. La versión anterior cruzaba los reportes solo
        # por nombre de elemento, así que cada ítem aparecía una vez por cada
        # control de esa asignación (41 ítems -> 82, 123, 164 filas...).
        # El GROUP BY garantiza una fila por ítem.
        elementos = conexion.execute('''
            SELECT 
                ic.elemento, 
                ic.categoria, 
                ic.estado, 
                ic.observacion, 
                ic.fecha_hora,
                MAX(r.entregado_por) as entregado_por,
                MAX(r.recibido_por) as recibido_por,
                MAX(r.fecha_entrega) as fecha_entrega
            FROM items_control_tecnico ic
            LEFT JOIN reportes r 
                   ON r.elemento = ic.elemento 
                  AND r.tipo = ?
                  AND r.control_id IN (
                        SELECT id FROM controles WHERE asignacion_id = ?
                      )
            WHERE ic.control_tecnico_id = ?
            GROUP BY ic.id
            ORDER BY ic.categoria, ic.elemento
        ''', (control['tipo_control'], control['asignacion_id'], control['id'])).fetchall()
        
        historial_detallado.append({
            'control': dict(control),
            'elementos': [dict(e) for e in elementos]
        })

    # Kilómetros recorridos entre un control y el anterior. La lista viene del
    # más nuevo al más viejo, así que el "anterior" es el siguiente de la lista.
    for indice, item in enumerate(historial_detallado):
        km = item['control']['kilometraje']
        item['km_recorridos'] = None
        if km is None:
            continue
        for previo in historial_detallado[indice + 1:]:
            anterior = previo['control']['kilometraje']
            if anterior is not None:
                item['km_recorridos'] = km - anterior
                break
    
    historial_elementos = conexion.execute('''
        SELECT
            r.id,
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
            r.ruta_remito,
            r.material_entregado,
            r.motivo_reposicion,
            r.firma_tecnico,
            r.firma_soporte,
            r.creado_por,
            c.patente,
            u.nombre as tecnico_nombre,
            r.tipo as tipo_control,
            sr.estado as estado_remito,
            COALESCE(ec.categoria, 'CAMIONETA') as categoria
        FROM reportes r
        JOIN controles co ON r.control_id = co.id
        JOIN asignaciones a ON co.asignacion_id = a.id
        JOIN camionetas c ON a.camioneta_id = c.id
        JOIN usuarios u ON a.tecnico_id = u.id
        LEFT JOIN seguimiento_remitos sr ON sr.reporte_id = r.id
        LEFT JOIN elementos_catalogo ec ON ec.nombre = r.elemento
        WHERE c.patente = ?
        ORDER BY r.elemento, r.fecha_hora DESC
    ''', (patente,)).fetchall()

    # Los elementos se agrupan por categoría para mostrarlos en las mismas tres
    # solapas que la vista por fecha.
    historial_por_elemento = {}
    categoria_de_elemento = {}
    for item in historial_elementos:
        elemento = item['elemento']
        historial_por_elemento.setdefault(elemento, []).append(dict(item))
        categoria_de_elemento[elemento] = item['categoria']

    elementos_por_categoria = {c: [] for c in CATEGORIAS}
    for elemento in historial_por_elemento:
        elementos_por_categoria.setdefault(
            categoria_de_elemento[elemento], []).append(elemento)
    for lista in elementos_por_categoria.values():
        lista.sort()
    
    conexion.close()
    
    return render_template('historial_camioneta.html',
                         patente=patente,
                         historial_detallado=historial_detallado,
                         historial_por_elemento=historial_por_elemento,
                         elementos_por_categoria=elementos_por_categoria,
                         etiqueta_categoria=ETIQUETA_CATEGORIA)

# ============================================
# RUTAS DE REPORTES Y REMITOS
# ============================================

@app.route('/comentar-reporte/<int:reporte_id>', methods=['POST'])
def comentar_reporte(reporte_id):
    if not autorizado('soporte'):
        return jsonify({'success': False, 'error': 'No autorizado'}), 401
    
    data = request.get_json(silent=True) or {}
    comentario = (data.get('comentario') or '').strip()
    
    if not comentario:
        return jsonify({'success': False, 'error': 'El comentario es requerido'}), 400
    
    conexion = get_db()
    try:
        # Antes se devolvía success aunque el reporte no existiera.
        cursor = conexion.execute('''
            UPDATE reportes 
            SET comentario_resolucion = ?
            WHERE id = ?
        ''', (comentario, reporte_id))
        
        if cursor.rowcount == 0:
            return jsonify({'success': False, 'error': 'Reporte no encontrado'}), 404
        
        conexion.commit()
        return jsonify({'success': True, 'comentario': comentario})
    except Exception as e:
        conexion.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conexion.close()

@app.route('/generar-remito/<int:reporte_id>', methods=['POST'])
def generar_remito_pdf(reporte_id):
    """Soporte crea el remito cuando ya tiene el material en su poder."""
    if not autorizado('soporte', 'jefe'):
        return jsonify({'success': False, 'error': 'No autorizado'}), 401

    creador_nombre = session.get('nombre', 'Soporte')
    creador_id = session.get('usuario_id')

    datos = request.get_json(silent=True) or {}
    motivo = (datos.get('motivo') or '').strip().upper()

    if motivo not in MOTIVOS_REPOSICION:
        return jsonify({
            'success': False,
            'error': 'Indicá el motivo de la reposición: rotura o pérdida.'
        }), 400

    conexion = get_db()
    try:
        reporte = conexion.execute('''
            SELECT r.id, r.elemento, c.patente
            FROM reportes r
            LEFT JOIN controles co ON r.control_id = co.id
            LEFT JOIN asignaciones a ON co.asignacion_id = a.id
            LEFT JOIN camionetas c ON a.camioneta_id = c.id
            WHERE r.id = ? AND r.estado = 'FALTANTE'
        ''', (reporte_id,)).fetchone()

        if not reporte:
            return jsonify({'success': False, 'error': 'Reporte no encontrado o ya resuelto'}), 404

        if conexion.execute('SELECT id FROM seguimiento_remitos WHERE reporte_id = ?',
                            (reporte_id,)).fetchone():
            return jsonify({'success': False, 'error': 'Este remito ya fue generado'}), 400

        fecha_hora = ahora()
        fecha_str = fecha_hora.strftime('%Y-%m-%d')
        hora_str = fecha_hora.strftime('%H-%M-%S')

        # El material que se entrega es el elemento que falta: no se escribe a mano.
        material = reporte['elemento']
        conexion.execute('''
            UPDATE reportes
            SET motivo_reposicion = ?, material_entregado = ?,
                creado_por = ?, creado_por_id = ?
            WHERE id = ?
        ''', (motivo, material, creador_nombre, creador_id, reporte_id))

        fila = datos_remito(conexion, reporte_id)

        carpeta_destino = crear_carpeta_remitos(fila['patente'], fecha_str)
        nombre_archivo = (f"{fila['patente']}_{fecha_str}_{hora_str}_"
                          f"{fila['elemento'].replace(' ', '_')}.pdf")
        ruta_pdf = carpeta_destino / nombre_archivo

        # El seguimiento todavía no existe, así que la fecha del PDF es la de ahora.
        datos_pdf = dict(fila)
        datos_pdf['fecha_generacion'] = fecha_hora.isoformat()
        escribir_pdf_remito(datos_pdf, ruta_pdf)

        conexion.execute('UPDATE reportes SET ruta_remito = ? WHERE id = ?',
                         (str(ruta_pdf), reporte_id))

        # Seguimiento y notificación van sobre la MISMA conexión/transacción.
        # Con una conexión aparte, SQLite devolvía 'database is locked' y ambos
        # se perdían en silencio: el técnico nunca veía el remito para firmar.
        crear_seguimiento_remito(conexion, reporte_id, fila['patente'],
                                 fila['elemento'], ruta_pdf)

        crear_notificacion(
            'REMITO_PENDIENTE',
            f'📄 Material pendiente de recibir: {material} para la camioneta '
            f'{fila["patente"]} (repone {fila["elemento"]})',
            fila['patente'],
            fila['elemento'],
            'tecnico',
            '/tecnico',
            reporte_id=reporte_id,
            conexion=conexion
        )

        conexion.commit()

        return jsonify({
            'success': True,
            'url': f"/remitos/{fila['patente']}/{fecha_str[:7]}/{nombre_archivo}",
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

@app.route('/forzar-devolucion', methods=['POST'])
def forzar_devolucion():
    """Soporte cierra a mano un control que dejó trabada a una camioneta.

    Sirve para los dos casos que la bloquean: una devolución que el técnico
    nunca hizo, y un retiro que quedó sin control. Sin esto la camioneta se
    trababa para siempre cuando el técnico no aparecía. Queda registrado quién
    lo cerró y por qué, y el control se marca como forzado y fuera de término
    para que no se confunda con una revisión real.
    """
    if not autorizado('soporte'):
        return redirect(url_for('login'))

    try:
        camioneta_id = int(request.form.get('camioneta_id', ''))
    except (TypeError, ValueError):
        return redirect(url_for('admin', error='Camioneta inválida'))

    tipo = (request.form.get('tipo') or 'DEVOLUCION').strip().upper()
    if tipo not in ('RETIRO', 'DEVOLUCION'):
        return redirect(url_for('admin', error='Tipo de control inválido'))

    motivo = (request.form.get('motivo') or '').strip()
    if not motivo:
        return redirect(url_for('admin',
            error='Hay que explicar por qué se cierra el control a mano.'))

    conexion = get_db()
    try:
        if tipo == 'DEVOLUCION':
            pendiente = custodia_de_camioneta(conexion, camioneta_id)
            if pendiente is None:
                return redirect(url_for('admin',
                    error='Esa camioneta no tiene ninguna devolución pendiente.'))
            asignacion_id = pendiente['asignacion_devolucion_id']
            patente = pendiente['patente']
            quien = pendiente['tecnico']
            cuando = f'{pendiente["retirada_fecha"]} ({pendiente["retirada_jornada"]})'
        else:
            # Puede haber más de un turno sin control: se cierra el más viejo,
            # así repetir la acción los va limpiando de a uno y siempre en orden.
            huecos = controles_faltantes(conexion, camioneta_id=camioneta_id)
            if not huecos:
                return redirect(url_for('admin',
                    error='Esa camioneta no tiene ningún retiro sin controlar.'))
            pendiente = huecos[-1]
            asignacion_id = pendiente['asignacion_id']
            patente = pendiente['patente']
            quien = pendiente['tecnico']
            cuando = f'{pendiente["fecha"]} ({pendiente["jornada"]})'

        destino = conexion.execute(
            'SELECT id, fecha, jornada FROM asignaciones WHERE id = ?',
            (asignacion_id,)).fetchone()
        if destino is None:
            return redirect(url_for('admin',
                error='No se encontró el turno donde registrar el control.'))

        fecha_hora = ahora().isoformat()
        conexion.execute('''
            INSERT INTO controles_tecnicos
                (asignacion_id, fecha, jornada, tipo_control, finalizado,
                 fecha_hora_inicio, fecha_hora_fin, forzado_por, observacion,
                 fuera_de_termino)
            VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, 1)
        ''', (destino['id'], destino['fecha'], destino['jornada'], tipo,
              fecha_hora, fecha_hora, session.get('nombre'), motivo))

        etiqueta = 'la devolución' if tipo == 'DEVOLUCION' else 'el control de retiro'
        crear_notificacion(
            'CONTROL_FORZADO',
            f'{session.get("nombre")} cerró a mano {etiqueta} de {patente} '
            f'que {quien} dejó sin hacer del {cuando}. Motivo: {motivo}',
            patente=patente,
            destinatario_rol='jefe',
            conexion=conexion)

        conexion.commit()
    finally:
        conexion.close()

    quedan = ''
    if tipo == 'RETIRO' and len(huecos) > 1:
        restantes = len(huecos) - 1
        quedan = (f' Todavía {"quedan" if restantes > 1 else "queda"} '
                  f'{restantes} turno{"s" if restantes > 1 else ""} sin control.')
    return redirect(url_for('admin',
        mensaje=f'🔓 {patente}: se cerró {etiqueta} a mano '
                f'({session.get("nombre")}).{quedan}'))


@app.route('/api/reportes')
def api_reportes():
    """Faltantes e historial al día, para refrescar el panel sin volver a entrar."""
    if not autorizado('soporte'):
        return jsonify({'error': 'No autorizado'}), 401

    conexion = get_db()
    try:
        reportes = consultar_reportes(conexion)
        historial, patentes, faltantes = agrupar_reportes(conexion, reportes)
    finally:
        conexion.close()

    return jsonify({'faltantes': faltantes, 'historial': historial, 'patentes': patentes})


@app.route('/api/alertas')
def api_alertas():
    """Panel de alertas (remitos + controles vencidos) para refrescarlo solo."""
    if not autorizado('soporte'):
        return jsonify({'error': 'No autorizado'}), 401

    conexion = get_db()
    try:
        pendientes = controles_pendientes(conexion)
        vencimientos = vencimientos_alerta(conexion)
        notificaciones = obtener_notificaciones(session.get('rol'), conexion=conexion)
    finally:
        conexion.close()

    return render_template('_alertas.html', pendientes_control=pendientes,
                           vencimientos=vencimientos,
                           notificaciones=notificaciones)


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
    
    ok, motivo = marcar_notificacion_leida(notificacion_id)
    if ok:
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': motivo}), 400

@app.route('/firmar-remito/<int:reporte_id>', methods=['POST'])
def firmar_remito_tecnico(reporte_id):
    """El técnico a cargo de la camioneta firma la recepción del material."""
    if 'usuario_id' not in session or session.get('rol') != 'tecnico':
        return jsonify({'success': False, 'error': 'No autorizado'}), 401

    tecnico_id = session['usuario_id']
    tecnico_nombre = session.get('nombre', 'Técnico')

    conexion = get_db()
    try:
        fila = datos_remito(conexion, reporte_id)

        if not fila or not fila['estado_remito']:
            return jsonify({'success': False, 'error': 'Remito no encontrado'}), 404

        if fila['estado_remito'] != 'PENDIENTE_FIRMA_TECNICO':
            return jsonify({
                'success': False,
                'error': 'Este remito ya fue firmado por el técnico'
            }), 400

        # Solo firma quien tiene la camioneta a cargo en este momento.
        asignado = conexion.execute('''
            SELECT a.tecnico_id
            FROM asignaciones a
            WHERE a.camioneta_id = ? AND a.tecnico_id = ?
              AND a.fecha >= ? AND a.estado = 'ASIGNADA'
            LIMIT 1
        ''', (fila['camioneta_id'], tecnico_id,
              (ahora() - timedelta(days=1)).strftime('%Y-%m-%d'))).fetchone()

        if not asignado:
            return jsonify({
                'success': False,
                'error': 'Este remito es de una camioneta que no tenés asignada.'
            }), 403

        firmar_remito_tecnico_db(conexion, reporte_id, tecnico_id, tecnico_nombre)

        if fila['ruta_remito']:
            escribir_pdf_remito(datos_remito(conexion, reporte_id), Path(fila['ruta_remito']))

        crear_notificacion(
            'REMITO_FIRMADO',
            f'✍️ {tecnico_nombre} recibió {fila["material_entregado"] or fila["elemento"]} '
            f'({fila["patente"]}). Falta que firme quien entregó el material.',
            fila['patente'],
            fila['elemento'],
            'soporte',
            '/admin/remitos',
            reporte_id=reporte_id,
            conexion=conexion
        )

        # Al firmar, la alerta que veía el técnico deja de tener sentido.
        conexion.execute('''
            UPDATE notificaciones
            SET leido = 1, fecha_lectura = ?
            WHERE reporte_id = ? AND tipo = 'REMITO_PENDIENTE' AND leido = 0
        ''', (ahora().isoformat(), reporte_id))

        conexion.commit()
        return jsonify({
            'success': True,
            'mensaje': '✅ Remito firmado. Queda pendiente la firma de soporte.'
        })

    except Exception as e:
        conexion.rollback()
        print(f"❌ Error al firmar remito: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conexion.close()


@app.route('/revisar-remito/<int:reporte_id>', methods=['POST'])
def revisar_remito_admin(reporte_id):
    """Firma de quien entregó el material: cierra el remito y libera el elemento."""
    if not autorizado('soporte', 'jefe'):
        return jsonify({'success': False, 'error': 'No autorizado'}), 401

    usuario_id = session['usuario_id']
    soporte_nombre = session.get('nombre', 'Soporte')

    conexion = get_db()
    try:
        fila = datos_remito(conexion, reporte_id)

        if not fila or not fila['estado_remito']:
            return jsonify({'success': False, 'error': 'Remito no encontrado'}), 404

        if fila['estado_remito'] == 'PENDIENTE_FIRMA_TECNICO':
            return jsonify({
                'success': False,
                'error': 'El técnico todavía no firmó la recepción del material'
            }), 400

        if fila['estado_remito'] == 'FINALIZADO':
            return jsonify({'success': False, 'error': 'Este remito ya está finalizado'}), 400

        # Firma el que entregó el material, y con eso queda registrado que fue
        # él. Cualquiera de soporte puede hacerlo: el sistema no sabe de antemano
        # quién va a bajar a entregar la herramienta, y el que firma lo declara.
        firmar_remito_soporte_db(conexion, reporte_id, soporte_nombre, usuario_id)
        desbloquear_elemento(conexion, fila['camioneta_id'], fila['elemento'])

        if fila['ruta_remito']:
            escribir_pdf_remito(datos_remito(conexion, reporte_id), Path(fila['ruta_remito']))

        crear_notificacion(
            'REMITO_FINALIZADO',
            f'✅ Remito de "{fila["elemento"]}" finalizado. '
            f'El elemento quedó habilitado en {fila["patente"]}.',
            fila['patente'],
            fila['elemento'],
            'todos',
            None,
            reporte_id=reporte_id,
            conexion=conexion
        )

        # Se cierra la alerta de "firmado" que dio origen a esta revisión.
        conexion.execute('''
            UPDATE notificaciones
            SET leido = 1, fecha_lectura = ?
            WHERE reporte_id = ? AND tipo = 'REMITO_FIRMADO' AND leido = 0
        ''', (ahora().isoformat(), reporte_id))

        conexion.commit()
        return jsonify({
            'success': True,
            'mensaje': f'✅ Remito finalizado. "{fila["elemento"]}" quedó habilitado.'
        })

    except Exception as e:
        conexion.rollback()
        print(f"❌ Error al finalizar remito: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        conexion.close()


@app.route('/remito/<int:reporte_id>')
def ver_remito(reporte_id):
    """Abre el PDF de un remito a partir del reporte, sin exponer la ruta."""
    if not autorizado('soporte', 'jefe', 'tecnico'):
        return redirect(url_for('login'))

    conexion = get_db()
    try:
        fila = conexion.execute(
            'SELECT ruta_remito FROM reportes WHERE id = ?', (reporte_id,)).fetchone()
    finally:
        conexion.close()

    if not fila or not fila['ruta_remito']:
        return "Remito no encontrado", 404

    remitos_real = REMITOS_DIR.resolve()
    try:
        ruta_real = Path(fila['ruta_remito']).resolve()
        ruta_real.relative_to(remitos_real)
    except (ValueError, OSError):
        return "Acceso denegado", 403

    if not ruta_real.is_file():
        return "Remito no encontrado", 404

    return send_file(ruta_real, as_attachment=False, mimetype='application/pdf')


@app.route('/remitos/<path:filename>')
def servir_remito(filename):
    # El técnico también necesita abrir el remito: es el que lo tiene que firmar.
    if not autorizado('soporte', 'jefe', 'tecnico'):
        return redirect(url_for('login'))
    
    # Se valida la ruta ANTES de tocar el disco, para que un filename con ".."
    # no pueda ni siquiera sondear qué archivos existen fuera de remitos/.
    remitos_real = REMITOS_DIR.resolve()
    try:
        ruta_real = (REMITOS_DIR / filename).resolve()
        ruta_real.relative_to(remitos_real)
    except (ValueError, OSError):
        return "Acceso denegado", 403
    
    if not ruta_real.is_file() or ruta_real.suffix.lower() != '.pdf':
        return "Archivo no encontrado", 404
    
    return send_file(ruta_real, as_attachment=False, mimetype='application/pdf')

@app.route('/admin/remitos')
def admin_remitos():
    if not autorizado('soporte', 'jefe'):
        return redirect(url_for('login'))

    conexion = get_db()
    try:
        seguimientos = conexion.execute('''
            SELECT sr.reporte_id, sr.patente, sr.elemento, sr.fecha_generacion,
                   sr.estado, sr.fecha_firma, sr.tecnico_firma,
                   sr.fecha_revision, sr.admin_revision, sr.ruta_pdf,
                   r.motivo_reposicion, r.material_entregado
            FROM seguimiento_remitos sr
            LEFT JOIN reportes r ON sr.reporte_id = r.id
            ORDER BY sr.fecha_generacion DESC
        ''').fetchall()
    finally:
        conexion.close()

    # El seguimiento se indexa por nombre de archivo para cruzarlo con el disco.
    por_archivo = {}
    for s in seguimientos:
        if s['ruta_pdf']:
            por_archivo[PurePosixPath(str(s['ruta_pdf']).replace(chr(92), '/')).name] = dict(s)

    remitos = []
    if REMITOS_DIR.exists():
        for patente_dir in REMITOS_DIR.iterdir():
            if not patente_dir.is_dir():
                continue
            for mes_dir in patente_dir.iterdir():
                if not mes_dir.is_dir():
                    continue
                for archivo in mes_dir.glob('*.pdf'):
                    seguimiento = por_archivo.get(archivo.name, {})
                    remitos.append({
                        'patente': patente_dir.name,
                        'mes': mes_dir.name,
                        'archivo': archivo.name,
                        'ruta': f"/remitos/{patente_dir.name}/{mes_dir.name}/{archivo.name}",
                        'fecha': archivo.stat().st_mtime,
                        'elemento': seguimiento.get('elemento', ''),
                        'estado': seguimiento.get('estado', 'SIN_SEGUIMIENTO'),
                        'motivo': MOTIVOS_REPOSICION.get(seguimiento.get('motivo_reposicion'), ''),
                        'material_entregado': seguimiento.get('material_entregado'),
                        'tecnico_firma': seguimiento.get('tecnico_firma'),
                        'admin_revision': seguimiento.get('admin_revision'),
                        'reporte_id': seguimiento.get('reporte_id'),
                    })

    remitos.sort(key=lambda x: x['fecha'], reverse=True)

    # El panel del admin embebe esta tabla dentro de una sección: en ese caso se
    # devuelve solo el fragmento, no una página HTML completa dentro de un div.
    if request.args.get('parcial') == '1':
        return render_template('_tabla_remitos.html', remitos=remitos)

    return render_template('admin_remitos.html', remitos=remitos)

# ============================================
# CONFIGURACIÓN (solo administrador)
# ============================================

ROLES = ('admin', 'soporte', 'jefe', 'tecnico')

ETIQUETA_ROL = {
    'admin': 'Administrador',
    'soporte': 'Soporte técnico',
    'jefe': 'Supervisor técnico',
    'tecnico': 'Técnico',
}


def _volver_config(seccion, mensaje=None, error=None):
    return redirect(url_for('admin_configuracion', seccion=seccion,
                            mensaje=mensaje or '', error=error or ''))


@app.route('/admin/tiempos')
def admin_tiempos():
    """Cuánto tardó cada control. Solo lo ve el administrador."""
    if not autorizado():
        return redirect(url_for('login'))

    patente = (request.args.get('patente') or '').strip()
    try:
        tecnico_id = int(request.args.get('tecnico') or 0) or None
    except (TypeError, ValueError):
        tecnico_id = None

    conexion = get_db()
    try:
        # Se traen todos los controles y el filtrado se hace acá: hace falta el
        # conjunto completo para poder decir, en cada tarjeta, cuántos controles
        # quedarían si se la eligiera.
        filas = conexion.execute('''
            SELECT ct.fecha, ct.jornada, ct.tipo_control,
                   ct.fecha_hora_inicio, ct.fecha_hora_fin,
                   c.patente, a.tecnico_id, u.nombre AS tecnico
            FROM controles_tecnicos ct
            JOIN asignaciones a ON ct.asignacion_id = a.id
            JOIN camionetas c ON a.camioneta_id = c.id
            JOIN usuarios u ON a.tecnico_id = u.id
            WHERE ct.finalizado = 1 AND ct.fecha_hora_fin IS NOT NULL
            ORDER BY ct.fecha_hora_inicio DESC
        ''').fetchall()

        camionetas = [f['patente'] for f in conexion.execute(
            'SELECT patente FROM camionetas WHERE activa = 1 ORDER BY patente')]
        tecnicos = [dict(f) for f in conexion.execute(
            "SELECT id, nombre FROM usuarios WHERE rol = 'tecnico' AND activo = 1 "
            "ORDER BY nombre")]
    finally:
        conexion.close()

    controles = []
    for f in filas:
        arranque = _a_fecha(f['fecha_hora_inicio'])
        cierre = _a_fecha(f['fecha_hora_fin'])
        if not arranque or not cierre or cierre < arranque:
            continue
        segundos = int((cierre - arranque).total_seconds())
        controles.append({
            'patente': f['patente'],
            'tecnico': f['tecnico'],
            'tecnico_id': f['tecnico_id'],
            'fecha': f['fecha'],
            'jornada': f['jornada'],
            'tipo': f['tipo_control'],
            'inicio': arranque.strftime('%d/%m/%Y %H:%M'),
            'fin': cierre.strftime('%H:%M'),
            'minutos': segundos // 60,
            'duracion': f'{segundos // 60} min {segundos % 60:02d} s',
        })

    def promedio_de(lista):
        return round(sum(c['minutos'] for c in lista) / len(lista), 1) if lista else None

    # Cada dimensión se cuenta con el OTRO filtro puesto: con una camioneta
    # elegida, las tarjetas de técnico muestran quiénes la controlaron y cuánto
    # tardaron en ella, no su promedio general.
    por_tecnico = [c for c in controles if not tecnico_id or c['tecnico_id'] == tecnico_id]
    por_patente = [c for c in controles if not patente or c['patente'] == patente]

    resumen_camionetas = []
    for cada in camionetas:
        propios = [c for c in por_tecnico if c['patente'] == cada]
        resumen_camionetas.append({
            'patente': cada,
            'controles': len(propios),
            'promedio': promedio_de(propios),
        })

    resumen_tecnicos = []
    for tec in tecnicos:
        propios = [c for c in por_patente if c['tecnico_id'] == tec['id']]
        resumen_tecnicos.append({
            'id': tec['id'],
            'nombre': tec['nombre'],
            'controles': len(propios),
            'promedio': promedio_de(propios),
        })

    filtrados = [c for c in controles
                 if (not patente or c['patente'] == patente)
                 and (not tecnico_id or c['tecnico_id'] == tecnico_id)]

    nombre_tecnico = next((t['nombre'] for t in tecnicos if t['id'] == tecnico_id), '')

    return render_template('admin_tiempos.html',
                           controles=filtrados[:300],
                           recortado=len(filtrados) > 300,
                           total_filtrados=len(filtrados),
                           camionetas=camionetas,
                           patente=patente,
                           tecnico_id=tecnico_id,
                           nombre_tecnico=nombre_tecnico,
                           promedio=promedio_de(filtrados) or 0,
                           resumen_camionetas=resumen_camionetas,
                           resumen_tecnicos=resumen_tecnicos,
                           total_controles=len(por_tecnico),
                           total_tecnicos=len(por_patente))


@app.route('/admin/configuracion')
def admin_configuracion():
    if not autorizado():
        return redirect(url_for('login'))

    conexion = get_db()
    try:
        zonas = [dict(f) for f in conexion.execute(
            'SELECT id, nombre, activa FROM zonas ORDER BY nombre')]
        camionetas = [dict(f) for f in conexion.execute(
            'SELECT id, patente, activa FROM camionetas ORDER BY patente')]
        usuarios = [dict(f) for f in conexion.execute(
            'SELECT id, nombre, usuario, rol, activo FROM usuarios ORDER BY rol, nombre')]
        catalogo = obtener_catalogo(conexion, incluir_inactivos=True)

        # Para avisar antes de desactivar algo que está en uso.
        zonas_en_uso = {f[0] for f in conexion.execute(
            "SELECT DISTINCT TRIM(zona) FROM asignaciones WHERE zona IS NOT NULL")}
    finally:
        conexion.close()

    return render_template('admin_configuracion.html',
                           zonas=zonas,
                           camionetas=camionetas,
                           usuarios=usuarios,
                           catalogo=catalogo,
                           categorias=CATEGORIAS,
                           etiqueta_categoria=ETIQUETA_CATEGORIA,
                           roles=ROLES,
                           etiqueta_rol=ETIQUETA_ROL,
                           zonas_en_uso=zonas_en_uso,
                           seccion=request.args.get('seccion', 'zonas'),
                           mensaje=request.args.get('mensaje', ''),
                           error=request.args.get('error', ''))


# ---------- Zonas ----------

@app.route('/admin/configuracion/zonas', methods=['POST'])
def config_zonas():
    if not autorizado():
        return redirect(url_for('login'))

    accion = request.form.get('accion')
    conexion = get_db()
    try:
        if accion == 'crear':
            nombre = (request.form.get('nombre') or '').strip().upper()
            if not nombre:
                return _volver_config('zonas', error='El nombre de la zona no puede estar vacío.')
            try:
                conexion.execute('INSERT INTO zonas (nombre, activa) VALUES (?, 1)', (nombre,))
                conexion.commit()
            except sqlite3.IntegrityError:
                return _volver_config('zonas', error=f'La zona "{nombre}" ya existe.')
            return _volver_config('zonas', mensaje=f'Zona "{nombre}" agregada.')

        zona_id = request.form.get('zona_id')
        zona = conexion.execute('SELECT nombre, activa FROM zonas WHERE id = ?', (zona_id,)).fetchone()
        if not zona:
            return _volver_config('zonas', error='Zona no encontrada.')

        if accion == 'renombrar':
            nombre = (request.form.get('nombre') or '').strip().upper()
            if not nombre:
                return _volver_config('zonas', error='El nombre de la zona no puede estar vacío.')
            try:
                conexion.execute('UPDATE zonas SET nombre = ? WHERE id = ?', (nombre, zona_id))
                # Las asignaciones guardan el texto de la zona: se renombran también.
                conexion.execute('UPDATE asignaciones SET zona = ? WHERE zona = ?',
                                 (nombre, zona['nombre']))
                conexion.commit()
            except sqlite3.IntegrityError:
                return _volver_config('zonas', error=f'Ya existe una zona llamada "{nombre}".')
            return _volver_config('zonas', mensaje=f'Zona renombrada a "{nombre}".')

        if accion == 'alternar':
            nueva = 0 if zona['activa'] else 1
            conexion.execute('UPDATE zonas SET activa = ? WHERE id = ?', (nueva, zona_id))
            conexion.commit()
            estado = 'activada' if nueva else 'desactivada'
            return _volver_config('zonas', mensaje=f'Zona "{zona["nombre"]}" {estado}.')
    finally:
        conexion.close()

    return _volver_config('zonas', error='Acción desconocida.')


# ---------- Camionetas ----------

@app.route('/admin/configuracion/camionetas', methods=['POST'])
def config_camionetas():
    if not autorizado():
        return redirect(url_for('login'))

    accion = request.form.get('accion')
    conexion = get_db()
    try:
        if accion == 'crear':
            patente = (request.form.get('patente') or '').strip().upper().replace(' ', '')
            if not patente:
                return _volver_config('camionetas', error='La patente no puede estar vacía.')
            try:
                conexion.execute('INSERT INTO camionetas (patente, activa) VALUES (?, 1)', (patente,))
                conexion.commit()
            except sqlite3.IntegrityError:
                return _volver_config('camionetas', error=f'La patente {patente} ya está cargada.')
            return _volver_config('camionetas', mensaje=f'Camioneta {patente} agregada.')

        camioneta_id = request.form.get('camioneta_id')
        camioneta = conexion.execute(
            'SELECT patente, activa FROM camionetas WHERE id = ?', (camioneta_id,)).fetchone()
        if not camioneta:
            return _volver_config('camionetas', error='Camioneta no encontrada.')

        if accion == 'renombrar':
            patente = (request.form.get('patente') or '').strip().upper().replace(' ', '')
            if not patente:
                return _volver_config('camionetas', error='La patente no puede estar vacía.')
            try:
                conexion.execute('UPDATE camionetas SET patente = ? WHERE id = ?',
                                 (patente, camioneta_id))
            except sqlite3.IntegrityError:
                return _volver_config('camionetas', error=f'La patente {patente} ya está cargada.')

            # El historial sigue colgado del id, pero los remitos se guardan por
            # patente: hay que arrastrarlos o quedan bajo un nombre que ya no existe.
            movidos, avisos = mudar_remitos_de_patente(
                conexion, camioneta_id, camioneta['patente'], patente)
            conexion.commit()

            mensaje = f'Patente corregida: {camioneta["patente"]} → {patente}.'
            if movidos:
                mensaje += f' Se actualizaron {movidos} remito(s).'
            if avisos:
                return _volver_config('camionetas', mensaje=mensaje,
                                      error=' · '.join(avisos))
            return _volver_config('camionetas', mensaje=mensaje)

        if accion == 'alternar':
            nueva = 0 if camioneta['activa'] else 1
            # Baja lógica: se conserva todo el historial de la camioneta.
            conexion.execute('UPDATE camionetas SET activa = ? WHERE id = ?', (nueva, camioneta_id))
            conexion.commit()
            estado = 'reactivada' if nueva else 'dada de baja'
            return _volver_config('camionetas', mensaje=f'Camioneta {camioneta["patente"]} {estado}.')
    finally:
        conexion.close()

    return _volver_config('camionetas', error='Acción desconocida.')


# ---------- Usuarios ----------

@app.route('/admin/configuracion/usuarios', methods=['POST'])
def config_usuarios():
    if not autorizado():
        return redirect(url_for('login'))

    accion = request.form.get('accion')
    conexion = get_db()
    try:
        if accion == 'crear':
            nombre = (request.form.get('nombre') or '').strip()
            usuario = (request.form.get('usuario') or '').strip().lower()
            password = request.form.get('password') or ''
            rol = request.form.get('rol')

            if not nombre or not usuario or not password:
                return _volver_config('usuarios', error='Nombre, usuario y contraseña son obligatorios.')
            if rol not in ROLES:
                return _volver_config('usuarios', error='Rol inválido.')
            if len(password) < 6:
                return _volver_config('usuarios', error='La contraseña debe tener al menos 6 caracteres.')
            try:
                conexion.execute('''
                    INSERT INTO usuarios (nombre, usuario, password, rol, activo)
                    VALUES (?, ?, ?, ?, 1)
                ''', (nombre, usuario, hashear_password(password), rol))
                conexion.commit()
            except sqlite3.IntegrityError:
                return _volver_config('usuarios', error=f'El usuario "{usuario}" ya existe.')
            return _volver_config('usuarios', mensaje=f'Usuario "{usuario}" creado.')

        usuario_id = request.form.get('usuario_id')
        destino = conexion.execute(
            'SELECT id, nombre, usuario, rol, activo FROM usuarios WHERE id = ?',
            (usuario_id,)).fetchone()
        if not destino:
            return _volver_config('usuarios', error='Usuario no encontrado.')

        propio = str(destino['id']) == str(session['usuario_id'])

        if accion == 'password':
            password = request.form.get('password') or ''
            if len(password) < 6:
                return _volver_config('usuarios', error='La contraseña debe tener al menos 6 caracteres.')
            conexion.execute('UPDATE usuarios SET password = ? WHERE id = ?',
                             (hashear_password(password), usuario_id))
            conexion.commit()
            return _volver_config('usuarios',
                                  mensaje=f'Contraseña de "{destino["usuario"]}" actualizada.')

        if accion == 'editar':
            nombre = (request.form.get('nombre') or '').strip()
            rol = request.form.get('rol')
            if not nombre:
                return _volver_config('usuarios', error='El nombre no puede estar vacío.')
            if rol not in ROLES:
                return _volver_config('usuarios', error='Rol inválido.')
            # Nadie se puede sacar a sí mismo el acceso de administrador y
            # quedar afuera del panel.
            if propio and rol != 'admin':
                return _volver_config('usuarios',
                    error='No podés cambiarte el rol a vos mismo: pedíselo a otro administrador.')
            conexion.execute('UPDATE usuarios SET nombre = ?, rol = ? WHERE id = ?',
                             (nombre, rol, usuario_id))
            conexion.commit()
            return _volver_config('usuarios', mensaje=f'Usuario "{destino["usuario"]}" actualizado.')

        if accion == 'alternar':
            if propio:
                return _volver_config('usuarios', error='No podés desactivarte a vos mismo.')
            nueva = 0 if destino['activo'] else 1
            if not nueva and destino['rol'] == 'admin':
                otros = conexion.execute('''
                    SELECT COUNT(*) FROM usuarios
                    WHERE rol = 'admin' AND activo = 1 AND id <> ?
                ''', (usuario_id,)).fetchone()[0]
                if otros == 0:
                    return _volver_config('usuarios',
                        error='Es el único administrador activo: no se puede desactivar.')
            # Baja lógica: el historial de controles y reportes queda intacto.
            conexion.execute('UPDATE usuarios SET activo = ? WHERE id = ?', (nueva, usuario_id))
            conexion.commit()
            estado = 'reactivado' if nueva else 'desactivado'
            return _volver_config('usuarios', mensaje=f'Usuario "{destino["usuario"]}" {estado}.')
    finally:
        conexion.close()

    return _volver_config('usuarios', error='Acción desconocida.')


# ---------- Catálogo de elementos ----------

@app.route('/admin/configuracion/elementos', methods=['POST'])
def config_elementos():
    if not autorizado():
        return redirect(url_for('login'))

    accion = request.form.get('accion')
    conexion = get_db()
    try:
        if accion == 'crear':
            nombre = (request.form.get('nombre') or '').strip().upper()
            categoria = request.form.get('categoria')
            if not nombre:
                return _volver_config('elementos', error='El nombre del elemento no puede estar vacío.')
            if categoria not in CATEGORIAS:
                return _volver_config('elementos', error='Categoría inválida.')
            orden = conexion.execute(
                'SELECT COALESCE(MAX(orden), 0) + 1 FROM elementos_catalogo').fetchone()[0]
            try:
                conexion.execute('''
                    INSERT INTO elementos_catalogo (nombre, categoria, activo, orden)
                    VALUES (?, ?, 1, ?)
                ''', (nombre, categoria, orden))
                conexion.commit()
            except sqlite3.IntegrityError:
                return _volver_config('elementos', error=f'El elemento "{nombre}" ya existe.')
            return _volver_config('elementos', mensaje=f'Elemento "{nombre}" agregado.')

        elemento_id = request.form.get('elemento_id')
        elemento = conexion.execute(
            'SELECT id, nombre, categoria, activo FROM elementos_catalogo WHERE id = ?',
            (elemento_id,)).fetchone()
        if not elemento:
            return _volver_config('elementos', error='Elemento no encontrado.')

        if accion == 'editar':
            nombre = (request.form.get('nombre') or '').strip().upper()
            categoria = request.form.get('categoria')
            if not nombre:
                return _volver_config('elementos', error='El nombre no puede estar vacío.')
            if categoria not in CATEGORIAS:
                return _volver_config('elementos', error='Categoría inválida.')
            try:
                conexion.execute(
                    'UPDATE elementos_catalogo SET nombre = ?, categoria = ? WHERE id = ?',
                    (nombre, categoria, elemento_id))
                # El historial guarda el nombre del elemento, no su id: se
                # renombra también para no cortar la trazabilidad.
                if nombre != elemento['nombre']:
                    for tabla in ('items_control_tecnico', 'reportes', 'elementos_bloqueados'):
                        conexion.execute(
                            f'UPDATE {tabla} SET elemento = ? WHERE elemento = ?',
                            (nombre, elemento['nombre']))
                conexion.commit()
            except sqlite3.IntegrityError:
                return _volver_config('elementos', error=f'Ya existe un elemento "{nombre}".')
            return _volver_config('elementos', mensaje=f'Elemento "{nombre}" actualizado.')

        if accion == 'alternar':
            nueva = 0 if elemento['activo'] else 1
            # Al desactivar, deja de pedirse en los controles nuevos, pero el
            # historial anterior se conserva.
            conexion.execute('UPDATE elementos_catalogo SET activo = ? WHERE id = ?',
                             (nueva, elemento_id))
            conexion.commit()
            estado = 'reactivado' if nueva else 'quitado del control'
            return _volver_config('elementos', mensaje=f'Elemento "{elemento["nombre"]}" {estado}.')
    finally:
        conexion.close()

    return _volver_config('elementos', error='Acción desconocida.')


# ============================================
# RUTAS DE LOGOUT
# ============================================

# ============================================
# CALENDARIO
# ============================================

@app.route('/calendario')
def calendario():
    """Qué se hizo, qué se viene y qué está vencido, por camioneta."""
    if not autorizado('soporte', 'jefe', 'admin'):
        return redirect(url_for('login'))

    momento = ahora()
    try:
        anio = int(request.args.get('anio') or momento.year)
        mes = int(request.args.get('mes') or momento.month)
        if not 1 <= mes <= 12 or not 2000 <= anio <= 2100:
            raise ValueError
    except (TypeError, ValueError):
        anio, mes = momento.year, momento.month

    conexion = get_db()
    try:
        filas = estado_flota(conexion, momento)
        semanas = calendario_mes(conexion, anio, mes, momento)
        # El detalle de cada día se arma en el navegador al hacer clic: se manda
        # indexado por fecha para no recorrer las semanas del lado del cliente.
        dias_indice = {d['fecha']: d for semana in semanas for d in semana if d['del_mes']}
        camionetas = obtener_camionetas()

        historial = [dict(f) for f in conexion.execute('''
            SELECT h.id, h.tipo, h.fecha_realizado, h.km_realizado,
                   h.registrado_por, h.observacion, c.patente
            FROM vencimientos_historial h
            JOIN camionetas c ON h.camioneta_id = c.id
            ORDER BY h.fecha_realizado DESC, h.id DESC
            LIMIT 40
        ''')]
    finally:
        conexion.close()

    resumen = {estado: sum(1 for f in filas if f['estado'] == estado)
               for estado in ORDEN_ESTADO}

    # La pantalla muestra una camioneta por fila desplegable, no los cuatro
    # vencimientos de cada una sueltos: con la flota entera era una lista de
    # decenas de renglones imposible de leer.
    por_camioneta = {}
    for f in filas:
        grupo = por_camioneta.setdefault(f['camioneta_id'], {
            'camioneta_id': f['camioneta_id'],
            'patente': f['patente'],
            'km_actual': f['km_actual'],
            'vencimientos': [],
            'conteo': {e: 0 for e in ORDEN_ESTADO},
        })
        grupo['vencimientos'].append(f)
        grupo['conteo'][f['estado']] += 1

    for grupo in por_camioneta.values():
        grupo['vencimientos'].sort(key=lambda v: list(TIPOS_VENCIMIENTO).index(v['tipo']))
        grupo['estado'] = min((v['estado'] for v in grupo['vencimientos']),
                              key=lambda e: ORDEN_ESTADO[e])

    # Primero las camionetas con algo pendiente, después por patente.
    camionetas_estado = sorted(por_camioneta.values(),
                               key=lambda g: (ORDEN_ESTADO[g['estado']], g['patente']))

    # Navegación entre meses sin hacer cuentas de calendario en la plantilla.
    anterior = (anio - 1, 12) if mes == 1 else (anio, mes - 1)
    siguiente = (anio + 1, 1) if mes == 12 else (anio, mes + 1)

    return render_template('calendario.html',
                           camionetas_estado=camionetas_estado,
                           dias_indice=dias_indice,
                           resumen=resumen,
                           semanas=semanas,
                           historial=historial,
                           camionetas=camionetas,
                           tipos=TIPOS_VENCIMIENTO,
                           anio=anio,
                           mes=mes,
                           nombre_mes=MESES[mes - 1],
                           mes_anterior=anterior,
                           mes_siguiente=siguiente,
                           hoy=momento.strftime('%Y-%m-%d'),
                           mensaje=request.args.get('mensaje', ''),
                           error=request.args.get('error', ''))


def _volver_calendario(mensaje=None, error=None):
    return redirect(url_for('calendario', mensaje=mensaje or '', error=error or ''))


def _leer_camioneta_y_tipo(conexion):
    """(camioneta, tipo, error) a partir del formulario."""
    try:
        camioneta_id = int(request.form.get('camioneta_id', ''))
    except (TypeError, ValueError):
        return None, None, 'Camioneta inválida.'

    tipo = (request.form.get('tipo') or '').strip().upper()
    if tipo not in TIPOS_VENCIMIENTO:
        return None, None, 'Tipo de vencimiento inválido.'

    camioneta = conexion.execute(
        'SELECT id, patente FROM camionetas WHERE id = ? AND activa = 1',
        (camioneta_id,)).fetchone()
    if camioneta is None:
        return None, None, 'Camioneta no encontrada.'

    return camioneta, tipo, None


@app.route('/calendario/registrar', methods=['POST'])
def calendario_registrar():
    """Marca un trabajo como hecho y corre el vencimiento al próximo período."""
    if not autorizado('soporte', 'admin'):
        return redirect(url_for('login'))

    conexion = get_db()
    try:
        camioneta, tipo, error = _leer_camioneta_y_tipo(conexion)
        if error:
            return _volver_calendario(error=error)

        fecha = (request.form.get('fecha') or '').strip()
        if _fecha_iso(fecha) is None:
            return _volver_calendario(error='La fecha en que se hizo el trabajo es obligatoria.')
        if _fecha_iso(fecha) > ahora().date():
            return _volver_calendario(error='No se puede registrar un trabajo con fecha futura.')

        # El kilometraje solo se pide donde sirve: el service vence por km, el
        # lavado no. Igual se guarda si lo cargan, queda como dato del historial.
        km_texto = (request.form.get('kilometraje') or '').strip()
        km = None
        if km_texto:
            km, error_km = validar_kilometraje(km_texto, None)
            if error_km:
                return _volver_calendario(error=error_km)
        elif TIPOS_VENCIMIENTO[tipo]['periodicidad_km']:
            km = ultimo_kilometraje(conexion, camioneta['id'])
            if km is None:
                return _volver_calendario(
                    error=f'El {TIPOS_VENCIMIENTO[tipo]["etiqueta"].lower()} vence por '
                          'kilómetros y esta camioneta todavía no tiene ninguno '
                          'registrado. Cargá el kilometraje del trabajo.')

        observacion = (request.form.get('observacion') or '').strip()
        nueva_fecha, nuevo_km = registrar_realizado(
            conexion, camioneta['id'], tipo, fecha, km,
            session.get('nombre'), observacion)
        conexion.commit()
    finally:
        conexion.close()

    etiqueta = TIPOS_VENCIMIENTO[tipo]['etiqueta']
    partes = []
    if nueva_fecha:
        partes.append(f'el {nueva_fecha}')
    if nuevo_km:
        partes.append(f'a los {miles(nuevo_km)} km')
    proximo = ' o '.join(partes) if partes else 'sin fecha (configurá la periodicidad)'

    return _volver_calendario(
        mensaje=f'✅ {etiqueta} de {camioneta["patente"]} registrado. '
                f'El próximo vence {proximo}.')


@app.route('/calendario/configurar', methods=['POST'])
def calendario_configurar():
    """Carga o corrige el vencimiento y la periodicidad de una camioneta."""
    if not autorizado('soporte', 'admin'):
        return redirect(url_for('login'))

    conexion = get_db()
    try:
        camioneta, tipo, error = _leer_camioneta_y_tipo(conexion)
        if error:
            return _volver_calendario(error=error)

        config = TIPOS_VENCIMIENTO[tipo]

        def entero(campo, por_defecto=None, minimo=0):
            texto = (request.form.get(campo) or '').strip()
            if not texto:
                return por_defecto
            try:
                valor = int(texto)
            except (TypeError, ValueError):
                raise ValueError(f'"{campo}" tiene que ser un número entero.')
            if valor < minimo:
                raise ValueError(f'"{campo}" no puede ser menor que {minimo}.')
            return valor

        fecha = (request.form.get('fecha_vencimiento') or '').strip() or None
        if fecha and _fecha_iso(fecha) is None:
            return _volver_calendario(error='La fecha de vencimiento no es válida.')

        try:
            km_vencimiento = entero('km_vencimiento')
            periodicidad_dias = entero('periodicidad_dias', config['periodicidad_dias'], 1)
            periodicidad_km = entero('periodicidad_km', config['periodicidad_km'], 1)
            aviso_dias = entero('aviso_dias', config['aviso_dias'], 0)
            aviso_km = entero('aviso_km', config['aviso_km'], 0)
        except ValueError as e:
            return _volver_calendario(error=str(e))

        if not fecha and km_vencimiento is None:
            return _volver_calendario(
                error='Cargá al menos una fecha de vencimiento o un kilometraje: '
                      'sin ninguno de los dos no hay nada que avisar.')

        observacion = (request.form.get('observacion') or '').strip()

        existe = conexion.execute(
            'SELECT id FROM vencimientos WHERE camioneta_id = ? AND tipo = ?',
            (camioneta['id'], tipo)).fetchone()

        if existe:
            conexion.execute('''
                UPDATE vencimientos
                SET fecha_vencimiento = ?, km_vencimiento = ?, periodicidad_dias = ?,
                    periodicidad_km = ?, aviso_dias = ?, aviso_km = ?,
                    observacion = ?, activo = 1
                WHERE id = ?
            ''', (fecha, km_vencimiento, periodicidad_dias, periodicidad_km,
                  aviso_dias, aviso_km, observacion, existe['id']))
        else:
            conexion.execute('''
                INSERT INTO vencimientos
                    (camioneta_id, tipo, fecha_vencimiento, km_vencimiento,
                     periodicidad_dias, periodicidad_km, aviso_dias, aviso_km,
                     observacion, activo)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            ''', (camioneta['id'], tipo, fecha, km_vencimiento, periodicidad_dias,
                  periodicidad_km, aviso_dias, aviso_km, observacion))
        conexion.commit()
    finally:
        conexion.close()

    return _volver_calendario(
        mensaje=f'✅ {TIPOS_VENCIMIENTO[tipo]["etiqueta"]} de {camioneta["patente"]} actualizado.')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ============================================
# MAIN
# ============================================

def create_app():
    """Punto de entrada para un servidor WSGI (waitress, gunicorn).

    Aplica las migraciones antes de aceptar tráfico:
        waitress-serve --host=0.0.0.0 --port=5000 --call app:create_app
    """
    crear_base_de_datos()
    if not os.environ.get('CONTROL_SECRET_KEY'):
        print("⚠️ CONTROL_SECRET_KEY no está definida: las sesiones se van a "
              "cerrar en cada reinicio del servidor.")
    return app


if __name__ == '__main__':
    # crear_base_de_datos() es idempotente (CREATE TABLE IF NOT EXISTS + migraciones),
    # así que se puede llamar siempre. Nunca se borra database.db: el historial de
    # la flota es el activo más importante del sistema.
    try:
        crear_base_de_datos()
        print("✅ Base de datos inicializada correctamente")
    except sqlite3.Error as e:
        print(f"❌ No se pudo inicializar la base de datos: {e}")
        print("   Revisá que database.db no esté abierto en otro programa.")
        raise SystemExit(1)

    # Los técnicos entran desde el celular, así que se escucha en toda la red.
    # debug queda APAGADO por defecto: debug=True + host 0.0.0.0 expone la consola
    # interactiva de Werkzeug, que permite ejecutar código en el servidor.
    debug = os.environ.get('CONTROL_DEBUG', '0') == '1'
    host = os.environ.get('CONTROL_HOST', '0.0.0.0')
    port = int(os.environ.get('CONTROL_PORT', '5000'))

    print(f"🚀 Iniciando servidor en el puerto {port} (host {host})")
    if debug:
        print("⚠️ MODO DEBUG ACTIVO: usar solo en la máquina de desarrollo.")
    app.run(debug=debug, host=host, port=port)
