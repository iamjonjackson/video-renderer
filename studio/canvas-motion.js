/* Deterministic authored motion; editing always uses the resting pose. */
function easeProgress(p, easing) {
	if (easing === "ease-out") return 1 - (1 - p) ** 3;
	if (easing === "ease-out-quart") return 1 - (1 - p) ** 4;
	if (easing === "ease-in-out") return 0.5 - 0.5 * Math.cos(Math.PI * p);
	return p;
}
function trackState(a, time, exit = false) {
	const state = { opacity: 1, dx: 0, dy: 0, scale: 1 };
	if (!a) return state;
	let p = Math.max(0, Math.min(1, (time - a.start) / a.duration));
	p = easeProgress(p, a.easing);
	state.opacity = exit
		? 1 - p
		: ["words", "wipe", "characters", "chart-draw"].includes(a.effect)
			? 1
			: p;
	if (a.effect === "scale")
		state.scale = 1 - 0.15 * (a.intensity ?? 1) * (exit ? p : 1 - p);
	if (a.effect === "slide") {
		const distance = 0.06 * (a.intensity ?? 1) * (exit ? p : 1 - p),
			sign = ["left", "up"].includes(a.direction || "left") ? -1 : 1;
		state[["up", "down"].includes(a.direction) ? "dy" : "dx"] = distance * sign;
	}
	return state;
}
function keyframePose(item, time) {
	const frames = item.keyframes;
	if (!frames?.length) return { x: 0, y: 0, scale: 1, opacity: 1 };
	if (time <= frames[0].time) return frames[0];
	for (let index = 1; index < frames.length; index++) {
		const next = frames[index],
			previous = frames[index - 1];
		if (time <= next.time) {
			const p = easeProgress(
				(time - previous.time) / (next.time - previous.time),
				"ease-in-out",
			);
			return Object.fromEntries(
				["x", "y", "scale", "opacity"].map((key) => [
					key,
					previous[key] + (next[key] - previous[key]) * p,
				]),
			);
		}
	}
	return frames.at(-1);
}
function motionState(item, time) {
	const a = trackState(item.animation, time),
		b = trackState(item.exit_animation, time, true),
		k = keyframePose(item, time);
	return {
		opacity: a.opacity * b.opacity * k.opacity,
		dx: a.dx + b.dx + k.x,
		dy: a.dy + b.dy + k.y,
		scale: a.scale * b.scale * k.scale,
	};
}
function revealProgress(item, time) {
	const a = item.animation;
	if (
		time === null ||
		!a ||
		!["words", "wipe", "characters", "chart-draw"].includes(a.effect)
	)
		return 1;
	const p = Math.max(0, Math.min(1, (time - a.start) / a.duration));
	return easeProgress(p, a.easing);
}
function applyElementReveal(node, item, time) {
	const effect = item.animation?.effect,
		p = revealProgress(item, time);
	node.style.maskImage =
		effect === "wipe" && time !== null
			? `linear-gradient(to right,#000 0%,#000 ${p * 100}%,transparent ${p * 100}%,transparent 100%)`
			: "";
	if (item.type === "chart" && effect === "chart-draw") {
		drawChart(node, item, time === null ? 1 : p);
	}
	if (
		item.type === "text" &&
		["words", "characters"].includes(effect) &&
		time !== null
	) {
		if (node.dataset.wordSource !== item.text + effect) {
			node.replaceChildren();
			for (const token of effect === "characters"
				? Array.from(item.text)
				: item.text.split(/(\s+)/)) {
				if (!token) continue;
				if (effect === "characters" || /\S/.test(token)) {
					const span = document.createElement("span");
					span.className = "reveal-word";
					span.textContent = token;
					node.append(span);
				} else node.append(document.createTextNode(token));
			}
			node.dataset.wordSource = item.text + effect;
		}
		const words = node.querySelectorAll(".reveal-word"),
			count = Math.floor(p * words.length);
		words.forEach(
			(word, index) =>
				(word.style.visibility = index < count ? "visible" : "hidden"),
		);
	} else if (node.dataset.wordSource !== undefined) {
		node.textContent = item.text;
		delete node.dataset.wordSource;
	}
}
let motionFrame = null,
	motionTime = null,
	transitionPlayback = null;
function clearTransitionPlayback() {
	if (transitionPlayback) {
		transitionPlayback.cancel();
		transitionPlayback = null;
	}
}
function stopCanvasPlayback(rest = false) {
	clearTransitionPlayback();
	if (motionFrame !== null) cancelAnimationFrame(motionFrame);
	motionFrame = null;
	$("motion-play").textContent = "Play scene";
	if (rest) applyCanvasTime(null);
}
function applyCanvasTime(time) {
	const bounds = $("canvas").getBoundingClientRect();
	for (const item of currentScene().elements || []) {
		const node = canvasNode(item.id);
		if (!node) continue;
		const state =
			time === null
				? { opacity: 1, dx: 0, dy: 0, scale: 1 }
				: motionState(item, time);
		applyElementReveal(node, item, time);
		node.style.opacity = state.opacity;
		node.style.transform = `translate(${state.dx * bounds.width}px,${state.dy * bounds.height}px) scale(${state.scale})`;
	}
	motionTime = time;
	$("motion-time").max = currentScene().duration || 4;
	$("motion-time").value = time || 0;
	$("motion-clock").textContent =
		time === null ? "Resting layout" : `${time.toFixed(1)} s`;
	$("resize-handles").hidden = time !== null || !itemById();
}
$("motion-play").onclick = () => {
	stopProjectPlayback();
	if (motionFrame !== null) {
		stopCanvasPlayback();
		return;
	}
	if (interactionMotionPreference.matches) {
		announce(
			"Playback disabled by reduced-motion preference; scrub to inspect frames.",
		);
		return;
	}
	const duration = currentScene().duration || 4,
		start =
			performance.now() -
			(motionTime === null || motionTime >= duration ? 0 : motionTime * 1000);
	$("motion-play").textContent = "Pause scene";
	const tick = (now) => {
		const time = Math.min(duration, (now - start) / 1000);
		applyCanvasTime(time);
		if (time < duration) motionFrame = requestAnimationFrame(tick);
		else stopCanvasPlayback();
	};
	motionFrame = requestAnimationFrame(tick);
};
$("motion-time").oninput = () => {
	stopProjectPlayback();
	stopCanvasPlayback();
	applyCanvasTime(Number($("motion-time").value));
};
$("motion-rest").onclick = () => stopCanvasPlayback(true);
function syncMotionControls() {
	const exit = $("animation-phase").value === "exit",
		a = itemById()?.[exit ? "exit_animation" : "animation"];
	$("animation-effect").value = a?.effect || "none";
	$("animation-start").value = a?.start || 0;
	$("animation-duration").value = a?.duration || 0.6;
	$("animation-direction").value = a?.direction || "left";
	$("animation-easing").value = a?.easing || "ease-out";
	$("animation-intensity").value = a?.intensity ?? 1;
	for (const option of $("animation-effect").options)
		option.disabled =
			(exit &&
				["words", "wipe", "characters", "chart-draw"].includes(option.value)) ||
			(["words", "characters"].includes(option.value) &&
				itemById()?.type !== "text") ||
			(option.value === "chart-draw" && itemById()?.type !== "chart");
}
$("animation-phase").onchange = syncMotionControls;
$("animation-save").onclick = async () => {
	const item = itemById(),
		owner = currentScene();
	if (!item) return;
	const candidate = structuredClone(project),
		scene = candidate.timeline[selected],
		target = scene.elements.find((i) => i.id === item.id),
		effect = $("animation-effect").value,
		key =
			$("animation-phase").value === "exit" ? "exit_animation" : "animation";
	if (effect === "none") delete target[key];
	else {
		scene.motion_version = 1;
		target[key] = {
			effect,
			start: Number($("animation-start").value),
			duration: Number($("animation-duration").value),
			easing: $("animation-easing").value,
			intensity: Number($("animation-intensity").value),
		};
		if (effect === "slide")
			target[key].direction = $("animation-direction").value;
	}
	const baseline = JSON.stringify(project);
	try {
		await request("/api/validate", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(candidate),
		});
		if (
			JSON.stringify(project) !== baseline ||
			currentScene() !== owner ||
			itemById() !== item
		)
			return;
		Object.assign(item, target);
		if (effect === "none") delete item[key];
		else owner.motion_version = 1;
		save();
		syncMotionControls();
		announce("Element motion saved.");
	} catch (error) {
		notice(error.message);
	}
};
$("scene-transition").onchange = async () => {
	const owner = currentScene(),
		baseline = JSON.stringify(project),
		candidate = structuredClone(project),
		scene = candidate.timeline[selected],
		effect = $("scene-transition").value;
	if (effect === "none") delete scene.transition;
	else {
		scene.motion_version = 1;
		scene.transition = { effect, duration: 0.5 };
	}
	try {
		await request("/api/validate", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(candidate),
		});
		if (JSON.stringify(project) !== baseline || currentScene() !== owner)
			return;
		if (effect === "none") delete owner.transition;
		else {
			owner.transition = scene.transition;
			owner.motion_version = 1;
		}
		save();
		announce("Scene transition saved.");
	} catch (e) {
		notice(e.message);
		$("scene-transition").value = owner.transition?.effect || "none";
	}
};
$("transition-preview").onclick = () => {
	if (interactionMotionPreference.matches) {
		announce("Transition playback disabled by reduced-motion preference.");
		return;
	}
	const outgoing = currentScene(),
		next = project.timeline[selected + 1],
		transition = outgoing.transition;
	if (!next || !transition) {
		announce("Choose a transition on a scene with a following scene.");
		return;
	}
	stopCanvasPlayback(true);
	const canvas = $("canvas"),
		r = canvas.getBoundingClientRect(),
		parent = canvas.parentElement.getBoundingClientRect(),
		stage = document.createElement("div");
	stage.className = "transition-preview";
	stage.inert = true;
	stage.setAttribute("aria-hidden", "true");
	Object.assign(stage.style, {
		position: "absolute",
		left: `${r.left - parent.left}px`,
		top: `${r.top - parent.top}px`,
		width: `${r.width}px`,
		height: `${r.height}px`,
		zIndex: 4,
		overflow: "hidden",
		pointerEvents: "none",
	});
	const layer = (scene) => {
		const node = document.createElement("div");
		renderSceneThumbnail(node, scene);
		Object.assign(node.style, {
			position: "absolute",
			inset: "0",
			containerType: "size",
			background: scene.background?.color || "#191925",
			overflow: "hidden",
		});
		stage.append(node);
		return node;
	};
	const incoming = editableScene(next, project.theme),
		old = layer(outgoing),
		fresh = layer(incoming);
	canvas.parentElement.append(stage);
	const evaluate = (node, scene, time) => {
		[...node.querySelectorAll(".thumbnail-element")].forEach(
			(element, index) => {
				const item = scene.elements[index],
					state = motionState(item, time);
				applyElementReveal(element, item, time);
				element.style.opacity = state.opacity;
				element.style.transform = `translate(${state.dx * r.width}px,${state.dy * r.height}px) scale(${state.scale})`;
			},
		);
	};
	evaluate(old, outgoing, Math.max(0, (outgoing.duration || 4) - 0.000001));
	const start = performance.now();
	let frame;
	transitionPlayback = {
		cancel() {
			cancelAnimationFrame(frame);
			stage.remove();
		},
	};
	const tick = (now) => {
		const time = Math.min(transition.duration, (now - start) / 1000),
			p = time / transition.duration;
		evaluate(fresh, incoming, time);
		if (transition.effect === "crossfade") fresh.style.opacity = p;
		else {
			old.style.transform = `translateX(${-p * r.width}px)`;
			fresh.style.transform = `translateX(${(1 - p) * r.width}px)`;
		}
		if (p < 1) frame = requestAnimationFrame(tick);
		else {
			stage.remove();
			transitionPlayback = null;
		}
	};
	frame = requestAnimationFrame(tick);
};
$("motion-preset-apply").onclick = async () => {
	const owner = currentScene(),
		baseline = JSON.stringify(project),
		candidate = structuredClone(project);
	try {
		const { applyMotionPreset } = await import("/design-presets.mjs");
		applyMotionPreset(
			candidate.timeline[selected],
			$("scene-motion-preset").value,
		);
		await request("/api/validate", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(candidate),
		});
		if (currentScene() !== owner || JSON.stringify(project) !== baseline)
			return;
		project.timeline[selected] = candidate.timeline[selected];
		update();
		announce("Scene animation preset applied.");
	} catch (e) {
		notice(e.message);
	}
};
function drawTimingTracks() {
	const root = $("timing-tracks");
	root.replaceChildren();
	const duration = currentScene().duration || 4;
	for (const item of currentScene().elements || [])
		for (const [key, phase] of [
			["animation", "entrance"],
			["exit_animation", "exit"],
		]) {
			const a = item[key];
			if (!a) continue;
			const row = document.createElement("button");
			row.type = "button";
			row.className = "timing-track button";
			row.textContent = `${item.text?.slice(0, 24) || item.icon || item.type} · ${phase}: ${a.start.toFixed(1)}–${(a.start + a.duration).toFixed(1)} s`;
			const bar = document.createElement("span");
			bar.className = "timing-bar";
			bar.style.marginLeft = `${(a.start / duration) * 100}%`;
			bar.style.width = `${(a.duration / duration) * 100}%`;
			row.append(bar);
			row.onclick = () => {
				$("timing-panel").hidePopover();
				selectElement(item.id);
				showElementOptions();
				$("animation-phase").value = phase;
				syncMotionControls();
			};
			root.append(row);
		}
	for (const item of currentScene().elements || []) {
		if (!item.keyframes) continue;
		const row = document.createElement("div");
		row.className = "timing-track";
		row.textContent = `${item.text?.slice(0, 24) || item.type} · directed poses: ${item.keyframes.map((k) => k.time.toFixed(1)).join(" → ")} s`;
		const button = document.createElement("button");
		button.className = "button subtle";
		button.textContent = "Remove directed poses";
		button.onclick = () => {
			delete item.keyframes;
			save();
			drawCanvas();
			drawTimingTracks();
		};
		row.append(button);
		root.append(row);
	}
	if (!root.children.length)
		root.textContent =
			"No animation tracks yet. Select an element or apply a scene preset.";
}
$("timing-open").addEventListener("click", drawTimingTracks);
document.addEventListener(
	"pointerdown",
	(event) => {
		if (event.target.closest(".canvas-element,.resize-handle"))
			stopCanvasPlayback(true);
	},
	true,
);
interactionMotionPreference.addEventListener("change", () => {
	if (interactionMotionPreference.matches) stopCanvasPlayback(true);
});
document.addEventListener("visibilitychange", () => {
	if (document.hidden) stopCanvasPlayback();
});
