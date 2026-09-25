// ============================================================
// PANELES EN VIVO
// ------------------------------------------------------------
// Cada pocos segundos se pregunta al servidor si cambió algo en la base
// (/api/version devuelve un número que sube con cada retiro, devolución,
// firma, reporte, etc.). Si cambió, la pantalla se vuelve a cargar sola.
//
// Lo único que se cuida es no pisarle el trabajo a nadie: si la persona está
// escribiendo, tiene una ventana abierta o acaba de tocar algo, no se recarga
// y aparece un aviso de "hay novedades". En cuanto termina, se actualiza.
//
// La página que lo incluye define window.VERSION_DATOS con la versión con
// la que se armó (la inyecta el servidor en cada pantalla).
// ============================================================
(function () {
    'use strict';

    const INTERVALO_MS = 8000;          // cada cuánto se consulta
    const QUIETO_MS = 15000;            // sin tocar nada durante este rato
    const CLAVE_SCROLL = 'tiempoReal.scroll:' + location.pathname;

    let versionPantalla = window.VERSION_DATOS;
    if (versionPantalla === undefined || versionPantalla === null) return;

    let ultimaInteraccion = 0;
    let formularioTocado = false;
    let pendiente = false;              // hay novedades esperando para aplicarse
    let aviso = null;

    // Después de una recarga automática se vuelve a la misma altura: si no,
    // quien estaba mirando el final de una lista vuelve al principio.
    try {
        const guardado = sessionStorage.getItem(CLAVE_SCROLL);
        if (guardado !== null) {
            sessionStorage.removeItem(CLAVE_SCROLL);
            window.addEventListener('load', () => window.scrollTo(0, parseInt(guardado, 10) || 0));
        }
    } catch (e) { /* almacenamiento bloqueado: se pierde el scroll y listo */ }

    ['pointerdown', 'keydown', 'wheel', 'touchstart'].forEach(evento =>
        document.addEventListener(evento, () => { ultimaInteraccion = Date.now(); },
                                  { passive: true, capture: true }));

    // Escribir en cualquier formulario lo marca como "en uso" hasta que se envíe.
    document.addEventListener('input', e => {
        if (e.target.closest && e.target.closest('form')) formularioTocado = true;
    }, true);
    document.addEventListener('change', e => {
        if (e.target.closest && e.target.closest('form')) formularioTocado = true;
    }, true);
    document.addEventListener('submit', () => { formularioTocado = false; }, true);

    function hayVentanaAbierta() {
        return !!document.querySelector(
            '.modal.show, dialog[open], .urgencia-hoja:not([hidden]), ' +
            '.visor-foto:not([hidden]), .actividad-cierre:not([hidden])');
    }

    function estaOcupado() {
        const activo = document.activeElement;
        const escribiendo = activo && /^(INPUT|TEXTAREA|SELECT)$/.test(activo.tagName)
                            && activo.type !== 'button' && activo.type !== 'submit';
        return formularioTocado || escribiendo || hayVentanaAbierta()
               || (Date.now() - ultimaInteraccion) < QUIETO_MS;
    }

    function urlLimpia() {
        // Los avisos de "guardado" viajan en la URL: al recargar no tienen que
        // volver a aparecer como si recién se hubiera hecho algo.
        const url = new URL(location.href);
        url.searchParams.delete('mensaje');
        url.searchParams.delete('error');
        return url.toString();
    }

    function recargar() {
        try { sessionStorage.setItem(CLAVE_SCROLL, String(window.scrollY)); } catch (e) { }
        location.replace(urlLimpia());
    }

    function mostrarAviso() {
        if (aviso) return;
        aviso = document.createElement('div');
        aviso.className = 'tiempo-real-aviso';
        aviso.setAttribute('role', 'status');
        aviso.innerHTML =
            '<span><i class="bi bi-arrow-repeat"></i> Hay novedades.</span>' +
            '<small>Se actualiza cuando termines lo que estás haciendo.</small>' +
            '<button type="button">Actualizar ahora</button>';
        aviso.querySelector('button').addEventListener('click', recargar);
        document.body.appendChild(aviso);
    }

    function aplicarSiSePuede() {
        if (!pendiente) return;
        if (estaOcupado()) {
            mostrarAviso();
            return;
        }
        recargar();
    }

    async function consultar() {
        if (document.hidden) return;    // pestaña en segundo plano: no gasta
        try {
            const resp = await fetch('/api/version', {
                cache: 'no-store', headers: { 'Accept': 'application/json' }
            });
            if (resp.status === 401) return;       // sesión cerrada
            if (!resp.ok) return;
            const datos = await resp.json();
            if (datos.version !== versionPantalla) pendiente = true;
        } catch (e) {
            return;                                // sin conexión: se reintenta
        }
        aplicarSiSePuede();
    }

    setInterval(consultar, INTERVALO_MS);
    // Al volver a la pestaña se consulta en el momento, sin esperar el ciclo.
    document.addEventListener('visibilitychange', () => { if (!document.hidden) consultar(); });

    // Estilos del aviso, acá para no depender de qué hoja carga cada pantalla.
    const estilo = document.createElement('style');
    estilo.textContent =
        '.tiempo-real-aviso{position:fixed;right:18px;bottom:18px;z-index:2000;' +
        'display:flex;flex-direction:column;gap:4px;max-width:300px;padding:12px 14px;' +
        'background:#1f2d5a;color:#fff;border-radius:10px;box-shadow:0 6px 20px rgba(0,0,0,.25);' +
        'font-size:.9rem}' +
        '.tiempo-real-aviso small{opacity:.8}' +
        '.tiempo-real-aviso button{align-self:flex-start;margin-top:4px;border:0;border-radius:6px;' +
        'padding:4px 12px;background:#667eea;color:#fff;font-weight:600;cursor:pointer}';
    document.head.appendChild(estilo);
})();
