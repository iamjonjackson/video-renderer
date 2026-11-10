/* One retained highlight per selector group survives scene-button rebuilds. */
function syncSelectionHighlight(root, selector) {
	const target = root.querySelector(selector);
	if (!target || root.offsetWidth === 0) {
		root.classList.remove("highlight-ready");
		return;
	}
	const container = root.getBoundingClientRect(),
		bounds = target.getBoundingClientRect();
	root.style.setProperty(
		"--highlight-x",
		`${bounds.left - container.left + root.scrollLeft - root.clientLeft}px`,
	);
	root.style.setProperty(
		"--highlight-y",
		`${bounds.top - container.top + root.scrollTop - root.clientTop}px`,
	);
	root.style.setProperty("--highlight-width", `${bounds.width}px`);
	root.style.setProperty("--highlight-height", `${bounds.height}px`);
	root.classList.add("highlight-ready");
}
function syncSelectionHighlights() {
	syncSelectionHighlight(
		document.querySelector(".page-nav"),
		'a[aria-current="page"]',
	);
	syncSelectionHighlight(
		document.getElementById("scenes"),
		'button[aria-current="true"]',
	);
}
window.addEventListener("resize", syncSelectionHighlights);
new ResizeObserver(syncSelectionHighlights).observe(
	document.querySelector(".page-nav"),
);
new ResizeObserver(syncSelectionHighlights).observe(
	document.getElementById("scenes"),
);
