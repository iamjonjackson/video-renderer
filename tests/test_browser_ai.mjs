import { test } from "node:test";
import assert from "node:assert/strict";
import {
	parseStoryboard,
	slidePlan,
	presentationSchema,
} from "../studio/ai-protocol.mjs";
const spec = {
	meta: { title: "Test" },
	timeline: [
		{ type: "title", text: "Open", duration: 3 },
		{
			type: "bullets",
			heading: "Facts",
			items: ["A fact", "Another fact"],
			duration: 4,
		},
		{
			type: "bullets",
			heading: "Action",
			items: ["A next step", "An action"],
			duration: 7,
		},
		{ type: "outro", text: "Close", duration: 3 },
	],
};
test("complete plain and fenced JSON accepted", () => {
	assert.deepEqual(parseStoryboard(JSON.stringify(spec)), spec);
	assert.deepEqual(
		parseStoryboard("```json\n" + JSON.stringify(spec) + "\n```"),
		spec,
	);
});
test("prose, truncation, wrong shapes and generated charts rejected", () => {
	for (const value of [
		"Here is your JSON: " + JSON.stringify(spec),
		JSON.stringify(spec).slice(0, -1),
		"null",
		'{"timeline":[]}',
		JSON.stringify({
			...spec,
			timeline: [...spec.timeline, { type: "chart" }],
		}),
	])
		assert.throws(() => parseStoryboard(value));
});

test("source points determine complete ordered deck without invented topics", () => {
	const brief = {
		title: "A project",
		description: "Explain the proposed plan to a general audience.",
		points: ["First fact", "Second fact", "Third fact"],
		structure: "explainer",
	};
	const plan = slidePlan(brief),
		schema = presentationSchema(brief, plan);
	assert.equal(plan.length, 5);
	assert.deepEqual(
		plan.slice(1, -1).map((s) => s.topics),
		[["First fact"], ["Second fact"], ["Third fact"]],
	);
	assert.equal(
		schema.properties.timeline.items[0].properties.text.const,
		"A project",
	);
	assert.equal(
		schema.properties.timeline.items[2].properties.heading.const,
		"Second fact",
	);
	assert.equal(
		schema.properties.timeline.items.at(-1).properties.type.const,
		"outro",
	);
	assert.throws(() => slidePlan({ ...brief, structure: "unknown" }));
});
