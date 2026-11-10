/* Scene JSON remains the source of truth; the canvas is a layout aid, not a render. */
const $ = (id) => document.getElementById(id);
const initial = {
	meta: { title: "The next chapter", fps: 30 },
	theme: { preset: "dark", bg: "#191925", fg: "#f5f0ff", accent: "#bba5ff" },
	timeline: [
		{
			type: "title",
			text: "Big ideas.\nBeautifully told.",
			subtitle: "A new perspective starts here.",
			duration: 4,
		},
		{
			type: "bullets",
			heading: "Make every frame count",
			items: [
				"Give your story a clear direction",
				"Turn complex ideas into simple visuals",
				"Leave your audience with something real",
			],
			duration: 5,
		},
		{
			type: "chart",
			heading: "A little progress, every day",
			chart_type: "bar",
			labels: ["Explore", "Create", "Refine"],
			values: [35, 65, 90],
			duration: 4,
		},
		{ type: "outro", text: "What will you create?", duration: 3 },
	],
};
let project = structuredClone(initial);
let selected = 0;
let token = "";

let rendering = false;
let downloads = [];
const names = {
	title: "Title",
	bullets: "Bullets",
	chart: "Chart",
	outro: "Outro",
	composition: "Canvas",
};
const symbols = { title: "T", bullets: "≡", chart: "▥", outro: "↗" };
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
let themeTransition = null;

function applyAppearance(appearance) {
	document.documentElement.dataset.appearance = appearance;
	const dark = appearance === "dark";
	const label = dark
		? "Switch to light appearance"
		: "Switch to dark appearance";
	$("ui-theme").setAttribute("aria-label", label);
	$("ui-theme").setAttribute("aria-pressed", String(dark));
	$("ui-theme").title = label;
	$("theme-icon").replaceChildren(icon(dark ? "sun" : "moon"));
}
function restoreAppearance() {
	let appearance = matchMedia("(prefers-color-scheme: dark)").matches
		? "dark"
		: "light";
	try {
		const saved = localStorage.getItem("frame-appearance-v1");
		if (saved === "dark" || saved === "light") appearance = saved;
	} catch {
		/* Appearance still works when browser storage is unavailable. */
	}
	applyAppearance(appearance);
}
async function toggleAppearance() {
	if (themeTransition) return;
	const appearance =
		document.documentElement.dataset.appearance === "dark" ? "light" : "dark";
	const change = () => {
		applyAppearance(appearance);
		try {
			localStorage.setItem("frame-appearance-v1", appearance);
		} catch {
			/* Project export remains available without browser persistence. */
		}
	};
	// Native view snapshots reveal the actual UI, not a coloured overlay.
	if (reducedMotion.matches || !document.startViewTransition) {
		change();
		return;
	}
	const bounds = $("ui-theme").getBoundingClientRect();
	const x = bounds.left + bounds.width / 2;
	const y = bounds.top + bounds.height / 2;
	const radius = Math.hypot(
		Math.max(x, innerWidth - x),
		Math.max(y, innerHeight - y),
	);
	const transition = document.startViewTransition(change);
	themeTransition = transition;
	try {
		await transition.ready;
		if (reducedMotion.matches) transition.skipTransition();
		else
			document.documentElement.animate(
				{
					clipPath: [
						`circle(0px at ${x}px ${y}px)`,
						`circle(${radius}px at ${x}px ${y}px)`,
					],
				},
				{
					duration: 560,
					easing: "cubic-bezier(.2, 0, .2, 1)",
					pseudoElement: "::view-transition-new(root)",
				},
			);
		await transition.finished;
	} catch {
		// A hidden document can skip snapshots; the theme change still completes.
		await transition.updateCallbackDone;
	} finally {
		themeTransition = null;
	}
}

$("ui-theme").onclick = toggleAppearance;
reducedMotion.addEventListener("change", () => {
	if (reducedMotion.matches) themeTransition?.skipTransition();
});

function element(tag, text, className) {
	const node = document.createElement(tag);
	if (text !== undefined) node.textContent = text;
	if (className) node.className = className;
	return node;
}
function notice(message) {
	$("notice").textContent = message;
	$("notice").hidden = !message;
	if (message && $("composer").hidden) $("notice").focus();
}
function announce(message) {
	$("editor-announcement").textContent = message;
}
function renderLabel() {
	return $("output-format").value === "pptx"
		? "Export PowerPoint"
		: "Render project";
}
function seconds() {
	return project.timeline.reduce(
		(sum, scene) => sum + (Number(scene.duration) || 4),
		0,
	);
}
function save() {
	if (typeof refreshSceneThumbnails === "function") refreshSceneThumbnails();
	try {
		localStorage.setItem("frame-project-v1", JSON.stringify(project));
	} catch {
		notice("Browser storage is unavailable. Export JSON to keep your work.");
	}
}
function update() {
	save();
	drawScenes();
	drawCanvas();
	drawMeta();
}
function drawMeta() {
	$("add").disabled = project.timeline.length >= 12;
}
let draggedScene = null;
function reorderScenes(from, to) {
	if (from === to) return;
	finishInlineEditing();
	const active = project.timeline[selected];
	const [scene] = project.timeline.splice(from, 1);
	project.timeline.splice(to, 0, scene);
	selected = project.timeline.indexOf(active);
	update();
	drawEditor();
	const buttons = $("scenes").querySelectorAll(".scene-button");
	buttons[to]?.focus();
	animateSceneArrival(true);
	announce(`Scene moved to position ${to + 1}.`);
}
function deleteScene(index) {
	if (project.timeline.length === 1) {
		announce("Keep at least one scene.");
		return;
	}
	finishInlineEditing();
	project.timeline.splice(index, 1);
	selected = Math.min(index, project.timeline.length - 1);
	selectedElement = null;
	update();
	drawEditor();
	$("scenes").querySelectorAll(".scene-button")[selected]?.focus();
	announce("Scene deleted.");
}
function choose(index) {
	const changed = selected !== index;
	finishInlineEditing();
	const snapshot = changed ? captureSceneTransition() : null;
	const source = document.activeElement?.closest("#scenes")?.id;
	selected = index;
	drawScenes();
	drawCanvas();
	drawEditor();
	drawMeta();
	announce(
		`Scene ${index + 1}, ${names[project.timeline[index].type]}, selected.`,
	);
	if (source) {
		const buttons = $(source).querySelectorAll(".scene-button");
		buttons[index]?.focus({ preventScroll: true });
	}
	if (changed) crossfadeScene(snapshot);
}
function sceneLabel(scene) {
	return (
		scene.name || scene.text || scene.heading || names[scene.type] || "Scene"
	);
}
function drawScenes() {
 closeSceneMenus(false);
	$("scenes").replaceChildren();
	project.timeline.forEach((scene, index) => {
		const button = element("button", undefined, "scene-button");
		button.type = "button";
		button.draggable = true;
		button.setAttribute("aria-current", String(index === selected));
		button.title = `Select scene ${index + 1}`;
		const text = element("span", undefined, "scene-text");
		text.append(
			element("strong", sceneLabel(scene)),
			element(
				"small",
				`${names[scene.type] || scene.type} · ${scene.duration || 4}s`,
			),
		);
		button.append(
			element("span", String(index + 1).padStart(2, "0"), "scene-number"),
			element("span", undefined, "mini-frame"),
			text,
		);
		renderSceneThumbnail(button.querySelector(".mini-frame"), scene);
		button.onclick = () => choose(index);
 button.oncontextmenu=event=>{event.preventDefault();showSceneOptions(project.timeline[index],event.clientX,event.clientY);};
		button.ondragstart = (event) => {
			draggedScene = index;
			event.dataTransfer.effectAllowed = "move";
			event.dataTransfer.setData("text/plain", String(index));
			button.classList.add("dragging-scene");
		};
		button.ondragend = () => {
			draggedScene = null;
			document
				.querySelectorAll(".drop-target,.dragging-scene")
				.forEach((n) => n.classList.remove("drop-target", "dragging-scene"));
		};
		button.ondragover = (event) => {
			if (draggedScene === null) return;
			event.preventDefault();
			event.dataTransfer.dropEffect = "move";
			button.classList.add("drop-target");
		};
		button.ondragleave = () => button.classList.remove("drop-target");
		button.ondrop = (event) => {
			event.preventDefault();
			if (draggedScene !== null) {
				const from = draggedScene;
				draggedScene = null;
				reorderScenes(from, index);
			}
		};
		button.onkeydown = (event) => {
 if(event.key==='ContextMenu' || (event.shiftKey && event.key==='F10')){event.preventDefault();showSceneOptions(project.timeline[index]);return;}
			if (event.key === "Backspace" || event.key === "Delete") {
				event.preventDefault();
				deleteScene(index);
				return;
			}
			if (
				event.altKey &&
				["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(event.key)
			) {
				event.preventDefault();
				const offset = ["ArrowUp", "ArrowLeft"].includes(event.key) ? -1 : 1;
				reorderScenes(
					index,
					Math.max(0, Math.min(project.timeline.length - 1, index + offset)),
				);
				return;
			}
			let target = index;
			if (event.key === "ArrowDown" || event.key === "ArrowRight")
				target = Math.min(index + 1, project.timeline.length - 1);
			else if (event.key === "ArrowUp" || event.key === "ArrowLeft")
				target = Math.max(index - 1, 0);
			else if (event.key === "Home") target = 0;
			else if (event.key === "End") target = project.timeline.length - 1;
			else return;
			event.preventDefault();
			choose(target);
		};
		const li = element("li");
		li.append(button);
 const options=element('button',undefined,'scene-more button');options.type='button';options.setAttribute('aria-label',`Options for scene ${index+1}`);options.append(icon('more'));options.onclick=()=>showSceneOptions(project.timeline[index]);li.append(options);
		$("scenes").append(li);
	});
	syncSelectionHighlights();
}
function drawLegacyCanvas() {
	const scene = project.timeline[selected];
	const theme = project.theme || {};
	const dark = theme.preset !== "light";
	const canvas = $("canvas");
	canvas.replaceChildren();
	canvas.style.background = /^#[0-9a-f]{6}$/i.test(theme.bg)
		? theme.bg
		: dark
			? "#191925"
			: "#f5f5f5";
	canvas.style.color = /^#[0-9a-f]{6}$/i.test(theme.fg)
		? theme.fg
		: dark
			? "#f5f0ff"
			: "#202020";
	canvas.style.setProperty(
		"--canvas-accent",
		/^#[0-9a-f]{6}$/i.test(theme.accent) ? theme.accent : "#bba5ff",
	);
	const content = element("div", undefined, "canvas-content");
	if (scene.type === "title" || scene.type === "outro") {
		content.classList.add("center");
		const title = element("h2", scene.text, "canvas-title");
		title.style.whiteSpace = "pre-line";
		content.append(title);
		if (scene.subtitle)
			content.append(element("p", scene.subtitle, "canvas-subtitle"));
	} else if (scene.type === "bullets") {
		content.append(
			element("h2", scene.heading || "Your ideas", "canvas-heading"),
		);
		const list = element("ul", undefined, "canvas-bullets");
		(scene.items || []).forEach((item) => list.append(element("li", item)));
		content.append(list);
	} else if (scene.type === "chart") {
		content.append(
			element("h2", scene.heading || "Your data", "canvas-heading"),
		);
		if (scene.chart_type !== "bar")
			content.append(
				element(
					"p",
					`${scene.chart_type} chart · see the final render for the exact visual`,
					"chart-note",
				),
			);
		const chart = element("div", undefined, "chart-preview");
		const values = scene.values || [];
		const maximum = Math.max(1, ...values.map((v) => Math.abs(Number(v)) || 0));
		(scene.labels || []).forEach((label, index) => {
			const column = element("div", undefined, "chart-column");
			const bar = element("div", undefined, "chart-bar");
			bar.style.height = `${(Math.abs(Number(values[index]) || 0) / maximum) * 100}%`;
			column.append(
				element("span", String(values[index] ?? "")),
				bar,
				element("span", label),
			);
			chart.append(column);
		});
		content.append(chart);
	} else
		content.append(
			element("p", "This scene is available in the CLI, not Studio."),
		);
	canvas.append(content);
}
function drawEditor() {
	syncCanvasTools();
}
function addScene(type) {
	if (project.timeline.length >= 12) return;
	project.timeline.push(canvasTemplate(type));
	selected = project.timeline.length - 1;
	update();
	drawEditor();
	$("editor").focus();
	animateSceneArrival(true);
	announce("Canvas scene added.");
}
$("project-title").oninput = () => {
	project.meta = { ...project.meta, title: $("project-title").value };
	save();
};
function download(blob, name) {
	const url = URL.createObjectURL(blob);
	const link = element("a");
	link.href = url;
	link.download = name;
	link.click();
	setTimeout(() => URL.revokeObjectURL(url), 1000);
}
$("export").onclick = () =>
	download(
		new Blob([JSON.stringify(project, null, 2)], { type: "application/json" }),
		"storyboard.json",
	);
$("import").onclick = () => $("file").click();
function checkImport(value) {
	const object = (item) =>
		item !== null && typeof item === "object" && !Array.isArray(item);
	const stringFields = (item, keys) =>
		keys.every(
			(key) => item[key] === undefined || typeof item[key] === "string",
		);
	if (
		!object(value) ||
		(value.meta !== undefined &&
			(!object(value.meta) || !stringFields(value.meta, ["title"]))) ||
		(value.theme !== undefined &&
			(!object(value.theme) ||
				!stringFields(value.theme, ["preset", "bg", "fg", "accent"]))) ||
		!Array.isArray(value.timeline) ||
		value.timeline.length < 1 ||
		value.timeline.length > 12
	)
		throw new Error(
			"Import a JSON project with 1–12 scenes and text-based project settings.",
		);
	for (const scene of value.timeline) {
		if (!object(scene)) throw new Error("Scenes must be objects.");
		if (scene.type === "composition") {
			if (
				!Array.isArray(scene.elements) ||
				scene.elements.length > 16 ||
				(scene.background !== undefined &&
					(!object(scene.background) ||
						!stringFields(scene.background, [
							"style",
							"color",
							"accent",
							"motion",
						])))
			)
				throw new Error("Invalid canvas elements or background.");
			for (const item of scene.elements) {
				if (
					!object(item) ||
					!["text", "chart", "shape"].includes(item.type) ||
					typeof item.id !== "string" ||
					typeof item.color !== "string" ||
					!["x", "y", "w", "h"].every(
						(k) => typeof item[k] === "number" && Number.isFinite(item[k]),
					)
				)
					throw new Error("Invalid canvas geometry.");
				if (
					item.type === "text" &&
					(typeof item.text !== "string" ||
						(item.font_size !== undefined &&
							typeof item.font_size !== "number"))
				)
					throw new Error("Invalid canvas text.");
				if (
					item.type === "chart" &&
					(!Array.isArray(item.labels) ||
						item.labels.some((v) => typeof v !== "string") ||
						!Array.isArray(item.values) ||
						item.values.some((v) => typeof v !== "number"))
				)
					throw new Error("Invalid chart data.");
			}
			continue;
		}
		if (
			!object(scene) ||
			typeof scene.type !== "string" ||
			!Object.hasOwn(names, scene.type) ||
			scene.image !== undefined ||
			!stringFields(scene, [
				"text",
				"subtitle",
				"heading",
				"narration",
				"chart_type",
			]) ||
			(scene.duration !== undefined &&
				(typeof scene.duration !== "number" ||
					!Number.isFinite(scene.duration)))
		)
			throw new Error(
				"Use title, bullets, chart or outro scenes with text fields and numeric durations. Images are CLI-only.",
			);
		for (const key of ["items", "labels", "narration_per_bullet"])
			if (
				scene[key] !== undefined &&
				(!Array.isArray(scene[key]) ||
					scene[key].some((item) => typeof item !== "string"))
			)
				throw new Error(`${key}: use a list of text values.`);
		if (
			scene.values !== undefined &&
			(!Array.isArray(scene.values) ||
				scene.values.some(
					(item) => typeof item !== "number" || !Number.isFinite(item),
				))
		)
			throw new Error("Chart values must be a list of finite numbers.");
	}
}
function importProject(value) {
	checkImport(value);
	project = structuredClone(value);
	selected = 0;
	$("project-title").value = project.meta?.title || "Untitled project";
	update();
	drawEditor();
	notice("");
}
$("file").onchange = async () => {
	try {
		const file = $("file").files[0];
		if (!file) return;
		if (file.size > 128 * 1024)
			throw new Error("JSON files must be smaller than 128 KB.");
		const value = JSON.parse(await file.text());
		checkImport(value);
		const { spec } = await request("/api/validate", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(value),
		});
		importProject(spec);
		announce("Project imported. Scene 1 selected.");
	} catch (error) {
		notice(error.message);
	} finally {
		$("file").value = "";
	}
};
async function request(path, options = {}) {
	const response = await fetch(path, {
		...options,
		headers: { "X-Studio-Token": token, ...options.headers },
	});
	const data = await response.json();
	if (!response.ok) throw new Error(data.error || "Studio request failed.");
	return data;
}
async function showArtifacts(job) {
	downloads.forEach((url) => URL.revokeObjectURL(url));
	downloads = [];
	$("artifacts").replaceChildren();
	for (const extension of job.artifacts) {
		const response = await fetch(`/api/artifact/${job.id}/${extension}`, {
			headers: { "X-Studio-Token": token },
		});
		if (!response.ok)
			throw new Error("The render completed, but its download is unavailable.");
		const blob = await response.blob();
		const url = URL.createObjectURL(blob);
		downloads.push(url);
		if (extension === "mp4") {
			const video = element("video");
			video.controls = true;
			video.preload = "metadata";
			video.src = url;
			video.setAttribute("aria-label", "Rendered project, silent video");
			$("artifacts").append(video);
		}
		const link = element(
			"a",
			extension === "mp4" ? "Download video" : "Download PowerPoint",
			"button outlined",
		);
		link.href = url;
		link.download = `frame-project.${extension}`;
		$("artifacts").append(link);
		enterInterface(link, { distance: 4 });
	}
}
async function followJob() {
	try {
		const { job } = await request("/api/job");
		if (!job) return;
		$("render-status").textContent = job.message;
		if (job.state === "rendering") {
			setTimeout(followJob, 1200);
			return;
		}
		rendering = false;
		$("render").disabled = false;
		$("render").textContent = renderLabel();
		$("output-format").disabled = false;
		if (job.state === "complete") await showArtifacts(job);
	} catch (error) {
		rendering = false;
		$("render").disabled = false;
		$("render").textContent = renderLabel();
		$("output-format").disabled = false;
		notice(error.message);
	}
}
$("render").onclick = async () => {
	if (rendering) return;
	notice("");
	try {
		await request("/api/render", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ spec: project, format: $("output-format").value }),
		});
		rendering = true;
		$("render").disabled = true;
		$("output-format").disabled = true;
		$("render").textContent = "Rendering…";
		$("artifacts").replaceChildren();
		$("render-status").textContent =
			"Rendering on your computer. This can take up to three minutes.";
		followJob();
	} catch (error) {
		notice(error.message);
	}
};
try {
	const saved = localStorage.getItem("frame-project-v1");
	if (saved) {
		checkImport(JSON.parse(saved));
		project = JSON.parse(saved);
		$("project-title").value = project.meta?.title || "Untitled project";
	}
} catch {
	notice(
		"Your saved project could not be restored. Import an exported JSON file to recover it.",
	);
}

fetch("/api/bootstrap")
	.then((response) => {
		if (!response.ok) throw new Error("Could not connect to Studio.");
		return response.json();
	})
	.then((data) => {
		token = data.token;

		return data;
	})
	.then(({ job }) => {
		if (job?.state === "rendering") {
			rendering = true;
			$("render").disabled = true;
			$("render").textContent = "Rendering…";
			followJob();
		} else if (job?.state === "complete") {
			$("render-status").textContent = job.message;
			return showArtifacts(job);
		}
	})
	.catch((error) => notice(error.message));
