/* Bounded full-document history includes generated/imported edits, not cloud jobs. */
const projectHistory = {
	past: [],
	future: [],
	last: JSON.stringify(project),
	restoring: false,
};
function recordProjectHistory() {
	if (projectHistory.restoring) return;
	const next = JSON.stringify(project);
	if (next === projectHistory.last) return;
	projectHistory.past.push(projectHistory.last);
	while (
		projectHistory.past.length > 12 ||
		projectHistory.past.reduce((sum, s) => sum + s.length, 0) > 8 * 1024 * 1024
	)
		projectHistory.past.shift();
	projectHistory.future = [];
	projectHistory.last = next;
	syncHistoryButtons();
}
function syncHistoryButtons() {
	$("undo-project").disabled = !projectHistory.past.length;
	$("redo-project").disabled = !projectHistory.future.length;
}
function restoreHistory(direction) {
	finishInlineEditing();
	const source =
			direction === "undo" ? projectHistory.past : projectHistory.future,
		target = direction === "undo" ? projectHistory.future : projectHistory.past;
	if (!source.length) return;
	const saved = source.pop();
	target.push(projectHistory.last);
	projectHistory.restoring = true;
	try {
		importProject(JSON.parse(saved));
		projectHistory.last = JSON.stringify(project);
	} finally {
		projectHistory.restoring = false;
		syncHistoryButtons();
	}
}
$("undo-project").onclick = () => restoreHistory("undo");
$("redo-project").onclick = () => restoreHistory("redo");
syncHistoryButtons();
document.addEventListener("keydown", (event) => {
	if (event.target.closest('input,textarea,[contenteditable="true"]')) return;
	if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "z") {
		event.preventDefault();
		restoreHistory(event.shiftKey ? "redo" : "undo");
	}
});
