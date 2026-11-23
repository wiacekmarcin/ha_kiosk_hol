/*
 * kiosk-voice-card - karta Home Assistant: wiadomość głosowa i komunikat tekstowy na tablety.
 *
 * Nagranie z mikrofonu przeglądarki (przytrzymaj i mów albo dotknij - mów - dotknij,
 * najwyżej 30 s) jest zamieniane na WAV i trafia do katalogu multimediów HA jako kiosk_glos_<nazwa>.wav,
 * a encja sensor.kiosk_wiadomosc_glosowa dostaje nowe id wiadomości - tablety HA Kiosk
 * i HA Intercom odtwarzają ją po zapowiedzi "Nowa wiadomość głosowa".
 * Pole tekstowe wywołuje script.kiosk_komunikat - tablety czytają tekst głosem (TTS HA).
 *
 * Mikrofon w przeglądarce działa tylko przez HTTPS (np. adres Nabu Casa).
 *
 * Konfiguracja karty (YAML):
 *   type: custom:kiosk-voice-card
 *   name: Dashboard          # nadawca widoczny na tabletach (opcjonalnie)
 *   text: true               # pole komunikatu tekstowego (domyślnie true)
 */
const MAX_SECONDS = 30;
const MIN_SECONDS = 0.7;
const TAP_SECONDS = 0.6;
const WARMUP_MS = 300;          // rozruch kodera przed sygnałem "mów"
const MIC_KEEP_SECONDS = 60;    // mikrofon otwarty po nagraniu (szybki start kolejnego)
const LEAD_SILENCE = 0.4;       // cisza na początku WAV - rozruch głośnika w tablecie
const STATE_ENTITY = "sensor.kiosk_wiadomosc_glosowa";

function safeId(name) {
  const map = { ą: "a", ć: "c", ę: "e", ł: "l", ń: "n", ó: "o", ś: "s", ź: "z", ż: "z", " ": "_" };
  const s = name.toLowerCase().split("").map((c) => map[c] ?? c).join("");
  return s.replace(/[^a-z0-9_]/g, "") || "dashboard";
}

class KioskVoiceCard extends HTMLElement {
  setConfig(config) {
    this._config = { name: "Dashboard", text: true, ...config };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
  }

  getCardSize() {
    return 5;
  }

  _render() {
    if (this._root) return;
    this._root = this.attachShadow({ mode: "open" });
    this._root.innerHTML = `
      <style>
        ha-card { padding: 16px; text-align: center; }
        .title { font-size: 1.2em; margin-bottom: 8px; text-align: left; }
        .count { font-size: 1.1em; color: var(--secondary-text-color); height: 1.6em; }
        .count.rec { color: #e53935; font-size: 2em; font-weight: bold; height: 1.6em; }
        button.talk { width: 180px; height: 180px; border-radius: 50%; border: none; cursor: pointer;
          background: var(--primary-color); color: white; font-size: 1.1em; font-weight: bold;
          margin: 12px auto; display: block; user-select: none; -webkit-user-select: none;
          touch-action: none; }
        button.talk.rec { background: #e53935; }
        button.talk:disabled { background: var(--disabled-color, #888); cursor: default; }
        .status { min-height: 1.4em; margin: 6px 0; }
        .text { display: flex; gap: 8px; margin-top: 12px; }
        .text input { flex: 1; padding: 8px; font-size: 1em; border-radius: 6px;
          border: 1px solid var(--divider-color); background: var(--card-background-color);
          color: var(--primary-text-color); }
        .text button { padding: 8px 14px; border-radius: 6px; border: none; cursor: pointer;
          background: var(--primary-color); color: white; }
      </style>
      <ha-card>
        <div class="title">Wiadomość na tablety</div>
        <div class="count" id="count">maks. ${MAX_SECONDS} s</div>
        <button class="talk" id="talk">🎤<br>Przytrzymaj<br>i mów</button>
        <div class="status" id="status"></div>
        <div class="text" id="textrow">
          <input id="text" maxlength="250" placeholder="Komunikat tekstowy (tablety przeczytają go głosem)">
          <button id="say">Wyślij</button>
        </div>
      </ha-card>`;
    const talk = this._root.getElementById("talk");
    talk.addEventListener("pointerdown", (e) => { e.preventDefault(); this._press(); });
    talk.addEventListener("pointerup", (e) => { e.preventDefault(); this._release(); });
    talk.addEventListener("pointerleave", () => { if (this._recording && !this._latched) this._release(); });
    this._root.getElementById("say").addEventListener("click", () => this._sendText());
    this._root.getElementById("text").addEventListener("keydown", (e) => { if (e.key === "Enter") this._sendText(); });
    this._root.getElementById("textrow").style.display = this._config.text === false ? "none" : "flex";
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      talk.disabled = true;
      this._status("Nagrywanie działa tylko przez HTTPS (np. adres Nabu Casa)");
    }
  }

  _status(text) {
    this._root.getElementById("status").textContent = text;
  }

  _count(text, rec) {
    const el = this._root.getElementById("count");
    el.textContent = text;
    el.classList.toggle("rec", !!rec);
  }

  // --- przycisk: trzymanie albo dotknij - mów - dotknij ------------------------------
  _press() {
    this._pressedAt = performance.now();
    if (!this._recording) { this._latched = false; this._start(); }
    else if (this._latched) this._stop();
  }

  _release() {
    if (!this._recording || this._latched) return;
    const now = performance.now();
    if (now - this._pressedAt < TAP_SECONDS * 1000) {
      this._latched = true;
      this._status("Nagrywanie - dotknij ponownie, aby wysłać");
      return;
    }
    this._stop();
  }

  // Mikrofon zostaje otwarty przez MIC_KEEP_SECONDS po nagraniu - kolejne nagranie startuje
  // od razu, bez rozruchu mikrofonu, który ucinał początek wypowiedzi.
  async _ensureStream() {
    clearTimeout(this._release_timer);
    if (this._stream && this._stream.getTracks().some((t) => t.readyState === "live")) return this._stream;
    this._stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    return this._stream;
  }

  _releaseStreamLater() {
    clearTimeout(this._release_timer);
    this._release_timer = setTimeout(() => {
      if (this._recording || !this._stream) return;
      this._stream.getTracks().forEach((t) => t.stop());
      this._stream = null;
    }, MIC_KEEP_SECONDS * 1000);
  }

  async _start() {
    this._recording = true;          // od teraz puszczenie przycisku kończy nagranie
    this._starting = true;
    this._t0 = 0;
    this._status("Przygotowanie mikrofonu…");
    try {
      await this._ensureStream();
    } catch (err) {
      this._recording = false;
      this._starting = false;
      this._status("Brak dostępu do mikrofonu: " + err.message);
      return;
    }
    // AAC w MP4 albo Opus w WebM; i tak karta zamienia nagranie na WAV przed wysłaniem.
    const types = ["audio/mp4;codecs=mp4a.40.2", "audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
    this._mime = types.find((t) => window.MediaRecorder && MediaRecorder.isTypeSupported(t)) || "";
    this._chunks = [];
    this._rec = new MediaRecorder(this._stream, this._mime ? { mimeType: this._mime, audioBitsPerSecond: 48000 } : {});
    this._rec.ondataavailable = (e) => { if (e.data.size) this._chunks.push(e.data); };
    this._rec.onstop = () => this._upload();
    await new Promise((resolve) => { this._rec.onstart = resolve; this._rec.start(250); });
    // koder potrzebuje chwili - sygnał "mów" dopiero po rozruchu
    await new Promise((resolve) => setTimeout(resolve, WARMUP_MS));
    this._starting = false;
    this._t0 = performance.now();
    if (!this._recording) { this._finish(); return; }   // puszczony w czasie przygotowania
    this._root.getElementById("talk").classList.add("rec");
    this._status(this._latched ? "Mów - dotknij ponownie, aby wysłać" : "Mów - puść przycisk, aby wysłać");
    this._timer = setInterval(() => {
      const left = MAX_SECONDS - (performance.now() - this._t0) / 1000;
      this._count(`${Math.max(0, Math.ceil(left))} s`, true);
      if (left <= 0) this._stop();
    }, 100);
  }

  _stop() {
    if (!this._recording) return;
    this._recording = false;
    this._latched = false;
    if (this._starting) return;      // _start dokończy przygotowanie i zamknie nagranie
    this._finish();
  }

  _finish() {
    clearInterval(this._timer);
    this._seconds = this._t0 ? (performance.now() - this._t0) / 1000 : 0;
    this._root.getElementById("talk").classList.remove("rec");
    this._count(`maks. ${MAX_SECONDS} s`, false);
    this._rec.stop();
    this._releaseStreamLater();
  }

  // Dekodowanie nagrania przeglądarki i zapis jako WAV 16 bit, 16 kHz, mono.
  async _toWav(blob) {
    const RATE = 16000;
    const Ctx = window.AudioContext || window.webkitAudioContext;
    const ctx = new Ctx();
    let decoded;
    try {
      decoded = await ctx.decodeAudioData(await blob.arrayBuffer());
    } finally {
      ctx.close();
    }
    const length = Math.ceil(decoded.duration * RATE);
    const off = new OfflineAudioContext(1, length, RATE);
    const src = off.createBufferSource();
    src.buffer = decoded;
    src.connect(off.destination);
    src.start();
    const pcm = (await off.startRendering()).getChannelData(0);
    let peak = 0;
    for (let i = 0; i < pcm.length; i++) peak = Math.max(peak, Math.abs(pcm[i]));
    const gain = peak > 0.01 ? Math.min(0.95 / peak, 8) : 1;  // normalizacja głośności
    const pad = Math.round(LEAD_SILENCE * RATE);   // próbki ciszy przed nagraniem
    const bytes = (pad + pcm.length) * 2;
    const buf = new ArrayBuffer(44 + bytes);
    const v = new DataView(buf);
    const str = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
    str(0, "RIFF"); v.setUint32(4, 36 + bytes, true); str(8, "WAVE");
    str(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
    v.setUint32(24, RATE, true); v.setUint32(28, RATE * 2, true); v.setUint16(32, 2, true);
    v.setUint16(34, 16, true); str(36, "data"); v.setUint32(40, bytes, true);
    for (let i = 0; i < pcm.length; i++) {
      const s = Math.max(-1, Math.min(1, pcm[i] * gain));
      v.setInt16(44 + (pad + i) * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }
    return new Blob([buf], { type: "audio/wav" });
  }
  async _upload() {

    if (this._seconds < MIN_SECONDS) { this._status("Za krótko - przytrzymaj przycisk i mów"); return; }
    const file = `kiosk_glos_${safeId(this._config.name)}.wav`;
    this._status(`Wysyłanie (${Math.round(this._seconds)} s)…`);
    try {
      // Przeglądarka nagrywa w swoim formacie (Chrome na Androidzie: Opus w MP4, którego
      // Android 7 nie odtworzy) - zamiana na WAV PCM 16 kHz mono, czytany przez każdy tablet.
      const wav = await this._toWav(new Blob(this._chunks, { type: this._rec.mimeType || this._mime }));
      const form = new FormData();
      form.append("media_content_id", "media-source://media_source/local/.");
      form.append("file", wav, file);
      const token = this._hass.auth.data.access_token;
      const r = await fetch("/api/media_source/local_source/upload", {
        method: "POST", headers: { Authorization: `Bearer ${token}` }, body: form });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      await this._hass.callApi("POST", `states/${STATE_ENTITY}`, {
        state: Math.random().toString(16).slice(2, 14),
        attributes: { friendly_name: "Wiadomość głosowa (tablety)", icon: "mdi:phone-message",
          from: this._config.name, file, time: new Date().toISOString(),
          duration: Math.round(this._seconds * 10) / 10 },
      });
      this._status("Wysłano na tablety");
    } catch (err) {
      this._status("Nie udało się wysłać: " + err.message);
    }
  }

  // --- komunikat tekstowy --------------------------------------------------------------
  async _sendText() {
    const input = this._root.getElementById("text");
    const text = input.value.trim();
    if (!text) return;
    try {
      await this._hass.callService("script", "kiosk_komunikat", { tekst: text });
      input.value = "";
      this._status("Komunikat wysłany - tablety przeczytają go głosem");
    } catch (err) {
      this._status("Nie udało się wysłać komunikatu: " + err.message);
    }
  }
}

customElements.define("kiosk-voice-card", KioskVoiceCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "kiosk-voice-card", name: "Wiadomość na tablety",
  description: "Nagranie głosowe i komunikat tekstowy na tablety HA Kiosk / HA Intercom" });
