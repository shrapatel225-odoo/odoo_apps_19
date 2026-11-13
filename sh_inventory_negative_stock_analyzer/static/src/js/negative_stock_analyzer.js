import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { deserializeDateTime, formatDateTime } from "@web/core/l10n/dates";
import { localization } from "@web/core/l10n/localization";
import { RootCauseChain } from "./root_cause_chain";

const MODEL = "inventory.negative.stock.incident";

export class NegativeStockAnalyzer extends Component {
    static template = "sh_inventory_negative_stock_analyzer.Dashboard";
    static components = { RootCauseChain };
    static props = {
        "*": true,
    };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({
            loading: true,
            scanning: false,
            options: {
                companies: [],
                warehouses: [],
                locations: [],
                categories: [],
                root_causes: [],
                states: [],
            },
            filters: {
                company_id: false,
                warehouse_id: false,
                location_id: false,
                categ_id: false,
                product_search: "",
                root_cause_type: "",
                state: "",
                stock_scope: "",
                date_from: "",
                date_to: "",
            },
            products: [],
            selectedSummaryId: false,
            productAnalysis: null,
            selectedIncidentId: false,
            incidentAnalysis: null,
        });

        onWillStart(async () => {
            await this.loadOptions();
            await this.loadProducts();
            const params = this.props.action?.params || {};
            if (params.summary_id) {
                await this.selectProduct(params.summary_id);
            }
        });
    }

    get filteredLocations() {
        const warehouseId = this.state.filters.warehouse_id;
        if (!warehouseId) {
            return this.state.options.locations;
        }
        return this.state.options.locations.filter(
            (location) => !location.warehouse_id || location.warehouse_id === warehouseId
        );
    }

    formatQty(value) {
        if (value === undefined || value === null || value === false) {
            return "0";
        }
        return Number(value).toLocaleString(undefined, { maximumFractionDigits: 4 });
    }

    formatDate(value) {
        if (!value) {
            return "";
        }
        try {
            // Odoo 19 user time formats include seconds; keep the dashboard compact.
            const timeFormat = (localization.timeFormat || "HH:mm").replace(/:ss/, "");
            return formatDateTime(deserializeDateTime(value), {
                format: `${localization.dateFormat} ${timeFormat}`,
            });
        } catch {
            return value;
        }
    }

    incidentLabel(incident) {
        const number = String(incident.incident_number || 0).padStart(3, "0");
        return `Incident #${number}`;
    }

    statusClass(status) {
        return {
            active: "text-bg-danger",
            corrected: "text-bg-success",
            investigating: "text-bg-warning",
            unknown: "text-bg-secondary",
        }[status] || "text-bg-secondary";
    }

    qtyClass(qty) {
        return qty < 0 ? "text-danger fw-bold" : "text-success";
    }

    async loadOptions() {
        this.state.options = await this.orm.call(MODEL, "get_filter_options", []);
        this.state.filters.company_id = this.state.options.current_company_id || false;
    }

    buildFilters() {
        const filters = { refresh_current: true };
        const values = this.state.filters;
        if (values.company_id) {
            filters.company_id = values.company_id;
        }
        if (values.warehouse_id) {
            filters.warehouse_id = values.warehouse_id;
        }
        if (values.location_id) {
            filters.location_id = values.location_id;
        }
        if (values.categ_id) {
            filters.categ_id = values.categ_id;
        }
        if (values.product_search) {
            filters.search = values.product_search;
        }
        if (values.root_cause_type) {
            filters.root_cause_type = values.root_cause_type;
        }
        if (values.state) {
            filters.state = values.state;
        }
        if (values.stock_scope) {
            filters.stock_scope = values.stock_scope;
        }
        if (values.date_from) {
            filters.date_from = values.date_from;
        }
        if (values.date_to) {
            filters.date_to = values.date_to;
        }
        return filters;
    }

    async loadProducts() {
        this.state.loading = true;
        try {
            this.state.products = await this.orm.call(MODEL, "get_dashboard_products", [
                this.buildFilters(),
            ]);
        } finally {
            this.state.loading = false;
        }
    }

    async onFilterChange() {
        await this.loadProducts();
    }

    async onSearchSubmit(ev) {
        ev.preventDefault();
        await this.loadProducts();
    }

    async scan(includeHistorical = false) {
        this.state.scanning = true;
        try {
            const result = await this.orm.call(MODEL, "scan_negative_stock", [
                { ...this.buildFilters(), include_historical: includeHistorical },
            ]);
            this.state.products = result.products || [];
            this.notification.add(
                _t("Analyzed %s product/location pairs. Created %s, updated %s incidents.", result.analyzed, result.created, result.updated),
                { type: "success" }
            );
            if (this.state.selectedSummaryId) {
                await this.selectProduct(this.state.selectedSummaryId);
            }
        } finally {
            this.state.scanning = false;
        }
    }

    async selectProduct(summaryId) {
        this.state.selectedSummaryId = summaryId;
        this.state.incidentAnalysis = null;
        this.state.selectedIncidentId = false;
        this.state.productAnalysis = await this.orm.call(MODEL, "get_product_analysis", [summaryId]);
        const selectedGroup = (this.state.productAnalysis.locations || []).find(
            (group) => group.is_selected
        );
        const firstIncident = selectedGroup?.incidents?.[selectedGroup.incidents.length - 1]
            || selectedGroup?.incidents?.[0];
        if (firstIncident) {
            await this.selectIncident(firstIncident.id);
        }
    }

    async selectIncident(incidentId) {
        this.state.selectedIncidentId = incidentId;
        this.state.incidentAnalysis = await this.orm.call(MODEL, "get_incident_analysis", [
            incidentId,
        ]);
    }

    async openRecord(resModel, resId) {
        if (!resModel || !resId) {
            return;
        }
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: resModel,
            res_id: resId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    async openFullHistory() {
        const action = this.state.incidentAnalysis?.history_action;
        if (action) {
            await this.action.doAction(action);
        }
    }

    async openIncidentList() {
        await this.action.doAction("sh_inventory_negative_stock_analyzer.action_inventory_negative_stock_incident");
    }

    onOpenChainRecord(resModel, resId) {
        this.openRecord(resModel, resId);
    }
}

registry.category("actions").add(
    "sh_inventory_negative_stock_analyzer.dashboard",
    NegativeStockAnalyzer
);
