/* A master scene clock: seek and playback share exactly the same frame evaluator. */
let projectFrame = null,
	projectTime = 0,
	projectStage = null,
	projectSceneIndex = -1,
	projectLayers = null;
function projectDuration() {
	return project.timeline.reduce((sum, s) => sum + (s.duration || 4), 0);
}
function projectPosition(time) {
	let start = 0;
	for (let index = 0; index < project.timeline.length; index++) {
		const duration = project.timeline[index].duration || 4;
		if (time < start + duration || index === project.timeline.length - 1)
			return { index, local: Math.min(duration, Math.max(0, time - start)) };
		start += duration;
	}
	return { index: 0, local: 0 };
}
function stopProjectPlayback(restore = true) {
	if (projectFrame !== null) cancelAnimationFrame(projectFrame);
	projectFrame = null;
	$("project-play").textContent = "Play project";
	if (restore) {
		projectStage?.remove();
		projectStage = null;
		projectLayers = null;
		projectSceneIndex = -1;
	}
}
function renderProjectTime(time) {
	const canvas = $("canvas"),
		bounds = canvas.getBoundingClientRect(),
		wrap = canvas.parentElement,
		parent = wrap.getBoundingClientRect();
	if (!projectStage) {
		projectStage = document.createElement("div");
		projectStage.className = "project-preview";
		projectStage.inert = true;
		projectStage.setAttribute("aria-hidden", "true");
		wrap.append(projectStage);
	}
	Object.assign(projectStage.style, {
		position: "absolute",
		left: `${bounds.left - parent.left}px`,
		top: `${bounds.top - parent.top}px`,
		width: `${bounds.width}px`,
		height: `${bounds.height}px`,
		overflow: "hidden",
		zIndex: 5,
		pointerEvents: "none",
	});
	const total = projectDuration();
	projectTime = Math.max(0, Math.min(total, time));
	const position = projectPosition(projectTime),
		scene = editableScene(project.timeline[position.index], project.theme),
		previous = position.index
			? editableScene(project.timeline[position.index - 1], project.theme)
			: null;
	const layer = (source) => {
		const node = document.createElement("div");
		renderSceneThumbnail(node, source);
		Object.assign(node.style, {
			position: "absolute",
			inset: "0",
			containerType: "size",
			background: source.background?.color || "#191925",
			overflow: "hidden",
		});
		projectStage.append(node);
		return node;
	};
	if (projectSceneIndex !== position.index) {
		projectStage.replaceChildren();
		projectLayers = {
			previous: previous ? layer(previous) : null,
			current: layer(scene),
		};
		projectSceneIndex = position.index;
	}
	const evaluate = (node, source, t) => {
		const bg = node.querySelector(".canvas-background");
		if (bg) {
			const motion = source.background?.motion;
			bg.style.transform =
				motion === "drift" ? `translate(${Math.sin(t * 0.35) * 2}%,0)` : "";
			bg.style.opacity =
				motion === "pulse" ? String(0.7 + 0.3 * Math.sin(t * 0.7)) : "1";
		}
		[...node.querySelectorAll(".thumbnail-element")].forEach(
			(element, index) => {
				const item = source.elements[index],
					state = motionState(item, t);
				applyElementReveal(element, item, t);
				element.style.opacity = state.opacity;
				element.style.transform = `translate(${state.dx * bounds.width}px,${state.dy * bounds.height}px) scale(${state.scale})`;
			},
		);
	};
	evaluate(projectLayers.current, scene, position.local);
	projectLayers.current.style.opacity = 1;
	projectLayers.current.style.transform = "";
	if (projectLayers.previous) {
		projectLayers.previous.style.display = "none";
		projectLayers.previous.style.transform = "";
	}
	const transition = previous?.transition;
	if (transition && position.local < transition.duration) {
		evaluate(
			projectLayers.previous,
			previous,
			Math.max(0, (previous.duration || 4) - 0.000001),
		);
		projectLayers.previous.style.display = "block";
		const p = position.local / transition.duration;
		if (transition.effect === "crossfade")
			projectLayers.current.style.opacity = p;
		else {
			projectLayers.previous.style.transform = `translateX(${-p * bounds.width}px)`;
			projectLayers.current.style.transform = `translateX(${(1 - p) * bounds.width}px)`;
		}
	}
	$("project-time").max = total;
	$("project-time").value = projectTime;
	$("project-clock").textContent =
		`Scene ${position.index + 1}/${project.timeline.length} · ${projectTime.toFixed(1)} / ${total.toFixed(1)} s`;
}
$("project-play").onclick = () => {
	if (projectFrame !== null) {
		stopProjectPlayback(false);
		return;
	}
	if (interactionMotionPreference.matches) {
		announce(
			"Project playback disabled by reduced-motion preference; scrub the project timeline to inspect it.",
		);
		return;
	}
	finishInlineEditing();
	stopCanvasPlayback(true);
	const total = projectDuration(),
		speed = Number($("project-speed").value),
		start =
			performance.now() -
			((projectTime >= total ? 0 : projectTime) * 1000) / speed;
	$("project-play").textContent = "Pause project";
	const tick = (now) => {
		renderProjectTime(Math.min(total, ((now - start) / 1000) * speed));
		if (projectTime < total) projectFrame = requestAnimationFrame(tick);
		else stopProjectPlayback(false);
	};
	projectFrame = requestAnimationFrame(tick);
};
$("project-time").oninput = () => {
	stopProjectPlayback(false);
	stopCanvasPlayback(true);
	renderProjectTime(Number($("project-time").value));
};
$("project-restart").onclick = () => {
	stopProjectPlayback(false);
	stopCanvasPlayback(true);
	renderProjectTime(0);
};
$("project-stop").onclick = () => stopProjectPlayback();
$("project-speed").onchange = () => stopProjectPlayback(false);
document.addEventListener(
	"pointerdown",
	(event) => {
		if (
			event.target.closest(
				".canvas-element,.resize-handle,#scenes,#add,#add-text,#add-chart,#add-shape,#add-icon,#compose,#import",
			)
		)
			stopProjectPlayback();
	},
	true,
);
window.addEventListener("resize", () => stopProjectPlayback());
document.addEventListener("visibilitychange", () => {
	if (document.hidden) stopProjectPlayback(false);
});
interactionMotionPreference.addEventListener("change", () => {
	if (interactionMotionPreference.matches) stopProjectPlayback();
});
