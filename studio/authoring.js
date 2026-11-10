/* Two-page authoring: staged candidates never replace a project before consent. */
let draftCandidate = null;
let draftRevision = 0;
let drafting = false;
let aiWorker=null, pendingGeneration=null;
const examples = {
	explainer: {
		title: "Designing for everyone",
		brief:
			"Explain how accessible design helps people use digital products with confidence.",
		points: [
			"Use clear language and readable text",
			"Make every action work with a keyboard",
			"Provide helpful feedback when something goes wrong",
		],
	},
	pitch: {
		title: "A simpler way to plan",
		brief:
			"Introduce a planning tool that helps a team organise work and see what matters next.",
		points: [
			"Bring tasks into one shared view",
			"Give each task a clear owner",
			"Review the next step together",
		],
	},
	update: {
		title: "This week, in focus",
		brief:
			"Share a concise project update with colleagues, including completed work and next steps.",
		points: [
			"Summarise the work completed",
			"Explain what still needs attention",
			"Agree the next milestone",
		],
	},
};
function clearCandidate() {
 cancelGeneration();
	draftRevision += 1;
	draftCandidate = null;
	$("draft-preview").hidden = true;
	$("replace-consent").checked = false;
	$("apply-draft").disabled = true;
}
function composerError(message) {
	$("composer-error").textContent = message;
	$("composer-error").hidden = !message;
	if (message) $("composer-error").focus();
}
let workspacePage = null;
function navigateWorkspace() {
	const create = location.hash === "#create";
	const changed = workspacePage !== null && workspacePage !== create;
	stopInterfaceMotion($("editor-page"));
	stopInterfaceMotion($("composer"));
	workspacePage = create;
	finishInlineEditing();
	stopPreview();
	$("editor-page").hidden = create;
	$("composer").hidden = !create;
	$("nav-editor").setAttribute("aria-current", create ? "false" : "page");
	$("compose").setAttribute("aria-current", create ? "page" : "false");
	$("skip-link").href = create ? "#composer" : "#editor";
 syncSelectionHighlights();
	if (create) $("composer").focus();
	else {
		clearCandidate();
		drawCanvas();
		$("editor").focus();
	}
 syncSelectionHighlights();
	if (changed)
		enterInterface(create ? $("composer") : $("editor-page"), {
			distance: 10,
			duration: 260,
		});
}
$("composer-close").onclick = () => {
	location.hash = "#edit";
};
$("skip-link").onclick = (event) => {
	event.preventDefault();
	(location.hash === "#create" ? $("composer") : $("editor")).focus();
};
window.addEventListener("hashchange", navigateWorkspace);
navigateWorkspace();
for (const button of document.querySelectorAll("[data-example]"))
	button.onclick = () => {
		const key = button.dataset.example;
		const example = examples[key];
		$("template").value = key;
		$("brief-title").value = example.title;
		$("brief").value = example.brief;
		$("key-points").value = example.points.join("\n");
		clearCandidate();
		composerError("");
		$("composer-status").textContent =
			"Example filled in. Make it your own before building a storyboard.";
	};
for (const id of [
	"template",
	"brief-title",
	"brief",
	"key-points",
])
	$(id).addEventListener("input", clearCandidate);
$("replace-consent").onchange = () => {
	$("apply-draft").disabled = !draftCandidate || !$("replace-consent").checked;
};
$("draft").onclick = async () => {
	if (drafting) return;
	clearCandidate();
	composerError("");
	const revision = draftRevision;
	drafting = true;
 $("cancel-draft").hidden=false;
	$("draft").disabled = true;
	$("composer-status").textContent = "Building and validating your storyboard…";
	try {
        const title=$("brief-title").value.trim(), description=$("brief").value.trim();
        if(!title || title.length>100)throw new Error("Add a title of 1–100 characters.");
        if(description.length<20 || description.length>3000)throw new Error("Describe your video in 20–3000 characters.");
        const points=$("key-points").value.split("\n").map(p=>p.trim()).filter(Boolean);
        if(points.length>6 || points.some(p=>p.length>180))throw new Error("Use up to 6 key points, each at most 180 characters.");
        const generated=await generateLocally({title,description,points,structure:$("template").value});
        if(revision!==draftRevision || $("composer").hidden)return;
        const {spec}=await request("/api/validate",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(generated)});
		if (revision !== draftRevision || $("composer").hidden) return;
		checkImport(spec);
		draftCandidate = spec;
		$("draft-summary").textContent =
			`${spec.timeline.length} scenes. Review the content and JSON; your current project is unchanged.`;
		$("draft-json").value = JSON.stringify(spec, null, 2);
		$("draft-preview").hidden = false;
		enterInterface($("draft-preview"), { distance: 8 });
		$("composer-status").textContent = "Storyboard ready for review.";
		$("draft-json").focus();
	} catch (error) {
		if (revision === draftRevision && !$("composer").hidden) {
			composerError(error.message);
			$("composer-status").textContent = "Your project has not changed.";
		}
	} finally {
        if(revision===draftRevision){drafting=false;$("draft").disabled=false;$("cancel-draft").hidden=true;}
	}
};
$("apply-draft").onclick = () => {
	if (!draftCandidate || !$("replace-consent").checked) return;
	importProject(draftCandidate);
	location.hash = "#edit";
	announce("New storyboard applied. Scene 1 selected.");
};
$("output-format").onchange = () => {
	if (!rendering) $("render").textContent = renderLabel();
};

function cancelGeneration(){
 if(pendingGeneration){aiWorker?.terminate();aiWorker=null;pendingGeneration.reject(new Error('Generation cancelled.'));pendingGeneration=null;}
 drafting=false;$("draft").disabled=false;$("cancel-draft").hidden=true;
}
function generateLocally(brief){
 return new Promise((resolve,reject)=>{
  if(!aiWorker){
   aiWorker=new Worker('/ai-worker.js',{type:'module'});
   aiWorker.onmessage=({data})=>{
    if(!pendingGeneration)return;
    if(data.type==='progress'){$('composer-status').textContent=data.message;return;}
    const pending=pendingGeneration;pendingGeneration=null;
    if(data.type==='result')pending.resolve(data.spec);else{aiWorker.terminate();aiWorker=null;pending.reject(new Error(data.message));}
   };
   aiWorker.onerror=()=>{const pending=pendingGeneration;pendingGeneration=null;aiWorker?.terminate();aiWorker=null;pending?.reject(new Error('Browser AI could not start. Run the setup script, and use a current browser with WebAssembly.'));};
  }
  pendingGeneration={resolve,reject};aiWorker.postMessage({brief});
 });
}
$('cancel-draft').onclick=()=>{clearCandidate();$('composer-status').textContent='Generation cancelled. Your project is unchanged.';};
