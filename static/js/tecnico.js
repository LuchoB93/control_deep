// ==========================================
// CONTROL RÁPIDO DEL TÉCNICO
// ==========================================

let elementoActual = null;
let categoriaActual = null;
let cardActual = null;
let modalInstance = null;

// ==========================================
// INICIALIZACIÓN
// ==========================================
document.addEventListener('DOMContentLoaded', function() {
    modalInstance = new bootstrap.Modal(document.getElementById('modalObservacion'));
    actualizarProgreso();
    
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && modalInstance) {
            modalInstance.hide();
        }
    });
});

// ==========================================
// TOGGLE ESTADO
// ==========================================
function toggleEstado(elemento, categoria, card) {
    if (card.classList.contains('bloqueado')) {
        mostrarMensaje('⚠️ Elemento bloqueado', 'warning');
        return;
    }

    elementoActual = elemento;
    categoriaActual = categoria;
    cardActual = card;

    if (card.classList.contains('estado-ok')) {
        if (!confirm('¿Quieres cambiar el estado de "' + elemento + '"?')) {
            return;
        }
    }

    document.getElementById('modal-elemento-nombre').textContent = elemento;
    document.getElementById('modal-observacion').value = '';
    modalInstance.show();
}

// ==========================================
// CONFIRMAR ESTADO
// ==========================================
function confirmarEstado(estado) {
    const observacion = document.getElementById('modal-observacion').value.trim();
    
    if (estado === 'OK') {
        guardarEstado(estado, '');
        return;
    }
    
    if (estado !== 'OK' && observacion === '') {
        if (!confirm('¿Estás seguro de marcar "' + elementoActual + '" como ' + estado + ' sin observación?')) {
            return;
        }
    }
    
    guardarEstado(estado, observacion);
}

// ==========================================
// GUARDAR ESTADO
// ==========================================
function guardarEstado(estado, observacion) {
    const controlId = document.getElementById('control-id').value;
    
    fetch('/guardar-estado-elemento', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({
            'control_id': controlId,
            'elemento': elementoActual,
            'categoria': categoriaActual,
            'estado': estado,
            'observacion': observacion
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            actualizarCard(cardActual, estado);
            modalInstance.hide();
            actualizarProgreso();
            
            const iconos = {
                'OK': '✅',
                'FALLA': '❌',
                'FALTANTE': '⚠️',
                'OBSERVACION': '💬'
            };
            mostrarMensaje(iconos[estado] + ' ' + elementoActual + ' → ' + estado, 'success');
        } else {
            mostrarMensaje('❌ Error: ' + (data.error || 'No se pudo guardar'), 'danger');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        mostrarMensaje('❌ Error de conexión', 'danger');
    });
}

// ==========================================
// ACTUALIZAR CARD
// ==========================================
function actualizarCard(card, estado) {
    card.classList.remove('estado-ok', 'estado-falla', 'estado-faltante', 'estado-observacion', 'estado-pendiente');
    
    const clases = {
        'OK': 'estado-ok',
        'FALLA': 'estado-falla',
        'FALTANTE': 'estado-faltante',
        'OBSERVACION': 'estado-observacion'
    };
    card.classList.add(clases[estado] || 'estado-pendiente');
    
    const badge = card.querySelector('.estado-badge');
    badge.textContent = estado;
    
    card.classList.add('registrado');
    card.classList.add('animar');
    setTimeout(() => card.classList.remove('animar'), 300);
}

// ==========================================
// ACTUALIZAR PROGRESO
// ==========================================
function actualizarProgreso() {
    const total = document.querySelectorAll('.elemento-card:not(.bloqueado)').length;
    const registrados = document.querySelectorAll('.elemento-card.registrado').length;
    
    let porcentaje = total > 0 ? Math.round((registrados / total) * 100) : 0;
    
    document.getElementById('contador-progreso').textContent = porcentaje + '%';
    const barra = document.getElementById('barra-progreso');
    barra.style.width = porcentaje + '%';
    
    if (porcentaje === 100) {
        barra.style.background = '#28a745';
    } else if (porcentaje >= 70) {
        barra.style.background = '#17a2b8';
    } else if (porcentaje >= 40) {
        barra.style.background = '#ffc107';
    } else {
        barra.style.background = '#6c757d';
    }
}

// ==========================================
// FINALIZAR CONTROL
// ==========================================
function finalizarControl() {
    const total = document.querySelectorAll('.elemento-card:not(.bloqueado)').length;
    const registrados = document.querySelectorAll('.elemento-card.registrado').length;
    
    if (registrados < total) {
        const pendientes = total - registrados;
        if (!confirm('⚠️ Faltan ' + pendientes + ' elementos. ¿Finalizar igual?')) {
            return;
        }
    }
    
    if (confirm('¿Finalizar este control?')) {
        document.getElementById('form-control').submit();
    }
}

// ==========================================
// MOSTRAR MENSAJE FLOTANTE
// ==========================================
function mostrarMensaje(mensaje, tipo) {
    const alerta = document.createElement('div');
    const colores = {
        'success': 'bg-success text-white',
        'danger': 'bg-danger text-white',
        'warning': 'bg-warning text-dark',
        'info': 'bg-info text-white'
    };
    
    alerta.className = `mensaje-flotante ${colores[tipo] || 'bg-secondary text-white'}`;
    alerta.textContent = mensaje;
    document.body.appendChild(alerta);
    
    setTimeout(() => {
        alerta.style.opacity = '0';
        setTimeout(() => alerta.remove(), 500);
    }, 2000);
}