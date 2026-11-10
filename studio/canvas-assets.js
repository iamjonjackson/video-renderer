/* Portable assets contain pixels, never URLs or filesystem references. */
let suppliedAsset = null;
async function readCanvasAsset(file) {
	if (
		!file ||
		!["image/png", "image/jpeg"].includes(file.type) ||
		file.size > 10 * 1024 * 1024
	)
		throw new Error("Choose a PNG or JPEG smaller than 10 MiB.");
	const bitmap = await createImageBitmap(file);
	try {
		const scale = Math.min(1, 1600 / Math.max(bitmap.width, bitmap.height)),
			canvas = document.createElement("canvas");
		canvas.width = Math.max(1, Math.round(bitmap.width * scale));
		canvas.height = Math.max(1, Math.round(bitmap.height * scale));
		canvas
			.getContext("2d")
			.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
		const src = canvas.toDataURL("image/jpeg", 0.82);
		if ((src.length * 3) / 4 > 256 * 1024)
			throw new Error(
				"This image is still larger than 256 KiB. Crop or compress it before adding.",
			);
		return { src, alt: file.name.replace(/\.[^.]+$/, "").slice(0, 160) };
	} finally {
		bitmap.close();
	}
}
$("add-image").onclick = () => $("image-file").click();
$("image-file").onchange = async (event) => {
	try {
		const asset = await readCanvasAsset(event.target.files[0]);
		if ((currentScene().elements || []).length >= 16)
			throw new Error("Use at most 16 elements.");
		finishInlineEditing();
		const item = {
			id: "image-" + crypto.randomUUID(),
			type: "image",
			...asset,
			fit: "cover",
			x: 0.15,
			y: 0.15,
			w: 0.65,
			h: 0.65,
			color: "#ffffff",
		};
		currentScene().elements.push(item);
		selectedElement = item.id;
		save();
		drawCanvas();
	} catch (error) {
		announce(error.message);
	} finally {
		event.target.value = "";
	}
};
$("brief-image").onchange = async (event) => {
	try {
		suppliedAsset = await readCanvasAsset(event.target.files[0]);
		$("brief-image-status").textContent = "Image ready: " + suppliedAsset.alt;
		clearCandidate();
	} catch (error) {
		suppliedAsset = null;
		$("brief-image-status").textContent = error.message;
	} finally {
		event.target.value = "";
	}
};
$("brief-image-clear").onclick = () => {
	suppliedAsset = null;
	$("brief-image-status").textContent = "No supplied image.";
	clearCandidate();
};
$("element-font").onchange = () => {
	const item = itemById();
	if (item?.type === "text") {
		item.font_family = $("element-font").value;
		save();
		drawCanvas();
	}
};
$("image-fit").onchange = () => {
	const item = itemById();
	if (item?.type === "image") {
		item.fit = $("image-fit").value;
		save();
		drawCanvas();
	}
};
$("image-alt").onchange = () => {
	const item = itemById();
	if (item?.type === "image") {
		item.alt = $("image-alt").value.trim() || "Supplied image";
		save();
		drawCanvas();
	}
};
async function fitGeneratedText(spec) {
	await Promise.all(
		Object.keys(canvasFontNames).flatMap((family) => [
			document.fonts.load(`16px "${canvasFontNames[family]}"`),
			document.fonts.load(`bold 16px "${canvasFontNames[family]}"`),
		]),
	);
	const resolution = spec.meta.resolution,
		probe = document.createElement("div");
	probe.style.cssText =
		"position:fixed;left:-10000px;top:0;visibility:hidden;white-space:pre-wrap;line-height:1.25;padding:2px;box-sizing:border-box;";
	document.body.append(probe);
	try {
		for (const scene of spec.timeline)
			for (const item of scene.elements.filter((i) => i.type === "text")) {
				probe.textContent = item.text;
				probe.style.width = `${item.w * resolution.width}px`;
				probe.style.fontFamily = `"${canvasFontNames[item.font_family || "sans"]}"`;
				probe.style.fontWeight = item.bold ? "700" : "400";
				let size = item.font_size;
				do {
					probe.style.fontSize = `${size * resolution.height}px`;
					if (
						probe.scrollHeight <= item.h * resolution.height + 1 &&
						probe.scrollWidth <= item.w * resolution.width + 1
					)
						break;
					size -= 0.001;
				} while (size >= 0.02);
				if (size < 0.02)
					throw new Error(
						"A generated text block does not fit at a readable size. Shorten the source point or change the aspect ratio.",
					);
				item.font_size = size;
			}
	} finally {
		probe.remove();
	}
	return spec;
}
