const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function app() {
  const elements = new Map();
  const document = {
    activeElement: null,
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, {
        textContent: "", innerHTML: "", fields: [],
        querySelectorAll(selector) { return selector === "input,select,textarea" ? this.fields : []; },
        focus() {}, close() {},
      });
      return elements.get(id);
    },
  };
  const context = vm.createContext({ document, window: { matchMedia: () => ({ matches: false }) } });
  const source = fs.readFileSync(path.join(__dirname, "../program/app.js"), "utf8");
  assert.ok(source.includes("  init();"));
  vm.runInContext(source.replace("  init();", `
    globalThis.app = {assertPanel, assertVerification, assertProtection, protectionOf, setVerification,
      updateCircuit, updatePoint, convert, renderCircuitDetail, updateDetail, searchFields,
      resolvedProtection, deletePointRecord, deleteCircuitRecord,
      configure(panel,otherPanels=[],role="owner") {
        state=panel;workbook.homes[0].panels=[panel,...otherPanels];workbook.homes[0].role=role;
        workbook.selectedPanelId=panel.id;currentUser={username:"tester",isLocal:false};detailCircuitId=panel.circuits[0]?.id;
      },
      stubRendering() {
        save=renderPanel=renderTotals=renderNavigation=renderPointRows=renderRows=applyTableSearch=applyRole=renderAll=notify=()=>{};
      }
    };`), context);
  return { ...context.app, document };
}

function panel() {
  return { id: 1, name: "Main panel", kind: "main", parentPanelId: null, parentCircuitId: null,
    spaces: 24, types: {}, nextCircuitId: 3, nextPointId: 2,
    circuits: [{ id: 1, name: "Kitchen", assignment: "5", voltage: 120, amps: 20, gauge: "12", labelMode: "circuits" },
      { id: 2, name: "Lights", assignment: "6", voltage: 120, amps: 15, gauge: "14", labelMode: "circuits" }],
    points: [{ id: 1, circuitId: 1, name: "Counter outlet", location: "Left of sink" }] };
}

const plain = value => JSON.parse(JSON.stringify(value));
const confirmed = () => ({ status: "confirmed", verifiedAt: "2026-10-01T12:30:00.000Z", verifiedBy: "owner" });
const target = (id, field, value, point = false) => ({
  value, dataset: point ? { pointField: field } : { field },
  closest: () => ({ dataset: point ? { pointId: id } : { circuitId: id },
    classList: { toggle() {} }, querySelector: () => ({ textContent: "" }) }),
});

test("legacy imports get defaults and documentation survives frontend normalization", () => {
  const a = app(), original = panel(), clean = a.assertPanel(original);
  assert.deepEqual(plain(clean.circuits[0].verification), { status: "unverified", verifiedAt: "", verifiedBy: "" });
  assert.equal(clean.points[0].protection, null);
  clean.circuits[0].verification = confirmed();
  clean.circuits[0].protection = plain(a.assertProtection({ type: "dual", device: "Kitchen breaker", resetLocation: "Main panel" }));
  clean.points[0].verification = confirmed();
  clean.points[0].protection = plain(a.assertProtection({ type: "gfci", device: "Bathroom GFCI", resetLocation: "Left of mirror" }));
  assert.equal(clean.circuits[0].protection.deviceKind, "custom");
  assert.equal(clean.circuits[0].protection.devicePointId, null);
  assert.deepEqual(plain(a.assertPanel(plain(clean))), plain(clean));
});

test("invalid verification and protection records fail before import", () => {
  const a = app();
  for (const value of [null, [], { status: ["confirmed"] }, { status: "confirmed" },
    { ...confirmed(), verifiedAt: "2026-02-30T12:30:00.000Z" },
    { ...confirmed(), verifiedAt: "0000-01-01T12:30:00.000Z" }, { ...confirmed(), verifiedBy: " " }]) {
    assert.throws(() => a.assertVerification(value, true));
  }
  assert.throws(() => a.assertVerification(confirmed(), false));
  for (const value of [null, [], { type: ["gfci"] }, { type: "invalid" },
    { type: "gfci", device: "x".repeat(161) }, { type: "afci", resetLocation: "x".repeat(501) }]) {
    assert.throws(() => a.assertProtection(value));
  }
});

test("confirming records the current user and preserves prior confirmation on reassignment", () => {
  const a = app(), p = panel();
  a.configure(p); a.stubRendering();
  assert.equal(a.setVerification(p.points[0], "confirmed", false), false);
  assert.equal(a.setVerification(p.points[0], "confirmed", true), true);
  assert.equal(p.points[0].verification.verifiedBy, "tester");
  const date = p.points[0].verification.verifiedAt;
  a.updatePoint(target(1, "circuitId", "2", true), true);
  assert.equal(p.points[0].circuitId, 2);
  assert.equal(p.points[0].verification.status, "needs-recheck");
  assert.equal(p.points[0].verification.verifiedAt, date);
});

test("moving a breaker and converting its layout invalidate circuit and linked point confirmations", () => {
  const a = app(), p = panel();
  p.circuits[0].verification = confirmed(); p.points[0].verification = confirmed();
  a.configure(p); a.stubRendering();
  a.updateCircuit(target(1, "assignment", "7"), true);
  assert.equal(p.circuits[0].verification.status, "needs-recheck");
  assert.equal(p.points[0].verification.status, "needs-recheck");
  p.circuits[0].verification = confirmed(); p.points[0].verification = confirmed();
  a.convert(7, "tandem");
  assert.equal(p.circuits[0].assignment, "7a");
  assert.equal(p.circuits[0].verification.status, "needs-recheck");
  assert.equal(p.points[0].verification.status, "needs-recheck");
});

test("point protection inherits the circuit and an explicit override takes precedence", () => {
  const a = app(), p = panel(), c = p.circuits[0], point = p.points[0];
  c.protection = { type: "dual", device: "Main breaker", resetLocation: "Main panel" };
  assert.equal(a.protectionOf(c, point).resetLocation, "Main panel");
  point.protection = { type: "none", device: "", resetLocation: "" };
  assert.equal(a.protectionOf(c, point).type, "none");
  point.protection = null;
  assert.equal(a.protectionOf(c, point).type, "dual");
});

test("details expose reset locations, escape user text, and remain read-only for viewers", () => {
  const a = app(), p = panel();
  p.points[0].name = '<img src=x onerror="alert(1)">';
  p.circuits[0].protection = { type: "gfci", device: "Kitchen GFCI", resetLocation: "Behind toaster" };
  a.configure(p, [], "viewer");
  const body = a.document.getElementById("circuitDetailBody");
  body.fields = [{ disabled: false }, { disabled: false }];
  a.renderCircuitDetail();
  assert.match(body.innerHTML, /Behind toaster/);
  assert.match(body.innerHTML, /&lt;img/);
  assert.doesNotMatch(body.innerHTML, /<img/);
  assert.ok(body.fields.every(field => field.disabled));
  assert.equal(a.document.getElementById("detailSaveStatus").textContent, "View-only access");
  assert.match(a.searchFields("points", p.points[0], p).protection, /Behind toaster/);
  p.points[0].protection = { type: "gfci", device: "Separate GFCI", resetLocation: "Hall bathroom" };
  assert.match(a.searchFields("circuits", p.circuits[0], p).protection, /Hall bathroom/);
});

const protection = (deviceKind, devicePointId = null, resetLocation = "") => ({
  type: "gfci", deviceKind, devicePointId, device: "", resetLocation,
});

test("protective device choices include only this circuit's endpoints and support override and custom records", () => {
  const a = app(), p = panel(), c = p.circuits[0];
  p.points.push({ id: 2, circuitId: 2, name: "Other circuit endpoint", location: "Hall" });
  p.nextPointId = 3;
  a.configure(p); a.stubRendering();
  const change = (field, value, pointId) => a.updateDetail({ value,
    dataset: { protectionField: field, ...(pointId ? { protectionPoint: String(pointId) } : {}) },
    hasAttribute: () => false });
  change("deviceChoice", "breaker");
  assert.equal(c.protection.deviceKind, "breaker");
  assert.match(a.resolvedProtection(c.protection, c, p).resetLocation, /Main panel.*5/);
  change("deviceChoice", "point:1");
  assert.equal(c.protection.devicePointId, 1);
  change("deviceChoice", "point:2");
  assert.equal(c.protection.devicePointId, 1);
  a.renderCircuitDetail();
  const html = a.document.getElementById("circuitDetailBody").innerHTML;
  assert.match(html, /Breaker itself/);
  assert.match(html, /Custom \/ endpoint group/);
  assert.match(html, /value="point:1" selected/);
  assert.doesNotMatch(html, /value="point:2"/);
  change("deviceChoice", "breaker", 1);
  assert.equal(p.points[0].protection.deviceKind, "breaker");
  change("deviceChoice", "custom", 1);
  change("device", "Kitchen outlet group", 1);
  change("resetLocation", "Pantry", 1);
  assert.equal(a.protectionOf(c, p.points[0]).device, "Kitchen outlet group");
  change("type", "", 1);
  assert.equal(p.points[0].protection, null);
  assert.equal(a.protectionOf(c, p.points[0]).deviceKind, "point");
});

test("selected endpoints follow edits, are searchable across panels, and allow an explicit reset location", () => {
  const a = app(), p = panel(), c = p.circuits[0];
  c.protection = protection("point", 1);
  assert.deepEqual(plain(a.assertPanel(p).circuits[0].protection), c.protection);
  a.configure(panel()); // Searches must use the panel being searched, not the selected panel.
  p.points[0].name = "New GFCI name";
  p.points[0].location = "New reset location";
  const fields = a.searchFields("circuits", c, p);
  assert.match(fields.protection, /New GFCI name.*New reset location/);
  c.protection.resetLocation = "Under the cover";
  assert.equal(a.resolvedProtection(c.protection, c, p).resetLocation, "Under the cover");
  c.protection = protection("breaker");
  c.assignment = "7"; p.name = "Garage panel";
  assert.match(a.resolvedProtection(c.protection, c, p).resetLocation, /Garage panel.*7/);
});

test("moved and deleted protective endpoints preserve custom records and flag mappings for rechecking", () => {
  for (const remove of [false, true]) {
    const a = app(), p = panel(), c = p.circuits[0];
    c.protection = protection("point", 1); c.verification = confirmed();
    p.points.push({ id: 2, circuitId: 1, name: "Downstream", location: "Kitchen",
      verification: confirmed(), protection: protection("point", 1) });
    p.nextPointId = 3;
    p.points[0].protection = protection("breaker");
    a.configure(p); a.stubRendering();
    if (remove) a.deletePointRecord(p.points[0]);
    else a.updatePoint(target(1, "circuitId", "2", true), true);
    for (const record of [c, p.points.find(point => point.id === 2)]) {
      assert.equal(record.protection.deviceKind, "custom");
      assert.equal(record.protection.devicePointId, null);
      assert.match(record.protection.device, /Counter outlet/);
      assert.equal(record.protection.resetLocation, "Left of sink");
      assert.equal(record.verification.status, "needs-recheck");
    }
    if (!remove) {
      assert.equal(p.points[0].protection.deviceKind, "custom");
      assert.match(p.points[0].protection.resetLocation, /Main panel.*5/);
    }
    assert.doesNotThrow(() => a.assertPanel(p));
  }
});

test("self-protection follows a reassigned endpoint and circuit deletion preserves all override locations", () => {
  const a = app(), p = panel(), c = p.circuits[0];
  p.points[0].protection = protection("point", 1);
  a.configure(p); a.stubRendering();
  a.updatePoint(target(1, "circuitId", "2", true), true);
  assert.equal(p.points[0].protection.deviceKind, "point");
  assert.doesNotThrow(() => a.assertPanel(p));
  a.updatePoint(target(1, "circuitId", "1", true), true);
  p.points[0].verification = confirmed();
  p.points.push({ id: 2, circuitId: 1, name: "Downstream", location: "Other wall",
    protection: protection("point", 1), verification: confirmed() });
  p.nextPointId = 3;
  a.deleteCircuitRecord(c);
  for (const point of p.points) {
    assert.equal(point.circuitId, null);
    assert.equal(point.protection.deviceKind, "custom");
    assert.equal(point.protection.resetLocation, "Left of sink");
    assert.equal(point.verification.status, "needs-recheck");
  }
  assert.doesNotThrow(() => a.assertPanel(p));
});

test("import rejects missing, off-circuit, and malformed protective device references", () => {
  const a = app();
  for (const record of [{ deviceKind: "invalid" }, { deviceKind: ["point"] },
    { deviceKind: "point", devicePointId: true }, { deviceKind: "point", devicePointId: 0 },
    { deviceKind: "point", devicePointId: 1.1 }, { deviceKind: "breaker", devicePointId: 1 }]) {
    assert.throws(() => a.assertProtection(record));
  }
  const p = panel();
  p.circuits[1].protection = protection("point", 1);
  assert.throws(() => a.assertPanel(p), /same circuit/);
  p.circuits[1].protection = protection("point", 999);
  assert.throws(() => a.assertPanel(p), /same circuit/);
  delete p.circuits[1].protection;
  p.points[0].circuitId = null; p.points[0].protection = protection("breaker");
  assert.throws(() => a.assertPanel(p), /same circuit/);
});
