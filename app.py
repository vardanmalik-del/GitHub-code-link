"""Streamlit dashboard - Community Microgrid Energy Forecasting.

Demo mode: runs the report's pipeline on a reproducible SYNTHETIC dataset
(120 kWp PV, ~60 kW average load). It does not read ESP32 / MQTT / SQLite data.
"""
import numpy as np
import pandas as pd
import streamlit as st

import microgrid_core as core

st.set_page_config(page_title="Community Microgrid Energy Forecasting", layout="wide")


@st.cache_data
def load_data():
    return core.generate_data()


@st.cache_resource
def run_experiments(_df):
    out = {}
    for target in ("pv_kw", "load_kw"):
        out[target] = core.evaluate_target(_df, target)
    return out


st.title("Community Microgrid Energy Forecasting")
st.caption("IoT-based monitoring and 24-hour-ahead forecasting for a solar-plus-storage community microgrid")
st.info(
    "Demo mode: all values come from a reproducible synthetic dataset (90 days, hourly, seed 42). "
    "They are software-simulation results, not live ESP32 readings or hardware measurements."
)

data = load_data()
with st.spinner("Training models (Ridge, Random Forest, Gradient Boosting)..."):
    exp = run_experiments(data)

pv_res, pv_act, pv_pred, pv_models, pv_cols = exp["pv_kw"]
ld_res, ld_act, ld_pred, ld_models, ld_cols = exp["load_kw"]
PRIMARY = "Ridge Regression"

# ---- sidebar ---------------------------------------------------------------
st.sidebar.header("Settings")
threshold = st.sidebar.number_input("Peak net-load alert threshold (kW)", min_value=1.0, value=40.0, step=1.0)
test_days = sorted({d.date() for d in pv_act.index})
selected = st.sidebar.selectbox("Forecast date (test period)", test_days, index=0)
st.sidebar.markdown("### Dataset")
st.sidebar.write(f"Period: {data.index.min():%d %b %Y} – {data.index.max():%d %b %Y}")
st.sidebar.write(f"Hourly samples: {len(data):,} (train {core.TRAIN_DAYS} d / test {core.TEST_DAYS} d)")
st.sidebar.write(f"Primary model: {PRIMARY} (alpha=1.0)")
st.sidebar.markdown("### Battery (dispatch simulation)")
st.sidebar.write(f"{core.BATT_KWH:.0f} kWh / {core.BATT_KW:.0f} kW, {core.BATT_EFF:.0%} one-way efficiency, "
                 f"{core.BATT_MIN_SOC:.0%} min SoC, start {core.BATT_START_SOC:.0%}")

# ---- model comparison (Table 7.1) ------------------------------------------
st.subheader("Model comparison (last 18 days = 432 h)")
table = pd.concat({"PV": pv_res, "Load": ld_res}, axis=1)
table.columns = [f"{t} {m}" for t, m in table.columns]
st.dataframe(table.round(2), use_container_width=True)
gain_pv = 100 * (1 - pv_res.loc[PRIMARY, "MAE"] / pv_res.loc["Persistence (t-24h)", "MAE"])
gain_ld = 100 * (1 - ld_res.loc[PRIMARY, "MAE"] / ld_res.loc["Persistence (t-24h)", "MAE"])
m1, m2, m3, m4 = st.columns(4)
m1.metric("PV MAE (Ridge)", f"{pv_res.loc[PRIMARY, 'MAE']:.2f} kW", f"-{gain_pv:.0f}% vs persistence", delta_color="normal")
m2.metric("PV nMAE", f"{pv_res.loc[PRIMARY, 'nMAE %']:.1f} %")
m3.metric("Load MAE (Ridge)", f"{ld_res.loc[PRIMARY, 'MAE']:.2f} kW", f"-{gain_ld:.0f}% vs persistence", delta_color="normal")
m4.metric("Load nMAE", f"{ld_res.loc[PRIMARY, 'nMAE %']:.1f} %",
          "meets < 8 % target" if ld_res.loc[PRIMARY, "nMAE %"] < 8 else "above 8 % target", delta_color="off")

# ---- selected-day forecast ---------------------------------------------------
st.subheader(f"Day-ahead forecast vs actual – {selected}")
mask = np.array([d.date() == selected for d in pv_act.index])
day_idx = pv_act.index[mask]
left, right = st.columns(2)
with left:
    st.markdown("**PV generation (kW)**")
    st.line_chart(pd.DataFrame({
        "Actual": pv_act[day_idx],
        "Forecast (Ridge)": pv_pred[PRIMARY][day_idx],
        "Persistence": pv_pred["Persistence (t-24h)"][day_idx]}))
with right:
    st.markdown("**Community load (kW)**")
    st.line_chart(pd.DataFrame({
        "Actual": ld_act[day_idx],
        "Forecast (Ridge)": ld_pred[PRIMARY][day_idx],
        "Persistence": ld_pred["Persistence (t-24h)"][day_idx]}))

# ---- peak alert + dispatch advice ------------------------------------------
st.subheader("Peak net-load alert and dispatch advice")
actual_net = ld_act - pv_act
fc_net = ld_pred[PRIMARY] - pv_pred[PRIMARY]
stats = core.peak_alert_stats(actual_net, fc_net, threshold)
sim = core.simulate_dispatch(pv_act, ld_act, with_battery=True)
base = core.simulate_dispatch(pv_act, ld_act, with_battery=False)

a1, a2, a3 = st.columns(3)
a1.metric("Alert precision", f"{stats['precision']:.1f} %", "target ≥ 90 %", delta_color="off")
a2.metric("Alert recall", f"{stats['recall']:.1f} %", "target ≥ 85 %", delta_color="off")
a3.metric("TP / FP / FN", f"{stats['TP']} / {stats['FP']} / {stats['FN']}")

soc_at_day_start = float(sim["soc_pct"][day_idx[0]])
message, alert_on = core.dispatch_advice(fc_net[day_idx], soc_at_day_start, threshold)
(st.warning if alert_on else st.success)(message)

b1, b2 = st.columns(2)
with b1:
    st.markdown("**Net load: forecast vs actual (kW)**")
    nl = pd.DataFrame({"Actual net load": actual_net[day_idx], "Forecast net load": fc_net[day_idx]})
    nl["Threshold"] = threshold
    st.line_chart(nl)
with b2:
    st.markdown("**Simulated battery SoC (%) – whole test period**")
    st.line_chart(sim["soc_pct"].rename("Battery SoC (%)"))

d1, d2, d3, d4 = st.columns(4)
d1.metric("Grid import, no battery", f"{base['import_kwh']:,.0f} kWh")
d2.metric("Grid import, with battery", f"{sim['import_kwh']:,.0f} kWh")
d3.metric("Self-sufficiency, no battery", f"{base['self_sufficiency_pct']:.1f} %")
d4.metric("Self-sufficiency, with battery", f"{sim['self_sufficiency_pct']:.1f} %")
st.caption("PV supplies only ~30 % of this community's energy, so storage gain is modest; forecasts are most "
           "valuable for peak-aware alerts and load shifting. Rule-based, 1 h resolution; no inverter limits, "
           "tariffs or battery degradation.")

# ---- feature importance ------------------------------------------------------
st.subheader("Feature importance (Gradient Boosting)")
f1, f2 = st.columns(2)
for col, label, models, cols in ((f1, "PV model", pv_models, pv_cols), (f2, "Load model", ld_models, ld_cols)):
    imp = pd.Series(models["Gradient Boosting"].feature_importances_, index=cols).sort_values(ascending=False).head(6)
    with col:
        st.markdown(f"**{label} – top features**")
        st.bar_chart(imp)

# ---- limitations + data ------------------------------------------------------
st.caption(
    "Limitations: synthetic data share the generator's structure with the features, so accuracy is optimistic; "
    "a single 18-day test window and one seed are used (no confidence intervals); weather forecasts are emulated. "
    "Hardware bench tests (report Section 8.3) are pending. Replace the generator with validated SQLite/CSV "
    "telemetry before operational use."
)
with st.expander("View sample dataset"):
    st.dataframe(data.tail(24), use_container_width=True)
