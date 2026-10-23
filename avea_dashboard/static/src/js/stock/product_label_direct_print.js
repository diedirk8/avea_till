/** @odoo-module **/

import { registry } from "@web/core/registry";
import { getReportUrl } from "@web/webclient/actions/reports/utils";
import { user } from "@web/core/user";

const DYMO_TEMPLATE_REPORT = "product.report_producttemplatelabel_dymo";

function printHtmlInHiddenFrame(url) {
    return new Promise((resolve, reject) => {
        const iframe = document.createElement("iframe");
        iframe.setAttribute("class", "o_avea_label_print_frame");
        iframe.style.cssText =
            "position:fixed;right:0;bottom:0;width:0;height:0;border:0;opacity:0;pointer-events:none;";
        iframe.src = url;

        const cleanup = () => {
            if (iframe.parentNode) {
                iframe.parentNode.removeChild(iframe);
            }
        };

        iframe.onload = () => {
            const frameWindow = iframe.contentWindow;
            if (!frameWindow) {
                cleanup();
                reject(new Error("Label print frame unavailable"));
                return;
            }
            // Allow barcode images and fonts to settle before the print dialog.
            window.setTimeout(() => {
                try {
                    frameWindow.focus();
                    frameWindow.print();
                } catch (error) {
                    cleanup();
                    reject(error);
                    return;
                }
                window.setTimeout(() => {
                    cleanup();
                    resolve();
                }, 1000);
            }, 400);
        };

        iframe.onerror = () => {
            cleanup();
            reject(new Error("Failed to load shelf label"));
        };

        document.body.appendChild(iframe);
    });
}

registry.category("ir.actions.report handlers").add(
    "avea_product_label_direct_print",
    async (action) => {
        if (!action.context?.avea_direct_label_print) {
            return false;
        }
        if (action.report_name !== DYMO_TEMPLATE_REPORT) {
            return false;
        }
        const downloadContext = { ...user.context };
        if (action.context) {
            Object.assign(downloadContext, action.context);
        }
        const htmlUrl = getReportUrl(action, "html", downloadContext);
        await printHtmlInHiddenFrame(htmlUrl);
        return true;
    }
);
