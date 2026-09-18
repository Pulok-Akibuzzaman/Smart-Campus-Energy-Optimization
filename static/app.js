/* ==========================================================================
   GridWise Smart Campus Energy Dashboard — Application Controller
   ========================================================================== */

let sampleData = {};
let currentScenario = null;
let lastResponse = null;
let dispatchChartInstance = null;
let socChartInstance = null;
let currentJsonTab = 'response';

// ---------------------------------------------------------------------------
// 1. Initialization & Health Monitoring
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', async () => {
  await fetchPublicSamplePack();
  checkHealth();
  setInterval(checkHealth, 5000);
});

async function checkHealth() {
  const healthBadge = document.getElementById('healthBadge');
  const healthText = document.getElementById('healthText');
  const latencyBadge = document.getElementById('latencyBadge');

  const t0 = performance.now();
  try {
    const res = await fetch('/health');
    const latency = Math.round(performance.now() - t0);
    if (res.ok) {
      const data = await res.json();
      if (data.status === 'ok') {
        healthBadge.style.background = 'rgba(16, 185, 129, 0.12)';
        healthBadge.style.color = 'var(--color-success)';
        healthBadge.style.borderColor = 'rgba(16, 185, 129, 0.25)';
        healthText.innerText = 'Service: Online (200 OK)';
        latencyBadge.innerText = `API Latency: ${latency} ms`;
      }
    } else {
      throw new Error(`HTTP ${res.status}`);
    }
  } catch (err) {
    healthBadge.style.background = 'rgba(239, 68, 68, 0.12)';
    healthBadge.style.color = 'var(--color-danger)';
    healthBadge.style.borderColor = 'rgba(239, 68, 68, 0.25)';
    healthText.innerText = 'Service: Offline';
    latencyBadge.innerText = 'API Latency: -- ms';
  }
}

// ---------------------------------------------------------------------------
// 2. Load Public Samples
// ---------------------------------------------------------------------------

async function fetchPublicSamplePack() {
  try {
    const res = await fetch('/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json');
    if (res.ok) {
      const data = await res.json();
      if (data.cases) {
        data.cases.forEach(c => {
          sampleData[c.id] = c.input;
        });
      }
    }
  } catch (e) {
    console.warn("Could not fetch sample pack directly; using internal fallback.", e);
  }

  // Load SAMPLE-01 by default
  loadSample('SAMPLE-01');
}

function loadSample(sampleId) {
  // Update preset button active state
  document.querySelectorAll('.preset-btn').forEach(btn => {
    btn.classList.toggle('active', btn.innerText.includes(sampleId));
  });

  document.getElementById('scenarioIdDisplay').innerText = sampleId;

  // If fetched data exists, use it
  if (sampleData[sampleId]) {
    currentScenario = JSON.parse(JSON.stringify(sampleData[sampleId]));
  } else {
    // Generate fallback scenario if not loaded yet
    currentScenario = createDefaultScenario(sampleId);
  }

  // Populate UI inputs
  document.getElementById('operatorNotesInput').value = currentScenario.operator_notes.join('\n');
  document.getElementById('battCapacity').value = currentScenario.battery.capacity_kwh;
  document.getElementById('battInitial').value = currentScenario.battery.initial_energy_kwh;
  document.getElementById('battMin').value = currentScenario.battery.minimum_energy_kwh;
  document.getElementById('battMaxCharge').value = currentScenario.battery.max_charge_kwh_per_hour;
  document.getElementById('battMaxDischarge').value = currentScenario.battery.max_discharge_kwh_per_hour;
  document.getElementById('battNeutrality').value = `${currentScenario.battery.initial_energy_kwh} kWh`;

  // Compute forecast stats
  const totalDemand = currentScenario.hours.reduce((acc, h) => acc + h.demand_kwh, 0);
  const totalSolar = currentScenario.hours.reduce((acc, h) => acc + h.solar_kwh, 0);
  const avgTariff = (currentScenario.hours.reduce((acc, h) => acc + h.tariff_bdt_per_kwh, 0) / 24).toFixed(1);

  document.getElementById('totalDemandDisplay').innerText = totalDemand.toFixed(0);
  document.getElementById('totalSolarDisplay').innerText = totalSolar.toFixed(0);
  document.getElementById('avgTariffDisplay').innerText = avgTariff;

  // Auto-run optimization for the loaded sample to populate visuals
  runOptimization();
}

function applyParaphrase(text) {
  const area = document.getElementById('operatorNotesInput');
  const lines = area.value.split('\n').filter(l => l.trim().length > 0);
  if (lines.length === 0) {
    area.value = text;
  } else {
    // Replace the first note with the paraphrase or append
    lines[0] = text;
    area.value = lines.join('\n');
  }
  runOptimization();
}

// ---------------------------------------------------------------------------
// 3. Run Optimization & Pipeline Stepper
// ---------------------------------------------------------------------------

async function runOptimization() {
  const btn = document.getElementById('runOptimizeBtn');
  btn.disabled = true;
  btn.innerHTML = '<span>⏳ Optimizing Dispatch...</span>';

  // Read current input values
  const notesText = document.getElementById('operatorNotesInput').value;
  const notes = notesText.split('\n').map(n => n.trim()).filter(n => n.length > 0);

  if (notes.length === 0) {
    alert("Please enter at least 1 operator note.");
    btn.disabled = false;
    btn.innerHTML = '<span>⚡ Optimize 24-Hour Schedule</span>';
    return;
  }

  currentScenario.operator_notes = notes;
  currentScenario.battery.capacity_kwh = parseFloat(document.getElementById('battCapacity').value);
  currentScenario.battery.initial_energy_kwh = parseFloat(document.getElementById('battInitial').value);
  currentScenario.battery.minimum_energy_kwh = parseFloat(document.getElementById('battMin').value);
  currentScenario.battery.max_charge_kwh_per_hour = parseFloat(document.getElementById('battMaxCharge').value);
  currentScenario.battery.max_discharge_kwh_per_hour = parseFloat(document.getElementById('battMaxDischarge').value);

  // Animate Stepper: Stage 1 -> 2 -> 3
  updateStepper(1);
  await delay(80);
  updateStepper(2);

  const t0 = performance.now();
  try {
    const res = await fetch('/optimize-energy', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(currentScenario)
    });

    const elapsed = Math.round(performance.now() - t0);

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.message || `HTTP ${res.status}`);
    }

    lastResponse = await res.json();

    // Animate Stepper: Stage 3 -> 4 -> 5 -> Complete
    updateStepper(3);
    await delay(60);
    updateStepper(4);
    await delay(60);
    updateStepper(5);
    await delay(60);
    completeStepper();

    // Render all results
    renderResults(lastResponse, elapsed);

  } catch (e) {
    console.error("Optimization failed:", e);
    alert(`Optimization Error: ${e.message}`);
    resetStepper();
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<span>⚡ Optimize 24-Hour Schedule</span>';
  }
}

function updateStepper(stepNum) {
  for (let i = 1; i <= 5; i++) {
    const el = document.getElementById(`step${i}`);
    el.classList.remove('active', 'completed');
    if (i < stepNum) {
      el.classList.add('completed');
    } else if (i === stepNum) {
      el.classList.add('active');
    }
  }
}

function completeStepper() {
  for (let i = 1; i <= 5; i++) {
    const el = document.getElementById(`step${i}`);
    el.classList.remove('active');
    el.classList.add('completed');
  }
}

function resetStepper() {
  for (let i = 1; i <= 5; i++) {
    const el = document.getElementById(`step${i}`);
    el.classList.remove('active', 'completed');
  }
}

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// ---------------------------------------------------------------------------
// 4. Render Results: KPIs, Directives, Guardrails, Charts
// ---------------------------------------------------------------------------

function renderResults(data, elapsedMs) {
  // 1. KPIs
  document.getElementById('kpiCost').innerHTML = `${data.total_cost_bdt.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}<span class="kpi-unit">BDT</span>`;
  document.getElementById('kpiGrid').innerHTML = `${data.total_grid_kwh.toLocaleString(undefined, {minimumFractionDigits: 1, maximumFractionDigits: 1})}<span class="kpi-unit">kWh</span>`;
  document.getElementById('kpiPeak').innerHTML = `${data.peak_grid_kwh.toFixed(1)}<span class="kpi-unit">kWh</span>`;
  document.getElementById('kpiLatency').innerHTML = `${elapsedMs}<span class="kpi-unit">ms</span>`;

  // 2. Defense-in-depth strip
  document.getElementById('defenseStrip').style.display = 'flex';

  // 3. Directives
  renderDirectives(data.directive_interpretation, currentScenario.operator_notes);

  // 4. Charts
  renderDispatchChart(data.hourly_plan, currentScenario.hours);
  renderSocChart(data.hourly_plan, currentScenario.battery, data.directive_interpretation);

  // 5. JSON tabs
  updateJsonViewer();
}

function renderDirectives(directives, originalNotes) {
  const container = document.getElementById('directivesContainer');
  container.innerHTML = '';

  directives.forEach((d, idx) => {
    const card = document.createElement('div');
    card.className = `directive-card ${d.directive_type}`;

    const noteText = originalNotes[d.note_index] || `Operator Note #${d.note_index}`;

    let paramsHtml = '';
    if (d.structured_adjustment) {
      paramsHtml = `<div class="directive-params">${JSON.stringify(d.structured_adjustment)}</div>`;
    } else {
      paramsHtml = `<div class="directive-params" style="color: var(--text-muted)">null (no adjustment applied)</div>`;
    }

    const appliesBadge = d.applies
      ? `<span style="color: var(--color-success); font-weight: 700; font-size: 0.75rem;">APPLIES: TRUE</span>`
      : `<span style="color: var(--text-muted); font-weight: 700; font-size: 0.75rem;">APPLIES: FALSE</span>`;

    card.innerHTML = `
      <div class="directive-header">
        <span class="directive-badge" style="background: rgba(59, 130, 246, 0.2); color: #60a5fa;">Note [${d.note_index}]: ${d.directive_type}</span>
        ${appliesBadge}
      </div>
      <div class="directive-note-text">"${noteText}"</div>
      ${paramsHtml}
      <div style="font-size: 0.8rem; color: var(--text-secondary); margin-top: 0.4rem;">
        <strong>Reasoning:</strong> ${d.explanation}
      </div>
    `;

    container.appendChild(card);
  });
}

// ---------------------------------------------------------------------------
// 5. Chart.js Implementations
// ---------------------------------------------------------------------------

function renderDispatchChart(plan, hours) {
  const ctx = document.getElementById('dispatchChart').getContext('2d');
  const labels = plan.map(p => `${p.hour}:00`);

  const gridData = plan.map(p => p.grid_kwh);
  const solarData = plan.map(p => p.solar_used_kwh);
  const chargeData = plan.map(p => p.battery_action === 'charge' ? p.battery_kwh : 0);
  const dischargeData = plan.map(p => p.battery_action === 'discharge' ? p.battery_kwh : 0);
  const tariffData = hours.map(h => h.tariff_bdt_per_kwh);

  if (dispatchChartInstance) {
    dispatchChartInstance.destroy();
  }

  dispatchChartInstance = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'Grid Import (kWh)',
          data: gridData,
          backgroundColor: 'rgba(59, 130, 246, 0.85)',
          stack: 'supply',
          order: 2
        },
        {
          label: 'Solar Used (kWh)',
          data: solarData,
          backgroundColor: 'rgba(245, 158, 11, 0.85)',
          stack: 'supply',
          order: 2
        },
        {
          label: 'Battery Discharge (kWh)',
          data: dischargeData,
          backgroundColor: 'rgba(139, 92, 246, 0.85)',
          stack: 'supply',
          order: 2
        },
        {
          label: 'Battery Charge (kWh)',
          data: chargeData,
          backgroundColor: 'rgba(16, 185, 129, 0.85)',
          stack: 'charge',
          order: 2
        },
        {
          label: 'Grid Tariff (BDT/kWh)',
          data: tariffData,
          type: 'line',
          borderColor: '#ec4899',
          borderWidth: 2.5,
          pointRadius: 2,
          yAxisID: 'yTariff',
          order: 1
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { labels: { color: '#cbd5e1', font: { family: 'Inter', size: 11 } } },
        tooltip: {
          backgroundColor: '#0f172a',
          titleColor: '#f8fafc',
          bodyColor: '#cbd5e1',
          borderColor: '#334155',
          borderWidth: 1
        }
      },
      scales: {
        x: {
          grid: { color: '#1e293b' },
          ticks: { color: '#94a3b8', font: { family: 'Inter', size: 10 } }
        },
        y: {
          grid: { color: '#1e293b' },
          ticks: { color: '#94a3b8', font: { family: 'JetBrains Mono', size: 10 } },
          title: { display: true, text: 'Energy (kWh)', color: '#94a3b8', font: { size: 11 } }
        },
        yTariff: {
          position: 'right',
          grid: { drawOnChartArea: false },
          ticks: { color: '#ec4899', font: { family: 'JetBrains Mono', size: 10 } },
          title: { display: true, text: 'Tariff (BDT/kWh)', color: '#ec4899', font: { size: 11 } }
        }
      }
    }
  });
}

function renderSocChart(plan, battery, directives) {
  const ctx = document.getElementById('socChart').getContext('2d');
  const labels = plan.map(p => `${p.hour}:00`);
  const socData = plan.map(p => p.battery_energy_after_kwh);
  const capacityLine = plan.map(() => battery.capacity_kwh);
  const baseReserveLine = plan.map(() => battery.minimum_energy_kwh);

  // Compute active reserve line if minimum_battery_reserve directive is active
  const activeReserveLine = plan.map((p, idx) => {
    let res = battery.minimum_energy_kwh;
    directives.forEach(d => {
      if (d.applies && d.directive_type === 'minimum_battery_reserve') {
        const affected = d.structured_adjustment?.hours || [];
        if (affected.includes(idx)) {
          res = Math.max(res, d.structured_adjustment?.minimum_energy_kwh || res);
        }
      }
    });
    return res;
  });

  if (socChartInstance) {
    socChartInstance.destroy();
  }

  socChartInstance = new Chart(ctx, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'Battery Energy (kWh)',
          data: socData,
          borderColor: '#10b981',
          backgroundColor: 'rgba(16, 185, 129, 0.15)',
          fill: true,
          tension: 0.25,
          borderWidth: 2.5,
          pointRadius: 3,
          pointHoverRadius: 6
        },
        {
          label: 'Active Required Reserve (kWh)',
          data: activeReserveLine,
          borderColor: '#f59e0b',
          borderDash: [5, 4],
          borderWidth: 1.8,
          pointRadius: 0,
          fill: false
        },
        {
          label: 'Battery Capacity (kWh)',
          data: capacityLine,
          borderColor: '#64748b',
          borderDash: [3, 3],
          borderWidth: 1.5,
          pointRadius: 0,
          fill: false
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { labels: { color: '#cbd5e1', font: { family: 'Inter', size: 11 } } },
        tooltip: {
          backgroundColor: '#0f172a',
          titleColor: '#f8fafc',
          bodyColor: '#cbd5e1',
          borderColor: '#334155',
          borderWidth: 1
        }
      },
      scales: {
        x: {
          grid: { color: '#1e293b' },
          ticks: { color: '#94a3b8', font: { family: 'Inter', size: 10 } }
        },
        y: {
          grid: { color: '#1e293b' },
          ticks: { color: '#94a3b8', font: { family: 'JetBrains Mono', size: 10 } },
          title: { display: true, text: 'Stored Energy (kWh)', color: '#94a3b8', font: { size: 11 } }
        }
      }
    }
  });
}

// ---------------------------------------------------------------------------
// 6. JSON Inspector Tabs
// ---------------------------------------------------------------------------

function switchJsonTab(tab) {
  currentJsonTab = tab;
  document.getElementById('btnTabResp').classList.toggle('active', tab === 'response');
  document.getElementById('btnTabReq').classList.toggle('active', tab === 'request');
  updateJsonViewer();
}

function updateJsonViewer() {
  const viewer = document.getElementById('jsonViewer');
  if (currentJsonTab === 'response') {
    viewer.innerText = lastResponse ? JSON.stringify(lastResponse, null, 2) : '// No response available yet.';
  } else {
    viewer.innerText = currentScenario ? JSON.stringify(currentScenario, null, 2) : '// No request loaded.';
  }
}

// ---------------------------------------------------------------------------
// 7. Fallback Scenario Generator
// ---------------------------------------------------------------------------

function createDefaultScenario(id) {
  return {
    scenario_id: id,
    operator_notes: [
      "Facilities will wash the rooftop solar panels from noon until 2 PM. During cleaning, usable solar should be treated as roughly 25% of the forecast.",
      "The sports office moved next month's registration deadline."
    ],
    hours: Array.from({ length: 24 }, (_, i) => ({
      hour: i,
      demand_kwh: 80 + (i >= 8 && i <= 20 ? 80 : 10),
      solar_kwh: (i >= 6 && i <= 17) ? Math.sin((i - 6) / 11 * Math.PI) * 180 : 0,
      tariff_bdt_per_kwh: (i >= 17 && i <= 21) ? 25 : (i >= 7 && i <= 16 ? 14 : 6)
    })),
    battery: {
      capacity_kwh: 220,
      initial_energy_kwh: 110,
      minimum_energy_kwh: 40,
      max_charge_kwh_per_hour: 50,
      max_discharge_kwh_per_hour: 50
    }
  };
}
