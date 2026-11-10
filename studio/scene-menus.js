let sceneMenuTarget = null,
	sceneMenuReturn = null;
function closeSceneMenus(restore = true) {
	for (const id of ["scene-picker", "scene-options"]) {
		const menu = $(id);
		if (menu.matches(":popover-open")) menu.hidePopover();
		stopInterfaceMotion(menu);
	}
	sceneMenuTarget = null;
	if (restore && sceneMenuReturn?.isConnected) sceneMenuReturn.focus();
}
function positionSceneMenu(menu, anchor, x, y) {
	const bounds = anchor.getBoundingClientRect();
	menu.showPopover();
	menu.style.left = `${Math.max(8, Math.min(x ?? bounds.left, innerWidth - menu.offsetWidth - 8))}px`;
	menu.style.top = `${Math.max(8, Math.min(y ?? bounds.bottom, innerHeight - menu.offsetHeight - 8))}px`;
	enterInterface(menu, { distance: 4, duration: 150 });
	menu.querySelector("button").focus();
}
$("add").onclick = () => {
	closeSceneMenus(false);
	sceneMenuReturn = $("add");
	positionSceneMenu($("scene-picker"), $("add"));
};
$("scene-picker-close").onclick = () => closeSceneMenus();
$("scene-options-close").onclick = () => closeSceneMenus();
function showSceneOptions(scene, x, y) {
	closeSceneMenus(false);
	const index = project.timeline.indexOf(scene);
	if (index < 0) return;
	sceneMenuTarget = scene;
	sceneMenuReturn = $("scenes").querySelectorAll(".scene-button")[index];
	$("scene-options-title").textContent = `Scene ${index + 1}`;
	$("scene-delete").disabled = project.timeline.length === 1;
	positionSceneMenu($("scene-options"), sceneMenuReturn, x, y);
}
for (const button of document.querySelectorAll("[data-scene-type]"))
	button.onclick = () => {
		const type = button.dataset.sceneType;
		closeSceneMenus(false);
		addScene(type);
	};
$("scene-edit").onclick = () => {
	const index = project.timeline.indexOf(sceneMenuTarget);
	closeSceneMenus(false);
	if (index < 0) return;
	choose(index);
	$("editor").focus();
};
$("scene-delete").onclick = () => {
	const index = project.timeline.indexOf(sceneMenuTarget);
	closeSceneMenus(false);
	if (index >= 0) deleteScene(index);
};
document.addEventListener(
	"pointerdown",
	(event) => {
		if (
			event.button === 0 &&
			!event.target.closest(".scene-menu,#add,.scene-more")
		)
			closeSceneMenus(false);
	},
	true,
);
document.addEventListener(
	"keydown",
	(event) => {
		if (
			event.key === "Escape" &&
			document.querySelector(".scene-menu:popover-open")
		) {
			event.preventDefault();
			closeSceneMenus();
		}
	},
	true,
);
