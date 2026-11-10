/* Numeric evidence is explicit user input; the model chooses how to show it, never its values. */
export function parseChartData(text = "") {
	if (!text.trim()) return null;
	const lines = text.trim().split("\n");
	if (lines.length < 2 || lines.length > 8)
		throw new Error("Chart data needs 2–8 label: value rows.");
	const labels = [],
		values = [];
	for (const line of lines) {
		const split = line.lastIndexOf(":");
		const label = line.slice(0, split).trim(),
			raw = line.slice(split + 1).trim();
		if (
			split < 1 ||
			!label ||
			label.length > 40 ||
			!raw ||
			!Number.isFinite(Number(raw)) ||
			Math.abs(Number(raw)) > 1000000
		)
			throw new Error(
				"Use chart rows like Week 1: 12, with finite numeric values.",
			);
		labels.push(label);
		values.push(Number(raw));
	}
	return { labels, values };
}
export function visualOptions(brief, slide) {
	if (slide.kind !== "body") return ["text", "accent"];
	if (!brief.chartData) return ["text", "accent", "card", "arrow"];
	const kinds = ["bar", "horizontal", "line", "area"];
	if (
		brief.chartData.values.every((v) => v >= 0) &&
		brief.chartData.values.some((v) => v > 0)
	)
		kinds.push("pie", "doughnut");
	return /chart|graph|counts|data|compare|trend/i.test(
		[brief.title, brief.description, ...(slide.topics || [])].join(" "),
	)
		? kinds
		: ["text", "accent", "card", "arrow", ...kinds];
}
export function applyVisualDesign(scene, design, brief, index, allowedDesigns = null) {
 const allowed=allowedDesigns || visualOptions(brief,{kind:index===0?'opening':scene.name==='Takeaway'?'closing':'body'});
 if(!allowed.includes(design))throw new Error('Unsupported generated visual design.');
	if (design === "text") return scene;
	const portrait =
		(brief.resolution?.height || 1080) > (brief.resolution?.width || 1920);
	const motion = brief.motion !== false,
		animation = motion
			? {
					animation: {
						effect: "scale",
						start: 0.2,
						duration: 0.6,
						easing: "ease-out",
					},
					exit_animation: {
						effect: "fade",
						start: scene.duration - 0.6,
						duration: 0.6,
						easing: "ease-out",
					},
				}
			: {};
	const chart = [
		"bar",
		"horizontal",
		"line",
		"area",
		"pie",
		"doughnut",
	].includes(design);
	const visual = {
		id: `scene-${index}-visual`,
		type: chart ? "chart" : "shape",
		x: 0.08,
		y: chart ? 0.39 : 0.04,
		w: chart ? 0.84 : 0.08,
		h: chart ? 0.4 : 0.04,
		color: "#bba5ff",
		...animation,
	};
	if (chart) {
		if (!brief.chartData) throw new Error("Charts require supplied data.");
		Object.assign(visual, {
			chart_type: design,
			labels: [...brief.chartData.labels],
			values: [...brief.chartData.values],
		});
		scene.elements[0].y = 0.08;
		scene.elements[0].h = 0.22;
		scene.elements[0].font_size = portrait ? 0.026 : 0.035;
		scene.elements[1].y = 0.82;
		scene.elements[1].h = 0.13;
		scene.elements[1].font_size = 0.025;
	} else if (design === "card") {
		Object.assign(visual, {
			shape: "rounded",
			x: 0.05,
			y: 0.06,
			w: 0.9,
			h: 0.56,
			color: "#302b43",
		});
	} else if (design === "arrow") {
		Object.assign(visual, {
			shape: "arrow",
			x: 0.78,
			y: 0.6,
			w: 0.12,
			h: 0.05,
		});
	} else visual.shape = "rect";
	scene.elements.unshift(visual);
	return scene;
}

export function validateChartData(data) {
	if (data == null) return;
	if (
		!Array.isArray(data.labels) ||
		!Array.isArray(data.values) ||
		data.labels.length < 2 ||
		data.labels.length > 8 ||
		data.labels.length !== data.values.length ||
		data.labels.some(
			(label) =>
				typeof label !== "string" || !label.trim() || label.length > 40,
		) ||
		data.values.some(
			(value) =>
				typeof value !== "number" ||
				!Number.isFinite(value) ||
				Math.abs(value) > 1000000,
		)
	)
		throw new Error(
			"Verified chart data must contain 2–8 matching labels and finite values.",
		);
}
