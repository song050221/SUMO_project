const socket = io();

const elapsedEl = document.getElementById("elapsed-time");
const vehicleCountEl = document.getElementById("vehicle-count");
const personCountEl = document.getElementById("person-count");
const accidentCountEl = document.getElementById("accident-count");
const alertListEl = document.getElementById("alert-list");

const detailOverlay = document.getElementById("zone-detail-overlay");
const detailTitle = document.getElementById("zone-detail-title");
const detailThead = document.getElementById("zone-detail-thead");
const detailTbody = document.getElementById("zone-detail-tbody");
const detailEmpty = document.getElementById("zone-detail-empty");
const detailClose = document.getElementById("zone-detail-close");
const detailFooter = document.getElementById("zone-detail-footer");
const triggerAccidentBtn = document.getElementById("trigger-accident-btn");
const spawnVehicleBtn = document.getElementById("spawn-vehicle-btn");
const pedestrianToggleBtn = document.getElementById("pedestrian-toggle-btn");

const ALERT_LABELS = {
  pedestrian_detected: "보행자 감지",
  congestion_detected: "정체 감지",
  accident_detected: "사고 감지",
  obstacle_detected: "장애물 감지",
  hardware_event: "실물 판단",
};

// 상세 패널이 보여줄 수 있는 4가지 종류. fetchUrl은 (targetId) => url, targetId는
// zone일 때만 쓰인다(구역 하나를 고정해서 보는 것과 달리 vehicle/person/accident는
// 항상 월드 전체 목록).
const DETAIL_KINDS = {
  // 구역(사거리) 상세 - 사고 추적 창과 같은 모양으로, 구역 안 차마다 지금 받는 중앙 제어를 보여 준다(2026-09-30)
  zone: {
    title: (targetId, extra) => extra || targetId,
    fetchUrl: (targetId) => `/api/zone/${targetId}/vehicles`,
    extractItems: (data) => data.vehicles,
    headers: ["차량 ID", "현재 도로", "적용 알고리즘", "예상 도착(전 → 후)"],
    renderRow: controlRowCells,
    rowFocus: (item) => ({ kind: "vehicle", id: item.vehicle_id }),
    onData: (data) => {
      const spinner = '<span class="tracking-spinner" aria-label="감시 중"></span>';
      const parts = [`화면 안 차량 ${data.vehicles.length}대`];
      (data.accidents || []).forEach((a) => {
        parts.push(a.remaining_s > 3600 ? `${a.road_name} 보행자 통과 대기` : `${a.road_name} 사고 ${a.remaining_s.toFixed(0)}s 후 해제`);
      });
      if (data.school_zone && data.hardware && data.hardware.enabled !== false) {
        parts.push(data.hardware.connected ? "실물 보드 연결됨" : "실물 보드 대기");
      }
      detailTitle.innerHTML = `${data.zone_name} ${spinner} ${parts.join(" · ")}`;
    },
    emptyText: "지금 이 구역 도로 위에 차량이 없습니다.",
  },
  vehicle: {
    title: () => "전체 차량",
    fetchUrl: () => "/api/world/vehicles",
    extractItems: (data) => data.vehicles,
    headers: ["차량 ID", "목적지 edge", "예상 도착"],
    renderRow: vehicleRowCells,
    rowFocus: (item) => ({ kind: "vehicle", id: item.vehicle_id }),
  },
  person: {
    title: () => "전체 보행자",
    fetchUrl: () => "/api/world/persons",
    extractItems: (data) => data.persons,
    headers: ["보행자 ID", "현재 위치(edge)"],
    renderRow: personRowCells,
    rowFocus: (item) => ({ kind: "person", id: item.person_id }),
  },
  accident: {
    title: () => "전체 사고",
    fetchUrl: () => "/api/world/accidents",
    extractItems: (data) => data.accidents,
    headers: ["위치(도로)", "남은 시간"],
    renderRow: accidentRowCells,
    rowFocus: (item) => ({ kind: "accident", id: item.accident_id }),
  },
  // 사고 추적 모드 - 새 사고마다 카메라가 따라가고, 사고 때문에 경로를 바꾼 차량이 위에서부터 쌓인다.
  tracking: {
    title: () => "사고 추적 모드",
    fetchUrl: () => "/api/tracking",
    extractItems: (data) => data.vehicles,
    headers: ["차량 ID", "사고 도로", "적용 알고리즘", "예상 도착(전 → 후)"],
    renderRow: controlRowCells,
    rowFocus: (item) => ({ kind: "vehicle", id: item.vehicle_id }),
    onData: (data) => {
      // 구분 기호 대신 돌아가는 로딩 표시 - 창 안에서도 추적이 계속 작동 중이라는 게 보이게
      const a = data.accident;
      const spinner = '<span class="tracking-spinner" aria-label="추적 중"></span>';
      detailTitle.innerHTML = a
        ? `사고 추적 중 ${spinner} ${a.road_name} (${a.remaining_s.toFixed(0)}s 후 해제)`
        : `사고 추적 중 ${spinner} 다음 사고 대기`;
    },
    emptyText: "아직 이 사고로 정지·감속·우회한 차량이 없습니다.",
  },
};

// 사고가 나면 차 위치에 따라 세 가지 중 하나를 받는다(core/decision_policy.py, 정지 > 우회 > 감속 순)
const ALGORITHM_HELP = {
  stop: "정지: 사고 도로 위에 있는 차는 진로가 막혔으므로 그 자리에서 멈춰 사고가 풀리기를 기다린다.",
  decelerate: "감속: 사고 1~2칸 앞 차는 우회할 여유가 없어 초속 5m로 속도를 줄여 사고 지점에 안전하게 접근한다.",
  reroute: "사고 회피 재탐색: 사고 3~5칸 앞이고 남은 경로가 사고 도로를 지나는 차를 골라, 사고 도로의 통행시간을 " +
    "사실상 무한대로 만든 뒤(30초) 현재 도로 상황 기준 최단시간 경로를 다시 찾는다. 우회가 기다리는 것보다 빠를 때만 우회한다.",
  keep: "원래 경로 유지: 우회 경로를 찾아봤지만, 원래 경로로 가서 사고가 풀릴 때까지 기다리는 쪽이 더 빨라서 우회하지 않았다.",
  predict: "정체 예측 선제 우회: 60초마다 각 차의 앞으로 90초 경로를 모아 처리량보다 많은 차가 몰릴 도로를 찾고, " +
    "아직 45초 이상 여유가 있는 차만 먼저 다른 길로 보낸다. 한 대체 도로로 몰리지 않게 나눠 배정한다.",
  central: "실시간 경로 재계산: 중앙 서버가 60초마다 모든 차의 경로를 지금 도로 통행시간 기준 최단시간 경로로 다시 계산한다. " +
    "이번 계산에서 더 빠른 길이 나와 경로가 바뀐 차.",
  signal: "신호 시간 배분: 신호마다 지금 초록 방향과 다음 방향의 대기열을 비교해, 대기가 많은 쪽은 초록을 늘리고 " +
    "다음 방향이 훨씬 급하면 일찍 넘긴다(최소 시간은 보장).",
  normal: "실시간 경로 재계산: 60초마다 경로를 다시 계산하지만, 지금 가는 길이 여전히 가장 빨라 그대로 가는 중.",
  hardware: "실물 차량: 신양초 사거리의 RC카. 주행 판단(보행자 앞 정지·후진·우회)은 RC카 제어기가 직접 하고 SUMO는 그대로 따라 그린다. " +
    "보드를 벗어나면 일반 차량으로 넘어가 위 알고리즘들을 똑같이 받는다.",
};

// 사고 추적 창과 구역 상세 창이 같이 쓰는 한 줄 - 차량 / 도로 / 적용 알고리즘 / 예상 도착(전 → 후)
// 보드 보행자처럼 해제 시각이 정해지지 않은 위험(아주 큰 값)을 기다리는 경우는 초 대신 문구로
function fmtEta(v) {
  if (v == null) return "-";
  return v > 500000 ? "보행자 통과 후" : `${v.toFixed(0)}s`;
}

function controlRowCells(r) {
  const action = r.action || "reroute";
  let eta;
  if (action === "hardware") {
    eta = `<span class="eta-normal">-</span><div class="algo-detail">실물 보드 주행 중</div>`;
  } else if (action === "keep") {
    // 원래 경로 유지: 경로가 안 바뀌므로 전·후 같은 시간(기다렸을 때 도착)
    const t = fmtEta(r.old_eta);
    eta = `<span class="eta-normal">${t}</span> → <span class="eta-new">${t}</span>`;
  } else if (r.old_eta != null) {
    // 우회: 전 = 우회 안 하고 사고 지점에서 사고가 풀릴 때까지 기다렸을 때, 후 = 우회 경로
    const saved = r.old_eta - r.new_eta;
    const diff = r.old_eta > 500000
      ? `<span class="eta-saved">무기한 대기 대신 우회</span>`
      : saved >= 0
      ? `<span class="eta-saved">${saved.toFixed(0)}s 단축</span>`
      : `<span class="eta-lost">${(-saved).toFixed(0)}s 늘어남</span>`;
    eta = `<span class="eta-normal">${fmtEta(r.old_eta)}</span> → <span class="eta-new">${fmtEta(r.new_eta)}</span><div class="algo-detail">${diff}</div>`;
  } else if (action === "stop" || action === "decelerate") {
    // 정지·감속: 경로는 그대로 - 사고 해제까지 기다린 뒤의 도착 예상 하나만
    eta = `<span class="eta-normal">${fmtEta(r.new_eta)}</span><div class="algo-detail">경로 유지 · 사고 해제 대기</div>`;
  } else {
    // 신호 조정·평소 주행: 경로가 안 바뀌었으므로 지금 경로 기준 도착 예상 하나만
    eta = `<span class="eta-normal">${fmtEta(r.new_eta)}</span>`;
  }
  const where = action === "stop" ? "사고 도로 위" : (r.hops_before != null ? `사고 ${r.hops_before}칸 전` : "");
  const detour = r.detour_edges != null ? `우회 도로 ${r.detour_edges}개` : "";
  const detail = [r.detail, where, detour].filter(Boolean).join(" · ");
  const algo = `<span class="algo-badge ${action}" title="${ALGORITHM_HELP[action] || ""}">${r.algorithm}</span><div class="algo-detail">${detail}</div>`;
  return `<td>${r.vehicle_id}</td><td>${r.road_name}</td><td>${algo}</td><td>${eta}</td>`;
}

function vehicleRowCells(v) {
  const etaText = `${v.eta.toFixed(0)}s`;
  const etaCell = v.optimized
    ? `<span class="optimized-badge">경로 최적화</span> <span class="eta-new">${etaText}</span>`
    : `<span class="eta-normal">${etaText}</span>`;
  return `<td>${v.vehicle_id}</td><td>${v.destination ?? "-"}</td><td>${etaCell}</td>`;
}

function personRowCells(p) {
  return `<td>${p.person_id}</td><td>${p.edge || "-"}</td>`;
}

function accidentRowCells(a) {
  // 어린이보호구역 보행자 시뮬레이션은 고정 시간이 아니라 "통과 완료" 버튼으로
  // 해제되는 사고라 남은 시간이 아주 큰 값(sentinel)으로 온다 - 그 경우 초 단위
  // 대신 문구로 표시한다.
  const remaining = a.remaining_s > 3600 ? "보행자 통과 대기 중" : `${a.remaining_s.toFixed(0)}s 후 해제`;
  const where = a.road_name && a.road_name !== a.edge ? `${a.road_name} (${a.edge})` : a.edge;
  return `<td>${where}</td><td>${remaining}</td>`;
}

let openDetail = null; // {kind, targetId}
let pollTimer = null;
const POLL_INTERVAL_MS = 1500;

function flashCard(el) {
  el.classList.add("focusing");
  setTimeout(() => el.classList.remove("focusing"), 400);
}

document.querySelectorAll(".zone-card").forEach((card) => {
  const zoneId = card.id.replace(/^card-/, "");
  card.addEventListener("click", () => {
    flashCard(card);
    focusTarget("zone", zoneId);
    openDetailPanel("zone", zoneId, card.querySelector("h2").textContent);
  });
});

document.getElementById("summary-vehicles").addEventListener("click", (e) => {
  flashCard(e.currentTarget);
  openDetailPanel("vehicle");
});
document.getElementById("summary-persons").addEventListener("click", (e) => {
  flashCard(e.currentTarget);
  openDetailPanel("person");
});
document.getElementById("summary-accidents").addEventListener("click", (e) => {
  flashCard(e.currentTarget);
  openDetailPanel("accident");
});
document.getElementById("summary-tracking").addEventListener("click", async (e) => {
  flashCard(e.currentTarget);
  try {
    await fetch("/api/tracking/start", { method: "POST" });
  } catch (err) {
    console.error("사고 추적 모드 시작 실패:", err);
  }
  openDetailPanel("tracking");
});

detailClose.addEventListener("click", closeDetailPanel);
detailOverlay.addEventListener("click", (e) => {
  if (e.target === detailOverlay) closeDetailPanel();
});

async function focusTarget(kind, targetId) {
  try {
    // 도로 id에 '#'이 들어가(예: 516648936#5) 그대로 붙이면 URL 조각으로 잘린다 - 인코딩
    const res = await fetch(`/api/focus/${kind}/${encodeURIComponent(targetId)}`, { method: "POST" });
    if (!res.ok) console.error(`카메라 이동 실패: ${kind}/${targetId}`, await res.text());
  } catch (err) {
    console.error(`카메라 이동 요청 실패: ${kind}/${targetId}`, err);
  }
}

function isSchoolZoneCard(targetId) {
  const card = document.getElementById(`card-${targetId}`);
  return !!card && card.dataset.schoolZone === "true";
}

function openDetailPanel(kind, targetId, titleOverride) {
  openDetail = { kind, targetId };
  const config = DETAIL_KINDS[kind];
  detailTitle.textContent = config.title(targetId, titleOverride);
  detailThead.innerHTML = `<tr>${config.headers.map((h) => `<th>${h}</th>`).join("")}</tr>`;
  // "사고 생성" 버튼은 구역 상세일 때만 보여준다(전체 차량/보행자/사고 목록엔 특정
  // 구역이 없어서 어디에 사고를 낼지 정할 수 없음). footer는 body와 별도 영역이라
  // 표의 행 수가 몇 개든 이 버튼 위치는 항상 패널 맨 아래로 고정된다.
  const isZone = kind === "zone";
  const isSchoolZone = isZone && isSchoolZoneCard(targetId);
  detailFooter.classList.toggle("hidden", !isZone);
  // 하드웨어 연동용 버튼(차량 감지/보행자 시뮬레이션)은 어린이보호구역에서만 보여준다 -
  // 실제 하드웨어가 아직 없어서 이 버튼들로 카메라/LED 신호를 대신 흉내낸다.
  spawnVehicleBtn.classList.toggle("hidden", !isSchoolZone);
  pedestrianToggleBtn.classList.toggle("hidden", !isSchoolZone);
  if (isSchoolZone) updatePedestrianToggleLabel(targetId);
  detailOverlay.classList.remove("hidden");
  refreshDetailPanel();
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(refreshDetailPanel, POLL_INTERVAL_MS);
}

function updatePedestrianToggleLabel(targetId) {
  const card = document.getElementById(`card-${targetId}`);
  const present = card?.querySelector('[data-field="accident_present"]')?.textContent === "발생";
  pedestrianToggleBtn.dataset.present = present ? "true" : "false";
  pedestrianToggleBtn.textContent = present ? "보행자 통과 완료" : "보행자 출현 시뮬레이션";
}

triggerAccidentBtn.addEventListener("click", async () => {
  if (!openDetail || openDetail.kind !== "zone") return;
  const zoneId = openDetail.targetId;
  triggerAccidentBtn.disabled = true;
  triggerAccidentBtn.textContent = "생성하는 중...";
  try {
    const res = await fetch(`/api/zone/${zoneId}/trigger_accident`, { method: "POST" });
    if (!res.ok) console.error(`사고 생성 요청 실패: ${zoneId}`, await res.text());
  } catch (err) {
    console.error(`사고 생성 요청 실패: ${zoneId}`, err);
  } finally {
    setTimeout(() => {
      triggerAccidentBtn.disabled = false;
      triggerAccidentBtn.textContent = "사고 생성";
    }, 1000);
  }
});

spawnVehicleBtn.addEventListener("click", async () => {
  spawnVehicleBtn.disabled = true;
  spawnVehicleBtn.textContent = "생성하는 중...";
  try {
    const res = await fetch("/api/school_zone/vehicle_detected", { method: "POST" });
    if (!res.ok) console.error("차량 감지 시뮬레이션 요청 실패", await res.text());
  } catch (err) {
    console.error("차량 감지 시뮬레이션 요청 실패", err);
  } finally {
    setTimeout(() => {
      spawnVehicleBtn.disabled = false;
      spawnVehicleBtn.textContent = "차량 감지 시뮬레이션";
    }, 1000);
  }
});

pedestrianToggleBtn.addEventListener("click", async () => {
  const nextPresent = pedestrianToggleBtn.dataset.present !== "true";
  pedestrianToggleBtn.disabled = true;
  try {
    const res = await fetch("/api/school_zone/pedestrian", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ present: nextPresent }),
    });
    if (!res.ok) console.error("보행자 상태 변경 요청 실패", await res.text());
  } catch (err) {
    console.error("보행자 상태 변경 요청 실패", err);
  } finally {
    pedestrianToggleBtn.disabled = false;
  }
});

function closeDetailPanel() {
  // 사고 추적 목록 창을 닫으면 추적 모드도 끈다
  if (openDetail && openDetail.kind === "tracking") {
    fetch("/api/tracking/stop", { method: "POST" }).catch((err) => console.error("사고 추적 모드 중지 실패:", err));
  }
  openDetail = null;
  detailOverlay.classList.add("hidden");
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
  // 패널을 닫으면 선택했던 차량의 경로선도 같이 지운다(안 그러면 지도에 남아있음).
  fetch("/api/route/clear", { method: "POST" }).catch((err) => {
    console.error("경로선 지우기 요청 실패:", err);
  });
}

async function refreshDetailPanel() {
  if (!openDetail) return;
  const { kind, targetId } = openDetail;
  const config = DETAIL_KINDS[kind];
  try {
    const res = await fetch(config.fetchUrl(targetId));
    if (!res.ok) return;
    const data = await res.json();
    if (!openDetail || openDetail.kind !== kind) return; // 기다리는 사이 창이 닫히거나 바뀜
    if (config.onData) config.onData(data);
    detailEmpty.textContent = config.emptyText || "지금 대상이 없습니다.";
    renderDetailRows(config, config.extractItems(data));
  } catch (err) {
    console.error("상세 패널 갱신 실패:", err);
  }
}

function renderDetailRows(config, items) {
  detailTbody.innerHTML = "";
  detailEmpty.classList.toggle("hidden", items.length > 0);

  items.forEach((item) => {
    const tr = document.createElement("tr");
    tr.className = "detail-row";
    tr.innerHTML = config.renderRow(item);
    tr.addEventListener("click", () => {
      const target = config.rowFocus(item);
      focusTarget(target.kind, target.id);
    });
    detailTbody.appendChild(tr);
  });
}

// 실물 보드(차량 호스트) 연동 상태 - 신양초 카드에 연결 여부와 차량별 동작을 보여준다.
// SUMO는 판단하지 않고 차량 호스트가 보낸 상황을 그대로 그리기만 한다.
const HW_COMMAND_LABELS = { F: "전진", B: "후진", L: "좌회전", R: "우회전", S: "정지" };
const HW_ROLE_LABELS = { lead: "선행", follow: "후행", unknown: "차량" };

function hardwareVehicleLine(v) {
  const role = HW_ROLE_LABELS[v.role] || "차량";
  // 보드에서 나온 차는 같은 그림의 일반 차량(rc_…)으로 SUMO에서 계속 달리며 중앙 제어를 받는다
  if (v.released_as) return `${role} ${v.vehicle_id} · 보드 도착 → SUMO에서 계속 주행 (${v.released_as})`;
  if (v.arrived) return `${role} ${v.vehicle_id} · 도착`;
  if (!v.visible) return `${role} ${v.vehicle_id} · 인식 끊김`;
  const dest = (v.destination_zone || "").charAt(0);
  // 차량 호스트가 보낸 판단(event)을 먼저 보여 준다. 없으면 예전처럼 명령과 우회 여부.
  if (v.event_label) return `${role} ${v.vehicle_id} · ${v.event_label}${dest ? ` → ${dest}` : ""}`;
  const cmd = HW_COMMAND_LABELS[v.command] || v.command || "-";
  const diverted = (v.route_id || "").startsWith("divert") ? " · 우회" : "";
  return `${role} ${v.vehicle_id} · ${cmd}${diverted}${dest ? ` → ${dest}` : ""}`;
}

function renderHardwareTwin(hw) {
  document.querySelectorAll(".school-zone-card").forEach((card) => {
    const link = card.querySelector('[data-field="hardware_link"]');
    const list = card.querySelector('[data-field="hardware_vehicles"]');
    if (!link || !list) return;
    if (!hw || hw.enabled === false) {
      link.textContent = "꺼짐";
      link.classList.remove("warn");
      list.innerHTML = "";
      return;
    }
    link.textContent = hw.connected ? "연결됨" : (hw.message_count ? "끊김" : "대기 중");
    link.classList.toggle("ok", !!hw.connected);
    list.innerHTML = "";
    (hw.vehicles || []).forEach((v) => {
      const li = document.createElement("li");
      li.textContent = hardwareVehicleLine(v);
      list.appendChild(li);
    });
  });
}

const trackingCard = document.getElementById("summary-tracking");
const trackingStateEl = document.getElementById("tracking-state");

socket.on("zone_update", (data) => {
  elapsedEl.textContent = `${data.summary.elapsed_step}s / ${data.summary.sim_end}s`;
  const tracking = !!data.summary.tracking;
  trackingStateEl.textContent = tracking ? "추적 중" : "꺼짐";
  trackingCard.classList.toggle("active", tracking);
  vehicleCountEl.textContent = data.summary.vehicle_count;
  personCountEl.textContent = data.summary.person_count;
  accidentCountEl.textContent = data.summary.accident_count;

  data.zones.forEach((zone) => {
    const card = document.getElementById(`card-${zone.zone_id}`);
    if (!card) return;

    card.querySelector('[data-field="vehicle_count"]').textContent = zone.vehicle_count;
    card.querySelector('[data-field="mean_speed"]').textContent = `${zone.mean_speed.toFixed(1)} m/s`;

    const pedField = card.querySelector('[data-field="pedestrian_present"]');
    pedField.textContent = zone.pedestrian_present ? "감지됨" : "없음";
    pedField.classList.toggle("warn", zone.pedestrian_present);

    const accidentField = card.querySelector('[data-field="accident_present"]');
    accidentField.textContent = zone.accident_present ? "발생" : "없음";
    accidentField.classList.toggle("warn", zone.accident_present);

    card.classList.toggle("alert", zone.pedestrian_present || zone.accident_present);
  });

  renderHardwareTwin(data.summary.hardware);

  // 어린이보호구역 상세 패널이 열려 있는 동안 사고 상태가 바뀌면(예: 30초 타이머로
  // 만료) 보행자 토글 버튼 라벨도 실시간으로 맞춰준다.
  if (openDetail && openDetail.kind === "zone" && isSchoolZoneCard(openDetail.targetId)) {
    updatePedestrianToggleLabel(openDetail.targetId);
  }

  alertListEl.innerHTML = "";
  data.recent_alerts.forEach((alert) => {
    const li = document.createElement("li");
    const label = ALERT_LABELS[alert.type] || alert.type;
    const where = alert.type === "hardware_event" ? alert.text : `${alert.zone_name} (${alert.edge})`;
    li.innerHTML = `<span class="tag">${label}</span>${where} — step ${alert.step}`;
    if (alert.type === "accident_detected") {
      // 사고가 어디서 났는지 바로 볼 수 있게 - 누르면 sumo-gui 카메라가 사고 지점으로 간다
      li.classList.add("clickable");
      li.title = "클릭하면 SUMO 화면이 사고 위치로 이동";
      li.addEventListener("click", () => focusTarget("accident", alert.edge));
    }
    alertListEl.appendChild(li);
  });
});
