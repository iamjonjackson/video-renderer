/* Two-page authoring: staged candidates never replace a project before consent. */
let draftCandidate = null;
let draftRevision = 0;
let drafting = false;
let aiWorker=null, pendingGeneration=null, generationId=0;
const examples = {
 explainer:{title:'Accessible forms: four practical checks',audience:'Junior web developers',motion:true,chartData:'',brief:'Teach junior developers how to make a sign-up form accessible. Clear labels explain what each field needs. Keyboard users must reach and activate every control. Error messages identify the problem and explain how to fix it. Keep focus visible throughout the form. Use grouped cards to organise the practical checks. Finish by asking viewers to test their next form without a mouse. Do not invent compliance claims or statistics.',points:['Clear labels explain each field','Every control works with a keyboard','Errors explain the problem and the fix','Focus remains visible']},
 pitch:{title:'One shared plan for our next event',audience:'A five-person volunteer team',motion:true,chartData:'',brief:'Pitch a proposed planning board to a five-person volunteer team. Tasks currently live in separate messages, making ownership unclear. The proposed board brings tasks into one shared view. Each task has an owner and a next action. A weekly review identifies blocked work. This is a proposal, not an existing product. No savings or customer results have been measured. Use a rounded card for the proposed solution and an arrow for the next action. Invite the team to trial the board for its next event.',points:['Separate messages make task ownership unclear','One shared view shows tasks and owners','Each task includes a concrete next action','A weekly review identifies blocked work','Trial the proposed board at the next event']},
 update:{title:'Support review: counts, context and next action',audience:'Support leads and service owners',motion:true,chartData:'Week 1: 12\nWeek 2: 18\nWeek 3: 15',brief:'Present a three-week support update to service owners. Week 1 recorded 12 requests, Week 2 recorded 18, and Week 3 recorded 15. Show a line graph comparing these verified counts. These are request counts, not percentages. The cause of the changes is unknown. No improvement has been attributed to a specific action. Use a quiet grid background for the data and a highlighted card for the caveat. Do not forecast a continuing trend. Ask the team to compare next week before drawing conclusions.',points:['Compare weekly request counts with a line graph','Week 1: 12; Week 2: 18; Week 3: 15','These are counts, not percentages','The cause of the change remains unknown','Review next week before drawing conclusions']},
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
 stopCanvasPlayback(true);
 stopProjectPlayback();
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
        $("brief-audience").value=example.audience;
        $("brief-chart-data").value=example.chartData;
        $("brief-motion").checked=example.motion;
		clearCandidate();
		composerError("");
		$("composer-status").textContent =
			"Example filled in. Make it your own before building a storyboard.";
	};
for (const id of [
	"template",
	"brief-title",
	"brief",
	"key-points", "brief-audience", "brief-motion", "brief-chart-data", "brief-style", "brief-motion-style",
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
        const setup=await request("/api/ai-setup");if(revision!==draftRevision || $("composer").hidden)return;if(setup.status!=="ready")throw new Error("Enable local AI in the setup panel first.");
        const {parseChartData}=await import("/ai-visuals.mjs");
        const chartData=parseChartData($("brief-chart-data").value);
        let generated=await generateLocally({title,description,points,chartData,designStyle:$("brief-style").value,motionStyle:$("brief-motion-style").value,asset:suppliedAsset,structure:$("template").value,audience:$("brief-audience").value.trim(),motion:$("brief-motion").checked,resolution:project.meta?.resolution||{width:1920,height:1080}});
        if(revision!==draftRevision || $("composer").hidden)return;
        generated=await fitGeneratedText(generated);
        const {spec}=await request("/api/validate",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(generated)});
		if (revision !== draftRevision || $("composer").hidden) return;
		checkImport(spec);
		draftCandidate = spec;
		$("draft-summary").textContent =
			`${spec.timeline.length} editable animated canvases. Source text is preserved; supporting sentences are selected from your brief. Review relevance and readability before applying. PowerPoint exports static editable layouts.`;
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
    if(!pendingGeneration || data.id!==pendingGeneration.id)return;
    if(data.type==='progress'){$('composer-status').textContent=data.message;return;}
    const pending=pendingGeneration;pendingGeneration=null;
    if(data.type==='result')pending.resolve(data.spec);else{aiWorker.terminate();aiWorker=null;pending.reject(new Error(data.message));}
   };
   aiWorker.onerror=()=>{const pending=pendingGeneration;pendingGeneration=null;aiWorker?.terminate();aiWorker=null;pending?.reject(new Error('Browser AI could not start. Enable local AI, and use a current browser with WebAssembly.'));};
  }
  const id=++generationId;pendingGeneration={resolve,reject,id};aiWorker.postMessage({brief,id});
 });
}
$('cancel-draft').onclick=()=>{clearCandidate();$('composer-status').textContent='Generation cancelled. Your project is unchanged.';};

let setupTimer=null;
async function refreshAISetup(){
 try{const state=await request('/api/ai-setup');if(state.manifest)$('setup-model').textContent=`${state.manifest.model} · ${Math.round(state.manifest.installed_bytes/1000000)} MB installed. No vision model required.`;$('setup-status').textContent=state.warning || state.error || (state.status==='ready'?'Local AI ready — verified offline.':`${state.status}: ${Math.round(state.bytes_downloaded/1024/1024)} MB downloaded`);$('setup-start').hidden=['ready','downloading','verifying'].includes(state.status);$('setup-cancel').hidden=!['downloading','verifying'].includes(state.status);$('draft').disabled=drafting||state.status!=='ready';
 if(['downloading','verifying'].includes(state.status)){setupTimer=setTimeout(refreshAISetup,500);}
 }catch(error){$('setup-status').textContent=error.message;}
}
$('setup-start').onclick=async()=>{try{await request('/api/ai-setup/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({consent:true})});refreshAISetup();}catch(error){$('setup-status').textContent=error.message;}};
$('setup-cancel').onclick=async()=>{await request('/api/ai-setup/cancel',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});clearTimeout(setupTimer);refreshAISetup();};
request('/api/bootstrap').then(()=>refreshAISetup());
