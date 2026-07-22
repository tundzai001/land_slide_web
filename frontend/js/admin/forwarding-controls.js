(() => {
class AdminForwardingControlsFeature extends window.AdminManager {
    // =========================================================================
    // iOS TOGGLE HANDLER (Forwarding Output params)
    // =========================================================================

    toggleForwardingWrap(eventOrWrap, wrapOrId, maybeCheckboxId) {
        const hasEvent = !!(maybeCheckboxId && eventOrWrap && typeof eventOrWrap === 'object');
        const event = hasEvent ? eventOrWrap : null;
        const wrapEl = hasEvent ? wrapOrId : eventOrWrap;
        const checkboxId = hasEvent ? maybeCheckboxId : wrapOrId;

        const checkbox = document.getElementById(checkboxId);
        if (!checkbox) return;

        if (event?.target?.closest('input')) {
            // Let native checkbox behavior run, then sync visual state.
            setTimeout(() => {
                wrapEl.classList.toggle('is-on', checkbox.checked);
            }, 0);
            return;
        }

        event?.preventDefault?.();
        checkbox.checked = !checkbox.checked;
        wrapEl.classList.toggle('is-on', checkbox.checked);
    }

    syncForwardingWrapStates() {
        const map = {
            'fwd-toggle-x': 'wrap-fwd-x',
            'fwd-toggle-y': 'wrap-fwd-y',
            'fwd-toggle-h': 'wrap-fwd-h',
            'fwd-toggle-dx': 'wrap-fwd-dx',
            'fwd-toggle-dy': 'wrap-fwd-dy',
            'fwd-toggle-dh': 'wrap-fwd-dh',
            'fwd-toggle-vdx': 'wrap-fwd-vdx',
            'fwd-toggle-vdy': 'wrap-fwd-vdy',
            'fwd-toggle-vdh': 'wrap-fwd-vdh',
        };
        for (const [cbId, wrapId] of Object.entries(map)) {
            const cb = document.getElementById(cbId);
            const wrap = document.getElementById(wrapId);
            if (cb && wrap) wrap.classList.toggle('is-on', cb.checked);
        }
    }

    toggleRtkForwardingSlide(animate = true) {
        const checkbox = document.getElementById('cfg-fwd-enabled');
        const content = document.getElementById('rtk-forwarding-content');
        if (!checkbox || !content) return;

        if (checkbox.checked) {
            content.style.display = 'block';
            if (animate) {
                content.style.maxHeight = '0px';
                content.style.opacity = '0';
                setTimeout(() => {
                    content.style.maxHeight = '600px';
                    content.style.opacity = '1';
                }, 10);
            } else {
                content.style.maxHeight = '600px';
                content.style.opacity = '1';
            }
        } else {
            if (animate) {
                content.style.maxHeight = '0px';
                content.style.opacity = '0';
                setTimeout(() => {
                    content.style.display = 'none';
                }, 300);
            } else {
                content.style.display = 'none';
            }
        }
    }


}
window.applyAdminFeature(AdminForwardingControlsFeature);
})();
