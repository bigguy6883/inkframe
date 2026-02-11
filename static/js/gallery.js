/* Gallery: select mode, delete, display controls */

var selectMode = false;
var selectedIds = new Set();

function toggleSelectMode() {
    selectMode = !selectMode;
    selectedIds.clear();

    var grid = document.getElementById('galleryGrid');
    var selectBtn = document.getElementById('selectBtn');
    var deleteBtn = document.getElementById('deleteBtn');
    var cancelBtn = document.getElementById('cancelBtn');

    if (!grid) return;

    if (selectMode) {
        grid.classList.add('select-mode');
        selectBtn.style.display = 'none';
        deleteBtn.style.display = '';
        cancelBtn.style.display = '';
    } else {
        grid.classList.remove('select-mode');
        grid.querySelectorAll('.gallery-item').forEach(function(el) {
            el.classList.remove('selected');
        });
        selectBtn.style.display = '';
        deleteBtn.style.display = 'none';
        cancelBtn.style.display = 'none';
    }
}

// Gallery item click
document.addEventListener('click', function(e) {
    var item = e.target.closest('.gallery-item');
    if (!item) return;
    if (e.target.closest('.show-btn')) return;

    if (selectMode) {
        var id = parseInt(item.dataset.id);
        if (selectedIds.has(id)) {
            selectedIds.delete(id);
            item.classList.remove('selected');
        } else {
            selectedIds.add(id);
            item.classList.add('selected');
        }
        var deleteBtn = document.getElementById('deleteBtn');
        deleteBtn.textContent = 'Delete (' + selectedIds.size + ')';
    }
});

function deleteSelected() {
    if (selectedIds.size === 0) return;
    if (!confirm('Delete ' + selectedIds.size + ' photo(s)?')) return;

    fetch('/api/photos/delete-bulk', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ids: Array.from(selectedIds)})
    })
    .then(function(r) { return r.json(); })
    .then(function() { location.reload(); });
}

function displayAction(action) {
    fetch('/api/display/' + action, {method: 'POST'});
}

function displayShow(photoId) {
    fetch('/api/display/show/' + photoId, {method: 'POST'});
}

function slideshowAction(action) {
    fetch('/api/slideshow/' + action, {method: 'POST'})
        .then(function() { location.reload(); });
}
