// static/js/mfa.js

(function () {
    // Copy to clipboard
    document.querySelectorAll('.mfa-copy-btn[data-copy]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            var targetId = this.getAttribute('data-copy');
            var el = document.getElementById(targetId);
            if (el) {
                navigator.clipboard.writeText(el.textContent.trim());
                var span = this.querySelector('span');
                if (span) {
                    var original = span.textContent;
                    span.textContent = 'Copiado';
                    setTimeout(function () { span.textContent = original; }, 2000);
                }
            }
        });
    });

    // Copy all backup codes
    var copyAllBtn = document.getElementById('copy-all-codes');
    if (copyAllBtn) {
        copyAllBtn.addEventListener('click', function () {
            var codesEl = document.getElementById('backup-codes');
            if (codesEl) {
                var codes = [];
                codesEl.querySelectorAll('.mfa-code-item').forEach(function (item) {
                    codes.push(item.textContent.trim());
                });
                navigator.clipboard.writeText(codes.join('\n'));
                var span = this.querySelector('span');
                if (span) {
                    var original = span.textContent;
                    span.textContent = 'Copiado';
                    setTimeout(function () { span.textContent = original; }, 2000);
                }
            }
        });
    }

    // Confirm checkbox enables finish button
    var confirmCheck = document.getElementById('confirm-saved');
    var finishBtn = document.getElementById('finish-btn');
    if (confirmCheck && finishBtn) {
        confirmCheck.addEventListener('change', function () {
            finishBtn.disabled = !this.checked;
        });
    }

    // File input label update
    var fileInput = document.getElementById('pem_file');
    var fileLabel = document.getElementById('file-label');
    if (fileInput && fileLabel) {
        fileInput.addEventListener('change', function () {
            var textEl = fileLabel.querySelector('.mfa-file-text');
            var hintEl = fileLabel.querySelector('.mfa-file-hint');
            if (this.files && this.files.length > 0) {
                textEl.textContent = this.files[0].name;
                hintEl.textContent = (this.files[0].size / 1024).toFixed(1) + ' KB';
                fileLabel.classList.add('has-file');
            } else {
                textEl.textContent = 'Seleccionar archivo .pem';
                hintEl.textContent = 'o arrastra aquí';
                fileLabel.classList.remove('has-file');
            }
        });
    }

    // TOTP input: auto-submit when 6 digits entered
    var codeInput = document.getElementById('code');
    if (codeInput) {
        codeInput.addEventListener('input', function () {
            this.value = this.value.replace(/[^0-9]/g, '');
        });
    }
}());
