/* ─── Coattail Investor Web App JS ────────────────────────────────────────── */

// ─── Fetch Data Controls ────────────────────────────────────────────────────

function startFetch() {
    const btn = document.getElementById('fetchBtn');
    const banner = document.getElementById('fetchBanner');
    const msg = document.getElementById('fetchMessage');
    const spinner = document.getElementById('fetchSpinner');
    const closeBtn = document.getElementById('fetchClose');

    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Fetching...';
    banner.classList.remove('d-none');
    spinner.style.display = '';
    closeBtn.style.display = 'none';
    msg.textContent = 'Fetching 13F filings from SEC EDGAR... This may take a few minutes.';

    fetch('/api/fetch', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'already_running') {
                msg.textContent = 'Fetch already in progress...';
            }
            pollFetchStatus();
        })
        .catch(err => {
            msg.textContent = 'Failed to start fetch: ' + err;
            btn.disabled = false;
            btn.innerHTML = '<i class="bi bi-cloud-download me-1"></i>Fetch Data';
        });
}

function pollFetchStatus() {
    const interval = setInterval(() => {
        fetch('/api/fetch-status')
            .then(r => r.json())
            .then(data => {
                const msg = document.getElementById('fetchMessage');
                const btn = document.getElementById('fetchBtn');
                const spinner = document.getElementById('fetchSpinner');
                const closeBtn = document.getElementById('fetchClose');

                if (data.done) {
                    clearInterval(interval);
                    spinner.style.display = 'none';
                    closeBtn.style.display = '';
                    btn.disabled = false;
                    btn.innerHTML = '<i class="bi bi-cloud-download me-1"></i>Fetch Data';

                    if (data.error) {
                        msg.textContent = 'Fetch error: ' + data.error;
                        document.getElementById('fetchBanner').classList.replace('alert-info', 'alert-danger');
                    } else {
                        msg.textContent = 'Fetch complete! Reload the page to see updated data.';
                        document.getElementById('fetchBanner').classList.replace('alert-info', 'alert-success');

                        // Add reload button
                        const reloadBtn = document.createElement('button');
                        reloadBtn.className = 'btn btn-sm btn-success ms-3';
                        reloadBtn.innerHTML = '<i class="bi bi-arrow-clockwise me-1"></i>Reload';
                        reloadBtn.onclick = () => location.reload();
                        msg.parentNode.insertBefore(reloadBtn, closeBtn);
                    }

                    // Reset state on server
                    fetch('/api/fetch-reset', { method: 'POST' });
                } else if (data.running) {
                    msg.textContent = data.message || 'Fetching data...';
                }
            });
    }, 2000);
}

function closeFetchBanner() {
    document.getElementById('fetchBanner').classList.add('d-none');
}

// ─── Chart Helpers ──────────────────────────────────────────────────────────

const CHART_COLORS = {
    green: '#22c55e',
    blue: '#3b82f6',
    orange: '#f59e0b',
    red: '#ef4444',
    purple: '#a855f7',
    teal: '#14b8a6',
    gray: '#6b7280',
    accent: '#00d97e',
};

const CHART_DEFAULTS = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
        legend: {
            labels: { color: '#9ca3af', font: { size: 12 } },
        },
        tooltip: {
            backgroundColor: '#1f2937',
            titleColor: '#e5e7eb',
            bodyColor: '#e5e7eb',
            borderColor: '#374151',
            borderWidth: 1,
            padding: 10,
        },
    },
    scales: {
        x: {
            grid: { color: 'rgba(255,255,255,0.05)' },
            ticks: { color: '#9ca3af' },
        },
        y: {
            grid: { color: 'rgba(255,255,255,0.05)' },
            ticks: { color: '#9ca3af' },
        },
    },
};

function createGrowthChart(canvasId, data) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;

    const labels = Array.from({ length: data.years + 1 }, (_, i) => `Year ${i}`);

    new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: '75th Percentile',
                    data: data.p75_path,
                    borderColor: CHART_COLORS.green,
                    backgroundColor: 'rgba(34,197,94,0.05)',
                    borderWidth: 1.5,
                    pointRadius: 3,
                    tension: 0.3,
                },
                {
                    label: 'Median (50th)',
                    data: data.median_path,
                    borderColor: CHART_COLORS.accent,
                    backgroundColor: 'rgba(0,217,126,0.1)',
                    borderWidth: 2.5,
                    pointRadius: 4,
                    tension: 0.3,
                    fill: false,
                },
                {
                    label: '25th Percentile',
                    data: data.p25_path,
                    borderColor: CHART_COLORS.orange,
                    backgroundColor: 'rgba(245,158,11,0.05)',
                    borderWidth: 1.5,
                    pointRadius: 3,
                    tension: 0.3,
                },
            ],
        },
        options: {
            ...CHART_DEFAULTS,
            plugins: {
                ...CHART_DEFAULTS.plugins,
                filler: { propagate: false },
            },
            scales: {
                ...CHART_DEFAULTS.scales,
                y: {
                    ...CHART_DEFAULTS.scales.y,
                    ticks: {
                        ...CHART_DEFAULTS.scales.y.ticks,
                        callback: v => '$' + v.toLocaleString(),
                    },
                },
            },
        },
    });
}

function createScenarioChart(canvasId, scenarios, initial) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;

    const colors = [CHART_COLORS.green, CHART_COLORS.blue, CHART_COLORS.orange, CHART_COLORS.red];
    const maxYears = Math.max(...scenarios.map(s => s.yearly.length));
    const labels = ['Year 0', ...Array.from({ length: maxYears }, (_, i) => `Year ${i + 1}`)];

    const datasets = scenarios.map((s, i) => ({
        label: s.label,
        data: [initial, ...s.yearly.map(y => y.ending_value)],
        borderColor: colors[i % colors.length],
        backgroundColor: 'transparent',
        borderWidth: 2,
        pointRadius: 3,
        tension: 0.3,
    }));

    new Chart(ctx, {
        type: 'line',
        data: { labels, datasets },
        options: {
            ...CHART_DEFAULTS,
            scales: {
                ...CHART_DEFAULTS.scales,
                y: {
                    ...CHART_DEFAULTS.scales.y,
                    ticks: {
                        ...CHART_DEFAULTS.scales.y.ticks,
                        callback: v => '$' + v.toLocaleString(),
                    },
                },
            },
        },
    });
}

function createAllocationPie(canvasId, positions) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;

    const palette = [
        CHART_COLORS.accent, CHART_COLORS.blue, CHART_COLORS.orange,
        CHART_COLORS.purple, CHART_COLORS.teal, CHART_COLORS.red,
        '#06b6d4', '#8b5cf6', '#ec4899', '#84cc16',
        '#f43f5e', '#0ea5e9', '#d946ef', '#22d3ee',
        '#fbbf24', '#a3e635', '#fb7185', '#38bdf8',
        '#818cf8', '#2dd4bf',
    ];

    new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: positions.map(p => p.ticker),
            datasets: [{
                data: positions.map(p => p.final_weight_pct),
                backgroundColor: positions.map((_, i) => palette[i % palette.length]),
                borderColor: '#1a1d23',
                borderWidth: 2,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'right',
                    labels: {
                        color: '#9ca3af',
                        font: { size: 11 },
                        padding: 8,
                        usePointStyle: true,
                        pointStyleWidth: 8,
                    },
                },
                tooltip: {
                    ...CHART_DEFAULTS.plugins.tooltip,
                    callbacks: {
                        label: ctx => `${ctx.label}: ${ctx.parsed.toFixed(1)}%`,
                    },
                },
            },
        },
    });
}

function createSectorChart(canvasId, sectorData) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;

    const palette = [
        CHART_COLORS.blue, CHART_COLORS.green, CHART_COLORS.orange,
        CHART_COLORS.purple, CHART_COLORS.teal, CHART_COLORS.red,
        CHART_COLORS.accent, CHART_COLORS.gray,
    ];

    const labels = Object.keys(sectorData);
    const values = Object.values(sectorData);

    new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{
                data: values,
                backgroundColor: labels.map((_, i) => palette[i % palette.length]),
                borderColor: '#1a1d23',
                borderWidth: 2,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'right',
                    labels: { color: '#9ca3af', font: { size: 11 }, usePointStyle: true, pointStyleWidth: 8 },
                },
                tooltip: {
                    ...CHART_DEFAULTS.plugins.tooltip,
                    callbacks: {
                        label: ctx => `${ctx.label}: ${ctx.parsed.toFixed(1)}%`,
                    },
                },
            },
        },
    });
}

// ─── Utility ────────────────────────────────────────────────────────────────

function formatCurrency(val) {
    return '$' + Number(val).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
