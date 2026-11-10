let trackOwner = null,
	trackBaseline = null;
/* Advanced tracks edit the same portable document, validated before application. */
function showTimelineEditor() {
	trackOwner = currentScene();
	trackBaseline = JSON.stringify(project);
	const scene = currentScene(),
		item = itemById();
	$("track-json").value = JSON.stringify(
		{
			beats: scene.beats || [],
			groups: scene.groups || [],
			element: item
				? {
						id: item.id,
						keyframes: item.keyframes || [],
						group: item.group || "",
						...(item.type === "path"
							? { points: item.points, stroke_width: item.stroke_width }
							: {}),
						...(item.type === "text" ? { chunks: item.chunks || [] } : {}),
						...(item.type === "chart"
							? { series_stagger: item.series_stagger || 0 }
							: {}),
					}
				: null,
		},
		null,
		2,
	);
	$("track-error").textContent = "";
}
$("track-open").onclick = () => {
	showTimelineEditor();
	$("track-panel").showPopover();
};
$("track-save").onclick = async () => {
	const baseline = JSON.stringify(project),
		candidate = structuredClone(project),
		scene = candidate.timeline[selected];
	try {
		if (
			currentScene() !== trackOwner ||
			JSON.stringify(project) !== trackBaseline
		)
			throw new Error("Project changed; reopen tracks before saving.");
		const value = JSON.parse($("track-json").value);
		if (
			!value ||
			Object.keys(value).some(
				(k) => !["beats", "groups", "element"].includes(k),
			)
		)
			throw new Error("Use beats, groups and element fields only.");
		scene.beats = value.beats;
		scene.groups = value.groups;
		if (value.element) {
			const target = scene.elements.find((i) => i.id === value.element.id);
			if (!target) throw new Error("Selected element is missing.");
			for (const key of Object.keys(value.element)) {
				if (
					![
						"id",
						"keyframes",
						"group",
						"points",
						"stroke_width",
						"chunks",
						"series_stagger",
					].includes(key)
				)
					throw new Error("Unsupported track field.");
				if (key === "id") continue;
				if (
					value.element[key] === "" ||
					(Array.isArray(value.element[key]) && !value.element[key].length)
				)
					delete target[key];
				else target[key] = value.element[key];
			}
		}
		scene.motion_version = 1;
		const active = selected;
		const { spec } = await request("/api/validate", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(candidate),
		});
		if (JSON.stringify(project) !== baseline)
			throw new Error("Project changed while validating; reopen tracks.");
		importProject(spec);
		selected = active;
		drawCanvas();
		drawScenes();
		$("track-panel").hidePopover();
		announce("Timeline tracks saved.");
	} catch (error) {
		$("track-error").textContent = error.message;
	}
};
$("quality-check").onclick = async () => {
	try {
		const report = await request("/api/quality", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(project),
		});
		$("quality-result").textContent =
			[...report.errors, ...report.warnings].join("\n") ||
			"No mechanical findings. Review facts and watch the full rendered film.";
	} catch (error) {
		$("quality-result").textContent = error.message;
	}
};
