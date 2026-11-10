/* Cloud calls are an explicit, staged alternative; no hidden fallback. */
let hostedJobId = null,
	hostedAbort = null;
async function refreshGenerationCapabilities() {
	const state = await request("/api/generation/capabilities"),
		select = $("generation-provider");
	select.replaceChildren();
	for (const provider of state.providers) {
		const option = document.createElement("option");
		option.value = JSON.stringify({
			provider: provider.provider,
			model: provider.model,
		});
		option.textContent = `${provider.provider} / ${provider.model}${provider.ready ? "" : " · unavailable"}`;
		option.disabled = !provider.ready;
		select.append(option);
	}
	$("generation-readiness").textContent = state.providers.some((p) => p.ready)
		? "API configuration ready. No request has been submitted."
		: "Configure FRAME_GOOGLE_MODEL or FRAME_MISTRAL_MODEL and its server-side key.";
	$("cloud-images").disabled = !state.image_model;
}
$("generation-mode").onchange = () => {
	$("hosted-controls").hidden = $("generation-mode").value !== "hosted";
	$("draft").disabled = false;
	clearCandidate();
	if ($("generation-mode").value === "hosted")
		refreshGenerationCapabilities().catch((e) => composerError(e.message));
	else refreshAISetup();
};
function cancelHostedGeneration() {
	const id = hostedJobId;
	hostedJobId = null;
	hostedAbort?.abort();
	hostedAbort = null;
	if (id)
		request("/api/generation/cancel", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ id }),
		}).catch((e) => announce(e.message));
}
async function generateHosted(brief, { shotOnly = false } = {}) {
	if (!$("cloud-consent").checked)
		throw new Error(
			"Confirm disclosure and API charges before hosted generation.",
		);
	if (!$("generation-provider").value)
		throw new Error("No configured hosted provider is available.");
	let identity;
	try {
		identity = JSON.parse($("generation-provider").value);
	} catch {
		throw new Error(
			"Provider selection is invalid; refresh available providers.",
		);
	}
	const images = $("cloud-images").checked,
		critique = $("cloud-critique").checked,
		repair = $("cloud-repair").checked;
	const abort = new AbortController();
	hostedAbort = abort;
	const { job } = await request("/api/generation/start", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({
			brief,
			shot_only: shotOnly,
			...identity,
			consent: true,
			images,
			critique,
			repair,
			max_calls: 2 + Number(images) + Number(critique) + Number(repair),
		}),
	});
	if (abort.signal.aborted) {
		await request("/api/generation/cancel", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ id: job.id }),
		});
		throw new Error("Generation cancelled.");
	}
	hostedJobId = job.id;
	try {
		while (!abort.signal.aborted) {
			const { job: current } = await request("/api/generation");
			if (abort.signal.aborted) throw new Error("Generation cancelled.");
			if (current?.id !== job.id) throw new Error("Generation superseded.");
			$("composer-status").textContent =
				`${current.stage} · ${current.calls} calls`;
			if (current.state === "complete") {
				if (current.critique?.issues?.length)
					announce("Critique: " + current.critique.issues.join("; "));
				if (current.quality?.warnings?.length)
					announce(current.quality.warnings.join("; "));
				return current.spec;
			}
			if (current.state !== "running") throw new Error(current.message);
			await new Promise((resolve, reject) => {
				const onAbort = () => {
					clearTimeout(timer);
					reject(new Error("Generation cancelled."));
				};
				const timer = setTimeout(() => {
					abort.signal.removeEventListener("abort", onAbort);
					resolve();
				}, 500);
				abort.signal.addEventListener("abort", onAbort, { once: true });
			});
		}
		throw new Error("Generation cancelled.");
	} finally {
		if (hostedJobId === job.id) hostedJobId = null;
		if (hostedAbort === abort) hostedAbort = null;
	}
}

request("/api/generation/capabilities")
	.then((state) => {
		$("narration-identity").textContent = state.narration?.provider
			? `Narration: ${state.narration.provider} / ${state.narration.model} / ${state.narration.voice}. Captions use whole-scene timing; review pronunciation.`
			: "Narration is unconfigured on the server.";
	})
	.catch((e) => announce(e.message));
