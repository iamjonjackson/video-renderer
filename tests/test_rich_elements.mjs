import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

function harness() {
	const context = vm.createContext({
		document: {
			createElement: (tag) => ({ tag, style: {}, dataset: {}, textContent: "" }),
			createElementNS: (_namespace, tag) => ({
			tag, attributes: {}, style: {}, children: [],
			setAttribute(key, value) { this.attributes[key] = String(value); },
			append(child) { this.children.push(child); },
		}) },
	});
	// Exercise the existing keyframe/easing implementation, excluding UI wiring.
	const motion = readFileSync(new URL("../studio/canvas-motion.js", import.meta.url), "utf8");
	vm.runInContext(motion.slice(0, motion.indexOf("function applyElementReveal")), context);
	vm.runInContext(readFileSync(new URL("../studio/rich-elements.js", import.meta.url), "utf8"), context);
	return context;
}
const plain = (value) => JSON.parse(JSON.stringify(value));

test("bar series have independently normalised starts, middles and actual endpoints", () => {
	const h = harness(), item = { values: [-2, 2, 0], series_stagger: 0.5 };
	for (const [p, expected] of [
		[-1, [0, 0, 0]], [0, [0, 0, 0]], [0.125, [0.25, 0, 0]],
		[0.375, [0.75, 0.25, 0]], [0.625, [1, 0.75, 0.25]],
		[1, [1, 1, 1]], [2, [1, 1, 1]],
	]) {
		assert.deepEqual(item.values.map((_, i) => h.chartSeriesProgress(item, i, p)), expected);
	}
	assert.equal(h.chartSeriesProgress({ values: [1, 2] }, 1, 0.25), 0.25);
	assert.equal(h.chartSeriesProgress({ values: [-2], series_stagger: 0.5 }, 0, 0.5), 0.5);
});

test("chunks retain full source and whitespace with indexed opacity-only spans on reverse seeks", () => {
	const h = harness(), item = { text: "AB  ÉF\nZ", chunks: [
		{ text: "AB  ", start: 0.5, duration: 1 },
		{ text: "ÉF\nZ", start: 2, duration: 1 },
	] };
	const node = { replaceChildren(...children) { this.children = children; } };
	const visible = () => node.children.filter((span) => span.style.opacity === "1").length;
	for (const [time, count] of [[0, 0], [0.5, 0], [1, 3], [1.5, 4], [2, 4], [2.5, 7], [3, 8], [20, 8], [1, 3], [null, 8]]) {
		h.drawTextChunks(node, item, time);
		assert.equal(visible(), count);
		assert.equal(node.children.map((span) => span.textContent).join(""), item.text);
		assert.deepEqual(node.children.map((span) => span.dataset.chunkIndex), ["0", "0", "0", "0", "1", "1", "1", "1"]);
		assert.ok(node.children.every((span) => Object.keys(span.style).join() === "opacity"));
	}
});
const path = { type: "path", color: "#ffffff", points: [[0, 0], [0.5, 0], [0.5, 1]] };

test("arc length uses the actual aspect ratio and interpolates endpoints", () => {
	const h = harness();
	assert.deepEqual(plain(h.canvasPathPoints(path, 200, 100, 0.75)), [[0, 0], [100, 0], [100, 50]]);
	assert.deepEqual(plain(h.canvasPathPoints(path, 100, 200, 0.5)), [[0, 0], [50, 0], [50, 75]]);
	assert.deepEqual(plain(h.canvasPathPoints(path, 200, 100, -1)), []);
	assert.deepEqual(plain(h.canvasPathPoints(path, 200, 100, 2)), [[0, 0], [100, 0], [100, 100]]);
	assert.deepEqual(plain(h.canvasPathPoints({ points: [[0.5, 0.5], [0.5, 0.5]] }, 100, 100, 0.5)), [[50, 50], [50, 50]]);
});

test("SVG rendering is deterministic and uses layout dimensions on reverse seek", () => {
	const h = harness();
	const node = { clientWidth: 200, clientHeight: 100, replaceChildren(child) { this.svg = child; } };
	h.drawCanvasPath(node, path, 0.75);
	const original = plain(node.svg);
	assert.equal(node.svg.attributes.viewBox, "0 0 200 100");
	assert.equal(node.svg.children[0].tag, "polyline");
	assert.deepEqual(node.svg.children[0].attributes, {
		points: "0,0 100,0 100,50", pathLength: "1", fill: "none", stroke: "#ffffff",
		"stroke-width": "1", "stroke-linecap": "round", "stroke-linejoin": "round",
	});
	h.drawCanvasPath(node, path, 0);
	assert.equal(node.svg.children[0].attributes.points, "");
	h.drawCanvasPath(node, path);
	assert.equal(node.svg.children[0].attributes.points, "0,0 100,0 100,100");
	h.drawCanvasPath(node, path, 0.75);
	assert.deepEqual(plain(node.svg), original);
});

function scene() {
	return { elements: [
		{ id: "left", group: "pair", x: 0.1, y: 0.2, w: 0.2, h: 0.2 },
		{ id: "right", group: "pair", x: 0.5, y: 0.2, w: 0.2, h: 0.2 },
		{ id: "unrelated", x: 0, y: 0, w: 1, h: 1 },
	], groups: [{ id: "pair", keyframes: [
		{ time: 0, x: 0, y: 0, scale: 1, opacity: 1 },
		{ time: 2, x: 0.1, y: 0.2, scale: 1.5, opacity: 0.5 },
	] }] };
}
const close = (actual, expected) => {
	for (const [key, value] of Object.entries(expected)) assert.ok(Math.abs(actual[key] - value) < 1e-12, `${key}: ${actual[key]} != ${value}`);
};

test("group pivot includes only members and composes additive offsets and centred scale", () => {
	const h = harness(), s = scene(), original = structuredClone(s);
	const base = { dx: 0.04, dy: -0.02, scale: 0.8, opacity: 0.4 };
	const baseFn = () => base;
	close(h.richMotionState(s, s.elements[0], 2, baseFn), { dx: 0.04, dy: 0.18, scale: 1.2, opacity: 0.2 });
	close(h.richMotionState(s, s.elements[1], 2, baseFn), { dx: 0.24, dy: 0.18, scale: 1.2, opacity: 0.2 });
	close(h.richMotionState(s, s.elements[0], 1, baseFn), { dx: 0.04, dy: 0.08, scale: 1, opacity: 0.3 });
	assert.deepEqual(plain(h.richMotionState(s, s.elements[2], 2, baseFn)), base);
	assert.deepEqual(s, original);
	assert.deepEqual(base, { dx: 0.04, dy: -0.02, scale: 0.8, opacity: 0.4 });
});

test("group motion reuses existing keyframes and is stateless on out-of-order seeks", () => {
	const h = harness(), s = scene();
	s.elements[0].keyframes = [
		{ time: 0, x: 0.04, y: 0, scale: 0.8, opacity: 0.4 },
		{ time: 2, x: 0.04, y: 0, scale: 0.8, opacity: 0.4 },
	];
	const end = h.richMotionState(s, s.elements[0], 2, h.motionState);
	close(end, { dx: 0.04, dy: 0.2, scale: 1.2, opacity: 0.2 });
	h.richMotionState(s, s.elements[0], 0, h.motionState);
	assert.deepEqual(plain(h.richMotionState(s, s.elements[0], 2, h.motionState)), plain(end));
	assert.deepEqual(plain(h.richMotionState(s, s.elements[0], 10, h.motionState)), plain(end));
});
