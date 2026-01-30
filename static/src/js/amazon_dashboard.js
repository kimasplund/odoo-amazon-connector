/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart, onMounted, onWillUnmount } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { formatCurrency } from "@web/core/currency";
import { loadJS } from "@web/core/assets";

/**
 * Amazon Smart Dashboard - OWL 2 Component for Odoo 18
 * 
 * A comprehensive, intelligent dashboard with:
 * - Real-time KPI cards with trend indicators
 * - Interactive charts (Revenue, Marketplace, Fulfillment)
 * - Priority alerts with action buttons
 * - Smart recommendations
 * - Auto-refresh capability
 */
class AmazonDashboard extends Component {
    static template = "amazon_connector.Dashboard";
    
    setup() {
        this.rpc = useService("rpc");
        this.action = useService("action");
        this.notification = useService("notification");
        this.user = useService("user");
        
        // Component state
        this.state = useState({
            loading: true,
            error: null,
            
            // Filters
            selectedAccountId: null,
            selectedPeriod: 'month',
            dateFrom: null,
            dateTo: null,
            
            // KPI Data
            kpis: {
                revenue_today: 0,
                revenue_week: 0,
                revenue_month: 0,
                revenue_trend: 'stable',
                revenue_trend_pct: 0,
                orders_today: 0,
                orders_week: 0,
                orders_month: 0,
                orders_pending_shipment: 0,
                orders_trend: 'stable',
                orders_trend_pct: 0,
                buy_box_percentage: 0,
                inventory_health_score: 100,
                stockout_risk_count: 0,
                low_stock_count: 0,
                units_sold_today: 0,
                units_sold_week: 0,
                average_order_value: 0,
                returns_rate: 0,
            },
            
            // Alerts & Recommendations
            alerts: [],
            recommendations: [],
            
            // Top/Bottom products
            topProducts: [],
            underperformers: [],
            
            // Accounts
            accounts: [],
            
            // Auto-refresh
            autoRefresh: false,
            lastRefresh: null,
        });
        
        // Chart instances
        this.charts = {
            revenue: null,
            marketplace: null,
            fulfillment: null,
        };
        
        // Auto-refresh interval
        this.refreshInterval = null;
        
        // Lifecycle hooks
        onWillStart(async () => {
            await loadJS("/web/static/lib/Chart/Chart.js");
            await this._loadAccounts();
        });
        
        onMounted(() => {
            this._loadDashboardData();
        });
        
        onWillUnmount(() => {
            this._stopAutoRefresh();
            this._destroyCharts();
        });
    }
    
    // =========================================================================
    // DATA LOADING
    // =========================================================================
    
    async _loadAccounts() {
        try {
            const result = await this.rpc("/web/dataset/call_kw/amazon.account/search_read", {
                model: "amazon.account",
                method: "search_read",
                args: [[["active", "=", true]]],
                kwargs: {
                    fields: ["id", "name", "seller_id"],
                },
            });
            this.state.accounts = result || [];
        } catch (error) {
            console.error("Failed to load accounts:", error);
        }
    }
    
    async _loadDashboardData() {
        this.state.loading = true;
        this.state.error = null;
        
        try {
            // Load all data in parallel
            await Promise.all([
                this._loadKPIs(),
                this._loadAlerts(),
                this._loadRecommendations(),
                this._loadTopProducts(),
                this._loadCharts(),
            ]);
            
            this.state.lastRefresh = new Date();
        } catch (error) {
            console.error("Dashboard load error:", error);
            this.state.error = error.message || "Failed to load dashboard data";
        } finally {
            this.state.loading = false;
        }
    }
    
    async _loadKPIs() {
        const result = await this.rpc("/amazon/dashboard/kpis", {
            account_id: this.state.selectedAccountId,
            date_from: this.state.dateFrom,
            date_to: this.state.dateTo,
        });
        
        if (result.success) {
            Object.assign(this.state.kpis, result.data);
        }
    }
    
    async _loadAlerts() {
        const result = await this.rpc("/amazon/dashboard/alerts", {
            account_id: this.state.selectedAccountId,
            limit: 10,
        });
        
        if (result.success) {
            this.state.alerts = result.data || [];
        }
    }
    
    async _loadRecommendations() {
        const result = await this.rpc("/amazon/dashboard/recommendations", {
            account_id: this.state.selectedAccountId,
            limit: 5,
        });
        
        if (result.success) {
            this.state.recommendations = result.data || [];
        }
    }
    
    async _loadTopProducts() {
        const [topResult, underResult] = await Promise.all([
            this.rpc("/amazon/dashboard/top-products", {
                account_id: this.state.selectedAccountId,
                limit: 5,
            }),
            this.rpc("/amazon/dashboard/underperformers", {
                account_id: this.state.selectedAccountId,
                limit: 5,
            }),
        ]);
        
        if (topResult.success) {
            this.state.topProducts = topResult.data || [];
        }
        if (underResult.success) {
            this.state.underperformers = underResult.data || [];
        }
    }
    
    async _loadCharts() {
        // Small delay to ensure DOM is ready
        await new Promise(resolve => setTimeout(resolve, 100));
        
        await Promise.all([
            this._loadRevenueChart(),
            this._loadMarketplaceChart(),
            this._loadFulfillmentChart(),
        ]);
    }
    
    async _loadRevenueChart() {
        const result = await this.rpc("/amazon/dashboard/charts/revenue", {
            account_id: this.state.selectedAccountId,
            period: this.state.selectedPeriod,
        });
        
        if (result.success && result.data) {
            this._renderRevenueChart(result.data);
        }
    }
    
    async _loadMarketplaceChart() {
        const result = await this.rpc("/amazon/dashboard/charts/marketplace", {
            account_id: this.state.selectedAccountId,
        });
        
        if (result.success && result.data) {
            this._renderMarketplaceChart(result.data);
        }
    }
    
    async _loadFulfillmentChart() {
        const result = await this.rpc("/amazon/dashboard/charts/fulfillment", {
            account_id: this.state.selectedAccountId,
        });
        
        if (result.success && result.data) {
            this._renderFulfillmentChart(result.data);
        }
    }
    
    // =========================================================================
    // CHART RENDERING
    // =========================================================================
    
    _renderRevenueChart(data) {
        const canvas = document.getElementById('amazon_revenue_chart');
        if (!canvas) return;
        
        if (this.charts.revenue) {
            this.charts.revenue.destroy();
        }
        
        const ctx = canvas.getContext('2d');
        this.charts.revenue = new Chart(ctx, {
            type: 'line',
            data: {
                labels: this._formatChartLabels(data.labels),
                datasets: data.datasets.map(ds => ({
                    ...ds,
                    tension: 0.4,
                    pointRadius: 3,
                    pointHoverRadius: 6,
                })),
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (context) => `€${context.parsed.y.toLocaleString()}`,
                        },
                    },
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            callback: (value) => `€${value.toLocaleString()}`,
                        },
                    },
                    x: {
                        grid: { display: false },
                    },
                },
            },
        });
    }
    
    _renderMarketplaceChart(data) {
        const canvas = document.getElementById('amazon_marketplace_chart');
        if (!canvas) return;
        
        if (this.charts.marketplace) {
            this.charts.marketplace.destroy();
        }
        
        const ctx = canvas.getContext('2d');
        this.charts.marketplace = new Chart(ctx, {
            type: 'doughnut',
            data: data,
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: { boxWidth: 12, padding: 15 },
                    },
                    tooltip: {
                        callbacks: {
                            label: (context) => {
                                const value = context.parsed;
                                const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                const pct = ((value / total) * 100).toFixed(1);
                                return `${context.label}: €${value.toLocaleString()} (${pct}%)`;
                            },
                        },
                    },
                },
                cutout: '60%',
            },
        });
    }
    
    _renderFulfillmentChart(data) {
        const canvas = document.getElementById('amazon_fulfillment_chart');
        if (!canvas) return;
        
        if (this.charts.fulfillment) {
            this.charts.fulfillment.destroy();
        }
        
        const ctx = canvas.getContext('2d');
        this.charts.fulfillment = new Chart(ctx, {
            type: 'doughnut',
            data: data,
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: { boxWidth: 12, padding: 15 },
                    },
                    tooltip: {
                        callbacks: {
                            label: (context) => {
                                const value = context.parsed;
                                const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                const pct = total > 0 ? ((value / total) * 100).toFixed(1) : 0;
                                return `${context.label}: €${value.toLocaleString()} (${pct}%)`;
                            },
                        },
                    },
                },
                cutout: '65%',
            },
        });
    }
    
    _formatChartLabels(labels) {
        return labels.map(label => {
            if (label.includes('-W')) {
                return label.replace(/^\d{4}-W/, 'Week ');
            }
            if (label.match(/^\d{4}-\d{2}$/)) {
                const [year, month] = label.split('-');
                const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                               'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
                return months[parseInt(month) - 1];
            }
            if (label.match(/^\d{4}-\d{2}-\d{2}$/)) {
                const date = new Date(label);
                return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
            }
            return label;
        });
    }
    
    _destroyCharts() {
        Object.values(this.charts).forEach(chart => {
            if (chart) chart.destroy();
        });
    }
    
    // =========================================================================
    // EVENT HANDLERS
    // =========================================================================
    
    onAccountChange(ev) {
        const value = ev.target.value;
        this.state.selectedAccountId = value ? parseInt(value) : null;
        this._loadDashboardData();
    }
    
    onPeriodChange(period) {
        this.state.selectedPeriod = period;
        this._loadDashboardData();
    }
    
    onRefresh() {
        this._loadDashboardData();
        this.notification.add(_t("Dashboard refreshed"), { type: "success" });
    }
    
    onToggleAutoRefresh() {
        this.state.autoRefresh = !this.state.autoRefresh;
        
        if (this.state.autoRefresh) {
            this._startAutoRefresh();
            this.notification.add(_t("Auto-refresh enabled (every 5 minutes)"), { type: "info" });
        } else {
            this._stopAutoRefresh();
            this.notification.add(_t("Auto-refresh disabled"), { type: "info" });
        }
    }
    
    _startAutoRefresh() {
        this._stopAutoRefresh();
        this.refreshInterval = setInterval(() => {
            this._loadDashboardData();
        }, 5 * 60 * 1000); // 5 minutes
    }
    
    _stopAutoRefresh() {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
            this.refreshInterval = null;
        }
    }
    
    // =========================================================================
    // ALERT ACTIONS
    // =========================================================================
    
    onAlertAction(alert) {
        switch (alert.action_type) {
            case 'open_account':
                this._openAccount(alert.action_data.account_id);
                break;
            case 'view_inventory':
                this._viewInventory(alert.action_data.filter);
                break;
            case 'view_orders':
                this._viewOrders(alert.action_data.filter);
                break;
            case 'view_listings':
                this._viewListings(alert.action_data.filter);
                break;
            case 'view_returns':
                this._viewReturns(alert.action_data.filter);
                break;
            default:
                console.log("Unknown action:", alert.action_type);
        }
    }
    
    onDismissAlert(alertId) {
        this.state.alerts = this.state.alerts.filter(a => a.id !== alertId);
    }
    
    // =========================================================================
    // RECOMMENDATION ACTIONS
    // =========================================================================
    
    onRecommendationAction(rec) {
        switch (rec.action_type) {
            case 'create_fba_shipment':
                this._createFBAShipment();
                break;
            case 'view_listings':
                this._viewListings(rec.filter || 'all');
                break;
            case 'view_fba_shipments':
                this._viewFBAShipments();
                break;
            default:
                console.log("Unknown recommendation action:", rec.action_type);
        }
    }
    
    // =========================================================================
    // QUICK ACTIONS
    // =========================================================================
    
    async onSyncOrders() {
        this.notification.add(_t("Syncing orders..."), { type: "info" });
        try {
            await this.rpc("/amazon/sync/trigger", {
                account_id: this.state.selectedAccountId,
                sync_type: 'orders',
            });
            this.notification.add(_t("Order sync completed"), { type: "success" });
            this._loadDashboardData();
        } catch (error) {
            this.notification.add(_t("Sync failed: ") + error.message, { type: "danger" });
        }
    }
    
    async onSyncInventory() {
        this.notification.add(_t("Syncing inventory..."), { type: "info" });
        try {
            await this.rpc("/amazon/sync/trigger", {
                account_id: this.state.selectedAccountId,
                sync_type: 'inventory',
            });
            this.notification.add(_t("Inventory sync completed"), { type: "success" });
            this._loadDashboardData();
        } catch (error) {
            this.notification.add(_t("Sync failed: ") + error.message, { type: "danger" });
        }
    }
    
    // =========================================================================
    // NAVIGATION ACTIONS
    // =========================================================================
    
    _openAccount(accountId) {
        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: 'amazon.account',
            res_id: accountId,
            views: [[false, 'form']],
            target: 'current',
        });
    }
    
    _viewInventory(filter) {
        let domain = [];
        if (filter === 'stockout') {
            domain = [['quantity_available', '=', 0]];
        } else if (filter === 'low_stock') {
            domain = [['quantity_available', '>', 0], ['quantity_available', '<=', 10]];
        }
        
        if (this.state.selectedAccountId) {
            domain.push(['account_id', '=', this.state.selectedAccountId]);
        }
        
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: _t('FBA Inventory'),
            res_model: 'amazon.fba.inventory',
            views: [[false, 'tree'], [false, 'form']],
            domain: domain,
            target: 'current',
        });
    }
    
    _viewOrders(filter) {
        let domain = [];
        if (filter === 'pending_ship' || filter === 'urgent_ship') {
            domain = [['order_status', '=', 'unshipped'], ['fulfillment_channel', '=', 'MFN']];
        }
        
        if (this.state.selectedAccountId) {
            domain.push(['account_id', '=', this.state.selectedAccountId]);
        }
        
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: _t('Amazon Orders'),
            res_model: 'amazon.order',
            views: [[false, 'tree'], [false, 'kanban'], [false, 'form']],
            domain: domain,
            target: 'current',
        });
    }
    
    _viewListings(filter) {
        let domain = [];
        if (filter === 'no_buybox') {
            domain = [['state', '=', 'active'], ['is_buybox_winner', '=', false]];
        } else if (filter === 'suppressed') {
            domain = [['state', '=', 'suppressed']];
        } else if (filter === 'issues') {
            domain = [['listing_issues', '!=', false]];
        }
        
        if (this.state.selectedAccountId) {
            domain.push(['account_id', '=', this.state.selectedAccountId]);
        }
        
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: _t('Amazon Listings'),
            res_model: 'amazon.product.listing',
            views: [[false, 'tree'], [false, 'form']],
            domain: domain,
            target: 'current',
        });
    }
    
    _viewReturns(filter) {
        let domain = [];
        if (filter === 'pending') {
            domain = [['state', '=', 'pending']];
        }
        
        if (this.state.selectedAccountId) {
            domain.push(['account_id', '=', this.state.selectedAccountId]);
        }
        
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: _t('Amazon Returns'),
            res_model: 'amazon.return',
            views: [[false, 'tree'], [false, 'form']],
            domain: domain,
            target: 'current',
        });
    }
    
    _viewFBAShipments() {
        let domain = [];
        if (this.state.selectedAccountId) {
            domain.push(['account_id', '=', this.state.selectedAccountId]);
        }
        
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: _t('FBA Shipments'),
            res_model: 'amazon.fba.shipment',
            views: [[false, 'tree'], [false, 'form']],
            domain: domain,
            target: 'current',
        });
    }
    
    _createFBAShipment() {
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: _t('Create FBA Shipment'),
            res_model: 'amazon.fba.shipment',
            views: [[false, 'form']],
            target: 'current',
            context: {
                default_account_id: this.state.selectedAccountId,
            },
        });
    }
    
    // =========================================================================
    // FORMATTING HELPERS
    // =========================================================================
    
    formatCurrency(value) {
        return `€${(value || 0).toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    }
    
    formatNumber(value) {
        return (value || 0).toLocaleString();
    }
    
    formatPercentage(value) {
        return `${(value || 0).toFixed(1)}%`;
    }
    
    getTrendClass(trend) {
        if (trend === 'up') return 'text-success';
        if (trend === 'down') return 'text-danger';
        return 'text-muted';
    }
    
    getTrendIcon(trend) {
        if (trend === 'up') return 'fa-arrow-up';
        if (trend === 'down') return 'fa-arrow-down';
        return 'fa-minus';
    }
    
    getSeverityClass(severity) {
        switch (severity) {
            case 'critical': return 'danger';
            case 'warning': return 'warning';
            case 'info': return 'info';
            default: return 'secondary';
        }
    }
    
    getPriorityClass(priority) {
        switch (priority) {
            case 'high': return 'danger';
            case 'medium': return 'warning';
            case 'low': return 'info';
            default: return 'secondary';
        }
    }
    
    getHealthScoreClass(score) {
        if (score >= 80) return 'success';
        if (score >= 60) return 'warning';
        return 'danger';
    }
    
    getHealthScoreLabel(score) {
        if (score >= 80) return _t('Excellent');
        if (score >= 60) return _t('Good');
        if (score >= 40) return _t('Fair');
        return _t('Poor');
    }
    
    formatLastRefresh() {
        if (!this.state.lastRefresh) return '';
        return this.state.lastRefresh.toLocaleTimeString();
    }
}

// Register the component
registry.category("actions").add("amazon_dashboard", AmazonDashboard);

export default AmazonDashboard;
