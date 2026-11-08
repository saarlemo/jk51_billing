class JK51BillingPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode: "open"});
    this.loaded = false;
  }
  set hass(value) {
    this._hass = value;
    if (!this.loaded) { this.loaded = true; this.load(); }
  }
  async load() {
    try { this.config = await this._hass.callWS({type: "jk51_billing/config/get"}); this.render(); }
    catch (e) { this.shadowRoot.textContent = `Unable to load settings: ${e.message}`; }
  }
  render() {
    const labels = [
      ["energy_entity", "Energy statistics sensor", "entity"],
      ["nordpool_entity", "Spot price statistics sensor (EUR/kWh)", "entity"],
      ["language", "Email template language", "language"],
      ["day_transfer_eur_per_kwh", "Day transfer (€/kWh)", "number"],
      ["night_transfer_eur_per_kwh", "Night transfer (€/kWh)", "number"],
      ["electricity_margin_eur_per_kwh", "Electricity margin (€/kWh)", "number"],
      ["monthly_fee_eur", "Monthly fee (€)", "number"],
      ["monthly_peak_eur_per_kw", "Monthly peak fee (€/kW)", "number"],
      ["spot_vat_multiplier", "Spot VAT multiplier", "number"],
      ["gmail_user", "Gmail address", "email"],
      ["gmail_app_password", "Gmail app password", "password"],
      ["ha_url", "Home Assistant URL", "url"],
      ["ha_token", "Home Assistant long-lived token", "password"],
    ];
    this.shadowRoot.innerHTML = `<style>
      :host{display:block;color:var(--primary-text-color);background:var(--primary-background-color);min-height:100%;font-family:var(--paper-font-body1_-_font-family, sans-serif)}
      header{padding:16px 24px;background:var(--app-header-background-color,var(--primary-color));color:var(--app-header-text-color,white);display:flex;align-items:center;gap:16px;font-size:20px}
      header button{background:none;border:0;color:inherit;font-size:24px;cursor:pointer}
      main{max-width:720px;margin:auto;padding:24px} form{display:grid;gap:16px} section{display:grid;gap:16px;margin-top:12px} section h2{margin:0;font-size:20px;font-weight:600} .test-row{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);align-items:end;gap:12px} .test-row label,.test-row input,.test-row select,.test-row button{min-width:0} .test-row button{white-space:normal;overflow-wrap:anywhere} @media(max-width:420px){main{padding:16px}.test-row{gap:8px}} .periods{display:flex;gap:16px;flex-wrap:wrap}.periods label{display:flex;align-items:center;gap:5px}.periods input{width:auto} label{display:grid;gap:6px} input,select{box-sizing:border-box;width:100%;padding:10px;background:var(--card-background-color);color:var(--primary-text-color);border:1px solid var(--divider-color);border-radius:4px;font-size:16px} button.save,button.send-test{padding:12px;background:var(--primary-color);color:var(--text-primary-color,white);border:0;border-radius:4px;cursor:pointer} .notice{color:var(--secondary-text-color)}
    </style><header><button type="button" aria-label="Open sidebar">☰</button>Electricity billing</header><main><form></form><p role="status"></p></main>`;
    this.shadowRoot.querySelector("header button").onclick = () => this.dispatchEvent(new CustomEvent("hass-toggle-menu", {bubbles:true, composed:true}));
    const form = this.shadowRoot.querySelector("form");
    for (const [name, label, type] of labels) {
      const wrapper = document.createElement("label");
      const title = document.createElement("span"); title.textContent = label; wrapper.append(title);
      const input = document.createElement(type === "entity" || type === "language" ? "select" : "input");
      input.name = name;
      if (type === "entity") {
        const empty = document.createElement("option"); empty.value = ""; empty.textContent = "Select a sensor"; input.append(empty);
        const entities = Object.keys(this._hass.states).filter(id => id.startsWith("sensor.")).sort();
        const current = this.config[name]; if (current && !entities.includes(current)) entities.unshift(current);
        for (const id of entities) { const option = document.createElement("option"); option.value=id; option.textContent=id; input.append(option); }
      } else if (type === "language") {
        for (const [value, text] of [["fi", "Suomi"], ["en", "English"]]) { const option = document.createElement("option"); option.value=value; option.textContent=text; input.append(option); }
      } else { input.type=type; if (type === "number") { input.min="0"; input.step="any"; } if (type === "password") input.autocomplete="new-password"; }
      const value = this.config[name];
      if (type !== "password") input.value = Array.isArray(value) ? value.join(", ") : (value ?? (name === "language" ? "fi" : ""));
      if (type === "password" && (this.config.configured_secrets || []).includes(name)) input.placeholder = "Saved; leave blank to keep";
      wrapper.append(input); form.append(wrapper);
    }
    for (const [heading, prefix, recipients, cc] of [
      ["Test billing", "test_periods", "test_recipient", "test_cc"],
      ["Billing", "billing_periods", "recipient", "cc"],
    ]) {
      const section = document.createElement("section");
      const title = document.createElement("h2"); title.textContent = heading; section.append(title);
      for (const [key, title] of [[recipients, "Email recipients (comma separated)"], [cc, "Email CC (comma separated)"]]) {
        const label = document.createElement("label"); const span = document.createElement("span"); span.textContent = title;
        const input = document.createElement("input"); input.name = key; input.type = "text";
        const value = this.config[key]; input.value = Array.isArray(value) ? value.join(", ") : (value ?? "");
        label.append(span, input); section.append(label);
      }
      if (prefix === "billing_periods") {
        const title = document.createElement("span"); title.textContent = "Automatic emails at 04:30 Home Assistant time"; section.append(title);
        const periods = document.createElement("div"); periods.className = "periods";
        for (const period of ["monthly", "quarterly"]) {
          const label = document.createElement("label"); const input = document.createElement("input");
          input.type = "checkbox"; input.name = prefix; input.value = period;
          input.checked = (this.config[prefix] || []).includes(period);
          label.append(input, document.createTextNode(period[0].toUpperCase() + period.slice(1))); periods.append(label);
        }
        section.append(periods);
        const notice = document.createElement("small"); notice.className = "notice";
        notice.textContent = "Selecting both periods sends overlapping invoices for the same consumption.";
        section.append(notice);
      } else {
        const hint = document.createElement("small"); hint.className = "notice";
        hint.textContent = "Choose a calendar period. Save settings before sending; the saved test recipients and CC will be used.";
        section.append(hint);
        for (const [period, labelText, inputType] of [
          ["monthly", "Month", "month"], ["quarterly", "Quarter", "quarter"]
        ]) {
          const label = document.createElement("label");
          const title = document.createElement("span"); title.textContent = labelText;
          const input = document.createElement(inputType === "quarter" ? "select" : "input");
          if (inputType === "quarter") {
            const empty = document.createElement("option"); empty.value = ""; empty.textContent = "Select a quarter"; input.append(empty);
            const year = new Date().getFullYear();
            for (let y = year; y >= year - 20; y--) for (let q = 4; q >= 1; q--) {
              const option = document.createElement("option"); option.value = `${y}-Q${q}`; option.textContent = `Q${q} ${y}`; input.append(option);
            }
          } else input.type = inputType;
          label.append(title, input);
          const send = document.createElement("button"); send.type = "button"; send.className = "send-test";
          send.textContent = `Send ${period} test bill`;
          const row = document.createElement("div"); row.className = "test-row";
          row.append(label, send); section.append(row);
          const result = document.createElement("span"); result.setAttribute("role", "status"); section.append(result);
          send.onclick = async () => {
            if (!input.value || !input.checkValidity()) { result.textContent = "Choose a valid period."; return; }
            send.disabled = true; result.textContent = "Sending test bill…";
            try {
              await this._hass.callWS({type: "jk51_billing/test/send", period, value: input.value});
              result.textContent = "Test bill sent to the saved test recipients and CC.";
            } catch (error) { result.textContent = `Could not send test bill: ${error.message}`; }
            finally { send.disabled = false; }
          };
        }
      }
      form.append(section);
    }
    const button = document.createElement("button"); button.type="submit"; button.className="save"; button.textContent="Save settings"; form.append(button);
    form.onsubmit = async event => {
      event.preventDefault(); const config = Object.fromEntries(new FormData(form));
      for (const key of ["recipient", "cc", "test_recipient", "test_cc"]) config[key] = config[key].split(",").map(x => x.trim()).filter(Boolean);
      for (const key of ["billing_periods"]) config[key] = [...form.querySelectorAll(`input[name="${key}"]:checked`)].map(input => input.value);
      const status = this.shadowRoot.querySelector('[role="status"]'); button.disabled=true;
      try { await this._hass.callWS({type:"jk51_billing/config/save", config}); status.textContent="Settings saved."; }
      catch (e) { status.textContent=`Could not save: ${e.message}`; }
      finally { button.disabled=false; }
    };
  }
}
customElements.define("jk51-billing-panel", JK51BillingPanel);
