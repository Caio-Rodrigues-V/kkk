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
  const activationPct = ds.qualificados_private > 0 ? (ds.ativados / ds.qualificados_private) : 0;
  document.getElementById("kpi-apps-ativados-pct").textContent = `${formatPercentage(activationPct)} dos particulares`;

  // Sub KPIs row
  document.getElementById("sub-taxa-qualif").textContent = formatPercentage(qualPrivatePct);
  document.getElementById("sub-taxa-qualif-det").textContent = `${formatInteger(ds.qualificados_private)} / ${formatInteger(ds.total_leads)}`;

  const cplQualif = ds.qualificados_private > 0 ? (ms.lead_campaign_spend / ds.qualificados_private) : 0;
  document.getElementById("sub-cpl-qualif").textContent = formatCurrency(cplQualif);
  document.getElementById("sub-cpl-qualif-det").textContent = `${formatCurrency(ms.lead_campaign_spend)} / ${formatInteger(ds.qualificados_private)}`;

  const taxaAtivacao = ds.qualificados_private > 0 ? (ds.ativados / ds.qualificados_private) : 0;
  const subTaxaAtivEl = document.getElementById("sub-taxa-ativacao");
  if (subTaxaAtivEl) {
    subTaxaAtivEl.textContent = formatPercentage(taxaAtivacao);
    document.getElementById("sub-taxa-ativacao-det").textContent = `${formatInteger(ds.ativados)} / ${formatInteger(ds.qualificados_private)}`;
  }

  // Top Highlights
  if (ms.campaigns && ms.campaigns.length > 0) {
    let topC = ms.campaigns[0];
    for (let c of ms.campaigns) {
      if ((c.dinx_approved || 0) > (topC.dinx_approved || 0)) topC = c;
    }
    const topCampEl = document.getElementById("top-campaign-name");
    if (topCampEl) {
      topCampEl.textContent = topC.name || "Desconhecida";
      document.getElementById("top-campaign-leads").textContent = formatInteger(topC.dinx_approved || 0);
    }
  }
  
  if (ms.ads && ms.ads.length > 0) {
    let topA = ms.ads[0];
    for (let a of ms.ads) {
      if ((a.dinx_approved || 0) > (topA.dinx_approved || 0)) topA = a;
    }
    const topCreEl = document.getElementById("top-creative-name");
    if (topCreEl) {
      topCreEl.textContent = topA.name || "Desconhecido";
      document.getElementById("top-creative-leads").textContent = formatInteger(topA.dinx_approved || 0);
      const imgEl = document.getElementById("top-creative-img");
      if (topA.thumbnail_url) {
        imgEl.src = topA.thumbnail_url;
        imgEl.classList.remove("hidden");
      } else {
        imgEl.classList.add("hidden");
      }
    }
  }

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

  // Render Daily Spend, CPL and Funnel
  renderOverviewSpendChart(ds.daily_trend);
  renderOverviewCPLChart(ds.daily_trend);
  renderOverviewFunnel(ds);

  // Render Instagram Tab
  renderInstagramTab();
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

// Render Daily Spend Chart (Bar Chart)
function renderOverviewSpendChart(trendData) {
  const container = document.getElementById("overview-spend-chart");
  if (!container) return;
  container.innerHTML = ""; // Clear

  const slicedData = trendData.slice(-30);
  const categories = slicedData.map(item => {
    const parts = item.date.split('-');
    return `${parts[2]}/${parts[1]}`;
  });

  const seriesSpend = slicedData.map(item => item.spend || 0.0);

  const options = {
    series: [{
      name: 'Investido',
      data: seriesSpend
    }],
    chart: {
      type: 'bar',
      height: '100%',
      fontFamily: 'Plus Jakarta Sans',
      toolbar: { show: false }
    },
    plotOptions: {
      bar: {
        borderRadius: 4,
        columnWidth: '55%'
      }
    },
    dataLabels: { enabled: false },
    colors: ['#7c3aed'],
    grid: {
      borderColor: '#f1f5f9',
      strokeDashArray: 4,
      padding: { left: 10, right: 10, top: 0, bottom: 0 }
    },
    xaxis: {
      categories: categories,
      labels: {
        style: { colors: '#94a3b8', fontSize: '9px', fontWeight: 600 }
      },
      axisBorder: { show: false },
      axisTicks: { show: false }
    },
    yaxis: {
      labels: {
        style: { colors: '#94a3b8', fontSize: '9px', fontWeight: 600 },
        formatter: (val) => formatCurrency(val).split(',')[0]
      }
    },
    tooltip: {
      theme: 'light',
      y: { formatter: (val) => formatCurrency(val) }
    }
  };

  const chart = new ApexCharts(container, options);
  chart.render();
}

// Render Daily CPL Chart (Line Chart)
function renderOverviewCPLChart(trendData) {
  const container = document.getElementById("overview-cpl-chart");
  if (!container) return;
  container.innerHTML = ""; // Clear

  const slicedData = trendData.slice(-30);
  const categories = slicedData.map(item => {
    const parts = item.date.split('-');
    return `${parts[2]}/${parts[1]}`;
  });

  const seriesCPL = slicedData.map(item => item.cpl || 0.0);

  const options = {
    series: [{
      name: 'CPL Qualificado',
      data: seriesCPL
    }],
    chart: {
      type: 'line',
      height: '100%',
      fontFamily: 'Plus Jakarta Sans',
      toolbar: { show: false }
    },
    stroke: {
      curve: 'smooth',
      width: 3
    },
    dataLabels: { enabled: false },
    colors: ['#ea580c'],
    grid: {
      borderColor: '#f1f5f9',
      strokeDashArray: 4,
      padding: { left: 10, right: 10, top: 0, bottom: 0 }
    },
    xaxis: {
      categories: categories,
      labels: {
        style: { colors: '#94a3b8', fontSize: '9px', fontWeight: 600 }
      },
      axisBorder: { show: false },
      axisTicks: { show: false }
    },
    yaxis: {
      labels: {
        style: { colors: '#94a3b8', fontSize: '9px', fontWeight: 600 },
        formatter: (val) => formatCurrency(val)
      }
    },
    tooltip: {
      theme: 'light',
      y: { formatter: (val) => formatCurrency(val) }
    }
  };

  const chart = new ApexCharts(container, options);
  chart.render();
}

// Helper to format values as 'k' if they are >= 1000
function formatK(num) {
  if (num >= 1000) {
    return (num / 1000).toFixed(1) + 'k';
  }
  return num.toString();
}

// Render Funnel de Jornada
function renderOverviewFunnel(ds) {
  const container = document.getElementById("journey-funnel-container");
  if (!container) return;
  container.innerHTML = "";

  const totalLeads = ds.total_leads || 0;
  const qualPrivate = ds.qualificados_private || 0;
  const approved = ds.qualificados_private || 0; // Same as qualified school particular
  const ativados = ds.ativados || 0;

  const qualPct = totalLeads > 0 ? ((qualPrivate / totalLeads) * 100).toFixed(1) : "0.0";
  const appPct = qualPrivate > 0 ? ((approved / qualPrivate) * 100).toFixed(1) : "100.0";
  const actPct = qualPrivate > 0 ? ((ativados / qualPrivate) * 100).toFixed(1) : "0.0";

  const funnelItems = [
    {
      label: "Leads",
      value: formatK(totalLeads),
      pct: null,
      width: "100%",
      color: "bg-purple-500"
    },
    {
      label: "Leads qualificados (escola particular)",
      value: formatK(qualPrivate),
      pct: `${qualPct}%`,
      width: `${totalLeads > 0 ? (qualPrivate / totalLeads * 100) : 0}%`,
      color: "bg-indigo-500"
    },
    {
      label: "Aprovados",
      value: formatK(approved),
      pct: `${appPct}%`,
      width: `${qualPrivate > 0 ? (approved / qualPrivate * 100) : 0}%`,
      color: "bg-orange-500"
    },
    {
      label: "Ativaram app",
      value: formatK(ativados),
      pct: `${actPct}%`,
      width: `${qualPrivate > 0 ? (ativados / qualPrivate * 100) : 0}%`,
      color: "bg-pink-500"
    }
  ];

  funnelItems.forEach(item => {
    const itemEl = document.createElement("div");
    itemEl.className = "space-y-1.5";
    
    const labelRow = document.createElement("div");
    labelRow.className = "flex justify-between items-end text-xs font-bold text-slate-700";
    
    const labelSpan = document.createElement("span");
    labelSpan.className = "text-slate-500 text-[11px] font-semibold";
    labelSpan.textContent = item.label;
    
    const valueSpan = document.createElement("span");
    valueSpan.className = "text-slate-800 text-xs font-extrabold";
    valueSpan.innerHTML = `${item.value} ${item.pct ? `<span class="text-[10px] text-slate-400 font-semibold ml-1">(${item.pct})</span>` : ""}`;
    
    labelRow.appendChild(labelSpan);
    labelRow.appendChild(valueSpan);
    
    const barContainer = document.createElement("div");
    barContainer.className = "w-full bg-slate-100/80 rounded-full h-3 overflow-hidden";
    
    const barFill = document.createElement("div");
    barFill.className = `${item.color} h-full rounded-full transition-all duration-500 ease-out`;
    barFill.style.width = item.width;
    
    barContainer.appendChild(barFill);
    
    itemEl.appendChild(labelRow);
    itemEl.appendChild(barContainer);
    
    container.appendChild(itemEl);
  });
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

  const ds = dashboardData.dinx_stats;

  // Calculate global summary stats for the Campaigns page big numbers
  const totalSpend = campaigns.reduce((acc, c) => acc + (c.spend || 0.0), 0.0);
  const totalLeads = campaigns.reduce((acc, c) => acc + (c.leads || 0), 0);
  const totalQual = ds.qualificados_private || 0;
  const totalActiv = ds.ativados || 0;
  const taxaQual = ds.total_leads > 0 ? (ds.qualificados_private / ds.total_leads) : 0;

  // Render big numbers
  document.getElementById("meta-kpi-investido").textContent = formatCurrency(totalSpend);
  document.getElementById("meta-kpi-investido-sub").textContent = `${formatInteger(totalLeads)} resultados na Meta`;
  document.getElementById("meta-kpi-leads").textContent = formatInteger(totalLeads);
  document.getElementById("meta-kpi-qualificados").textContent = formatInteger(totalQual);
  document.getElementById("meta-kpi-ativados").textContent = formatInteger(totalActiv);
  document.getElementById("meta-kpi-taxa-qualif").textContent = formatPercentage(taxaQual);

  // Active vs Paused counts
  const activeCampaigns = campaigns.filter(c => (c.status || "").toUpperCase() === "ACTIVE").length;
  const pausedCampaigns = campaigns.length - activeCampaigns;
  document.getElementById("label-campaign-status").textContent = `Campanha Destaque (${activeCampaigns} ativas / ${pausedCampaigns} pausadas)`;

  const activeAds = ads.filter(ad => (ad.status || "").toUpperCase() === "ACTIVE").length;
  const pausedAds = ads.length - activeAds;
  document.getElementById("label-ad-status").textContent = `Criativo Destaque (${activeAds} ativos / ${pausedAds} pausados)`;

  // Find Highlight Campaign (Award Campaign with highest qualified leads)
  let topCampaign = null;
  campaigns.forEach(c => {
    if (!topCampaign || (c.dinx_approved || 0) > (topCampaign.dinx_approved || 0)) {
      topCampaign = c;
    }
  });

  if (topCampaign && (topCampaign.dinx_approved || 0) > 0) {
    document.getElementById("highlight-campaign-name").textContent = topCampaign.name;
    document.getElementById("highlight-campaign-value").textContent = `${formatInteger(topCampaign.dinx_approved)} qualif.`;
    document.getElementById("highlight-campaign-sub").textContent = `${formatCurrency(topCampaign.spend)} investido`;
  } else {
    document.getElementById("highlight-campaign-name").textContent = "Nenhuma campanha atribuída";
    document.getElementById("highlight-campaign-value").textContent = "0 qualif.";
    document.getElementById("highlight-campaign-sub").textContent = "R$ 0,00 investido";
  }

  // Find Highlight Ad (Creative with highest qualified leads)
  let topAd = null;
  ads.forEach(ad => {
    if (!topAd || (ad.dinx_approved || 0) > (topAd.dinx_approved || 0)) {
      topAd = ad;
    }
  });

  const adImgContainer = document.getElementById("highlight-ad-image-container");
  if (topAd && (topAd.dinx_approved || 0) > 0) {
    document.getElementById("highlight-ad-name").textContent = topAd.name;
    document.getElementById("highlight-ad-value").textContent = `${formatInteger(topAd.dinx_approved)} qualif.`;
    document.getElementById("highlight-ad-sub").textContent = `${formatCurrency(topAd.spend)} investido`;
    
    if (topAd.thumbnail_url) {
      adImgContainer.innerHTML = `<img src="${topAd.thumbnail_url}" class="w-full h-full object-cover rounded-lg">`;
    } else {
      adImgContainer.innerHTML = `<i data-lucide="image" class="w-5 h-5 text-slate-400"></i>`;
    }
  } else {
    document.getElementById("highlight-ad-name").textContent = "Nenhum criativo atribuído";
    document.getElementById("highlight-ad-value").textContent = "0 qualif.";
    document.getElementById("highlight-ad-sub").textContent = "R$ 0,00 investido";
    adImgContainer.innerHTML = `<i data-lucide="image" class="w-5 h-5 text-slate-400"></i>`;
  }

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
        <th class="px-6 py-4">Nome da campanha</th>
        <th class="px-6 py-4">Status</th>
        <th class="px-6 py-4 text-right">Valor investido</th>
        <th class="px-6 py-4 text-right">Cadastros totais</th>
        <th class="px-6 py-4 text-right">Cadastros qualificados</th>
        <th class="px-6 py-4 text-right text-orange-600">Custo/Cad. Qualificado</th>
      </tr>
    `;
  } else if (activeSubTab === "adsets") {
    dataList = adsets;
    header.innerHTML = `
      <tr class="bg-slate-50 text-slate-500 font-bold border-b border-slate-100">
        <th class="px-6 py-4">Nome do conjunto</th>
        <th class="px-6 py-4">Status</th>
        <th class="px-6 py-4 text-right">Valor investido</th>
        <th class="px-6 py-4 text-right">Cadastros totais</th>
        <th class="px-6 py-4 text-right">Cadastros qualificados</th>
        <th class="px-6 py-4 text-right text-orange-600">Custo/Cad. Qualificado</th>
      </tr>
    `;
  } else {
    dataList = ads;
    header.innerHTML = `
      <tr class="bg-slate-50 text-slate-500 font-bold border-b border-slate-100">
        <th class="px-6 py-4">Nome do anúncio</th>
        <th class="px-6 py-4">Status</th>
        <th class="px-6 py-4 text-right">Valor investido</th>
        <th class="px-6 py-4 text-right">Cadastros totais</th>
        <th class="px-6 py-4 text-right">Cadastros qualificados</th>
        <th class="px-6 py-4 text-right text-orange-600">Custo/Cad. Qualificado</th>
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
    
    const spend = item.spend || 0.0;
    const leads = item.leads || 0;
    const qualificados = item.dinx_approved || 0;
    const ativados = item.dinx_activated || 0;
    
    const cpl = leads > 0 ? (spend / leads) : 0;
    const cpaQualif = qualificados > 0 ? (spend / qualificados) : 0;
    const cpaActiv = ativados > 0 ? (spend / ativados) : 0;

    if (activeSubTab === "campaigns") {
      tr.innerHTML = `
        <td class="px-6 py-4 font-bold text-slate-800 break-words whitespace-normal min-w-[240px] max-w-[340px]" title="${item.name}">${item.name}</td>
        <td class="px-6 py-4"><span class="inline-block px-2.5 py-1 rounded-full text-[10px] font-extrabold border ${statusClass}">${statusText}</span></td>
        <td class="px-6 py-4 text-right font-extrabold text-slate-800">${formatCurrency(spend)}</td>
        <td class="px-6 py-4 text-right font-semibold text-slate-700">${formatInteger(leads)}</td>
        <td class="px-6 py-4 text-right font-bold text-orange-600">${formatInteger(qualificados)}</td>
        <td class="px-6 py-4 text-right text-orange-600 font-extrabold">${qualificados > 0 ? formatCurrency(cpaQualif) : '—'}</td>
      `;
    } else if (activeSubTab === "adsets") {
      tr.innerHTML = `
        <td class="px-6 py-4 font-bold text-slate-800 break-words whitespace-normal min-w-[240px] max-w-[340px]" title="${item.name}">${item.name}</td>
        <td class="px-6 py-4"><span class="inline-block px-2.5 py-1 rounded-full text-[10px] font-extrabold border ${statusClass}">${statusText}</span></td>
        <td class="px-6 py-4 text-right font-extrabold text-slate-800">${formatCurrency(spend)}</td>
        <td class="px-6 py-4 text-right font-semibold text-slate-700">${formatInteger(leads)}</td>
        <td class="px-6 py-4 text-right font-bold text-orange-600">${formatInteger(qualificados)}</td>
        <td class="px-6 py-4 text-right text-orange-600 font-extrabold">${qualificados > 0 ? formatCurrency(cpaQualif) : '—'}</td>
      `;
    } else {
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
        <td class="px-6 py-4 text-right font-extrabold text-slate-800">${formatCurrency(spend)}</td>
        <td class="px-6 py-4 text-right font-semibold text-slate-700">${formatInteger(leads)}</td>
        <td class="px-6 py-4 text-right font-bold text-orange-600">${formatInteger(qualificados)}</td>
        <td class="px-6 py-4 text-right text-orange-600 font-extrabold">${qualificados > 0 ? formatCurrency(cpaQualif) : '—'}</td>
      `;
    }
    
    tbody.appendChild(tr);
  });

  // Re-run lucide icons to build the fallback image icon if needed
  lucide.createIcons();

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

// 5. Render Instagram Tab
function renderInstagramTab() {
  try {
    const profile = dashboardData.ig_profile || {};
    const media = dashboardData.ig_media || [];
    const ms = dashboardData.meta_daily_spend || {};

    document.getElementById("ig-username").textContent = profile.username ? `@${profile.username}` : "@_";
  document.getElementById("ig-bio").textContent = profile.biography || "-";
  document.getElementById("ig-followers").textContent = formatInteger(profile.followers_count || 0);
  document.getElementById("ig-media-count").textContent = formatInteger(profile.media_count || 0);
  
  if (profile.profile_picture_url) {
    document.getElementById("ig-profile-img").src = profile.profile_picture_url;
  }

  // Spend for profile visits
  document.getElementById("ig-spend").textContent = formatCurrency(ms.profile_visit_spend || 0);

  const tableBody = document.getElementById("ig-media-table-body");
  if (!tableBody) return;
  
  tableBody.innerHTML = "";

  if (media.length === 0) {
    tableBody.innerHTML = `<tr><td colspan="10" class="text-center py-10 text-slate-400 font-bold uppercase tracking-wide text-xs">Nenhuma publicação encontrada</td></tr>`;
    const bestPostContainer = document.getElementById("ig-best-post-container");
    if(bestPostContainer) bestPostContainer.classList.add("hidden");
    return;
  }

  // Find best engaged post
  let bestPost = media[0];
  let maxEngagement = -1;
  media.forEach(m => {
    const engagement = (m.like_count || 0) + (m.comments_count || 0);
    if (engagement > maxEngagement) {
      maxEngagement = engagement;
      bestPost = m;
    }
  });

  const bestPostContainer = document.getElementById("ig-best-post-container");
  if (bestPostContainer && bestPost && maxEngagement > 0) {
    bestPostContainer.classList.remove("hidden");
    document.getElementById("ig-best-post-link").href = bestPost.permalink;
    
    let bestUrl = bestPost.media_url;
    if (bestPost.media_type === "VIDEO" && bestPost.thumbnail_url) {
      bestUrl = bestPost.thumbnail_url;
      document.getElementById("ig-best-post-video-icon").classList.remove("hidden");
    } else {
      document.getElementById("ig-best-post-video-icon").classList.add("hidden");
    }
    
    document.getElementById("ig-best-post-img").src = bestUrl;
    document.getElementById("ig-best-post-caption").textContent = bestPost.caption || "Publicação sem legenda.";
    document.getElementById("ig-best-post-likes").textContent = formatInteger(bestPost.like_count || 0);
    document.getElementById("ig-best-post-comments").textContent = formatInteger(bestPost.comments_count || 0);
  } else if(bestPostContainer) {
    bestPostContainer.classList.add("hidden");
  }

  media.forEach(m => {
    let mediaUrl = m.media_url;
    if (m.media_type === "VIDEO" && m.thumbnail_url) {
      mediaUrl = m.thumbnail_url;
    }

    const caption = m.caption ? m.caption.substring(0, 60) + "..." : "Publicação sem legenda";
    const typeLabel = m.media_type === "VIDEO" ? "Reels" : (m.media_type === "CAROUSEL_ALBUM" ? "Carrossel" : "Imagem");
    
    // Insights metrics (defaulting to 0 or - if not fetched yet)
    const views = m.plays || m.video_views || m.impressions || "-";
    const reach = m.reach || "-";
    const saved = m.saved || "-";
    const shares = m.shares || "-";
    
    const likes = m.like_count || 0;
    const comments = m.comments_count || 0;
    
    const interactions = m.total_interactions || (likes + comments + (parseInt(saved) || 0) + (parseInt(shares) || 0));
    
    let interactionRate = "-";
    if (reach !== "-" && parseInt(reach) > 0) {
      interactionRate = formatPercentage(interactions / parseInt(reach));
    }

    const tr = document.createElement("tr");
    tr.className = "hover:bg-slate-50/50 transition-colors border-b border-slate-100 last:border-b-0";
    tr.innerHTML = `
      <td class="px-6 py-4">
        <a href="${m.permalink}" target="_blank" class="flex items-center gap-4 group">
          <div class="w-12 h-12 rounded-lg overflow-hidden bg-slate-100 flex-shrink-0 relative">
            <img src="${mediaUrl}" class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300">
            ${m.media_type === 'VIDEO' ? `<div class="absolute inset-0 flex items-center justify-center bg-black/20"><i data-lucide="play" class="w-4 h-4 text-white fill-white"></i></div>` : ''}
          </div>
          <p class="text-xs font-semibold text-slate-700 w-48 whitespace-normal line-clamp-2">${caption}</p>
        </a>
      </td>
      <td class="px-6 py-4 font-medium text-slate-600">${typeLabel}</td>
      <td class="px-6 py-4 text-right font-semibold">${views !== "-" ? formatInteger(views) : "-"}</td>
      <td class="px-6 py-4 text-right font-semibold text-blue-600">${reach !== "-" ? formatInteger(reach) : "-"}</td>
      <td class="px-6 py-4 text-right font-semibold">${formatInteger(interactions)}</td>
      <td class="px-6 py-4 text-right font-semibold text-emerald-600">${interactionRate}</td>
      <td class="px-6 py-4 text-right font-semibold text-slate-700">${formatInteger(likes)}</td>
      <td class="px-6 py-4 text-right font-semibold text-slate-700">${formatInteger(comments)}</td>
      <td class="px-6 py-4 text-right font-semibold text-slate-700">${saved !== "-" ? formatInteger(saved) : "-"}</td>
      <td class="px-6 py-4 text-right font-semibold text-slate-700">${shares !== "-" ? formatInteger(shares) : "-"}</td>
    `;
    tableBody.appendChild(tr);
  });
  
  lucide.createIcons();
  } catch (error) {
    console.error("Error in renderInstagramTab:", error);
    alert("Erro na aba Instagram: " + error.message + "\nLinha: " + error.stack);
  }
}
