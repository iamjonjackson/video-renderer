/* Shot regeneration is a staged cloud operation, guarded against concurrent edits. */
let shotCandidate = null,
	shotBaseline = null,
	shotIndex = null,
	shotOperation = 0;
$("regenerate-shot").onclick = async () => {
	const operation = ++shotOperation;
	cancelHostedGeneration();
	shotCandidate = null;
	$("shot-apply").disabled = true;
	try {
		if (!$("cloud-consent").checked)
			throw new Error("Confirm hosted disclosure in Create first.");
		if (!$("generation-provider").value)
			throw new Error("Select a configured hosted provider in Create first.");
		const scene = currentScene(),
			text = scene.elements
				?.filter((i) => i.type === "text")
				.map((i) => i.text)
				.join(" ");
		if (!text) throw new Error("This shot has no text source.");
		shotBaseline = JSON.stringify(project);
		shotIndex = selected;
		const baseline = shotBaseline,
			index = shotIndex;
		$("shot-status").textContent =
			"Generating a candidate; the current shot is unchanged.";
		const spec = await generateHosted(
			{
				title: scene.name || "Shot",
				description: text,
				points: [text.slice(0, 180)],
				structure: "explainer",
				audience: $("brief-audience").value || "general",
				designStyle: $("brief-style").value,
				motionStyle: $("brief-motion-style").value,
				motion: !!scene.motion_version,
				resolution: project.meta?.resolution || { width: 1920, height: 1080 },
				chartData: scene.elements.find((i) => i.type === "chart")
					? {
							labels: scene.elements.find((i) => i.type === "chart").labels,
							values: scene.elements.find((i) => i.type === "chart").values,
						}
					: null,
			},
			{ shotOnly: true },
		);
		if (
			operation !== shotOperation ||
			JSON.stringify(project) !== baseline ||
			selected !== index
		)
			throw new Error("Project changed; candidate discarded.");
		shotCandidate =
			spec.timeline.find((s) => s.source_ids?.includes("source-1")) ||
			spec.timeline[0];
		$("shot-json").value = JSON.stringify(shotCandidate, null, 2);
		$("shot-apply").disabled = false;
		$("shot-panel").showPopover();
		$("shot-status").textContent =
			"Review one replacement shot. Other scenes are unchanged.";
	} catch (error) {
		if (operation === shotOperation)
			$("shot-status").textContent = error.message;
	}
};
$("shot-apply").onclick = async () => {
	const operation = shotOperation,
		baseline = shotBaseline,
		index = shotIndex,
		replacement = structuredClone(shotCandidate);
	try {
		if (!shotCandidate || JSON.stringify(project) !== shotBaseline)
			throw new Error("Project changed; regenerate again.");
		const candidate = structuredClone(project);
		delete replacement.transition;
		candidate.timeline[index] = replacement;
		const { spec } = await request("/api/validate", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(candidate),
		});
		if (operation !== shotOperation || JSON.stringify(project) !== baseline)
			throw new Error("Project changed during validation.");
		importProject(spec);
		selected = index;
		drawCanvas();
		drawScenes();
		shotCandidate = null;
		$("shot-panel").hidePopover();
		announce("Shot replaced. Undo restores the previous version.");
	} catch (error) {
		if (operation === shotOperation)
			$("shot-status").textContent = error.message;
	}
};
