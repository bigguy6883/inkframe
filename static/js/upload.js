/* Upload handling: drag-drop + file picker, sequential upload with progress */

(function() {
    const zone = document.getElementById('uploadZone');
    const input = document.getElementById('fileInput');
    const progress = document.getElementById('uploadProgress');

    if (!zone || !input) return;

    // Click to open file picker
    zone.addEventListener('click', () => input.click());

    // Drag and drop
    zone.addEventListener('dragover', (e) => {
        e.preventDefault();
        zone.classList.add('dragover');
    });

    zone.addEventListener('dragleave', () => {
        zone.classList.remove('dragover');
    });

    zone.addEventListener('drop', (e) => {
        e.preventDefault();
        zone.classList.remove('dragover');
        handleFiles(e.dataTransfer.files);
    });

    // File picker change
    input.addEventListener('change', () => {
        if (input.files.length > 0) {
            handleFiles(input.files);
            input.value = '';
        }
    });

    function handleFiles(files) {
        const validFiles = Array.from(files).filter(f =>
            f.type.startsWith('image/') && f.size <= 20 * 1024 * 1024
        );

        if (validFiles.length === 0) return;

        progress.innerHTML = '';
        progress.classList.add('active');

        // Create progress items
        validFiles.forEach((file, i) => {
            const item = document.createElement('div');
            item.className = 'progress-item';
            item.id = 'progress-' + i;
            item.innerHTML = `
                <span style="flex:0 0 120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${file.name}</span>
                <div class="progress-bar-container"><div class="progress-bar" id="bar-${i}"></div></div>
                <span class="progress-status" id="status-${i}">Waiting</span>
            `;
            progress.appendChild(item);
        });

        // Upload sequentially
        uploadSequential(validFiles, 0);
    }

    function uploadSequential(files, index) {
        if (index >= files.length) {
            // All done, reload after short delay
            setTimeout(() => location.reload(), 500);
            return;
        }

        const file = files[index];
        const bar = document.getElementById('bar-' + index);
        const status = document.getElementById('status-' + index);
        status.textContent = 'Uploading...';

        const formData = new FormData();
        formData.append('file', file);

        const xhr = new XMLHttpRequest();
        xhr.open('POST', '/api/photos/upload');

        xhr.upload.addEventListener('progress', (e) => {
            if (e.lengthComputable) {
                const pct = Math.round((e.loaded / e.total) * 100);
                bar.style.width = pct + '%';
                status.textContent = pct + '%';
            }
        });

        xhr.addEventListener('load', () => {
            if (xhr.status === 200) {
                bar.style.width = '100%';
                bar.classList.add('complete');
                status.textContent = 'Done';
            } else {
                bar.classList.add('error');
                try {
                    const resp = JSON.parse(xhr.responseText);
                    status.textContent = resp.error || 'Error';
                } catch(e) {
                    status.textContent = 'Error';
                }
            }
            uploadSequential(files, index + 1);
        });

        xhr.addEventListener('error', () => {
            bar.classList.add('error');
            status.textContent = 'Failed';
            uploadSequential(files, index + 1);
        });

        xhr.send(formData);
    }
})();
