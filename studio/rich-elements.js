/* Rich geometry and transforms; load after canvas-motion.js. */
function chartSeriesProgress(item, index, p) {
	p = Math.max(0, Math.min(1, p));
	if (p === 1) return 1;
	const stagger = item.series_stagger ?? 0;
	return Math.max(0, Math.min(1,
		p * (1 + stagger * (item.values.length - 1)) - index * stagger,
	));
}
function drawTextChunks(node, item, time) {
	// Keep every source codepoint in the layout, including spaces and newlines.
	// Opacity-only spans avoid reflow and restore exactly on reverse seeks.
	const spans = [];
	item.chunks.forEach((chunk, chunkIndex) => {
		const characters = Array.from(chunk.text);
		const p = time === null ? 1 : Math.max(0, Math.min(1,
			(time - chunk.start) / chunk.duration,
		));
		const count = Math.floor(easeProgress(p, "ease-out") * characters.length);
		characters.forEach((character, index) => {
			const span = document.createElement("span");
			span.textContent = character;
			span.dataset.chunkIndex = String(chunkIndex);
			span.style.opacity = index < count ? "1" : "0";
			spans.push(span);
		});
	});
	node.replaceChildren(...spans);
}
function canvasPathPoints(item, width, height, p = 1) {
	const points = item.points.map(([x, y]) => [x * width, y * height]);
	p = Math.max(0, Math.min(1, p));
	if (p === 0) return [];
	if (p === 1) return points;
	const lengths = points.slice(1).map(([x, y], index) =>
		Math.hypot(x - points[index][0], y - points[index][1]),
	);
	let remaining = lengths.reduce((sum, length) => sum + length, 0) * p;
	const revealed = [points[0]];
	for (let index = 0; index < lengths.length; index++) {
		const length = lengths[index], start = points[index], end = points[index + 1];
		if (length <= remaining) {
			revealed.push(end);
			remaining -= length;
		} else {
			const fraction = remaining / length;
			revealed.push([
				start[0] + (end[0] - start[0]) * fraction,
				start[1] + (end[1] - start[1]) * fraction,
			]);
			break;
		}
	}
	return revealed;
}
function drawCanvasPath(node, item, p = 1) {
	// Layout dimensions, not transformed bounds: seeking must not alter geometry.
	const width = node.clientWidth, height = node.clientHeight;
	const namespace = "http://www.w3.org/2000/svg";
	const svg = document.createElementNS(namespace, "svg");
	svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
	svg.setAttribute("width", "100%");
	svg.setAttribute("height", "100%");
	svg.style.display = "block";
	const path = document.createElementNS(namespace, "polyline");
	path.setAttribute("points", canvasPathPoints(item, width, height, p)
		.map((point) => point.join(",")).join(" "));
	path.setAttribute("pathLength", "1");
	path.setAttribute("fill", "none");
	path.setAttribute("stroke", item.color);
	path.setAttribute("stroke-width", (item.stroke_width ?? 0.01) * Math.min(width, height));
	path.setAttribute("stroke-linecap", "round");
	path.setAttribute("stroke-linejoin", "round");
	svg.append(path);
	node.replaceChildren(svg);
}
function richMotionState(scene, item, time, baseMotionFn) {
	const state = { ...baseMotionFn(item, time) };
	const group = scene.groups?.find((group) => group.id === item.group);
	if (!group) return state;
	const members = scene.elements.filter((member) => member.group === group.id);
	const pose = keyframePose(group, time);
	for (const [axis, size, offset] of [["x", "w", "dx"], ["y", "h", "dy"]]) {
		const centre = (Math.min(...members.map((member) => member[axis])) +
			Math.max(...members.map((member) => member[axis] + member[size]))) / 2;
		state[offset] += pose[axis] + (item[axis] + item[size] / 2 - centre) * (pose.scale - 1);
	}
	state.scale *= pose.scale;
	state.opacity *= pose.opacity;
	return state;
}
