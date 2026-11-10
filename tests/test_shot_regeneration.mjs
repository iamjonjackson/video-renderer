import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

test("superseded Apply cannot import or clear a newer shot candidate", async () => {
	const nodes = new Map();
	const $ = (id) => {
		if (!nodes.has(id))
			nodes.set(id, {
				value: "",
				checked: true,
				showPopover() {},
				hidePopover() {},
			});
		return nodes.get(id);
	};
	const project = {
		timeline: [
			{ type: "composition", elements: [] },
			{ type: "composition", elements: [] },
		],
	};
	let release,
		imports = 0;
	const context = vm.createContext({
		$,
		project,
		selected: 0,
		structuredClone,
		JSON,
		Error,
		importProject() {
			imports++;
		},
		drawCanvas() {},
		drawScenes() {},
		announce() {},
		request: () =>
			new Promise((resolve) => {
				release = resolve;
			}),
	});
	vm.runInContext(
		readFileSync(
			new URL("../studio/shot-regeneration.js", import.meta.url),
			"utf8",
		),
		context,
	);
	vm.runInContext(
		`shotCandidate={type:'composition',elements:[]};shotBaseline=JSON.stringify(project);shotIndex=0;`,
		context,
	);
	const pending = $("shot-apply").onclick();
	vm.runInContext(
		`shotOperation++;shotIndex=1;shotCandidate={type:'composition',name:'newer',elements:[]};`,
		context,
	);
	release({ spec: structuredClone(project) });
	await pending;
	assert.equal(imports, 0);
	assert.equal(vm.runInContext("shotCandidate.name", context), "newer");
});
