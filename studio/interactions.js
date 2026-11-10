/* Finite interface motion. Rendering/background timelines are separate. */
const interfaceAnimations = new Map();
const interactionMotionPreference = matchMedia(
	"(prefers-reduced-motion: reduce)",
);

function stopInterfaceMotion(root = document) {
	for (const [node, animation] of interfaceAnimations) {
		if (
			root === document ||
			root === node ||
			root.contains(node) ||
			!node.isConnected
		) {
			animation.cancel();
			interfaceAnimations.delete(node);
		}
	}
}
function enterInterface(
	node,
	{ distance = 8, duration = 220, scale = 1 } = {},
) {
	if (!node || node.hidden || !node.isConnected) return;
	for (const [target, animation] of interfaceAnimations) {
		if (!target.isConnected) {
			animation.cancel();
			interfaceAnimations.delete(target);
		}
	}
	stopInterfaceMotion(node);
	if (interactionMotionPreference.matches || document.hidden) return;
	const animation = node.animate(
		[
			{ opacity: 0.25, transform: `translateY(${distance}px) scale(${scale})` },
			{ opacity: 1, transform: "translateY(0) scale(1)" },
		],
		{ duration, easing: "cubic-bezier(.2,.8,.2,1)" },
	);
	interfaceAnimations.set(node, animation);
	const settle = () => {
		if (interfaceAnimations.get(node) === animation)
			interfaceAnimations.delete(node);
	};
	animation.finished.then(settle, settle);
}
let sceneTransition = null;
function stopSceneTransition() {
	if (!sceneTransition) return;
	const { snapshot, animation } = sceneTransition;
	sceneTransition = null;
	animation?.cancel();
	snapshot.remove();
}
function captureSceneTransition() {
	stopSceneTransition();
	if (interactionMotionPreference.matches || document.hidden) return null;
	const canvas = document.getElementById("canvas");
	if (!canvas || !canvas.children.length) return null;
	const snapshot = canvas.cloneNode(true);
	snapshot.removeAttribute("id");
	snapshot
		.querySelectorAll("[id]")
		.forEach((node) => node.removeAttribute("id"));
	snapshot
		.querySelectorAll("[contenteditable]")
		.forEach((node) => node.removeAttribute("contenteditable"));
	snapshot
		.querySelectorAll(".selected,.typing")
		.forEach((node) => node.classList.remove("selected", "typing"));
	snapshot.setAttribute("aria-hidden", "true");
	snapshot.inert = true;
	snapshot.classList.add("scene-snapshot");
	return snapshot;
}
function crossfadeScene(snapshot) {
	if (!snapshot) return;
	if (interactionMotionPreference.matches || document.hidden) return;
	const canvas = document.getElementById("canvas"),
		wrap = canvas.parentElement;
	const bounds = canvas.getBoundingClientRect(),
		parent = wrap.getBoundingClientRect();
	Object.assign(snapshot.style, {
		position: "absolute",
		left: `${bounds.left - parent.left}px`,
		top: `${bounds.top - parent.top}px`,
		margin: "0",
		zIndex: "3",
		pointerEvents: "none",
	});
	snapshot.style.setProperty("width", `${bounds.width}px`, "important");
	snapshot.style.setProperty("height", `${bounds.height}px`, "important");
	wrap.append(snapshot);
	const animation = snapshot.animate([{ opacity: 1 }, { opacity: 0 }], {
		duration: 200,
		easing: "ease-out",
	});
	sceneTransition = { snapshot, animation };
	const settle = () => {
		if (sceneTransition?.snapshot === snapshot) stopSceneTransition();
	};
	animation.finished.then(settle, settle);
}
function animateSceneArrival(added = false) {
	if (added)
		enterInterface(
			document.querySelector('#scenes button[aria-current="true"]'),
			{ distance: 8, duration: 220, scale: 0.97 },
		);
}
// Pointer/keyboard work takes priority over decorative motion, especially drag geometry.
document.addEventListener(
	"pointerdown",
	(event) => {
		for (const [node, animation] of interfaceAnimations) {
			if (node.contains(event.target)) {
				animation.cancel();
				interfaceAnimations.delete(node);
			}
		}
	},
	true,
);
document.addEventListener(
	"pointerdown",
	(event) => {
		if (event.target.closest(".canvas-wrap")) stopSceneTransition();
	},
	true,
);
window.addEventListener("resize", stopSceneTransition);
document.addEventListener(
	"keydown",
	() => {
		stopInterfaceMotion();
		stopSceneTransition();
	},
	true,
);
interactionMotionPreference.addEventListener("change", () => {
	if (interactionMotionPreference.matches) {
		stopInterfaceMotion();
		stopSceneTransition();
	}
});
document.addEventListener("visibilitychange", () => {
	if (document.hidden) {
		stopInterfaceMotion();
		stopSceneTransition();
	}
});
