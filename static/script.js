document.addEventListener('DOMContentLoaded', () => {
    // --- Elements ---
    const searchInput = document.getElementById('searchInput');
    const searchBtn = document.getElementById('searchBtn');
    const resultsContainer = document.getElementById('results');
    const loader = document.getElementById('loader');
    const toast = document.getElementById('toast');

    // DOM Elements
    const searchTab = document.getElementById('search-tab');

    // Splash Screen Logic
    window.addEventListener('load', () => {
        const splash = document.getElementById('splash-screen');
        setTimeout(() => {
            splash.classList.add('hidden');
        }, 5000); // 5 Seconds
    });

    // Theme Logic
    const themeCheckbox = document.getElementById('themeToggleCheckbox');
    const html = document.documentElement;

    // Load saved theme
    const savedTheme = localStorage.getItem('theme') || 'dark';
    html.setAttribute('data-theme', savedTheme);

    // Sync Checkbox: Checked = Dark, Unchecked = Light (or vice versa depending on CSS)
    // Looking at CSS: :checked + container -> container-night-bg. So Checked = Dark Mode.
    // Default is dark.
    if (savedTheme === 'dark') {
        themeCheckbox.checked = true;
    } else {
        themeCheckbox.checked = false;
    }

    themeCheckbox.addEventListener('change', () => {
        const newTheme = themeCheckbox.checked ? 'dark' : 'light';
        html.setAttribute('data-theme', newTheme);
        localStorage.setItem('theme', newTheme);
    });

    // Tab Elements
    const tabs = document.querySelectorAll('.tab-btn');
    const views = document.querySelectorAll('.view');

    // Bulk Elements
    const bulkInput = document.getElementById('bulkInput');
    const bulkBtn = document.getElementById('bulkBtn');
    const bulkStatus = document.getElementById('bulkStatus');
    const progressFill = document.getElementById('progressFill');
    const progressText = document.getElementById('progressText');
    const bulkDownloadBtn = document.getElementById('bulkDownloadBtn');

    // --- Tab Logic ---
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            tabs.forEach(t => t.classList.remove('active'));
            views.forEach(v => v.classList.add('hidden')); // Hide all
            views.forEach(v => v.classList.remove('active'));

            tab.classList.add('active');
            const target = document.getElementById(`${tab.dataset.tab}-view`);
            target.classList.remove('hidden');
            target.classList.add('active');
        });
    });

    // --- Search Logic ---
    searchBtn.addEventListener('click', performSearch);
    searchInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') performSearch();
    });

    async function performSearch() {
        const query = searchInput.value.trim();
        if (!query) return;

        resultsContainer.innerHTML = '';
        loader.classList.remove('hidden');

        try {
            const response = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
            const data = await response.json();

            if (data.error) throw new Error(data.error);
            displayResults(data);
        } catch (error) {
            showToast(error.message || 'Search failed', 'error');
        } finally {
            loader.classList.add('hidden');
        }
    }

    function displayResults(tracks) {
        if (!tracks || tracks.length === 0) {
            resultsContainer.innerHTML = '<p style="text-align:center; grid-column: 1/-1; opacity: 0.6;">No results found.</p>';
            return;
        }

        tracks.forEach(track => {
            const artists = track.artist ? (track.artist.name || track.artist) : 'Unknown Artist';
            // Fix: API returns flat albumTitle and albumCover
            const albumName = track.albumTitle || (track.album ? (track.album.name || track.album) : 'Unknown Album');
            const coverUrl = track.albumCover || (track.album && (track.album.cover_xl || track.album.cover));
            const imageSrc = coverUrl || 'https://via.placeholder.com/300/1a1a1a/FFFFFF?text=No+Cover';

            const card = document.createElement('div');
            card.className = 'track-card';

            const trackData = JSON.stringify({
                trackId: track.id,
                metadata: {
                    artist: artists,
                    title: track.title,
                    album: albumName,
                    cover_url: coverUrl
                }
            });

            card.innerHTML = `
                <div class="card-image-wrapper">
                    <img src="${imageSrc}" alt="${track.title}" class="card-image" loading="lazy">
                </div>
                <div class="card-content">
                    <div class="track-title" title="${track.title}">${track.title}</div>
                    <div class="track-artist">${artists}</div>
                    <div class="track-album">${albumName}</div>
                    <button class="download-btn" onclick='initiateDownload(this, ${trackData})'>
                        <i class="fa-solid fa-download"></i> Download FLAC
                    </button>
                </div>
            `;
            resultsContainer.appendChild(card);
        });
    }

    window.initiateDownload = async (btn, trackData) => {
        if (btn.disabled) return;

        const originalText = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Downloading...';
        showToast(`Starting download: ${trackData.metadata.title}`, 'success');

        try {
            const response = await fetch('/api/download', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(trackData)
            });

            if (!response.ok) throw new Error('Download failed on server');

            const blob = await response.blob();
            const downloadUrl = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = downloadUrl;

            const disposition = response.headers.get('Content-Disposition');
            let filename = `${trackData.metadata.artist} - ${trackData.metadata.title}.flac`;
            if (disposition && disposition.indexOf('attachment') !== -1) {
                const filenameRegex = /filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/;
                const matches = filenameRegex.exec(disposition);
                if (matches != null && matches[1]) {
                    filename = matches[1].replace(/['"]/g, '');
                }
            }

            a.download = filename;
            document.body.appendChild(a);
            a.click();
            a.remove();
            window.URL.revokeObjectURL(downloadUrl);

            showToast('Download complete!', 'success');
        } catch (error) {
            console.error(error);
            showToast('Error downloading file', 'error');
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalText;
        }
    };

    // --- Bulk Logic ---
    bulkBtn.addEventListener('click', async () => {
        const text = bulkInput.value.trim();
        if (!text) return showToast("Please paste some songs!", "error");

        // UI Reset
        bulkBtn.disabled = true;
        bulkBtn.innerText = "Processing...";
        bulkStatus.classList.remove("hidden");
        bulkDownloadBtn.classList.add("hidden");
        progressFill.style.width = "0%";
        progressText.innerText = "Initializing...";

        try {
            const res = await fetch('/api/bulk_init', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text })
            });
            const data = await res.json();
            if (data.error) throw new Error(data.error);

            pollProgress(data.jobId);
        } catch (e) {
            showToast(e.message, "error");
            bulkBtn.disabled = false;
            bulkBtn.innerText = "Start Bulk Download";
        }
    });

    async function pollProgress(jobId) {
        let finished = false;
        while (!finished) {
            try {
                const res = await fetch(`/api/bulk_progress/${jobId}`);
                const job = await res.json();

                if (job.error || job.status === 'error') {
                    showToast("Bulk job failed", "error");
                    finished = true;
                    break;
                }

                const percent = Math.round((job.progress / job.total) * 100);
                progressFill.style.width = `${percent}%`;
                progressText.innerText = `${job.progress} / ${job.total} Songs Processed`;

                if (job.status === 'completed') {
                    finished = true;

                    if (job.zip_path) {
                        progressText.innerText = "Finished! Downloading in 5 seconds...";

                        // Wait 5 seconds
                        await new Promise(r => setTimeout(r, 5000));

                        // Auto-download using anchor tag for better reliability
                        const downloadUrl = `/api/bulk_result/${jobId}`;
                        const a = document.createElement('a');
                        a.style.display = 'none';
                        a.href = downloadUrl;
                        document.body.appendChild(a);
                        a.click();
                        document.body.removeChild(a);

                        bulkDownloadBtn.classList.remove("hidden");
                        bulkDownloadBtn.onclick = () => {
                            window.location.href = downloadUrl;
                        };
                        showToast("Bulk download started!", "success");
                    } else {
                        showToast("Completed, but no songs were downloaded.", "warning");
                    }

                    bulkBtn.disabled = false;
                    bulkBtn.innerText = "Start Bulk Download";
                }
            } catch (e) {
                console.error(e);
            }
            if (!finished) await new Promise(r => setTimeout(r, 1000));
        }
    }

    function showToast(message, type = 'success') {
        toast.textContent = message;
        toast.className = `toast show ${type}`;
        setTimeout(() => {
            toast.classList.remove('show');
        }, 3000);
    }
});
