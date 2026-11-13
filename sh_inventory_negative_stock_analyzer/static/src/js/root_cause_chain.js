import { Component } from "@odoo/owl";

const ICON_BY_TYPE = {
    stock_before: "fa-cubes",
    stock_move: "fa-exchange",
    picking: "fa-truck",
    sale_order: "fa-shopping-cart",
    purchase_order: "fa-shopping-basket",
    production: "fa-cogs",
    inventory_adjustment: "fa-sliders",
    related_move: "fa-link",
    transfer: "fa-random",
    source: "fa-file-text-o",
};

export class RootCauseChain extends Component {
    static template = "sh_inventory_negative_stock_analyzer.RootCauseChain";
    static props = {
        nodes: { type: Array, optional: true },
        onOpenRecord: { type: Function, optional: true },
    };

    get nodes() {
        return this.props.nodes || [];
    }

    iconFor(node) {
        return ICON_BY_TYPE[node.type] || "fa-circle-o";
    }

    isClickable(node) {
        return Boolean(node.res_model && node.res_id);
    }

    onNodeClick(node) {
        if (!this.isClickable(node) || !this.props.onOpenRecord) {
            return;
        }
        this.props.onOpenRecord(node.res_model, node.res_id);
    }
}
