FROM python:3.12-slim

# Zona horaria de Argentina: las jornadas y las alertas de controles vencidos
# se calculan con la hora local del contenedor.
ENV TZ=America/Argentina/Buenos_Aires \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Las dependencias se instalan antes de copiar el código, para que un cambio
# en la aplicación no invalide esta capa del build.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Los datos van en un volumen; ver docker-compose.yml.
RUN mkdir -p /app/remitos /app/static/firmas /app/fotos

# Usuario sin privilegios.
RUN useradd --create-home --uid 1000 control \
    && chown -R control:control /app
USER control

EXPOSE 5000

# waitress es el servidor de producción; el de Flask es solo para desarrollo.
# create_app() aplica las migraciones antes de aceptar tráfico.
CMD ["waitress-serve", "--host=0.0.0.0", "--port=5000", "--call", "app:create_app"]
