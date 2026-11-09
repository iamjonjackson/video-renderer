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
	$("theme-icon").textContent = dark ? "☀" : "☾";
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
restoreAppearance();
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
}
function seconds() {
	return project.timeline.reduce(
		(sum, scene) => sum + (Number(scene.duration) || 4),
		0,
	);
}
function save() {
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
	$("project-stats").textContent =
		`${project.timeline.length} scenes · ${seconds()} seconds`;
	$("scene-count").textContent = String(project.timeline.length).padStart(
		2,
		"0",
	);
	$("add").disabled = project.timeline.length >= 12;
	$("up").disabled = selected === 0;
	$("down").disabled = selected === project.timeline.length - 1;
	$("delete").disabled = project.timeline.length === 1;
}
function choose(index) {
	const source = document.activeElement?.closest("#scenes")?.id;
	selected = index;
	drawScenes();
	drawCanvas();
	drawEditor();
	drawMeta();
	if (source) {
		const buttons = $(source).querySelectorAll("button");
		buttons[index]?.focus({ preventScroll: true });
	}
}
function sceneLabel(scene) {
	return scene.text || scene.heading || names[scene.type] || "Scene";
}
function drawScenes() {
	$("scenes").replaceChildren();
	project.timeline.forEach((scene, index) => {
		const button = element("button", undefined, "scene-button");
		button.type = "button";
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
			element("span", symbols[scene.type] || "?", "mini-frame"),
			text,
		);
		button.onclick = () => choose(index);
		const li = element("li");
		li.append(button);
		$("scenes").append(li);
	});
}
function drawCanvas() {
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
	$("preview-name").textContent =
		`Scene ${String(selected + 1).padStart(2, "0")} · ${names[scene.type] || scene.type}`;
}
function field(label, key, options = {}) {
	const wrapper = element("div");
	const id = `field-${key}`;
	const caption = element("label", label);
	caption.htmlFor = id;
	const control = element(
		options.multiline ? "textarea" : options.choices ? "select" : "input",
	);
	control.id = id;
	if (options.choices)
		options.choices.forEach((value) => {
			const option = element("option", value);
			option.value = value;
			control.append(option);
		});
	if (!options.multiline && !options.choices)
		control.type = options.number ? "number" : "text";
	if (options.number) {
		control.min = "1";
		control.max = "15";
		control.step = "0.5";
	}
	if (!options.number && !options.choices)
		control.maxLength = options.array ? 1200 : key === "narration" ? 1200 : 300;
	const scene = project.timeline[selected];
	control.value = options.array
		? (scene[key] || []).join("\n")
		: (scene[key] ?? options.default ?? "");
	control.oninput = () => {
		scene[key] = options.array
			? control.value.split("\n")
			: options.number
				? Number(control.value)
				: control.value;
		if (key === "values")
			scene[key] = control.value
				.split("\n")
				.map((v) => (v.trim() === "" ? null : Number(v)));
		update();
	};
	wrapper.append(caption, control);
	if (options.hint) {
		const hint = element("p", options.hint, "field-hint");
		hint.id = `${id}-hint`;
		control.setAttribute("aria-describedby", hint.id);
		wrapper.append(hint);
	}
	$("scene-form").append(wrapper);
}
function drawEditor() {
	const scene = project.timeline[selected];
	$("scene-form").replaceChildren();
	$("editor-index").textContent =
		`SCENE ${String(selected + 1).padStart(2, "0")}`;
	$("editor-kind").textContent = names[scene.type] || "Unsupported scene";
	if (scene.type === "title" || scene.type === "outro")
		field("Main text", "text", { multiline: true });
	if (scene.type === "title") field("Supporting line", "subtitle");
	if (scene.type === "bullets" || scene.type === "chart")
		field("Heading", "heading");
	if (scene.type === "bullets")
		field("Bullet points", "items", {
			multiline: true,
			array: true,
			hint: "One idea per line. Up to 6 bullets; keep each one short.",
		});
	if (scene.type === "chart") {
		field("Chart style", "chart_type", {
			choices: ["bar", "line", "pie"],
			default: "bar",
		});
		field("Labels", "labels", {
			multiline: true,
			array: true,
			hint: "One label per line, up to 8.",
		});
		field("Values", "values", {
			multiline: true,
			array: true,
			hint: "One number per line, in the same order as labels.",
		});
	}
	field("On-screen duration · seconds", "duration", {
		number: true,
		default: 4,
		hint: "1–15 seconds per scene. Project maximum: 60 seconds.",
	});
	field("Narration notes", "narration", {
		multiline: true,
		hint: "Saved in JSON for the CLI. Studio exports are silent and use your explicit duration.",
	});
	$("preset").value = project.theme?.preset || "dark";
	$("accent").value = /^#[0-9a-f]{6}$/i.test(project.theme?.accent)
		? project.theme.accent
		: "#bba5ff";
	$("accent-value").textContent = $("accent").value.toUpperCase();
}
function move(offset) {
	const destination = selected + offset;
	if (destination < 0 || destination >= project.timeline.length) return;
	const [scene] = project.timeline.splice(selected, 1);
	project.timeline.splice(destination, 0, scene);
	selected = destination;
	update();
	drawEditor();
}
$("up").onclick = () => move(-1);
$("down").onclick = () => move(1);
$("delete").onclick = () => {
	if (project.timeline.length < 2) return;
	project.timeline.splice(selected, 1);
	selected = Math.min(selected, project.timeline.length - 1);
	update();
	drawEditor();
	$("editor").focus();
};
$("add").onclick = () => {
	if (project.timeline.length >= 12) return;
	const type = $("new-type").value;
	const scene =
		type === "bullets"
			? { type, heading: "A fresh idea", items: ["Your first point"] }
			: type === "chart"
				? {
						type,
						heading: "A new perspective",
						chart_type: "bar",
						labels: ["One", "Two", "Three"],
						values: [20, 40, 60],
					}
				: {
						type,
						text:
							type === "title"
								? "Your story starts here"
								: "Thanks for watching",
					};
	scene.duration = 4;
	project.timeline.push(scene);
	selected = project.timeline.length - 1;
	update();
	drawEditor();
	$("field-heading")?.focus();
	$("field-text")?.focus();
};
$("project-title").oninput = () => {
	project.meta = { ...project.meta, title: $("project-title").value };
	save();
};
$("preset").onchange = () => {
	const dark = $("preset").value === "dark";
	project.theme = {
		...project.theme,
		preset: $("preset").value,
		bg: dark ? "#191925" : "#faf9fd",
		fg: dark ? "#f5f0ff" : "#24212d",
	};
	update();
};
$("accent").oninput = () => {
	project.theme = { ...project.theme, accent: $("accent").value };
	$("accent-value").textContent = $("accent").value.toUpperCase();
	update();
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
		importProject(JSON.parse(await file.text()));
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
			video.setAttribute("aria-label", "Rendered project");
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
		$("render").textContent = "Render project ↗";
		if (job.state === "complete") await showArtifacts(job);
	} catch (error) {
		rendering = false;
		$("render").disabled = false;
		$("render").textContent = "Render project ↗";
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
			body: JSON.stringify(project),
		});
		rendering = true;
		$("render").disabled = true;
		$("render").textContent = "Rendering…";
		$("artifacts").replaceChildren();
		$("render-status").textContent =
			"Rendering on your computer. This can take up to three minutes.";
		followJob();
	} catch (error) {
		notice(error.message);
	}
};
$("scene-form").onsubmit = (event) => event.preventDefault();
try {
	const saved = localStorage.getItem("frame-project-v1");
	if (saved) importProject(JSON.parse(saved));
} catch {
	notice(
		"Your saved project could not be restored. Import an exported JSON file to recover it.",
	);
}
drawScenes();
drawCanvas();
drawEditor();
drawMeta();
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
