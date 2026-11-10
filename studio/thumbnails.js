/* Passive miniature canvases use the same geometry and chart renderer as the editor. */
function renderSceneThumbnail(frame, scene) {
	const preview = editableScene(scene, project.theme);
	const resolution = project.meta?.resolution || { width: 1920, height: 1080 };
	frame.replaceChildren();
	frame.setAttribute("aria-hidden", "true");
	frame.style.aspectRatio = `${resolution.width}/${resolution.height}`;
	frame.style.background = preview.background?.color || "#191925";
	const background = element("span", undefined, "canvas-background");
	background.dataset.style = preview.background?.style || "solid";
	background.style.setProperty(
		"--bg-accent",
		preview.background?.accent || "#6750a4",
	);
	frame.append(background);
	for (const item of preview.elements) {
		const node = element("span", undefined, `thumbnail-element ${item.type}`);
		positionNode(node, item);
		node.style.color = item.color;
		if (item.type === "text") {
			node.textContent = item.text;
			node.style.fontSize = `${item.font_size * 100}cqh`;
			node.style.fontWeight = item.bold ? "700" : "400";
			node.style.textAlign = item.align || "left";
		} else if (item.type === "shape") {
			node.style.background = item.color;
			styleShape(node,item);
		} else drawChart(node, item);
		frame.append(node);
	}
}
function refreshSceneThumbnails() {
	document.querySelectorAll("#scenes .mini-frame").forEach((frame, index) => {
		if (project.timeline[index])
			renderSceneThumbnail(frame, project.timeline[index]);
	});
}
