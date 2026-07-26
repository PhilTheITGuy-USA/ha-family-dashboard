// Family Dashboard - custom Lovelace DASHBOARD STRATEGY.
//
// WHY THIS EXISTS (not a stylistic choice - a real, live-confirmed bug fix): this integration
// used to generate one static dashboard config server-side (Python), containing every viewer
// bucket's views (Kiosk + one per HA-user-linked roster member) in a single flat list, with
// each view's `visibility` field meant to hide the wrong ones from the wrong viewer. That
// worked for view CONTENT (loading a specific view path always showed the right, correctly
// scoped cards), but HA's native per-view tab strip does NOT consult `visibility` at all - it
// lists every non-subview view in the dashboard's stored config unconditionally, for every
// viewer, admin or not. Live-verified with a real account (`gerald`, non-admin, fresh
// incognito session, no other login): his own Calendar view loaded with correctly-scoped
// content, but the native tab strip showed BOTH his own tabs AND another linked member's
// tabs stacked together ("Calendar Lists Chores Calendar Lists Chores Settings Settings").
//
// A dashboard STRATEGY fixes this structurally instead of by filtering: it runs client-side,
// per viewer, with real access to `hass`/`hass.user`, and generates the `views` array HA
// actually renders. If a viewer's browser is only ever HANDED their own bucket's views in the
// first place, there is nothing left for the tab strip to duplicate - no visibility-list
// bookkeeping required. This also makes the earlier "which view loads by default" bug (HA's
// bare-dashboard-URL default view selection also ignores `visibility`, always uses views[0])
// resolve itself for free: views[0] of a viewer's own FILTERED list is naturally their own
// Calendar tab, so the separate JS-redirect "router view" this integration used as a
// workaround for that specific bug is no longer needed and has been removed.
//
// All of this integration's actual card/view-content generation stays exactly as it was
// (Python-side, in dashboard/registry.py) - this file's only job is choosing WHICH of those
// already-fully-built views to hand to HA for the current viewer.
class FamilyDashboardStrategy {
  static async generateDashboard({ config, hass }) {
    const strategyConfig = (config && config.strategy) || {};
    const allViews = strategyConfig.views || [];
    const userBucketMap = strategyConfig.user_bucket_map || {};
    const kioskKey = strategyConfig.kiosk_key || "kiosk";

    const userId = hass && hass.user && hass.user.id;
    const bucket = (userId && userBucketMap[userId]) || kioskKey;
    const suffix = "-" + bucket;

    const views = allViews.filter(
      (view) => typeof view.path === "string" && view.path.endsWith(suffix)
    );

    // A dashboard strategy's return value becomes the ENTIRE resolved dashboard config, not
    // a patch merged onto the stored one - any key from the stored config this doesn't
    // explicitly forward (like `theme`) is silently dropped. Live-verified real bug, not
    // theoretical: registry.py sets `theme: "Family Dashboard"` at the top level of the
    // stored config, but this function only ever read/returned `title`/`views`, so the
    // "Family Dashboard" theme (the 'Ovo' font, every `card-mod-theme` CSS variable) has
    // never actually applied on ANY install since this strategy was introduced - completely
    // independent of whether card_mod itself is installed, since this is a dashboard-level
    // theme resolution issue, not a missing-resource one.
    return {
      title: strategyConfig.title || "Family Dashboard",
      theme: config && config.theme,
      views: views,
    };
  }
}

customElements.define("ll-strategy-dashboard-family-dashboard", FamilyDashboardStrategy);
