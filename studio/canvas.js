/* Direct canvas editing. Normalised positions are the exported source of truth. */
let selectedElement = null;
let drag = null;
let previewAnimation = null;
let contentTarget = null;
let contentScene = null;
let contentReturn = null;
let inlineEditing = null;
let chartEditing = null;
function fitCanvas() {
	if ($("editor-page").hidden) return;
	const canvas = $("canvas"),
		wrap = canvas.parentElement,
		res = project.meta?.resolution || { width: 1920, height: 1080 };
	const padding = parseFloat(getComputedStyle(wrap).paddingLeft) || 0;
	const width = Math.min(
		Math.max(100, wrap.clientWidth - padding * 2),
		(Math.max(1, wrap.clientHeight - padding * 2) * res.width) / res.height,
	);
	canvas.style.setProperty("width", `${width}px`, "important");
	canvas.style.setProperty(
		"height",
		`${(width * res.height) / res.width}px`,
		"important",
	);
	canvas.style.setProperty("min-height", "0", "important");
	canvas.style.setProperty("flex", "none", "important");
	canvas.style.aspectRatio = `${res.width}/${res.height}`;
	syncCanvasTools();
}
function syncResizeHandles() {
	const overlay = $("resize-handles");
	const item = itemById();
	if (!item || inlineEditing || chartEditing) {
		overlay.hidden = true;
		return;
	}
	const canvas = $("canvas").getBoundingClientRect(),
		wrap = $("canvas").parentElement.getBoundingClientRect();
	overlay.hidden = false;
	overlay.style.left = `${canvas.left - wrap.left + item.x * canvas.width}px`;
	overlay.style.top = `${canvas.top - wrap.top + item.y * canvas.height}px`;
	overlay.style.width = `${item.w * canvas.width}px`;
	overlay.style.height = `${item.h * canvas.height}px`;
}
function resizedGeometry(original, edge, dx, dy) {
	let left = original.x,
		top = original.y,
		right = original.x + original.w,
		bottom = original.y + original.h;
	if (edge.includes("w")) left = Math.max(0, Math.min(right - 0.02, left + dx));
	if (edge.includes("e"))
		right = Math.min(1, Math.max(left + 0.02, right + dx));
	if (edge.includes("n")) top = Math.max(0, Math.min(bottom - 0.02, top + dy));
	if (edge.includes("s"))
		bottom = Math.min(1, Math.max(top + 0.02, bottom + dy));
    // Subtraction can place the legal minimum just below .02 in floating point.
	return { x: left, y: top, w: Math.max(0.02, right - left), h: Math.max(0.02, bottom - top) };
}
for (const edge of ["nw", "n", "ne", "e", "se", "s", "sw", "w"]) {
	const handle = element("button", undefined, `resize-handle handle-${edge}`);
	handle.type = "button";
	handle.dataset.edge = edge;
	handle.setAttribute(
		"aria-label",
		`Resize ${{ nw: "top left", n: "top", ne: "top right", e: "right", se: "bottom right", s: "bottom", sw: "bottom left", w: "left" }[edge]} edge. Use arrow keys.`,
	);
	handle.onpointerdown = (event) => {
		if (event.button !== 0) return;
		event.preventDefault();
		event.stopPropagation();
		stopInterfaceMotion();
		const item = itemById();
		if (!item) return;
		handle.focus();
		handle.setPointerCapture(event.pointerId);
		const original = { x: item.x, y: item.y, w: item.w, h: item.h };
		const start = { x: event.clientX, y: event.clientY };
		const bounds = $("canvas").getBoundingClientRect();
		const apply = () => {
			const node = $("canvas").querySelector(`[data-id="${item.id}"]`);
			if (node) positionNode(node, item);
			syncResizeHandles();
		};
		let resizing = true;
		handle.onpointermove = (e) => {
			if (
				!resizing ||
				e.pointerId !== event.pointerId ||
				!handle.hasPointerCapture(e.pointerId)
			)
				return;
			Object.assign(
				item,
				resizedGeometry(
					original,
					edge,
					(e.clientX - start.x) / bounds.width,
					(e.clientY - start.y) / bounds.height,
				),
			);
			apply();
		};
		const finish = (e) => {
			if (!resizing) return;
			resizing = false;
			if (e.type !== "pointerup") {
				Object.assign(item, original);
				apply();
			}
			save();
		};
		handle.onpointerup = finish;
		handle.onpointercancel = finish;
		handle.onlostpointercapture = finish;
	};
	handle.onkeydown = (event) => {
		const vectors = {
			ArrowLeft: [-0.005, 0],
			ArrowRight: [0.005, 0],
			ArrowUp: [0, -0.005],
			ArrowDown: [0, 0.005],
		};
		if (!vectors[event.key]) return;
		event.preventDefault();
		const item = itemById();
		if (!item) return;
		const multiplier = event.shiftKey ? 4 : 1;
		Object.assign(
			item,
			resizedGeometry(
				item,
				edge,
				vectors[event.key][0] * multiplier,
				vectors[event.key][1] * multiplier,
			),
		);
		positionNode($("canvas").querySelector(`[data-id="${item.id}"]`), item);
		syncResizeHandles();
		save();
		announce("Element resized.");
	};
	$("resize-handles").append(handle);
}
const paths = {
	scene: "M4 5h16v14H4z M8 9h8 M8 13h6",
	chart: "M5 19V9 M12 19V5 M19 19v-7 M3 21h18",
	moon: "M20 14A8 8 0 0 1 10 4a8 8 0 1 0 10 10Z",
	sun: "M12 8a4 4 0 1 0 0 8a4 4 0 0 0 0-8 M12 2v2 M12 20v2 M2 12h2 M20 12h2 M5 5l1 1 M18 18l1 1 M5 19l1-1 M18 6l1-1",
	plus: "M12 5v14 M5 12h14",
	text: "M5 5h14 M12 5v14 M8 19h8",
	shape: "M5 5h14v14H5z",
	palette:
		"M12 3a9 9 0 1 0 0 18h1a2 2 0 0 0 1-4 2 2 0 0 1 0-4h3a4 4 0 0 0 4-4c0-4-4-6-9-6z M7 9h.01 M11 6h.01 M16 7h.01 M6 14h.01",
	upload: "M12 16V3 M7 8l5-5 5 5 M4 16v5h16v-5",
	download: "M12 3v13 M7 11l5 5 5-5 M4 16v5h16v-5",
	close: "M6 6l12 12 M18 6 6 18",
	edit: "m4 16 12-12 4 4-12 12-5 1z M13 7l4 4",
	trash: "M4 7h16 M9 7V4h6v3 M6 7l1 13h10l1-13 M10 11v5 M14 11v5",
	layers: "m12 3 9 5-9 5-9-5z M3 12l9 5 9-5 M3 16l9 5 9-5",
	more: "M5 12h.01 M12 12h.01 M19 12h.01",
	sparkle: "m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z",
	arrow: "M19 12H5 M11 6l-6 6 6 6",
};
function icon(name) {
	const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
	svg.setAttribute("viewBox", "0 0 24 24");
	svg.setAttribute("aria-hidden", "true");
	svg.setAttribute("focusable", "false");
	svg.classList.add("ui-icon");
	const path = document.createElementNS(svg.namespaceURI, "path");
	path.setAttribute("d", paths[name] || paths.scene);
	path.setAttribute("fill", "none");
	path.setAttribute("stroke", "currentColor");
	path.setAttribute("stroke-width", "2.5");
	path.setAttribute("stroke-linecap", "round");
	path.setAttribute("stroke-linejoin", "round");
	svg.append(path);
	return svg;
}
function textElement(
	text,
	x = 0.1,
	y = 0.3,
	w = 0.8,
	h = 0.25,
	size = 0.07,
	color = "#f5f0ff",
) {
	return {
		id: crypto.randomUUID(),
		type: "text",
		text,
		x,
		y,
		w,
		h,
		font_size: size,
		color,
		align: "left",
		bold: false,
	};
}
function canvasTemplate(kind) {
	const scene = {
		type: "composition",
		name:
			{
				blank: "Blank canvas",
				title: "Opening",
				quote: "Quote",
				data: "Data story",
				compare: "Comparison",
				closing: "Closing",
			}[kind] || "Canvas",
		duration: 4,
		background: {
			style: kind === "title" ? "orbits" : "solid",
			color: "#191925",
			accent: "#6750a4",
			motion: "none",
		},
		elements: [],
	};
	if (kind === "title")
		scene.elements = [
			{
				...textElement("Your next big idea", 0.1, 0.34, 0.8, 0.3, 0.09),
				bold: true,
			},
			textElement(
				"A story worth telling",
				0.1,
				0.67,
				0.8,
				0.15,
				0.04,
				"#bba5ff",
			),
		];
	if (kind === "quote")
		scene.elements = [
			textElement(
				"A clear thought can change a conversation.",
				0.12,
				0.25,
				0.76,
				0.45,
				0.075,
			),
			textElement("Add attribution", 0.12, 0.75, 0.76, 0.1, 0.03, "#bba5ff"),
		];
	if (kind === "data")
		scene.elements = [
			textElement("Your data, in focus", 0.08, 0.07, 0.84, 0.15, 0.065),
			{
				id: crypto.randomUUID(),
				type: "chart",
				chart_type: "bar",
				labels: ["Example A", "Example B", "Example C"],
				values: [20, 40, 60],
				x: 0.1,
				y: 0.3,
				w: 0.8,
				h: 0.6,
				color: "#bba5ff",
			},
		];
	if (kind === "compare")
		scene.elements = [
			textElement("Two perspectives", 0.08, 0.07, 0.84, 0.15, 0.065),
			textElement(
				"First idea\nAdd your argument",
				0.08,
				0.35,
				0.39,
				0.5,
				0.045,
			),
			textElement(
				"Second idea\nAdd your argument",
				0.53,
				0.35,
				0.39,
				0.5,
				0.045,
			),
		];
	if (kind === "closing")
		scene.elements = [
			{
				...textElement(
					"What happens next?",
					0.1,
					0.38,
					0.8,
					0.3,
					0.085,
					"#bba5ff",
				),
				align: "center",
				bold: true,
			},
		];
	return scene;
}
function currentScene() {
	return project.timeline[selected];
}
function itemById() {
	return currentScene().elements?.find((item) => item.id === selectedElement);
}
function editableScene(old, theme = {}) {
	if (old.type === "composition") return old;
	const elements = [];
	const fg = theme.fg || "#f5f0ff";
	const accent = theme.accent || "#bba5ff";
	if (old.type === "title" || old.type === "outro") {
		elements.push({
			...textElement(
				old.text,
				0.1,
				0.32,
				0.8,
				0.3,
				0.085,
				old.type === "outro" ? accent : fg,
			),
			bold: true,
			align: "center",
		});
		if (old.subtitle)
			elements.push({
				...textElement(old.subtitle, 0.1, 0.65, 0.8, 0.15, 0.04, accent),
				align: "center",
			});
	}
	if (old.type === "bullets") {
		if (old.heading)
			elements.push(
				textElement(old.heading, 0.08, 0.08, 0.84, 0.18, 0.06, accent),
			);
		const rowHeight = Math.min(0.2, 0.58 / old.items.length);
		old.items.forEach((point, index) =>
			elements.push(
				textElement(
					"• " + point,
					0.1,
					0.33 + index * rowHeight,
					0.8,
					rowHeight,
					0.04,
					fg,
				),
			),
		);
	}
	if (old.type === "chart") {
		if (old.heading)
			elements.push(textElement(old.heading, 0.08, 0.07, 0.84, 0.15, 0.06, fg));
		elements.push({
			id: crypto.randomUUID(),
			type: "chart",
			chart_type: old.chart_type || "bar",
			labels: [...old.labels],
			values: [...old.values],
			x: 0.1,
			y: 0.3,
			w: 0.8,
			h: 0.6,
			color: accent,
		});
	}
	const scene = {
		type: "composition",
		name: sceneLabel(old).slice(0, 100),
		duration: old.duration || 4,
		background: {
			style: "solid",
			color: theme.bg || "#191925",
			accent,
			motion: "none",
		},
		elements,
	};
	if (old.narration_per_bullet)
		scene.narration = old.narration_per_bullet.join("\n");
	else if (old.narration) scene.narration = old.narration;
	if (old.padding !== undefined) scene.padding = old.padding;
	return scene;
}
function convertScene() {
	if (currentScene().type === "composition") return;
	project.timeline[selected] = editableScene(currentScene(), project.theme);
	selectedElement = null;
	update();
	syncCanvasTools();
	announce(
		"Converted to an editable canvas. Layout and animation may differ; original narration notes are retained.",
	);
}
function styleShape(node,item){node.style.borderRadius=item.shape==="ellipse"?"50%":item.shape==="rounded"?"20%":"0";node.style.clipPath=item.shape==="triangle"?"polygon(50% 0,100% 100%,0 100%)":item.shape==="arrow"?"polygon(0 33%,66% 33%,66% 0,100% 50%,66% 100%,66% 66%,0 66%)":"none";}
function positionNode(node, item) {
	node.style.left = `${item.x * 100}%`;
	node.style.top = `${item.y * 100}%`;
	node.style.width = `${item.w * 100}%`;
	node.style.height = `${item.h * 100}%`;
}
function stopPreview() {
	previewAnimation?.cancel();
	previewAnimation = null;
	if ($("preview-motion")) $("preview-motion").textContent = "Preview motion";
}
function drawCanvas() {
	stopInterfaceMotion($("canvas"));
	chartEditing = null;
	if (contentScene && contentScene !== currentScene()) {
		$("content-editor").hidden = true;
		contentScene = null;
	}
	finishInlineEditing();
	stopPreview();
	selectedElement = currentScene().elements?.some(
		(i) => i.id === selectedElement,
	)
		? selectedElement
		: null;
	if (currentScene().type !== "composition") {
		project.timeline[selected] = editableScene(currentScene(), project.theme);
		save();
	}
	const scene = currentScene();
	const res = project.meta?.resolution || { width: 1920, height: 1080 };
	$("canvas").style.aspectRatio = `${res.width}/${res.height}`;
	$("canvas").style.setProperty("--canvas-ratio", res.width / res.height);
	$("preview-name").textContent =
		`Scene ${selected + 1} · ${scene.name || names[scene.type]}`;
	const availableWidth = Math.max(
		100,
		$("canvas").parentElement.clientWidth -
			2 * parseFloat(getComputedStyle($("canvas").parentElement).paddingLeft),
	);
	$("canvas").style.width =
		`${Math.min(availableWidth, (620 * res.width) / res.height)}px`;
	$("canvas").style.flex = "none";
	$("canvas").style.height =
		`${(Math.min(availableWidth, (620 * res.width) / res.height) * res.height) / res.width}px`;
	if (scene.type !== "composition") {
		$("canvas").classList.remove("freeform");
		drawLegacyCanvas();
		syncCanvasTools();
		return;
	}
	const canvas = $("canvas");
	canvas.replaceChildren();
	canvas.classList.add("freeform");
	canvas.style.background = scene.background?.color || "#191925";
	canvas.style.color = "#f5f0ff";
	const bg = element("div", undefined, "canvas-background");
	const config = scene.background || {};
	bg.dataset.style = config.style || "solid";
	bg.style.setProperty("--bg-accent", config.accent || "#6750a4");
	canvas.append(bg);
	for (const item of scene.elements) {
		const node = element("div", undefined, `canvas-element ${item.type}`);
		node.dataset.id = item.id;
		node.tabIndex = 0;
		node.setAttribute("role", "button");
		node.setAttribute(
			"aria-label",
			`${item.text || item.labels?.join(" ") || item.shape} ${item.type} element. Use arrow keys to move; Enter to edit.`,
		);
		node.setAttribute("aria-pressed", String(selectedElement === item.id));
		positionNode(node, item);
		node.style.color = item.color;
		if (item.type === "text") {
			node.textContent = item.text;
			node.style.whiteSpace = "pre-wrap";
			node.style.fontSize = `${item.font_size * 100}cqh`;
			node.style.fontWeight = item.bold ? "700" : "400";
			node.style.textAlign = item.align || "left";
		} else if (item.type === "shape") {
			node.style.background = item.color;
			styleShape(node,item);
		} else drawChart(node, item);
		if (item.type === "chart")
			node.setAttribute(
				"aria-label",
				`${node.textContent} chart element. Use arrow keys to move; Enter to edit.`,
			);
		node.onclick = () => {
			if (!node.isContentEditable) selectElement(item.id);
		};
		node.oncontextmenu = (event) => {
			event.preventDefault();
			finishInlineEditing();
			selectElement(item.id);
			showElementOptions(event.clientX, event.clientY);
		};
		node.ondblclick = (event) => {
			if (!event.target.closest(".chart-direct-editor")) openContent(item);
		};
		node.onpointerdown = (event) => startDrag(event, node, item);
		node.onkeydown = (event) => {
			if (
				event.key === "ContextMenu" ||
				(event.shiftKey && event.key === "F10")
			) {
				event.preventDefault();
				selectElement(item.id);
				showElementOptions();
				return;
			}
			if (event.target !== node) return;
			if (
				!node.isContentEditable &&
				(event.key === "Backspace" || event.key === "Delete")
			) {
				event.preventDefault();
				selectElement(item.id);
				deleteElement();
				return;
			}
			if (node.isContentEditable) {
				if (event.key === "Escape") {
					event.preventDefault();
					item.text = inlineEditing.original;
					node.textContent = item.text;
					finishInlineEditing();
				} else if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
					event.preventDefault();
					finishInlineEditing();
				}
				return;
			}
			if (event.key === " ") {
				event.preventDefault();
				selectElement(item.id);
				return;
			}
			if (event.key === "Enter") {
				event.preventDefault();
				selectElement(item.id);
				openContent(item);
				return;
			}
			if (event.key === "Escape") {
				selectedElement = null;
				syncCanvasTools();
				drawSelection();
				return;
			}
			const directions = {
				ArrowLeft: [-1, 0],
				ArrowRight: [1, 0],
				ArrowUp: [0, -1],
				ArrowDown: [0, 1],
			};
			if (directions[event.key]) {
				event.preventDefault();
				const step = event.shiftKey ? 0.02 : 0.005;
				item.x = Math.max(
					0,
					Math.min(1 - item.w, item.x + directions[event.key][0] * step),
				);
				item.y = Math.max(
					0,
					Math.min(1 - item.h, item.y + directions[event.key][1] * step),
				);
				positionNode(node, item);
				syncCanvasTools();
				save();
				announce(
					`Element position ${Math.round(item.x * 100)} percent across, ${Math.round(item.y * 100)} percent down.`,
				);
			}
		};
		canvas.append(node);
	}
	drawSelection();
	syncCanvasTools();
	fitCanvas();
	refreshSceneThumbnails();
}
function drawChart(node, item) {
	const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
	svg.setAttribute("viewBox", "0 0 400 240");
	svg.setAttribute("aria-hidden", "true");
	const max = Math.max(1, ...item.values.map(Math.abs));
 const low=Math.min(0,...item.values),high=Math.max(0,...item.values),span=high-low||1,baseline=190-(0-low)/span*160;
	const ns = svg.namespaceURI;
	if (["pie","doughnut"].includes(item.chart_type)) {
		let angle = 0;
		const total = item.values.reduce((a, b) => a + b, 0);
		item.values.forEach((value, i) => {
			const end = angle + (value / total) * Math.PI * 2;
			const path = document.createElementNS(ns, "path");
			const x1 = 200 + 85 * Math.cos(angle),
				y1 = 100 + 85 * Math.sin(angle),
				x2 = 200 + 85 * Math.cos(end),
				y2 = 100 + 85 * Math.sin(end);
			path.setAttribute(
				"d",
				`M200 100 L${x1} ${y1} A85 85 0 ${end - angle > Math.PI ? 1 : 0} 1 ${x2} ${y2} Z`,
			);
			path.setAttribute("fill", item.color);
			path.setAttribute("opacity", String(1 - i * 0.08));
			svg.append(path);
			angle = end;
		});
 if(item.chart_type==="doughnut"){const clip=document.createElementNS(ns,'clipPath'),path=document.createElementNS(ns,'path');const id='ring-'+crypto.randomUUID();clip.id=id;path.setAttribute('d','M115 15h170v170H115z M248 100a48 48 0 1 0-96 0a48 48 0 1 0 96 0');path.setAttribute('clip-rule','evenodd');clip.append(path);svg.prepend(clip);svg.querySelectorAll(':scope > path').forEach(slice=>slice.setAttribute('clip-path',`url(#${id})`));}
	} else {
 if(["line","area"].includes(item.chart_type)){const line=document.createElementNS(ns,"path");const points=item.values.map((v,i)=>`${35+i*(330/item.values.length)+15},${190-(v-low)/span*160}`);line.setAttribute("d","M"+points.join(" L")+(item.chart_type==="area"?` L${35+(item.values.length-1)*(330/item.values.length)+15},${baseline} L50,${baseline} Z`:""));line.setAttribute("fill",item.chart_type==="area"?item.color:"none");line.setAttribute("fill-opacity",".3");line.setAttribute("stroke",item.color);line.setAttribute("stroke-width","3");svg.append(line);}
		item.values.forEach((v, i) => {
			const x = 35 + i * (330 / item.values.length);
			const height = Math.abs(v)/span*160;
			const shape = document.createElementNS(
				ns,
				["line","area"].includes(item.chart_type) ? "circle" : "rect",
			);
			if (["line","area"].includes(item.chart_type)) {
				shape.setAttribute("cx", String(x + 15));
				shape.setAttribute("cy", String(190-(v-low)/span*160));
				shape.setAttribute("r", "5");
			} else {
				shape.setAttribute("x", String(x));
				shape.setAttribute("y", String(v>=0?baseline-height:baseline));
				shape.setAttribute("width", String(220 / item.values.length));
				shape.setAttribute("height", String(height));
			}
			shape.setAttribute("fill", item.color);
			if(item.chart_type==="horizontal"){shape.setAttribute("x",String(100+(Math.min(0,v)-low)/span*280));shape.setAttribute("y",String(10+i*180/item.values.length));shape.setAttribute("width",String(Math.abs(v)/span*280));shape.setAttribute("height",String(130/item.values.length));}
			svg.append(shape);
		});
 }
	item.labels.forEach((label, i) => {
		const text = document.createElementNS(ns, "text");
		text.setAttribute("x", item.chart_type==="horizontal"?"5":String(35 + (i * 330) / item.labels.length));
		text.setAttribute("y",item.chart_type==="horizontal"?String(30+i*180/item.labels.length):"222");
		text.setAttribute("fill", item.color);
		text.setAttribute("font-size", "13");
		text.textContent = label;
		svg.append(text);
	});
	node.append(svg);
}
function drawSelection() {
	syncResizeHandles();
	for (const node of $("canvas").querySelectorAll(".canvas-element")) {
		node.classList.toggle("selected", node.dataset.id === selectedElement);
		node.setAttribute(
			"aria-pressed",
			String(node.dataset.id === selectedElement),
		);
	}
}
function showElementOptions(x, y) {
	const menu = $("context-tools");
	const item = itemById();
	if (!item) return;
	syncCanvasTools();
	if (!menu.matches(":popover-open")) menu.showPopover();
	const anchor = $("element-options").getBoundingClientRect();
	menu.style.left = `${Math.max(12, Math.min(x ?? anchor.left, innerWidth - menu.offsetWidth - 12))}px`;
	menu.style.top = `${Math.max(12, Math.min(y ?? anchor.bottom, innerHeight - menu.offsetHeight - 12))}px`;
	$("edit-element").focus();
	enterInterface(menu, { distance: 5, duration: 160, scale: 0.98 });
}
$("element-options").onclick = () => showElementOptions();
function closeElementOptions(restore = true) {
	const menu = $("context-tools");
	if (menu.matches(":popover-open")) menu.hidePopover();
	stopInterfaceMotion(menu);
	if (restore && !$("element-options").hidden) $("element-options").focus();
}
$("options-close").onclick = () => closeElementOptions();
document.addEventListener(
	"pointerdown",
	(event) => {
		if (event.button !== 0) return;
		const menu = $("context-tools");
		if (
			menu.matches(":popover-open") &&
			!menu.contains(event.target) &&
			event.target !== $("element-options")
		)
			closeElementOptions(false);
	},
	true,
);
document.addEventListener(
	"keydown",
	(event) => {
		if (event.key === "Escape" && $("context-tools").matches(":popover-open")) {
			event.preventDefault();
			event.stopPropagation();
			closeElementOptions();
		}
	},
	true,
);
function selectElement(id) {
	if (chartEditing && chartEditing.item.id !== id) {
		chartEditing = null;
		drawCanvas();
	}
	selectedElement = id;
	drawSelection();
	syncCanvasTools();
}
function startDrag(event, node, item) {
	if (
		node.classList.contains("chart-editing") ||
		node.isContentEditable ||
		event.target.closest("input,select,button,[contenteditable=true]")
	)
		return;
	if (event.button !== 0) return;
	event.preventDefault();
	selectElement(item.id);
	node.focus({ preventScroll: true });
	const bounds = $("canvas").getBoundingClientRect();
	drag = {
		id: event.pointerId,
		x: event.clientX,
		y: event.clientY,
		originalX: item.x,
		originalY: item.y,
	};
	node.setPointerCapture(event.pointerId);
	node.onpointermove = (e) => {
		if (!drag || e.pointerId !== drag.id) return;
		item.x = Math.max(
			0,
			Math.min(
				1 - item.w,
				drag.originalX + (e.clientX - drag.x) / bounds.width,
			),
		);
		item.y = Math.max(
			0,
			Math.min(
				1 - item.h,
				drag.originalY + (e.clientY - drag.y) / bounds.height,
			),
		);
		positionNode(node, item);
		syncCanvasTools();
	};
	const finish = (e) => {
		if (!drag) return;
		if (e.type === "pointercancel") {
			item.x = drag.originalX;
			item.y = drag.originalY;
			positionNode(node, item);
			syncCanvasTools();
		}
		drag = null;
		save();
	};
	node.onpointerup = finish;
	node.onpointercancel = finish;
	node.onlostpointercapture = finish;
}
function syncCanvasTools() {
	const scene = currentScene();
	const composition = scene.type === "composition";
	$("edit-canvas").hidden = composition;
	for (const id of [
		"background-style",
		"background-color",
		"background-accent",
		"background-motion",
		"preview-motion",
	])
		$(id).disabled = !composition;
	$("scene-duration").value = scene.duration || 4;
	$("resolution").value =
		`${project.meta?.resolution?.width || 1920}x${project.meta?.resolution?.height || 1080}`;
	if (composition) {
		scene.background ||= {
			style: "solid",
			color: "#191925",
			accent: "#6750a4",
			motion: "none",
		};
		const bg = scene.background;
		$("background-style").value = bg.style || "solid";
		$("background-color").value = bg.color || "#191925";
		$("background-accent").value = bg.accent || "#6750a4";
		$("background-motion").value = bg.motion || "none";
	}
	const item = itemById();
	$("element-options").hidden = !item;
	if (!item) $("resize-handles").hidden = true;
	if (!item) {
		if ($("context-tools").matches(":popover-open"))
			$("context-tools").hidePopover();
		return;
	}
	const canvasBounds = $("canvas").getBoundingClientRect();
	const wrapBounds = $("canvas").parentElement.getBoundingClientRect();
	$("element-options").style.left =
		`${canvasBounds.left - wrapBounds.left + Math.min(item.x + item.w, 0.95) * canvasBounds.width - 28}px`;
	$("element-options").style.top =
		`${canvasBounds.top - wrapBounds.top + item.y * canvasBounds.height}px`;
	$("selection-kind").textContent = item.type;
 $("shape-control").hidden=item.type!=="shape";
 if(item.type==="shape")$("shape-kind").value=item.shape;
	$("element-color").value = item.color;
	const exportHeight = project.meta?.resolution?.height || 1080;
	$("element-size").min = Math.ceil(exportHeight * 0.02);
	$("element-size").max = Math.floor(exportHeight * 0.15);
	$("element-size").value = Math.round((item.font_size || 0.06) * exportHeight);
	$("element-size").disabled = item.type !== "text";
	$("element-bold").disabled = item.type !== "text";
	$("element-align").disabled = item.type !== "text";
	$("element-bold").textContent = `Bold · ${item.bold ? "on" : "off"}`;
	$("element-bold").setAttribute("aria-pressed", String(!!item.bold));
	$("element-align").textContent = `Align ${item.align || "left"}`;
	syncResizeHandles();
}
$("edit-canvas").onclick = convertScene;
for (const type of ["text", "chart", "shape"])
	$(`add-${type}`).onclick = () => {
		convertScene();
		const scene = currentScene();
		if (scene.elements.length >= 16) {
			notice("A canvas supports at most 16 elements.");
			return;
		}
		const item =
			type === "text"
				? textElement("Double-click to edit", 0.1, 0.35, 0.8, 0.25)
				: type === "shape"
					? {
							id: crypto.randomUUID(),
							type,
							shape: "rect",
							x: 0.2,
							y: 0.2,
							w: 0.25,
							h: 0.25,
							color: "#6750a4",
						}
					: {
							id: crypto.randomUUID(),
							type,
							chart_type: "bar",
							labels: ["Example A", "Example B", "Example C"],
							values: [20, 40, 60],
							x: 0.1,
							y: 0.25,
							w: 0.8,
							h: 0.6,
							color: "#bba5ff",
						};
		scene.elements.push(item);
		selectedElement = item.id;
		update();
		const addedNode = $("canvas").querySelector(`[data-id="${item.id}"]`);
		addedNode.focus();
		enterInterface(addedNode, { distance: 6, duration: 190, scale: 0.98 });
		announce(`${type} added. Chart values are example data.`);
 if(type==="chart")beginChartEditing(item);
 if(type==="shape")showElementOptions();
	};
function changeItem(action) {
	const item = itemById();
	if (!item) return;
	const focusId = document.activeElement?.id;
	action(item);
	save();
	drawCanvas();
	if (focusId) $(focusId)?.focus({ preventScroll: true });
}
$("shape-kind").onchange=()=>changeItem(item=>{item.shape=$("shape-kind").value;});
$("element-color").oninput = () =>
	changeItem((i) => {
		i.color = $("element-color").value;
	});
$("element-size").onchange = () => {
	const input = $("element-size"),
		pixels = Number(input.value),
		height = project.meta?.resolution?.height || 1080;
	if (
		!input.value.trim() ||
		!Number.isFinite(pixels) ||
		pixels < height * 0.02 ||
		pixels > height * 0.15
	) {
		input.setAttribute("aria-invalid", "true");
		announce(
			`Text size must be ${Math.ceil(height * 0.02)} to ${Math.floor(height * 0.15)} pixels.`,
		);
		return;
	}
	input.removeAttribute("aria-invalid");
	changeItem((i) => {
		i.font_size = pixels / height;
	});
};
$("element-bold").onclick = () =>
	changeItem((i) => {
		i.bold = !i.bold;
	});
$("element-align").onclick = () =>
	changeItem((i) => {
		i.align = { left: "center", center: "right", right: "left" }[
			i.align || "left"
		];
	});
function deleteElement() {
	if (!itemById()) return;
	currentScene().elements = currentScene().elements.filter(
		(i) => i.id !== selectedElement,
	);
	selectedElement = null;
	closeElementOptions(false);
	update();
	$("add-text").focus();
	announce("Element deleted.");
}
$("element-delete").onclick = deleteElement;
$("element-front").onclick = () => {
	const item = itemById();
	if (!item) return;
	const items = currentScene().elements;
	const index = items.indexOf(item);
	if (index < items.length - 1) {
		items.splice(index, 1);
		items.splice(index + 1, 0, item);
		update();
		announce("Element moved forward one layer.");
	}
};
$("resolution").onchange = () => {
	const [width, height] = $("resolution").value.split("x").map(Number);
	project.meta = { ...project.meta, resolution: { width, height } };
	update();
	announce(
		`Export resolution ${width} by ${height}. Legacy scenes are fitted without distortion.`,
	);
};
$("scene-duration").oninput = () => {
	currentScene().duration = Number($("scene-duration").value);
	save();
	drawMeta();
};
for (const [id, key] of [
	["background-style", "style"],
	["background-color", "color"],
	["background-accent", "accent"],
	["background-motion", "motion"],
])
	$(id).onchange = () => {
		currentScene().background[key] = $(id).value;
		save();
		drawCanvas();
	};
$("preview-motion").onclick = () => {
	if (previewAnimation) {
		stopPreview();
		return;
	}
	if (reducedMotion.matches) {
		announce("Motion preview is disabled by your reduced-motion preference.");
		return;
	}
	const bg = $("canvas").querySelector(".canvas-background");
	if (!bg || currentScene().background.motion === "none") {
		announce("Choose Drift or Pulse to preview background motion.");
		return;
	}
	previewAnimation = bg.animate(
		currentScene().background.motion === "pulse"
			? [{ opacity: 0.6 }, { opacity: 1 }, { opacity: 0.6 }]
			: [{ transform: "translate(0,0)" }, { transform: "translate(3%,2%)" }],
		{ duration: 5000, easing: "linear" },
	);
	$("preview-motion").textContent = "Stop preview";
	previewAnimation.finished.then(stopPreview).catch(() => {});
};
reducedMotion.addEventListener("change", () => {
	if (reducedMotion.matches) stopPreview();
});
document.addEventListener("visibilitychange", () => {
	if (document.hidden) stopPreview();
});
function finishInlineEditing() {
	if (!inlineEditing) return;
	const { node, item } = inlineEditing;
	item.text = node.innerText.replace(/\r/g, "").slice(0, 600);
	inlineEditing = null;
	node.contentEditable = "false";
	node.classList.remove("typing");
	node.setAttribute("role", "button");
	node.setAttribute(
		"aria-label",
		`${item.text} text element. Enter to edit, arrows to move.`,
	);
	node.oninput = null;
	node.onblur = null;
	save();
	const fingerprint = JSON.stringify(project);
	request("/api/validate", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(project),
	}).catch((error) => {
		if (fingerprint === JSON.stringify(project)) notice(error.message);
	});
}
function beginInlineEditing(item) {
	finishInlineEditing();
	selectElement(item.id);
	const node = $("canvas").querySelector(`[data-id="${item.id}"]`);
	if (!node) return;
	inlineEditing = { node, item, original: item.text };
	node.contentEditable = "plaintext-only";
	node.classList.add("typing");
	node.setAttribute("role", "textbox");
	node.setAttribute("aria-multiline", "true");
	node.removeAttribute("aria-pressed");
	node.setAttribute("aria-label", "Edit canvas text");
	node.spellcheck = true;
	node.oninput = () => {
		item.text = node.innerText.replace(/\r/g, "").slice(0, 600);
		save();
	};
	node.onblur = finishInlineEditing;
	syncResizeHandles();
	node.focus();
	const range = document.createRange();
	range.selectNodeContents(node);
	const selection = window.getSelection();
	selection.removeAllRanges();
	selection.addRange(range);
	announce(
		"Editing text on canvas. Escape cancels; Control or Command Enter finishes.",
	);
}
function beginChartEditing(item) {
	const node = $("canvas").querySelector(`[data-id="${item.id}"]`);
	if (!node) return;
	if (chartEditing?.item === item) {
		node.querySelector("input")?.focus();
		return;
	}
	chartEditing = { item, node, scene: currentScene() };
	node.classList.add("chart-editing");
	node.setAttribute("role", "group");
	node.setAttribute("aria-label", "Edit chart data");
	node.removeAttribute("aria-pressed");
	const editor = element("div", undefined, "chart-direct-editor");
	const top = element("div", undefined, "chart-edit-heading");
	top.append(element("strong", "Chart data"));
	const done = element("button", "Done", "button subtle");
	done.type = "button";
	// Done validates the complete draft atomically; field changes do not race saves.
	top.append(done);
	editor.append(top);
	const label = element("label", "Chart style");
	const kind = element("select");
	kind.setAttribute("aria-label", "Chart style");
	for (const value of ["bar", "horizontal", "line", "area", "pie", "doughnut"]) {
		const option = element("option", ({bar:"Column / bar",horizontal:"Horizontal bar",line:"Line",area:"Area",pie:"Pie",doughnut:"Doughnut"})[value] || value);
		option.value = value;
		kind.append(option);
	}
	kind.value = item.chart_type;
	label.append(kind);
	editor.append(label);
	const rows = element("div", undefined, "chart-data-rows");
	for (let index = 0; index < item.labels.length; index++) {
		const row = element("div", undefined, "chart-data-row");
		const text = element("input");
		text.value = item.labels[index];
		text.maxLength = 40;
		text.setAttribute("aria-label", `Label ${index + 1}`);
		const number = element("input");
		number.type = "number";
		number.value = item.values[index];
		number.setAttribute("aria-label", `Value ${index + 1}`);
		row.append(text, number);
		rows.append(row);
	}
	editor.append(rows);
	const status = element("p", "", "chart-data-status");
	status.setAttribute("role", "status");
	editor.append(status);
	const commit = async () => {
		const baseline = JSON.stringify(project);
		const source = chartEditing;
		if (!source || source.item !== item) return;
		const candidate = structuredClone(project);
		const target = candidate.timeline[selected].elements.find(
			(i) => i.id === item.id,
		);
		target.chart_type = kind.value;
		target.labels = [...rows.querySelectorAll(".chart-data-row")].map(
			(row) => row.children[0].value,
		);
		target.values = [...rows.querySelectorAll(".chart-data-row")].map((row) =>
			row.children[1].value.trim() === ""
				? null
				: Number(row.children[1].value),
		);
		try {
			for (const control of [done, kind, ...rows.querySelectorAll("input")])
				control.disabled = true;
			await request("/api/validate", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify(candidate),
			});
			if (chartEditing !== source || baseline !== JSON.stringify(project)) {
				status.textContent = "Newer changes kept. Edit again to save.";
				return;
			}
			Object.assign(item, target);
			save();
			node.querySelector("svg")?.remove();
			drawChart(node, item);
			status.textContent = "Saved";
			chartEditing = null;
			drawCanvas();
			$("element-options").focus();
			announce("Chart data saved.");
		} catch (error) {
			if (chartEditing === source) {
				status.textContent = error.message;
				status.setAttribute("role", "alert");
			}
		} finally {
			for (const control of [done, kind, ...rows.querySelectorAll("input")])
				control.disabled = false;
		}
	};
	done.onclick = commit;
	for (const control of [kind, ...rows.querySelectorAll("input")])
		control.oninput = () => {
			status.textContent = "Unsaved changes · choose Done to save";
		};
	node.append(editor);
	enterInterface(editor, { distance: 4, duration: 160 });
	node.onkeydown = (event) => {
		if (event.key === "Escape") {
			event.preventDefault();
			chartEditing = null;
			drawCanvas();
			$("element-options").focus();
		}
	};
	rows.querySelector("input")?.focus();
	announce(
		"Edit chart labels and numbers directly on the chart. Done saves all changes; Escape cancels.",
	);
}
function openContent(item, notes = false) {
	if ($("context-tools").matches(":popover-open"))
		$("context-tools").hidePopover();
	if (!notes && item.type === "chart") {
		beginChartEditing(item);
		return;
	}
	if (!notes && item.type === "text") {
		beginInlineEditing(item);
		return;
	}
	if (!notes && item.type === "shape") {
		showElementOptions();
        $("shape-kind").focus();
		return;
	}
	contentReturn = document.activeElement;
	contentScene = currentScene();
	contentTarget = notes ? "notes" : item.id;
	$("chart-fields").hidden = notes || item.type !== "chart";
	$("content-text").hidden = !notes && item.type === "chart";
	document.querySelector('label[for="content-text"]').hidden =
		$("content-text").hidden;
	$("content-text").value = notes
		? currentScene().narration || ""
		: item.text || "";
	$("content-text").maxLength = notes ? 7205 : 600;
	if (!notes && item.type === "chart") {
		$("chart-kind").value = item.chart_type;
		$("chart-labels").value = item.labels.join("\n");
		$("chart-values").value = item.values.join("\n");
	}
	$("content-error").hidden = true;
	$("content-editor").hidden = false;
	enterInterface($("content-editor"), { distance: 6 });
	($("content-text").hidden ? $("chart-labels") : $("content-text")).focus();
}
$("edit-element").onclick = () => {
	const item = itemById();
	if (item?.type === "shape") {
		$("shape-kind").focus();
	} else if (item) openContent(item);
};
$("scene-notes").onclick = () => openContent({}, true);
$("content-close").onclick = closeContent;
function closeContent() {
	$("content-editor").hidden = true;
	if (contentReturn?.isConnected) contentReturn.focus();
	else $("editor").focus();
}
$("content-save").onclick = async () => {
	if (contentScene !== currentScene()) {
		closeContent();
		return;
	}
	const baseline = JSON.stringify(project);
	const originalScene = contentScene;
	const candidate = structuredClone(project);
	const scene = candidate.timeline[selected];
	if (contentTarget === "notes") scene.narration = $("content-text").value;
	else {
		const item = scene.elements.find((i) => i.id === contentTarget);
		if (item.type === "chart") {
			item.chart_type = $("chart-kind").value;
			item.labels = $("chart-labels").value.split("\n");
			item.values = $("chart-values")
				.value.split("\n")
				.map((v) => (v.trim() === "" ? null : Number(v)));
		} else item.text = $("content-text").value;
	}
	try {
		await request("/api/validate", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(candidate),
		});
		if (
			baseline !== JSON.stringify(project) ||
			originalScene !== currentScene() ||
			$("content-editor").hidden
		) {
			announce(
				"The project changed while validating. Your newer edits were preserved.",
			);
			return;
		}
		project = candidate;
		contentScene = project.timeline[selected];
		update();
		closeContent();
		announce("Content saved.");
	} catch (error) {
		$("content-error").textContent = error.message;
		$("content-error").hidden = false;
	}
};
new ResizeObserver(() => fitCanvas()).observe($("canvas").parentElement);
window.addEventListener("resize", fitCanvas);
document.querySelector(".brand-mark").replaceChildren(icon("scene"));
restoreAppearance();
for (const [id, name] of Object.entries({
	add: "plus",
	"add-text": "text",
	"add-chart": "chart",
	"add-shape": "shape",
	import: "upload",
	export: "download",
	"options-close": "close",
	"edit-element": "edit",
	"element-front": "layers",
	"element-delete": "trash",
	"content-close": "close",
	"composer-close": "arrow",
	draft: "sparkle",
	"apply-draft": "scene",
	"cancel-draft": "close",
})) {
	const button = $(id);
	if (!button) continue;
	if (id === "add") button.replaceChildren(icon(name));
	else {
		for (const span of button.querySelectorAll("span[aria-hidden=true]"))
			span.remove();
		button.prepend(icon(name));
	}
}
$("element-options").replaceChildren(icon("more"));
const styleButton = document.querySelector('[popovertarget="scene-settings"]');
styleButton.prepend(icon("palette"));
drawScenes();
drawCanvas();
drawMeta();
$("project-title").value = project.meta?.title || "Untitled project";
