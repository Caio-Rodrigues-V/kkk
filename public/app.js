// State Variables
let dashboardData = null;
let activeTab = 'overview';
let activeSubTab = 'campaigns';
let excludeInternal = localStorage.getItem("exclude_internal") === "true";
let dateRange = localStorage.getItem("date_range") || "all";
let customStartDate = localStorage.getItem("custom_start_date") || "";
let customEndDate = localStorage.getItem("custom_end_date") || "";

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

  // Checkbox for excluding internal users
  const chkExcludeInternal = document.getElementById("chk-exclude-internal");
  if (chkExcludeInternal) {
    chkExcludeInternal.checked = excludeInternal;
    chkExcludeInternal.addEventListener("change", (e) => {
      excludeInternal = e.target.checked;
      localStorage.setItem("exclude_internal", excludeInternal);
      fetchDashboardData(false);
    });
  }

  // Date Filter Dropdown Logic
  const btnDateFilter = document.getElementById("btn-date-filter");
  const dateDropdown = document.getElementById("date-filter-dropdown");
  const selectedFilterText = document.getElementById("selected-filter");
  const customDatePanel = document.getElementById("custom-date-panel");
  const customStartInput = document.getElementById("custom-start-date");
  const customEndInput = document.getElementById("custom-end-date");
  const btnApplyCustom = document.getElementById("btn-apply-custom-date");
  
  const rangeLabels = {
    all: "Todo o período",
    "7days": "Últimos 7 dias",
    "30days": "Últimos 30 dias",
    thismonth: "Este mês",
    lastmonth: "Mês passado",
    custom: "Personalizado"
  };

  // Set initial values
  if (customStartInput) customStartInput.value = customStartDate;
  if (customEndInput) customEndInput.value = customEndDate;

  // Format custom date for display
  function formatCustomDateLabel(start, end) {
    if (!start || !end) return "Personalizado";
    const parseAndFormat = (dStr) => {
      const parts = dStr.split('-');
      return `${parts[2]}/${parts[1]}`;
    };
    return `${parseAndFormat(start)} a ${parseAndFormat(end)}`;
  }

  // Set initial text label
  if (selectedFilterText) {
    if (dateRange === "custom") {
      selectedFilterText.textContent = formatCustomDateLabel(customStartDate, customEndDate);
    } else {
      selectedFilterText.textContent = rangeLabels[dateRange] || "Todo o período";
    }
  }

  if (btnDateFilter && dateDropdown) {
    btnDateFilter.addEventListener("click", (e) => {
      e.stopPropagation();
      dateDropdown.classList.toggle("hidden");
      
      // If panel is currently active, ensure customDatePanel visibility matches
      if (dateRange === "custom") {
        customDatePanel?.classList.remove("hidden");
      } else {
        customDatePanel?.classList.add("hidden");
      }
    });

    // Close dropdown on click outside, but DO NOT close if clicked inside the custom date panel
    document.addEventListener("click", (e) => {
      if (dateDropdown && !dateDropdown.contains(e.target) && e.target !== btnDateFilter) {
        dateDropdown.classList.add("hidden");
      }
    });

    const options = document.querySelectorAll(".date-filter-opt");
    options.forEach(opt => {
      opt.addEventListener("click", (e) => {
        e.stopPropagation(); // Prevent document click listener from firing
        const selectedRange = opt.getAttribute("data-range");
        
        if (selectedRange === "custom") {
          customDatePanel?.classList.toggle("hidden");
        } else {
          customDatePanel?.classList.add("hidden");
          dateRange = selectedRange;
          localStorage.setItem("date_range", dateRange);
          if (selectedFilterText) {
            selectedFilterText.textContent = rangeLabels[dateRange] || "Todo o período";
          }
          dateDropdown.classList.add("hidden");
          fetchDashboardData(false);
        }
      });
    });

    if (btnApplyCustom) {
      btnApplyCustom.addEventListener("click", (e) => {
        e.stopPropagation();
        const startVal = customStartInput.value;
        const endVal = customEndInput.value;
        
        if (!startVal || !endVal) {
          alert("Por favor, preencha as datas de início e fim.");
          return;
        }
        
        dateRange = "custom";
        customStartDate = startVal;
        customEndDate = endVal;
        
        localStorage.setItem("date_range", dateRange);
        localStorage.setItem("custom_start_date", customStartDate);
        localStorage.setItem("custom_end_date", customEndDate);
        
        if (selectedFilterText) {
          selectedFilterText.textContent = formatCustomDateLabel(customStartDate, customEndDate);
        }
        
        dateDropdown.classList.add("hidden");
        fetchDashboardData(false);
      });
    }
  }

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

  // Sub-tab Navigation
  const subTabBtns = document.querySelectorAll(".sub-tab-btn");
  subTabBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      subTabBtns.forEach(b => {
        b.classList.remove("active", "border-purple-600", "text-purple-600");
        b.classList.add("border-transparent", "text-slate-500");
      });
      btn.classList.add("active", "border-purple-600", "text-purple-600");
      btn.classList.remove("border-transparent", "text-slate-500");
      
      activeSubTab = btn.getAttribute("data-subtab");
      campaignCurrentPage = 1;
      
      // Update placeholder search text
      const searchInput = document.getElementById("campaign-search");
      if (activeSubTab === "campaigns") {
        searchInput.placeholder = "Buscar campanhas por nome...";
      } else if (activeSubTab === "adsets") {
        searchInput.placeholder = "Buscar conjuntos de anúncios...";
      } else {
        searchInput.placeholder = "Buscar anúncios por nome...";
      }
      
      renderCampaignsTable();
    });
  });

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
  const isFirstLoad = (dashboardData === null);
  
  if (isFirstLoad) {
    loadingOverlayEl.classList.add("active");
    loadingOverlayEl.classList.remove("opacity-0", "pointer-events-none");
  }
  
  syncIconEl.classList.add("animate-spin");
  
  let endpoint = (forceSync ? "/api/sync" : "/api/data") + `?exclude_internal=${excludeInternal}&date_range=${dateRange}`;
  if (dateRange === "custom") {
    endpoint += `&start_date=${customStartDate}&end_date=${customEndDate}`;
  }
  try {
    const response = await fetch(endpoint);
    if (!response.ok) throw new Error("Erro de rede");
    const resPayload = await response.json();
    
    dashboardData = resPayload.data;
    
    // Update all views
    updateDashboardUI();
    
    // Check if background fetch is running
    const syncTextEl = document.getElementById("sync-text");
    if (resPayload.is_fetching) {
      if (syncTextEl) syncTextEl.textContent = "Sincronizando...";
      syncIconEl.classList.add("animate-spin");
      btnSyncEl.disabled = true;
      // Poll again in 3 seconds
      setTimeout(() => {
        fetchDashboardData(false);
      }, 3000);
    } else {
      if (syncTextEl) syncTextEl.textContent = "Atualizar";
      syncIconEl.classList.remove("animate-spin");
      btnSyncEl.disabled = false;
    }
  } catch (error) {
    console.error("Erro ao carregar dados:", error);
    if (isFirstLoad) {
      alert("Não foi possível carregar os dados das APIs. Certifique-se de que o backend está ativo.");
    }
  } finally {
    if (isFirstLoad) {
      loadingOverlayEl.classList.remove("active");
      loadingOverlayEl.classList.add("opacity-0", "pointer-events-none");
    }
  }
}

// Global UI Updater
function updateDashboardUI() {
  if (!dashboardData) return;

  // 1. Header updated time
  if (dashboardData.last_updated) {
    const updatedDate = new Date(dashboardData.last_updated);
    syncTimeEl.textContent = `Atualizado ${formatDate(dashboardData.last_updated)} às ${updatedDate.toLocaleTimeString('pt-BR', {hour: '2-digit', minute:'2-digit'})}`;
  } else {
    syncTimeEl.textContent = "Atualizado --/--/----";
  }

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


}

// 3. Render Breakdown Demographics Tab
function renderBreakdownTab() {
  const ds = dashboardData.dinx_stats;

  // Clear existing charts
  const schoolCont = document.getElementById("chart-school-breakdown");
  const deviceCont = document.getElementById("chart-device-breakdown");
  const originCont = document.getElementById("chart-origin-breakdown");

  schoolCont.innerHTML = "";
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

// 4. Render Meta Campaigns, Adsets, or Ads Table
function renderCampaignsTable() {
  if (!dashboardData) return;

  const ms = dashboardData.meta_stats;
  const campaigns = ms.campaigns || [];
  const adsets = ms.adsets || [];
  const ads = ms.ads || [];

  // 1. Update sub-tab badge counts
  const badgeCampaigns = document.getElementById("badge-count-campaigns");
  const badgeAdsets = document.getElementById("badge-count-adsets");
  const badgeAds = document.getElementById("badge-count-ads");
  
  if (badgeCampaigns) badgeCampaigns.textContent = campaigns.length;
  if (badgeAdsets) badgeAdsets.textContent = adsets.length;
  if (badgeAds) badgeAds.textContent = ads.length;

  // 2. Select dataset and dynamically set table header
  let dataList = [];
  const header = document.getElementById("campaigns-table-header");

  if (!header) return;

  if (activeSubTab === "campaigns") {
    dataList = campaigns;
    header.innerHTML = `
      <tr class="bg-slate-50 text-slate-500 font-bold border-b border-slate-100">
        <th class="px-6 py-4">Campanha</th>
        <th class="px-6 py-4">Status</th>
        <th class="px-6 py-4 text-right">Investimento</th>
        <th class="px-6 py-4 text-right">Leads (Meta)</th>
        <th class="px-6 py-4 text-right">Leads (Dinx)</th>
        <th class="px-6 py-4 text-right text-orange-600">Qualificados</th>
        <th class="px-6 py-4 text-right">CPL (Meta)</th>
        <th class="px-6 py-4 text-right text-orange-600">CPA (Dinx)</th>
      </tr>
    `;
  } else if (activeSubTab === "adsets") {
    dataList = adsets;
    header.innerHTML = `
      <tr class="bg-slate-50 text-slate-500 font-bold border-b border-slate-100">
        <th class="px-6 py-4">Conjunto de Anúncios</th>
        <th class="px-6 py-4">Status</th>
        <th class="px-6 py-4 text-right">Investimento</th>
        <th class="px-6 py-4 text-right">Leads (Meta)</th>
        <th class="px-6 py-4 text-right">CPL (Meta)</th>
      </tr>
    `;
  } else {
    dataList = ads;
    header.innerHTML = `
      <tr class="bg-slate-50 text-slate-500 font-bold border-b border-slate-100">
        <th class="px-6 py-4">Anúncio</th>
        <th class="px-6 py-4">Status</th>
        <th class="px-6 py-4 text-right">Investimento</th>
        <th class="px-6 py-4 text-right">Leads (Meta)</th>
        <th class="px-6 py-4 text-right">CPL (Meta)</th>
      </tr>
    `;
  }

  // 3. Filter list
  let filtered = dataList.filter(item => {
    const nameStr = item.name || "";
    const matchSearch = nameStr.toLowerCase().includes(campaignSearchQuery.toLowerCase());
    
    let matchStatus = true;
    if (campaignStatusFilter === "ACTIVE") {
      matchStatus = (item.status || "").toUpperCase() === "ACTIVE";
    } else if (campaignStatusFilter === "PAUSED") {
      matchStatus = (item.status || "").toUpperCase() === "PAUSED";
    }
    
    return matchSearch && matchStatus;
  });

  // Sort by spend descending
  filtered.sort((a, b) => b.spend - a.spend);

  const tbody = document.getElementById("campaigns-table-body");
  tbody.innerHTML = "";

  const itemsName = activeSubTab === "campaigns" ? "campanhas" : (activeSubTab === "adsets" ? "conjuntos" : "anúncios");

  if (filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="9" class="text-center py-10 text-slate-400 font-bold text-xs uppercase tracking-wide">Nenhum registro encontrado.</td></tr>`;
    document.getElementById("table-pagination").innerHTML = "";
    return;
  }

  const startIndex = (campaignCurrentPage - 1) * campaignItemsPerPage;
  const paginated = filtered.slice(startIndex, startIndex + campaignItemsPerPage);
  const totalPages = Math.ceil(filtered.length / campaignItemsPerPage);

  // 4. Render rows
  paginated.forEach(item => {
    const tr = document.createElement("tr");
    tr.className = "hover:bg-slate-50/50 transition-colors border-b border-slate-100 last:border-b-0";
    
    const isActive = (item.status || "").toLowerCase() === 'active';
    const statusClass = isActive ? 'bg-emerald-50 text-emerald-700 border-emerald-100' : 'bg-slate-100 text-slate-600 border-slate-200';
    const statusText = isActive ? 'Ativo' : 'Pausado';
    const cpl = item.leads > 0 ? (item.spend / item.leads) : 0;

    if (activeSubTab === "campaigns") {
      const cpa = item.dinx_approved > 0 ? (item.spend / item.dinx_approved) : 0;
      tr.innerHTML = `
        <td class="px-6 py-4 font-bold text-slate-800 break-words whitespace-normal min-w-[240px] max-w-[340px]" title="${item.name}">${item.name}</td>
        <td class="px-6 py-4"><span class="inline-block px-2.5 py-1 rounded-full text-[10px] font-extrabold border ${statusClass}">${statusText}</span></td>
        <td class="px-6 py-4 text-right font-extrabold text-slate-800">${formatCurrency(item.spend)}</td>
        <td class="px-6 py-4 text-right">${formatInteger(item.leads)}</td>
        <td class="px-6 py-4 text-right font-semibold">${formatInteger(item.dinx_leads || 0)}</td>
        <td class="px-6 py-4 text-right font-bold text-orange-600">${formatInteger(item.dinx_approved || 0)}</td>
        <td class="px-6 py-4 text-right text-slate-400 font-semibold">${item.leads > 0 ? formatCurrency(cpl) : '—'}</td>
        <td class="px-6 py-4 text-right font-extrabold text-orange-600">${item.dinx_approved > 0 ? formatCurrency(cpa) : '—'}</td>
      `;
    } else if (activeSubTab === "adsets") {
      tr.innerHTML = `
        <td class="px-6 py-4 font-bold text-slate-800 break-words whitespace-normal min-w-[240px] max-w-[340px]" title="${item.name}">${item.name}</td>
        <td class="px-6 py-4"><span class="inline-block px-2.5 py-1 rounded-full text-[10px] font-extrabold border ${statusClass}">${statusText}</span></td>
        <td class="px-6 py-4 text-right font-extrabold text-slate-800">${formatCurrency(item.spend)}</td>
        <td class="px-6 py-4 text-right">${formatInteger(item.leads)}</td>
        <td class="px-6 py-4 text-right text-slate-400 font-semibold">${item.leads > 0 ? formatCurrency(cpl) : '—'}</td>
      `;
    } else {
      // For Ads: display ad image next to name
      const imgTag = item.thumbnail_url 
        ? `<img src="${item.thumbnail_url}" class="w-10 h-10 rounded-lg object-cover bg-slate-100 flex-shrink-0 shadow-sm border border-slate-100">`
        : `<div class="w-10 h-10 rounded-lg bg-purple-50 text-purple-500 border border-purple-100/50 flex items-center justify-center flex-shrink-0 shadow-sm"><i data-lucide="image" class="w-4 h-4"></i></div>`;
      
      tr.innerHTML = `
        <td class="px-6 py-4 flex items-center gap-3 min-w-[240px] max-w-[360px]">
          ${imgTag}
          <div class="flex flex-col leading-tight break-words whitespace-normal w-full">
            <span class="font-bold text-slate-800" title="${item.name}">${item.name}</span>
            <span class="text-[9px] text-slate-400 font-semibold mt-0.5">ID: ${item.id}</span>
          </div>
        </td>
        <td class="px-6 py-4"><span class="inline-block px-2.5 py-1 rounded-full text-[10px] font-extrabold border ${statusClass}">${statusText}</span></td>
        <td class="px-6 py-4 text-right font-extrabold text-slate-800">${formatCurrency(item.spend)}</td>
        <td class="px-6 py-4 text-right">${formatInteger(item.leads)}</td>
        <td class="px-6 py-4 text-right text-slate-400 font-semibold">${item.leads > 0 ? formatCurrency(cpl) : '—'}</td>
      `;
    }
    
    tbody.appendChild(tr);
  });

  // Re-run lucide icons to build the fallback image icon if needed
  if (activeSubTab === "ads") {
    lucide.createIcons();
  }

  // Render pagination controls
  const paginationContainer = document.getElementById("table-pagination");
  paginationContainer.innerHTML = `
    <div>Mostrando ${startIndex + 1} a ${Math.min(startIndex + campaignItemsPerPage, filtered.length)} de ${filtered.length} ${itemsName}</div>
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
