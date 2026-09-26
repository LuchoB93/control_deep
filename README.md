# Control de Camionetas

Control diario de la flota del departamento técnico: asignación de camionetas
por jornada, control de retiro y devolución sobre el catálogo de elementos,
seguimiento de faltantes y remitos de reposición firmados.

## Roles

| Rol | Quién | Qué hace |
|---|---|---|
| `admin` | Soporte técnico | Arma las planillas, resuelve faltantes, genera y cierra remitos, administra zonas / camionetas / usuarios / elementos |
| `jefe` | Gerencia técnica | Ve el estado de la flota y las estadísticas. No opera |
| `tecnico` | Técnico de calle | Hace el control de retiro y devolución de su camioneta |

## Cómo funciona el control

La camioneta necesita **retiro cuando cambia de manos** y **devolución cuando
va a cambiar de manos**. No es por turno: si el mismo técnico la conserva en el
turno siguiente (por ejemplo alguien de guardia, con zona `GUARDIA`, que se la
lleva a la casa toda la semana), retira una sola vez al principio y devuelve
recién cuando pasa a otra persona. Hasta que el responsable anterior no
devuelve, el siguiente no puede retirar.

Un elemento reportado como faltante queda **bloqueado** para esa camioneta y
deja de pedirse en los controles siguientes. Se destraba de dos maneras: soporte
lo resuelve desde el panel, o el técnico lo marca como recuperado en el
desplegable del final de la pantalla de control, con una explicación obligatoria.

## Jornadas

| Jornada | Días | Horario |
|---|---|---|
| Mañana | Lunes a viernes | 07:30 – 14:45 |
| Tarde | Lunes a viernes | 14:30 – 20:30 |
| Tarde | Sábados | 09:30 – 15:30 |

Los domingos no se trabaja. Soporte ve una alerta cuando pasa **una hora** del
inicio del turno sin que se haya hecho el retiro, o una hora del cierre sin la
devolución. El bloque se refresca solo cada 2 minutos.

Los horarios se configuran en `HORARIOS` y el margen en `MARGEN_CONTROL`,
ambos al principio de `app.py`.

## Variables de entorno

| Variable | Default | Para qué |
|---|---|---|
| `CONTROL_SECRET_KEY` | aleatoria por arranque | Firma las sesiones. **Definirla en producción**: sin ella, cada reinicio cierra las sesiones abiertas |
| `CONTROL_DATA_DIR` | carpeta del proyecto | Dónde vive `database.db` |
| `CONTROL_REMITOS_DIR` | `./remitos` | PDF de remitos |
| `CONTROL_FIRMAS_DIR` | `./static/firmas` | Firmas de los administradores |
| `CONTROL_FOTOS_DIR` | `./fotos` | Las cinco fotos de cada control |
| `CONTROL_FOTOS_OBLIGATORIAS` | `1` | `0` vuelve opcionales las fotos del control. **Solo para pruebas** desde una PC sin cámara |
| `CONTROL_TZ` | `America/Argentina/Buenos_Aires` | Zona horaria de las jornadas y alertas |
| `CONTROL_HOST` | `0.0.0.0` | Solo para el servidor de desarrollo |
| `CONTROL_PORT` | `5000` | Puerto |
| `CONTROL_DEBUG` | `0` | `1` activa el modo debug. **Nunca en producción**: expone una consola que permite ejecutar código en el servidor |

## Varias personas a la vez

**Una sola maquina corre el servidor.** El resto entra por el navegador a la
direccion de esa maquina; no ejecutan nada. Es la unica forma de que todos vean
la misma informacion: `database.db` esta en `.gitignore` y no se versiona, asi
que si cada uno corre `python app.py` en su PC, cada uno se crea una base vacia
propia y nunca ven lo mismo.

En la maquina que hace de servidor:

```
servidor.bat
```

Ese script levanta waitress y muestra la direccion de la red (algo como
`http://192.168.1.147:5000`). Los demas la abren en el navegador del celular o
de la otra compu, estando en la misma red Wi-Fi.

La primera vez, Windows pregunta si permite el acceso: hay que aceptar para la
red **privada** y la **publica**, si no el firewall corta las conexiones de los
otros dispositivos.

Si desde otro dispositivo no carga:

| Sintoma | Causa habitual |
|---|---|
| No carga / tarda y corta | Firewall de Windows, o el router tiene aislamiento de clientes activado |
| Carga pero los datos son distintos | La otra persona esta corriendo su propia copia del servidor |
| Los saca a todos cada tanto | `CONTROL_SECRET_KEY` cambio: cada reinicio con clave nueva cierra las sesiones |

La clave de sesion vive en `.env`, que no se versiona. Si no existe, se genera
una al azar en cada arranque y las sesiones se cierran en cada reinicio:

```
CONTROL_SECRET_KEY=<clave larga y aleatoria>
```

Se genera con `python -c "import secrets; print(secrets.token_hex(32))"`.

## Desarrollo

```bash
python -m venv venv
venv\Scripts\activate          # Linux/Mac: source venv/bin/activate
pip install -r requirements.txt
python app.py
```

Queda en http://localhost:5000. La base se crea sola con usuarios de ejemplo si
no existe.

## Producción con Docker

Mientras se sigue desarrollando **no hace falta Docker**: se usa `servidor.bat`
como siempre. Todo lo de producción está preparado pero solo se activa con
`docker compose`.

### Qué se levanta

| Servicio  | Qué hace                                                        |
|-----------|-----------------------------------------------------------------|
| `caddy`   | Único expuesto (80/443). Saca y renueva solo el certificado HTTPS. |
| `control` | La app (waitress). Sin puertos publicados: solo le habla Caddy.   |
| `backup`  | Backup diario de la base y los archivos, sin acceso a la red.     |

Los datos viven en volúmenes (`control-datos`, `control-remitos`,
`control-firmas`, `control-fotos`), así que reconstruir la imagen no borra nada.

### Requisitos de red (una sola vez)

1. IP pública fija para el servidor (idealmente en una DMZ).
2. Registro DNS tipo `A` en DonWeb: `control.<dominio>` → esa IP.
3. Firewall: abiertos solo 80 y 443 hacia el servidor. SSH solo desde la red interna.

### Primer despliegue

```bash
git clone <repo> control && cd control
cp .env.example .env
python3 -c "import secrets; print(secrets.token_hex(32))"   # clave NUEVA -> .env
# en .env: CONTROL_DOMINIO=control.<dominio>
docker compose up -d --build
docker compose logs -f          # ver que Caddy obtenga el certificado
```

Para probar la pila completa en una PC sin dominio, dejar `CONTROL_DOMINIO`
sin definir y entrar a https://localhost (el navegador avisa del certificado
interno; es normal).

### Actualizar a una versión nueva

```bash
git pull
docker compose up -d --build     # las migraciones corren solas al arrancar
```

### Backup

El servicio `backup` corre todos los días a las `CONTROL_BACKUP_HORA` (3 AM) y
guarda en `backups-produccion/` una copia de la base (`database_*.db`) y un
`archivos_*.tar.gz` con remitos, firmas y fotos. Conserva `CONTROL_BACKUP_DIAS`
días. **Copiar esa carpeta a otro equipo**: un backup en el mismo disco no
sirve si el disco se rompe.

Backup manual en cualquier momento:

```bash
docker compose run --rm backup python backup.py
```

Restaurar la base:

```bash
docker compose stop control
docker run --rm -v control_control-datos:/datos -v "$PWD/backups-produccion":/b alpine   sh -c "cp /b/database_AAAA-MM-DD_HHMM.db /datos/database.db && rm -f /datos/database.db-wal /datos/database.db-shm"
docker compose start control
```

(El nombre real del volumen se ve con `docker volume ls`.)

### Checklist antes de publicar la versión final

- [ ] `.env` de producción con clave nueva y **sin** `CONTROL_FOTOS_OBLIGATORIAS=0`.
- [ ] Protección CSRF en los formularios (pendiente).
- [ ] Límite de intentos de login (pendiente).
- [ ] Borrar usuarios y datos de prueba; cambiar contraseñas por defecto.
- [ ] Decidir acceso: VPN de la empresa o público (+ Cloudflare Access opcional).
- [ ] Probar un restore del backup al menos una vez.

## Contraseñas

Se guardan hasheadas (scrypt). Las que quedaron en texto plano de la versión
anterior se convierten solas la primera vez que cada usuario entra con su
contraseña de siempre: nadie tiene que cambiar nada. El admin puede resetear
cualquier contraseña desde **Configuración → Usuarios**.

## Configuración desde la aplicación

**Configuración** en el panel de soporte (solo `admin`) administra:

- **Zonas** — lista fija que alimenta el desplegable de la planilla. Renombrar
  una zona actualiza las asignaciones que la usan.
- **Camionetas** — alta y baja lógica. Dar de baja la saca de la planilla pero
  conserva su historial.
- **Usuarios** — alta, rol, activación y reseteo de contraseña. No podés
  desactivarte ni cambiarte el rol a vos mismo, y no se puede dejar al sistema
  sin ningún administrador activo.
- **Elementos del control** — el catálogo que se revisa en cada camioneta.
  Quitar un elemento deja de pedirlo en los controles nuevos sin borrar el
  historial; renombrarlo arrastra el historial para no cortar la trazabilidad.

## Estructura de datos

- `asignaciones` — camioneta + técnico responsable + acompañante + zona, por fecha y jornada.
- `controles_tecnicos` — cada control de retiro o devolución.
- `items_control_tecnico` — la planilla completa de cada control: **todos** los
  elementos con su estado. Es la prueba de que se revisó todo y la fuente de la
  consulta "última vez que este elemento estuvo OK".
- `reportes` — **solo los problemas**. Un control sin novedades no genera filas.
- `elementos_bloqueados` — faltantes vigentes por camioneta.
- `seguimiento_remitos` — estado de cada remito: pendiente de firma → firmado → revisado.
