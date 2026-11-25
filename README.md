# Community Microgrid Energy Forecasting

HCLTech BTech Learner Program · Embedded Systems & IoT · Vardan Malik · v1.0 (November 2026)

An IoT-based monitoring and 24-hour-ahead forecasting system for a solar-plus-storage community microgrid. Two ESP32 nodes measure PV, battery, load and weather, stream validated telemetry over MQTT (HiveMQ, TLS) into Node-RED and SQLite, and a Python engine forecasts PV generation and community load. A Streamlit app, a Node-RED dashboard and a Telegram bot present live status, forecasts, peak net-load alerts and battery-dispatch advice.

> **Data note.** All forecasting results in this repository come from a **software simulation on a synthetic dataset** (90 days, hourly, 120 kWp PV, ~60 kW average load, seed 42). They are not hardware measurements. Hardware bench tests (report Section 8.3) are pending and no hardware outcomes are claimed.

## Repository contents

| Path | Description |
| --- | --- |
| `app.py` | Streamlit dashboard: model comparison, date-selectable forecast vs actual, peak net-load alert (precision/recall), battery SoC simulation, dispatch advice, feature importance |
| `microgrid_core.py` | Synthetic data generator, features, models, dispatch simulation, alert metrics, and a Python mirror of the edge-side rules |
| `tests/test_microgrid.py` | 15 software tests (UT-01..UT-08, ST-01..ST-07 from report Section 8.2) |
| `requirements.txt` | Python dependencies |

Planned full-repository layout (firmware, Node-RED flow, docs) is described in report Section 6.1: `firmware/node_a`, `firmware/node_b`, `nodered/flows.json`, `forecast/`, `data/`, `docs/`.

## System architecture

1. **Edge:** Node A (INA219 PV, BH1750 light, DHT22, OLED) and Node B (two INA219 for battery and load, ADC cross-check, MOSFET load, buzzer, green/red LEDs). 1 Hz sampling, 10-sample moving average, one JSON message per 10 s.
2. **Transport:** MQTT over TLS (port 8883, QoS 1), HiveMQ broker, retained status topics with last-will. A local Mosquitto fallback is documented.
3. **Processing:** Node-RED validates schema and physical range, stores accepted readings in SQLite; the forecast engine (Pandas, NumPy, scikit-learn) runs hourly.
4. **Presentation:** Node-RED dashboard, Streamlit app, Telegram bot, local buzzer/LED alerts.

Edge rules: low-battery alert (SoC < 20 %), over-temperature (> 55 °C, load PWM forced to 0), stuck-sensor detection (30 zero-variance readings), reconnect with exponential back-off (1, 2, 4 … 30 s). Local alerts work with the network down.

### MQTT topics

| Topic | Direction | Payload |
| --- | --- | --- |
| `microgrid/nodeA/telemetry` | Node A → broker | `{node, ts, pv_v, pv_i, pv_w, lux, temp, hum}` |
| `microgrid/nodeB/telemetry` | Node B → broker | `{node, ts, batt_v, batt_i, soc, load_i, load_w}` |
| `microgrid/+/status` | Node → broker (retained, LWT) | online / offline, firmware version, uptime |
| `microgrid/forecast/hourly` | Engine → broker | `{ts, horizon, pv_kw[24], load_kw[24]}` |
| `microgrid/alerts` | Engine / Node-RED → broker | `{level, source, message, value}` |
| `microgrid/nodeB/cmd` | Broker → Node B | `{buzzer, led, load_pwm}` |

## Forecasting method

- **Features:** sin/cos of hour, day of week, weekend flag; target lags 24, 25, 48, 168 h and lagged 24 h rolling mean (every lag ≥ 24 h, so no leakage); forecast irradiance and temperature.
- **Models:** 24 h persistence baseline, Ridge regression (primary), Random Forest (200 trees), Gradient Boosting (300 trees, depth 3, learning rate 0.05).
- **Evaluation:** chronological split, first 72 days train, last 18 days (432 h) test; forecast weather = truth + noise (12 % irradiance, 1 °C temperature).
- **Dispatch simulation:** 200 kWh / 50 kW battery, 95 % one-way efficiency, 10 % minimum SoC, 50 % start; rule-based at 1 h resolution.

### Results reported in the project report (synthetic data)

| Model | PV MAE (kW) | Load MAE (kW) | Load nMAE |
| --- | --- | --- | --- |
| Persistence (t-24h) | 3.61 | 4.24 | 7.2 % |
| Ridge Regression | 1.67 | 2.70 | 4.6 % |
| Random Forest | 1.68 | 2.71 | 4.6 % |
| Gradient Boosting | 1.69 | 2.75 | 4.7 % |

Ridge cuts MAE by about 54 % (PV) and 36 % (load) versus persistence. The forecast-based peak net-load alert (> 40 kW) reached 95.4 % precision and 90.8 % recall. The dispatch study showed a modest storage gain (self-sufficiency 28.6 % → 29.9 %), so forecasts are most valuable for peak-aware alerts and load shifting.

The dashboard regenerates the synthetic dataset and computes its own metrics at run time. They are close to, but not identical with, the figures above, because the generator in `microgrid_core.py` is a re-implementation of the report's documented assumptions.

## Run locally

1. Install Python 3.10 or newer.
2. Clone this repository and open a terminal in the project folder.
3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Start the dashboard:

   ```bash
   streamlit run app.py
   ```

5. Open the URL printed by Streamlit (usually `http://localhost:8501`).

## Run the tests

```bash
pytest -q
```

Runs the 15 executed software tests from report Section 8.2 (payload validation, moving average, stuck-sensor detection, alert threshold, SoC estimate, dataset integrity, forecast sanity, and baseline/target checks).

## Hardware setup (summary)

- Two ESP32 DevKit v1 boards, low-voltage DC only: 6 V 6 W panel, 18650 Li-ion via TP4056 (with protection and a fuse on the battery lead), 10 Ω / 10 W resistive load driven by an IRLZ44N MOSFET. No mains wiring.
- I²C on GPIO21 (SDA) / GPIO22 (SCL), 4.7 kΩ pull-ups; INA219 at 0x40 (+0x41 on Node B), BH1750 0x23, SSD1306 0x3C. DHT22 on GPIO4, battery divider (30 k / 7.5 k) on GPIO34, MOSFET gate GPIO18 (1 kHz PWM), buzzer GPIO25, LEDs GPIO26/27.
- Estimated bill of materials: about ₹3,920 (indicative; confirm at purchase). Calibration and bench tests are in report Sections 8.3 and 8.4.

Flashing the nodes, importing the Node-RED flow and the demo video link will be added here when the firmware and `docs/` folder are committed (report Section 11 checklist).

## Security

TLS for broker traffic; per-node credentials and client IDs; secrets in a git-ignored `config.py` (template: `config.example.py`) or environment variables; Telegram token and chat ID from environment variables only; nothing hard-coded in source.

## Deploy on Streamlit Community Cloud

1. Push `app.py`, `microgrid_core.py`, `requirements.txt` and `README.md` to a GitHub repository.
2. Sign in to Streamlit Community Cloud and choose **Create app**.
3. Select the repository, branch, and `app.py` as the main file, then deploy.

## Limitations and future scope

- Results use synthetic data with a single 18-day test window and one seed (no confidence intervals); accuracy is likely optimistic versus real deployments.
- Prototype is laboratory scale (6 W panel, DC load); weather forecasts are emulated; no live weather API.
- Future work: replace synthetic data with measured data and re-compare models (including tree ensembles and quantile forecasts), live weather API, mains-rated metering (e.g. PZEM-004T v3) under qualified supervision, tariff-aware dispatch, edge inference with OTA updates, anomaly detection.

## Safety

The prototype is a low-voltage DC laboratory build. This dashboard is a software demonstration only; it does not control a battery, inverter, grid connection or power electronics.
