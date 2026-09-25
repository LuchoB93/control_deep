"""Manejo de las fotos obligatorias de cada control.

Cada control de camioneta exige cinco fotos sacadas en el momento:
frente, lateral izquierdo, lateral derecho, trasera e interior. No hay
fotos opcionales ni de elementos sueltos: son las cinco posiciones fijas
de la camioneta y cada una admite una sola foto (una nueva reemplaza la
anterior, así el técnico puede corregir si salió movida).

Las fotos se guardan en disco (nunca dentro de SQLite) y en la base queda
solo la ruta relativa. Se comprimen al subirlas: una foto de celular de
4 MB queda en ~200 KB sin perder detalle útil para documentar el estado
de la camioneta.

Se rechazan las fotos viejas: la app pide la cámara al celular en vez de
la galería, y además el servidor verifica el EXIF y la fecha de captura
para descartar imágenes que no fueron sacadas en el momento del control.
"""

from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
import secrets

from PIL import Image, ImageOps
from PIL.ExifTags import TAGS

# Resolución máxima del lado largo. 1600px alcanza para leer una patente o
# distinguir una cubierta gastada, y baja el peso de la foto ~20 veces.
MAX_ANCHO = 1600
CALIDAD_JPEG = 80

# Posiciones obligatorias del control. El orden es el que se muestra en la
# pantalla y el que se recorre al validar que estén todas.
POSICIONES = {
    'FRENTE': {
        'etiqueta': 'Frente',
        'ayuda': 'Foto de la camioneta de frente, donde se vea la patente.',
        'icono': 'arrow-up',
    },
    'LATERAL_IZQ': {
        'etiqueta': 'Lateral izquierdo',
        'ayuda': 'Perfil izquierdo completo de la camioneta.',
        'icono': 'arrow-left',
    },
    'LATERAL_DER': {
        'etiqueta': 'Lateral derecho',
        'ayuda': 'Perfil derecho completo de la camioneta.',
        'icono': 'arrow-right',
    },
    'TRASERA': {
        'etiqueta': 'Parte trasera',
        'ayuda': 'Foto de atrás, donde se vea la patente trasera.',
        'icono': 'arrow-down',
    },
    'INTERIOR': {
        'etiqueta': 'Interior',
        'ayuda': 'Cabina y caja: se tiene que ver el orden y la limpieza.',
        'icono': 'grid',
    },
}

EXTENSIONES = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}

# Cuánto puede tener una foto como máximo, contando desde el momento en que
# el servidor la recibe. Es el margen para subir fotos de un control que se
# empezó hace un rato: si alguien intenta subir una foto de la semana pasada,
# el EXIF lo delata y se rechaza.
ANTIGUEDAD_MAXIMA = timedelta(hours=2)

# Puntero al sub-bloque Exif dentro del EXIF de la imagen.
EXIF_IFD = 0x8769


def fecha_declarada(fecha_captura, ultima_modificacion, zona_horaria):
    """La fecha de captura que informó el navegador, como datetime local naive.

    Primero la del EXIF del original ('AAAA:MM:DD HH:MM:SS', hora local del
    celular, igual que la que lee _fecha_exif). Si la foto no traía EXIF, la
    fecha de modificación del archivo (milisegundos desde 1970): una foto de
    la galería suele tenerla vieja, una recién sacada la tiene de ahora.
    None si no vino ninguna de las dos.
    """
    try:
        if fecha_captura:
            return datetime.strptime(fecha_captura.strip()[:19], '%Y:%m:%d %H:%M:%S')
    except ValueError:
        pass
    try:
        milisegundos = int(ultima_modificacion)
        if milisegundos > 0:
            return (datetime.fromtimestamp(milisegundos / 1000, zona_horaria)
                    .replace(tzinfo=None))
    except (TypeError, ValueError, OverflowError, OSError):
        pass
    return None


def _carpeta_destino(fotos_dir, patente, fecha):
    """fotos/AA123BB/2026-09/ — creada si no existe."""
    carpeta = Path(fotos_dir) / patente / fecha[:7]
    carpeta.mkdir(parents=True, exist_ok=True)
    return carpeta


def _fecha_exif(imagen):
    """Fecha en que se sacó la foto según el EXIF, o None si no la trae.

    Los celulares casi siempre la incluyen en DateTimeOriginal. Las fotos
    editadas o reencodeadas suelen perderla, y ese es justamente uno de los
    casos que queremos detectar.
    """
    try:
        exif = imagen.getexif()
        if not exif:
            return None
        # DateTimeOriginal no está en el primer nivel del EXIF sino en el
        # sub-bloque Exif (0x8769), que es donde la escriben los celulares.
        # Antes solo se miraba el primer nivel, así que nunca se encontraba
        # y ninguna foto vieja se rechazaba.
        for bloque in (exif.get_ifd(EXIF_IFD), exif):
            for tag_id, valor in bloque.items():
                if TAGS.get(tag_id) == 'DateTimeOriginal':
                    return datetime.strptime(str(valor).strip()[:19], '%Y:%m:%d %H:%M:%S')
    except (AttributeError, ValueError, TypeError, KeyError):
        return None
    return None


def validar_imagen(archivo, momento, fecha_declarada=None):
    """(ok, error). Valida formato, tamaño y que la foto sea reciente.

    `fecha_declarada` es la fecha de captura que leyó el navegador del
    archivo original. Hace falta porque el celular comprime la foto con un
    canvas antes de subirla, y eso borra el EXIF: sin este dato, cualquier
    foto de la galería pasaría como recién sacada. Solo se usa cuando la
    imagen que llega no trae su propia fecha.

    No alcanza con mirar la extensión: hay que abrir el archivo. Un .jpg
    renombrado desde un .exe pasaría el filtro de extensión; abrirlo con
    Pillow y verificarlo lo rechaza.

    El chequeo de fecha es a propósito laxo: si el EXIF está, se usa; si no
    está, se confía en el timestamp del servidor. Lo que se rechaza es una
    foto cuya fecha EXIF sea claramente vieja, porque eso indica que salió
    de la galería y no de la cámara.
    """
    if not archivo or not archivo.filename:
        return False, 'No se seleccionó ninguna foto.'

    extension = PurePosixPath(archivo.filename).suffix.lower()
    if extension not in EXTENSIONES:
        return False, f'Formato no permitido ({extension}). Usá JPG, PNG o WEBP.'

    try:
        archivo.stream.seek(0, 2)
        tamano = archivo.stream.tell()
        archivo.stream.seek(0)
        if tamano == 0:
            return False, 'El archivo está vacío.'
        if tamano > 20 * 1024 * 1024:
            return False, 'La foto pesa más de 20 MB. Sacala con menos resolución.'

        with Image.open(archivo.stream) as img:
            img.verify()

        archivo.stream.seek(0)
        with Image.open(archivo.stream) as img:
            fecha_exif = _fecha_exif(img) or fecha_declarada

        if fecha_exif and momento - fecha_exif > ANTIGUEDAD_MAXIMA:
            return False, ('Esta foto no fue sacada en el momento del control. '
                           'Sacá una nueva con la cámara.')
    except Exception:
        return False, 'El archivo no es una imagen válida.'

    archivo.stream.seek(0)
    return True, None


def guardar_foto(archivo, fotos_dir, patente, control_id, posicion, fecha, momento,
                 fecha_declarada=None):
    """Comprime y guarda una foto. Devuelve (ruta_relativa, error).

    La ruta relativa es lo único que va a la base: 'AA123BB/2026-09/xxx.jpg'.
    Guardar la ruta absoluta rompería todo el día que se mueva el servidor
    (es el mismo error que ya se corrigió en las firmas).
    """
    ok, error = validar_imagen(archivo, momento, fecha_declarada)
    if not ok:
        return None, error

    try:
        with Image.open(archivo.stream) as img:
            # Las fotos de celular traen la orientación en el EXIF: sin esto,
            # las verticales se ven acostadas.
            img = ImageOps.exif_transpose(img)

            if img.width > MAX_ANCHO:
                alto = int(img.height * MAX_ANCHO / img.width)
                img = img.resize((MAX_ANCHO, alto), Image.LANCZOS)

            # JPEG no soporta transparencia: los PNG con alpha hay que aplanarlos
            # o Pillow tira error al guardar.
            if img.mode in ('RGBA', 'LA', 'P'):
                fondo = Image.new('RGB', img.size, (255, 255, 255))
                fondo.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = fondo
            elif img.mode != 'RGB':
                img = img.convert('RGB')

            carpeta = _carpeta_destino(fotos_dir, patente, fecha)
            # El sufijo random evita colisiones si dos fotos caen en el mismo
            # segundo (pasa: el técnico saca varias seguidas).
            sufijo = secrets.token_hex(3)
            momento_str = momento.strftime('%Y%m%d_%H%M%S')
            nombre = f"control_{control_id}_{posicion.lower()}_{momento_str}_{sufijo}.jpg"

            ruta_absoluta = carpeta / nombre
            img.save(ruta_absoluta, 'JPEG', quality=CALIDAD_JPEG, optimize=True)

    except Exception as e:
        return None, f'No se pudo procesar la imagen: {e}'

    relativa = f'{patente}/{fecha[:7]}/{nombre}'
    return relativa, None


def resolver_ruta(fotos_dir, ruta_relativa):
    """Ruta absoluta de una foto guardada, validando que no se escape de fotos/.

    Igual que con remitos: sin esta validación, un '..' en la ruta permitiría
    leer cualquier archivo del servidor.
    """
    if not ruta_relativa:
        return None
    base = Path(fotos_dir).resolve()
    try:
        candidata = (base / ruta_relativa).resolve()
        candidata.relative_to(base)
    except (ValueError, OSError):
        return None
    return candidata if candidata.is_file() else None


def borrar_foto(fotos_dir, ruta_relativa):
    """Borra el archivo del disco. No falla si ya no está."""
    ruta = resolver_ruta(fotos_dir, ruta_relativa)
    if ruta and ruta.exists():
        try:
            ruta.unlink()
        except OSError as e:
            print(f'⚠️ No se pudo borrar la foto {ruta.name}: {e}')