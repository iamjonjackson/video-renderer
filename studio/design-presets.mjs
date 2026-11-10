/* Original bounded compositions, not imported HyperFrames/Motion assets. */
export const motionPresets = [
	"none",
	"reveal",
	"rise",
	"focus",
	"story",
	"calm",
	"balanced",
	"energetic",
	"cinematic",
];
export const motionStyles = {
	calm: {
		duration: 1.2,
		stagger: 0.16,
		intensity: 0.35,
		easing: "ease-in-out",
	},
	balanced: {
		duration: 0.8,
		stagger: 0.12,
		intensity: 0.8,
		easing: "ease-out",
	},
	energetic: {
		duration: 0.45,
		stagger: 0.07,
		intensity: 1.5,
		easing: "ease-out-quart",
	},
	cinematic: {
		duration: 1.6,
		stagger: 0.18,
		intensity: 0.55,
		easing: "ease-in-out",
	},
};
export function applyMotionPreset(scene, preset) {
	if (!motionPresets.includes(preset))
		throw new Error("Unsupported motion preset.");
	for (const [index, item] of scene.elements.entries()) {
		delete item.keyframes;
        delete item.animation;
		delete item.exit_animation;
		if (preset === "none") continue;
		if (motionStyles[preset]) {
			const style = motionStyles[preset],
				duration = Math.min(style.duration, scene.duration / 3),
				exitDuration = Math.min(0.5, scene.duration / 5),
				start = Math.min(
					index * style.stagger,
					Math.max(0, scene.duration - duration - exitDuration),
				);
			const chapter = item.id?.endsWith("-chapter");
			const effect =
				item.type === "chart"
					? "chart-draw"
					: item.type === "text"
						? chapter
							? "fade"
							: preset === "energetic"
								? "words"
								: preset === "cinematic"
									? "characters"
									: "slide"
						: item.type === "shape"
							? "wipe"
							: item.type === "image"
								? "scale"
								: "scale";
			item.animation = {
				effect,
				start,
				duration,
				easing: style.easing,
				intensity: style.intensity,
			};
			if (effect === "slide")
				item.animation.direction = index % 2 ? "down" : "left";
			item.exit_animation = {
				effect: "fade",
				start: scene.duration - exitDuration,
				duration: exitDuration,
				easing: style.easing,
			};
			continue;
		}
		const duration = Math.min(0.6, scene.duration / 3),
			start = Math.min(
				index * 0.12,
				Math.max(0, scene.duration - 2 * duration),
			);
		item.animation = {
			effect:
				preset === "rise" ? "slide" : preset === "focus" ? "scale" : "fade",
			start,
			duration,
			easing: "ease-out",
		};
		if (preset === "story") {
			item.animation.effect =
				item.type === "text"
					? "characters"
					: item.type === "chart"
						? "chart-draw"
						: "scale";
		}
		if (preset === "rise") item.animation.direction = "down";
		item.exit_animation = {
			effect: "fade",
			start: scene.duration - duration,
			duration,
			easing: "ease-out",
		};
	}
	if (preset === "none") delete scene.transition;
	else scene.motion_version = 1;
	return scene;
}
export function applyArtDirection(scene, layout, palette, iconName, index) {
	const palettes = {
		violet: { bg: "#191925", accent: "#bba5ff", card: "#302b43" },
		teal: { bg: "#122126", accent: "#72ddd0", card: "#203c40" },
		amber: { bg: "#241e18", accent: "#f5c26b", card: "#403225" },
	};
	const theme = palettes[palette];
	if (
		!theme ||
		!["editorial", "spotlight", "split"].includes(layout) ||
		!["none", "check", "star", "info", "target", "heart", "arrow"].includes(
			iconName,
		)
	)
		throw new Error("Unsupported art direction.");
	const oldAccent = scene.background.accent;
	scene.background.color = theme.bg;
	scene.background.accent = theme.accent;
	for (const item of scene.elements) {
		if (item.color === oldAccent) item.color = theme.accent;
		if (item.type === "shape" && item.color === "#302b43")
			item.color = theme.card;
	}
	const texts = scene.elements.filter((i) => i.type === "text");
	if (
		scene.name !== "Takeaway" &&
		texts.length > 1 &&
		!scene.elements.some((i) => i.type === "chart")
	) {
		texts[0].y = 0.18;
		texts[0].h = 0.32;
		texts[1].y = 0.58;
		texts[1].h = 0.26;
	}
	if (layout === "spotlight" && !scene.elements.some((i) => i.type === "chart"))
		for (const text of texts) {
			text.align = "center";
			text.x = 0.12;
			text.w = 0.76;
		}
	if (
		layout === "split" &&
		texts.length > 1 &&
		!scene.elements.some((i) => i.type === "chart")
	) {
		texts[0].x = 0.08;
		texts[0].w = 0.4;
		texts[0].y = 0.22;
		texts[0].h = 0.56;
		texts[1].x = 0.55;
		texts[1].w = 0.37;
		texts[1].y = 0.3;
		texts[1].h = 0.5;
	}
	if (iconName !== "none")
		scene.elements.unshift({
			id: `scene-${index}-symbol`,
			type: "icon",
			icon: iconName,
			x: 0.83,
			y: 0.04,
			w: 0.07,
			h: 0.09,
			color: theme.accent,
		});
	return scene;
}
