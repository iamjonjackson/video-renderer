/* A shot is a timed reading order, compiled to portable element tracks, not executable AI code. */
export const shotKinds = ["build", "spotlight", "visual-first", "text-first"];
export function directSequence(
	scene,
	{ shot = "build", motionStyle = "balanced" } = {},
) {
	if (!shotKinds.includes(shot)) throw new Error("Unsupported shot direction.");
	const D = scene.duration,
		settle = Math.min(1.2, D * 0.22),
		reveal = D * 0.38,
		hold = D * 0.72;
	const texts = scene.elements.filter(
		(i) => i.type === "text" && !i.id.endsWith("-chapter"),
	);
	const heading = texts[0],
		body = texts[1],
		visual = scene.elements.find((i) =>
			["image", "chart", "icon"].includes(i.type),
		);
	const subtle = Math.min(
		heading?.y || 0,
		Math.max(0, 1 - (heading?.y || 0) - (heading?.h || 0)),
		motionStyle === "calm"
			? 0.008
			: motionStyle === "energetic"
				? 0.025
				: 0.015,
	);
	if (["visual-first", "text-first"].includes(shot) && !visual)
		throw new Error("The selected shot needs an image, chart or symbol.");
	const pose = (time, { x = 0, y = 0, scale = 1, opacity = 1 } = {}) => ({
		time,
		x,
		y,
		scale,
		opacity,
	});
	for (const item of scene.elements) {
		delete item.keyframes;
	}
	if (body) {
		// Explanations enter after the focal idea has been established, not all at once.
		if (body.animation) {
			body.animation.start = reveal;
			body.animation.duration = Math.min(body.animation.duration, D * 0.18);
		}
		body.keyframes = [
			pose(0, { opacity: 0 }),
			pose(Math.max(0.01, reveal - 0.15), { opacity: 0 }),
			pose(reveal + Math.min(0.25, D * 0.12)),
			pose(D),
		];
	}
	if (shot === "spotlight" && heading) {
		// Quiet emphasis: one type block advances, then settles before the supporting copy.
		heading.keyframes = [
			pose(0, { y: subtle }),
			pose(settle),
			pose(reveal, { y: -subtle }),
			pose(hold),
			pose(D),
		];
	}
	if (visual && shot === "visual-first") {
		if (visual.animation) {
			visual.animation.start = 0;
			visual.animation.duration = Math.min(visual.animation.duration, settle);
		}
		if (heading?.animation) {
			heading.animation.start = settle;
			heading.animation.duration = Math.min(
				heading.animation.duration,
				D * 0.18,
			);
		}
		// Zoom inward only when there is safe room; images retain their original crop box.
		visual.keyframes = [
			pose(0, { scale: 0.96 }),
			pose(settle),
			pose(hold),
			pose(D),
		];
	}
	if (visual && shot === "text-first") {
		if (visual.animation) {
			visual.animation.start = reveal;
			visual.animation.duration = Math.min(visual.animation.duration, D * 0.22);
		}
		visual.keyframes = [
			pose(0, { opacity: 0 }),
			pose(Math.max(0.01, reveal - 0.15), { opacity: 0 }),
			pose(reveal + Math.min(0.3, D * 0.12)),
			pose(D),
		];
	}
	scene.motion_version = 1;
	return scene;
}
export function shotPrompt() {
	return "Direct a shot, not a slide: build establishes a headline then reveals supporting context; spotlight gently moves the headline before settling; visual-first reveals the chart/image/symbol before the headline; text-first establishes the claim then brings in evidence. Choose based on what viewers must read first. Avoid visual-first when there is no visual. Leave a clear reading hold; do not animate every element continuously.";
}
