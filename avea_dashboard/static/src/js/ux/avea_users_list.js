/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class AveaUsersListController extends ListController {
    static template = "avea_till.AveaUsersList";

    setup() {
        super.setup();
        this.actionService = useService("action");
        this.orm = useService("orm");
    }

    get className() {
        const base = this.props.className || "";
        return `${base} o_avea_workspace o_avea_workspace--users`.trim();
    }

    async onClickNewUser() {
        const action = await this.orm.call("res.users", "action_avea_new_user", [], {});
        await this.actionService.doAction(action);
    }

    async createRecord() {
        return this.onClickNewUser();
    }
}

registry.category("views").add("avea_users_list", {
    ...listView,
    Controller: AveaUsersListController,
});
