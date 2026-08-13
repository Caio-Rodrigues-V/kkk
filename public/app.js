// State Variables
let dashboardData = null;
let activeTab = 'overview';

// Pagination state for Meta Campaigns
let campaignCurrentPage = 1;
const campaignItemsPerPage = 10;
let campaignSearchQuery = "";
let campaignStatusFilter = "ALL"; // ALL, ACTIVE, PAUSED

// Helper Formatter Functions
const formatCurrency = (val) => {
  return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(val);
};

const formatInteger = (val) => {
  return new Intl.NumberFormat('pt-BR').format(val);
};

const formatPercentage = (val) => {
  return new Intl.NumberFormat('pt-BR', { style: 'percent', minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(val);
};

const formatDate = (isoString) => {
  if (!isoString) return "";
  const d = new Date(isoString);
  return d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric' });
};

// Document Elements
const syncTimeEl = document.getElementById("sync-time");
const btnSyncEl = document.getElementById("btn-sync");
const syncIconEl = document.getElementById("sync-icon");
const loadingOverlayEl = document.getElementById("loading-overlay");

// Navigation elements
const menuItems = document.querySelectorAll(".menu-item");
const tabPages = document.querySelectorAll(".tab-page");

// Mobile Sidebar drawer elements
const sidebarEl = document.getElementById("sidebar");
const backdropEl = document.getElementById("sidebar-backdrop");
const btnToggleSidebarEl = document.getElementById("btn-toggle-sidebar");

// Initialize Navigation & Event Listeners
document.addEventListener("DOMContentLoaded", () => {
  // Initialize Lucide Icons
  lucide.createIcons();
  
  // Tab Routing
  menuItems.forEach(item => {
    item.addEventListener("click", () => {
      const targetTab = item.getAttribute("data-tab");
      switchTab(targetTab);
    });
  });

  // Sync / Refresh Button
  btnSyncEl.addEventListener("click", () => {
    fetchDashboardData(true);
  });

  // Search input for campaigns
  document.getElementById("campaign-search").addEventListener("input", (e) => {
    campaignSearchQuery = e.target.value;
    campaignCurrentPage = 1;
    renderCampaignsTable();
  });

  // Filters for campaigns status
  const filterBtns = document.querySelectorAll(".btn-filter");
  filterBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      filterBtns.forEach(b => b.classList.remove("active", "bg-purple-600", "text-white"));
      filterBtns.forEach(b => b.classList.add("text-slate-500"));
      
      btn.classList.add("active", "bg-purple-600", "text-white");
      btn.classList.remove("text-slate-500");
      
      campaignStatusFilter = btn.getAttribute("data-status");
      campaignCurrentPage = 1;
      renderCampaignsTable();
    });
  });

  // Mobile drawer events
  btnToggleSidebarEl.addEventListener("click", openMobileSidebar);
  backdropEl.addEventListener("click", closeMobileSidebar);

  // Set initial active tab state
  switchTab('overview');

  // Initial Data Fetch
  fetchDashboardData(false);
});

// Mobile Sidebar logic
function openMobileSidebar() {
  sidebarEl.classList.remove("-translate-x-full");
  sidebarEl.classList.add("translate-x-0");
  backdropEl.classList.remove("hidden");
}

function closeMobileSidebar() {
  sidebarEl.classList.remove("translate-x-0");
  sidebarEl.classList.add("-translate-x-full");
  backdropEl.classList.add("hidden");
}

// Tab switcher with Tailwind class handling
function switchTab(tabId) {
  activeTab = tabId;
  
  // Update sidebar menu active state
  menuItems.forEach(item => {
    const tTab = item.getAttribute("data-tab");
    const labelEl = item.querySelector("span");
    const subtextEl = item.querySelector("span:nth-child(2)");
    
    if (tTab === tabId) {
      item.classList.add("bg-white/10", "text-white");
      item.classList.remove("text-purple-200");
    } else {
      item.classList.remove("bg-white/10", "text-white");
      item.classList.add("text-purple-200");
    }
  });

  // Show corresponding page container
  tabPages.forEach(page => {
    if (page.getAttribute("id") === `page-${tabId}`) {
      page.classList.remove("hidden");
      page.classList.add("block", "space-y-8");
    } else {
      page.classList.add("hidden");
      page.classList.remove("block", "space-y-8");
    }
  });

  // Close sidebar drawer on mobile after nav click
  closeMobileSidebar();

  // Trigger resize on ApexCharts to prevent rendering size bugs
  window.dispatchEvent(new Event('resize'));
}

// Fetch data from Python Server
async function fetchDashboardData(forceSync = false) {
  loadingOverlayEl.classList.add("active");
  loadingOverlayEl.classList.remove("opacity-0", "pointer-events-none");
  syncIconEl.classList.add("animate-spin");
  
  const endpoint = forceSync ? "/api/sync" : "/api/data";
  try {
    const response = await fetch(endpoint);
    if (!response.ok) throw new Error("Erro de rede");
    dashboardData = await response.json();
    
    // Update all views
    updateDashboardUI();
  } catch (error) {
    console.error("Erro ao carregar dados:", error);
    alert("Não foi possível carregar os dados das APIs. Certifique-se de que o backend está ativo.");
  } finally {
    loadingOverlayEl.classList.remove("active");
    loadingOverlayEl.classList.add("opacity-0", "pointer-events-none");
    syncIconEl.classList.remove("animate-spin");
  }
}

// Global UI Updater
function updateDashboardUI() {
  if (!dashboardData) return;

  // 1. Header updated time
  const updatedDate = new Date(dashboardData.last_updated);
  syncTimeEl.textContent = `Atualizado ${formatDate(updatedDate)} às ${updatedDate.toLocaleTimeString('pt-BR', {hour: '2-digit', minute:'2-digit'})}`;

  // 2. Render Overview Tab
  renderOverviewTab();

  // 3. Render Daily Evolution & Breakdowns inside Journey Tab
  renderDailyTab();
  renderBreakdownTab();

  // 4. Render Campaigns Tab
  renderCampaignsTable();
}

// 1. Render Dashboard Page (Overview)
function renderOverviewTab() {
  const ds = dashboardData.dinx_stats;
  const ms = dashboardData.meta_stats;

  // main KPI values
  document.getElementById("kpi-investido-leads").textContent = formatCurrency(ms.lead_campaign_spend);
  document.getElementById("kpi-investido-outros").textContent = formatCurrency(ms.profile_visit_spend);
  document.getElementById("kpi-investido-total").textContent = `Total campanhas ${formatCurrency(ms.total_spend)}`;
  
  document.getElementById("kpi-leads-totais").textContent = formatInteger(ds.total_leads);
  document.getElementById("kpi-qualificados-private").textContent = formatInteger(ds.qualificados_private);
  
  const qualPrivatePct = ds.total_leads > 0 ? (ds.qualificados_private / ds.total_leads) : 0;
  document.getElementById("kpi-qualificados-private-pct").textContent = `${formatPercentage(qualPrivatePct)} do total`;

  document.getElementById("kpi-apps-ativados").textContent = formatInteger(ds.ativados);
  const activePrivatePct = ds.qualificados_private > 0 ? (ds.ativados / ds.qualificados_private) : 0;
  document.getElementById("kpi-apps-ativados-pct").textContent = `${formatPercentage(activePrivatePct)} dos particulares`;

  // Sub KPIs row
  document.getElementById("sub-taxa-qualif").textContent = formatPercentage(qualPrivatePct);
  document.getElementById("sub-taxa-qualif-det").textContent = `${formatInteger(ds.qualificados_private)} / ${formatInteger(ds.total_leads)}`;

  const cplQualif = ds.qualificados_private > 0 ? (ms.lead_campaign_spend / ds.qualificados_private) : 0;
  document.getElementById("sub-cpl-qualif").textContent = formatCurrency(cplQualif);
  document.getElementById("sub-cpl-qualif-det").textContent = `${formatCurrency(ms.lead_campaign_spend)} / ${formatInteger(ds.qualificados_private)}`;

  // Circular progress & CPA panel
  const cpaVal = ds.qualificados > 0 ? (ms.lead_campaign_spend / ds.qualificados) : 0;
  document.getElementById("cpa-value-text").textContent = formatCurrency(cpaVal);
  document.getElementById("cpa-formula-text").textContent = `${formatCurrency(ms.lead_campaign_spend)} / ${formatInteger(ds.qualificados)}`;
  document.getElementById("cpa-ratio-text").textContent = `${formatInteger(ds.qualificados)} / ${formatInteger(ds.total_leads)}`;
  
  const qualTotalPct = ds.total_leads > 0 ? (ds.qualificados / ds.total_leads) : 0;
  document.getElementById("cpa-ratio-pct").textContent = `${formatPercentage(qualTotalPct)} qualif.`;

  // Render Apex Radialbar for CPA
  renderCPARadialBar(qualTotalPct * 100);

  // Render Area Chart for Evolution Trend
  renderOverviewTrendChart(ds.daily_trend);
}

// Render CPA circular progress using ApexCharts
function renderCPARadialBar(percentValue) {
  const container = document.getElementById("cpa-radial-chart");
  container.innerHTML = ""; // Clear
  
  const options = {
    series: [percentValue],
    chart: {
      height: 180,
      type: 'radialBar',
      fontFamily: 'Plus Jakarta Sans'
    },
    plotOptions: {
      radialBar: {
        hollow: {
          size: '68%',
        },
        dataLabels: {
          show: true,
          name: { show: false },
          value: {
            fontSize: '18px',
            fontWeight: '800',
            color: '#ea580c',
            offsetY: 6,
            formatter: function (val) {
              return val.toFixed(2) + "%";
            }
          }
        },
        track: {
          background: '#f1f5f9',
          strokeWidth: '100%',
        }
      }
    },
    colors: ['#ea580c'], // High contrast orange
    stroke: { lineCap: 'round' }
  };

  const chart = new ApexCharts(container, options);
  chart.render();
}

// Render Overview Trend Chart (Area Chart)
function renderOverviewTrendChart(trendData) {
  const container = document.getElementById("overview-trend-chart");
  container.innerHTML = ""; // Clear

  const slicedData = trendData.slice(-30);
  const categories = slicedData.map(item => {
    const parts = item.date.split('-');
    return `${parts[2]}/${parts[1]}`;
  });

  const seriesCadastros = slicedData.map(item => item.cadastros);
  const seriesQualificados = slicedData.map(item => item.qualificados);
  const seriesAtivados = slicedData.map(item => item.ativados);

  const options = {
    series: [
      { name: 'Cadastros', data: seriesCadastros },
      { name: 'Qualificados Total', data: seriesQualificados },
      { name: 'Ativados', data: seriesAtivados }
    ],
    chart: {
      type: 'area',
      height: '100%',
      fontFamily: 'Plus Jakarta Sans',
      toolbar: { show: false },
      zoom: { enabled: false }
    },
    dataLabels: { enabled: false },
    stroke: { curve: 'smooth', width: 2.5 },
    colors: ['#7c3aed', '#f97316', '#10b981'],
    fill: {
      type: 'gradient',
      gradient: {
        shadeIntensity: 1,
        opacityFrom: 0.35,
        opacityTo: 0.02,
        stops: [0, 90, 100]
      }
    },
    grid: {
      borderColor: '#f1f5f9',
      strokeDashArray: 4,
      padding: { left: 10, right: 10, top: 0, bottom: 0 }
    },
    xaxis: {
      categories: categories,
      labels: {
        style: { colors: '#94a3b8', fontSize: '10px', fontWeight: 600 }
      },
      axisBorder: { show: false },
      axisTicks: { show: false }
    },
    yaxis: {
      labels: {
        style: { colors: '#94a3b8', fontSize: '10px', fontWeight: 600 },
        formatter: (val) => Math.round(val)
      }
    },
    tooltip: {
      shared: true,
      intersect: false,
      theme: 'light',
      y: { formatter: (val) => formatInteger(val) }
    },
    legend: { show: false }
  };

  const chart = new ApexCharts(container, options);
  chart.render();
}

// 2. Render Daily Evolution Tab
function renderDailyTab() {
  const trend = dashboardData.dinx_stats.daily_trend;

  // Render larger chart
  const container = document.getElementById("daily-detail-chart");
  container.innerHTML = "";

  const categories = trend.map(item => {
    const parts = item.date.split('-');
    return `${parts[2]}/${parts[1]}/${parts[0]}`;
  });

  const seriesCadastros = trend.map(item => item.cadastros);
  const seriesQualificados = trend.map(item => item.qualificados);
  const seriesAtivados = trend.map(item => item.ativados);

  const options = {
    series: [
      { name: 'Cadastros', data: seriesCadastros },
      { name: 'Qualificados Total', data: seriesQualificados },
      { name: 'Ativados', data: seriesAtivados }
    ],
    chart: {
      type: 'line',
      height: '100%',
      fontFamily: 'Plus Jakarta Sans',
      toolbar: { show: true },
      zoom: { enabled: true }
    },
    dataLabels: { enabled: false },
    stroke: { curve: 'smooth', width: 3 },
    colors: ['#7c3aed', '#f97316', '#10b981'],
    grid: {
      borderColor: '#f1f5f9',
      strokeDashArray: 4
    },
    xaxis: {
      categories: categories,
      labels: { style: { colors: '#94a3b8', fontSize: '10px', fontWeight: 600 } }
    },
    yaxis: {
      labels: { style: { colors: '#94a3b8', fontSize: '10px', fontWeight: 600 } }
    },
    tooltip: {
      shared: true,
      y: { formatter: (val) => formatInteger(val) }
    }
  };

  const chart = new ApexCharts(container, options);
  chart.render();

  // Populate Daily stats Table (sorted descending)
  const tbody = document.getElementById("daily-table-body");
  tbody.innerHTML = "";
  
  const sortedTrendDesc = [...trend].reverse();
  sortedTrendDesc.forEach(item => {
    const tr = document.createElement("tr");
    tr.className = "hover:bg-slate-50/50 transition-colors";
    
    const qualRate = item.cadastros > 0 ? (item.qualificados / item.cadastros) : 0;
    const activeRate = item.qualificados > 0 ? (item.ativados / item.qualificados) : 0;

    tr.innerHTML = `
      <td class="px-6 py-4"><strong>${formatDate(item.date)}</strong></td>
      <td class="px-6 py-4">${formatInteger(item.cadastros)}</td>
      <td class="px-6 py-4">${formatInteger(item.qualificados)}</td>
      <td class="px-6 py-4">${formatInteger(item.ativados)}</td>
      <td class="px-6 py-4"><span class="text-orange-600 font-bold">${formatPercentage(qualRate)}</span></td>
      <td class="px-6 py-4"><span class="text-emerald-600 font-bold">${formatPercentage(activeRate)}</span></td>
    `;
    tbody.appendChild(tr);
  });
}

// 3. Render Breakdown Demographics Tab
function renderBreakdownTab() {
  const ds = dashboardData.dinx_stats;

  // Clear existing charts
  const schoolCont = document.getElementById("chart-school-breakdown");
  const incomeCont = document.getElementById("chart-income-breakdown");
  const deviceCont = document.getElementById("chart-device-breakdown");
  const originCont = document.getElementById("chart-origin-breakdown");

  schoolCont.innerHTML = "";
  incomeCont.innerHTML = "";
  deviceCont.innerHTML = "";
  originCont.innerHTML = "";

  // Helper function for Doughnut options
  const getDoughnutOptions = (labels, series, colors) => ({
    series: series,
    labels: labels,
    chart: { type: 'donut', height: 280, fontFamily: 'Plus Jakarta Sans' },
    colors: colors,
    legend: { position: 'bottom', horizontalAlign: 'center', fontSize: '11px', fontWeight: 600, labels: { colors: '#64748b' } },
    plotOptions: {
      pie: {
        donut: {
          size: '62%',
          labels: {
            show: true,
            total: {
              show: true,
              label: 'Total',
              fontSize: '12px',
              fontWeight: 700,
              color: '#94a3b8',
              formatter: function (w) {
                return formatInteger(w.globals.seriesTotals.reduce((a, b) => a + b, 0));
              }
            }
          }
        }
      }
    },
    dataLabels: { enabled: true, formatter: (val) => val.toFixed(1) + "%", style: { fontSize: '10px' } }
  });

  // School Type Breakdown
  const schoolLabels = ["Particular", "Pública", "Bolsista", "Não Informado"];
  const schoolSeries = [
    ds.school_breakdown["SITE_BETA_ACCESS_SCHOOL_TYPE_PRIVATE"] || 0,
    ds.school_breakdown["SITE_BETA_ACCESS_SCHOOL_TYPE_PUBLIC"] || 0,
    ds.school_breakdown["SITE_BETA_ACCESS_SCHOOL_TYPE_SCHOLARSHIP"] || 0,
    ds.school_breakdown["None"] || 0
  ];
  const schoolChart = new ApexCharts(schoolCont, getDoughnutOptions(schoolLabels, schoolSeries, ['#f97316', '#7c3aed', '#fb7185', '#94a3b8']));
  schoolChart.render();

  // Income Range Breakdown
  const incomeKeys = [
    { key: "under2k", label: "Até R$ 2k" },
    { key: "between2kAnd4k", label: "R$ 2k a 4k" },
    { key: "between4kAnd12k", label: "R$ 4k a 12k" },
    { key: "between12kAnd25k", label: "R$ 12k a 25k" },
    { key: "over25k", label: "Acima de R$ 25k" },
    { key: "notInformed", label: "Não Informado" }
  ];
  const incomeLabels = incomeKeys.map(k => k.label);
  const incomeSeries = incomeKeys.map(k => ds.income_breakdown[k.key] || 0);
  const incomeChart = new ApexCharts(incomeCont, getDoughnutOptions(incomeLabels, incomeSeries, ['#ef4444', '#f97316', '#eab308', '#06b6d4', '#10b981', '#94a3b8']));
  incomeChart.render();

  // Device Breakdown
  const deviceLabels = ["Android", "iOS", "Outro", "Não Informado"];
  const deviceSeries = [
    ds.device_breakdown["android"] || 0,
    ds.device_breakdown["ios"] || 0,
    ds.device_breakdown["other"] || 0,
    ds.device_breakdown["empty"] || 0
  ];
  const deviceChart = new ApexCharts(deviceCont, getDoughnutOptions(deviceLabels, deviceSeries, ['#10b981', '#3b82f6', '#ec4899', '#94a3b8']));
  deviceChart.render();

  // Origin Breakdown
  const originLabels = ["Meta Ads", "Site Dinx", "Acesso Direto"];
  const originSeries = [
    ds.origin_breakdown["SITE_BETA_ACCESS_INVITE_ORIGIN_META"] || 0,
    ds.origin_breakdown["SITE_BETA_ACCESS_INVITE_ORIGIN_SITE"] || 0,
    ds.origin_breakdown["None"] || 0
  ];
  const originChart = new ApexCharts(originCont, getDoughnutOptions(originLabels, originSeries, ['#7c3aed', '#ec4899', '#94a3b8']));
  originChart.render();
}

// 4. Render Meta Campaigns Table
function renderCampaignsTable() {
  const campaigns = dashboardData.meta_stats.campaigns;

  // Filter campaigns
  let filtered = campaigns.filter(c => {
    const matchSearch = c.name.toLowerCase().includes(campaignSearchQuery.toLowerCase());
    
    let matchStatus = true;
    if (campaignStatusFilter === "ACTIVE") {
      matchStatus = c.status === "ACTIVE";
    } else if (campaignStatusFilter === "PAUSED") {
      matchStatus = c.status === "PAUSED";
    }
    
    return matchSearch && matchStatus;
  });

  filtered.sort((a, b) => b.spend - a.spend);

  const tbody = document.getElementById("campaigns-table-body");
  tbody.innerHTML = "";

  if (filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="9" class="text-center py-10 text-slate-400 font-bold text-xs uppercase tracking-wide">Nenhuma campanha encontrada.</td></tr>`;
    document.getElementById("table-pagination").innerHTML = "";
    return;
  }

  const startIndex = (campaignCurrentPage - 1) * campaignItemsPerPage;
  const paginated = filtered.slice(startIndex, startIndex + campaignItemsPerPage);
  const totalPages = Math.ceil(filtered.length / campaignItemsPerPage);

  paginated.forEach(c => {
    const tr = document.createElement("tr");
    tr.className = "hover:bg-slate-50/50 transition-colors";
    
    const isActive = c.status.toLowerCase() === 'active';
    const statusClass = isActive ? 'bg-emerald-50 text-emerald-700 border-emerald-100' : 'bg-slate-100 text-slate-600 border-slate-200';
    const statusText = isActive ? 'Ativo' : 'Pausado';
    const cpl = c.leads > 0 ? (c.spend / c.leads) : 0;
    const cpa = c.dinx_approved > 0 ? (c.spend / c.dinx_approved) : 0;

    tr.innerHTML = `
      <td class="px-6 py-4 font-bold text-slate-800 max-w-[280px] overflow-hidden text-overflow-ellipsis whitespace-nowrap" title="${c.name}">${c.name}</td>
      <td class="px-6 py-4"><span class="inline-block px-2.5 py-1 rounded-full text-[10px] font-extrabold border ${statusClass}">${statusText}</span></td>
      <td class="px-6 py-4 text-right font-extrabold text-slate-800">${formatCurrency(c.spend)}</td>
      <td class="px-6 py-4 text-right">${formatInteger(c.leads)}</td>
      <td class="px-6 py-4 text-right font-semibold">${formatInteger(c.dinx_leads)}</td>
      <td class="px-6 py-4 text-right font-bold text-orange-600">${formatInteger(c.dinx_approved)}</td>
      <td class="px-6 py-4 text-right text-slate-400 font-semibold">${c.leads > 0 ? formatCurrency(cpl) : '—'}</td>
      <td class="px-6 py-4 text-right font-extrabold text-orange-600">${c.dinx_approved > 0 ? formatCurrency(cpa) : '—'}</td>
    `;
    tbody.appendChild(tr);
  });

  // Render pagination controls
  const paginationContainer = document.getElementById("table-pagination");
  paginationContainer.innerHTML = `
    <div>Mostrando ${startIndex + 1} a ${Math.min(startIndex + campaignItemsPerPage, filtered.length)} de ${filtered.length} campanhas</div>
    <div class="flex gap-2">
      <button class="bg-white hover:bg-slate-50 border border-slate-200 px-3 py-1.5 rounded-lg text-xs font-bold text-slate-700 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed" id="btn-page-prev" ${campaignCurrentPage === 1 ? 'disabled' : ''}>Anterior</button>
      <button class="bg-white hover:bg-slate-50 border border-slate-200 px-3 py-1.5 rounded-lg text-xs font-bold text-slate-700 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed" id="btn-page-next" ${campaignCurrentPage === totalPages ? 'disabled' : ''}>Próxima</button>
    </div>
  `;

  // Attach button events
  document.getElementById("btn-page-prev")?.addEventListener("click", () => {
    if (campaignCurrentPage > 1) {
      campaignCurrentPage--;
      renderCampaignsTable();
    }
  });

  document.getElementById("btn-page-next")?.addEventListener("click", () => {
    if (campaignCurrentPage < totalPages) {
      campaignCurrentPage++;
      renderCampaignsTable();
    }
  });
}
