/** @odoo-module **/

import { titleService } from "@web/core/browser/title_service";
import { patch } from "@web/core/utils/patch";

patch(titleService, {
    start() {
        const service = super.start(...arguments);
        const setParts = service.setParts.bind(service);
        service.setParts = (parts) => setParts({ zopenerp: "Avea", ...parts });
        service.setParts({});
        return service;
    },
});
