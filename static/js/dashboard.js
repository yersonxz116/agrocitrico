// static/js/dashboard.js

(function () {

    // Inicializa iconos Lucide
    if (window.lucide) {
        lucide.createIcons();
    }

    // Fecha en el topbar
    var dateEl = document.getElementById('js-date');
    if (dateEl) {
        var now = new Date();
        var opts = { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' };
        dateEl.textContent = now.toLocaleDateString('es-CO', opts);
    }

    // Anima la barra de progreso de cosecha
    document.querySelectorAll('.harvest-bar').forEach(function (bar) {
        var progress = Math.max(0, Math.min(100, Number(bar.dataset.progress || 0)));
        var fill = bar.querySelector('div');
        if (fill) {
            requestAnimationFrame(function () {
                fill.style.width = progress + '%';
            });
        }
    });

    // Función para actualizar sensores en tiempo real
    function actualizarSensores() {
        fetch('/api/sensores/ultimo')
            .then(function (res) {
                if (res.ok) return res.json();
                throw new Error('Error al obtener datos de los sensores');
            })
            .then(function (data) {
                // Actualizar temperatura
                var tempVal = document.getElementById('sensor-val-0');
                var tempTrend = document.getElementById('sensor-trend-0');
                var weatherTemp = document.getElementById('js-weather-temp');
                var weatherDesc = document.getElementById('js-weather-desc');
                
                var formatTemp = data.temperatura !== null ? data.temperatura.toFixed(1) + ' °C' : '—';
                
                if (tempVal && data.temperatura !== null) {
                    tempVal.textContent = formatTemp;
                }
                if (tempTrend && data.trends) {
                    tempTrend.textContent = data.trends.temperatura;
                }
                if (weatherTemp) {
                    weatherTemp.textContent = formatTemp;
                }
                if (weatherDesc && data.trends) {
                    weatherDesc.textContent = data.trends.temperatura || 'Esperando sensor';
                }

                // Actualizar humedad ambiental
                var humAireVal = document.getElementById('sensor-val-1');
                var humAireTrend = document.getElementById('sensor-trend-1');
                if (humAireVal && data.humedad_aire !== null) {
                    humAireVal.textContent = data.humedad_aire.toFixed(0) + '%';
                }
                if (humAireTrend && data.trends) {
                    humAireTrend.textContent = data.trends.humedad_aire;
                }

                // Actualizar humedad del suelo (lista y stat card)
                var humSueloVal = document.getElementById('sensor-val-2');
                var humSueloTrend = document.getElementById('sensor-trend-2');
                var statSueloVal = document.getElementById('js-stat-hum-suelo');
                var statSueloTrend = document.getElementById('js-stat-hum-suelo-detail');

                var formatSuelo = data.humedad_suelo !== null ? data.humedad_suelo.toFixed(0) + '%' : '—';

                if (humSueloVal && data.humedad_suelo !== null) {
                    humSueloVal.textContent = formatSuelo;
                }
                if (humSueloTrend && data.trends) {
                    humSueloTrend.textContent = data.trends.humedad_suelo;
                }
                if (statSueloVal) {
                    statSueloVal.textContent = formatSuelo;
                }
                if (statSueloTrend && data.trends) {
                    statSueloTrend.textContent = data.trends.humedad_suelo;
                }
            })
            .catch(function (err) {
                console.error('Error polling sensors:', err);
            });
    }

    // Ejecutar inmediatamente y luego cada 10 segundos
    actualizarSensores();
    setInterval(actualizarSensores, 10000);

    // Modal editar meta semanal
    var btnEditMeta = document.getElementById('js-btn-edit-meta');
    var modal = document.getElementById('js-modal-meta');
    var modalClose = document.getElementById('js-modal-close');
    var modalCancel = document.getElementById('js-modal-cancel');

    function openModal() {
        modal.classList.add('is-open');
        modal.setAttribute('aria-hidden', 'false');
        modal.querySelector('.modal-input').focus();
    }

    function closeModal() {
        modal.classList.remove('is-open');
        modal.setAttribute('aria-hidden', 'true');
    }

    if (btnEditMeta && modal) {
        btnEditMeta.addEventListener('click', openModal);
        modalClose.addEventListener('click', closeModal);
        modalCancel.addEventListener('click', closeModal);
        modal.addEventListener('click', function (e) {
            if (e.target === modal) closeModal();
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && modal.classList.contains('is-open')) closeModal();
        });
    }

}());
