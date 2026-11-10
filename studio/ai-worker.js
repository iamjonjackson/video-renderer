import { Wllama } from "/ai-assets/wllama.js";
import {
	parseStoryboard,
	storyboardMessages,
	slidePlan,
	presentationMessages,
	presentationSchema,
} from "./ai-protocol.mjs";

const progress = (message) => self.postMessage({ type: "progress", message });
let engine;
self.onmessage = async ({ data }) => {
	try {
		storyboardMessages(data.brief);
		if (!engine) {
			engine = new Wllama(
				{ default: "/ai-assets/wllama.wasm" },
				{ logger: { debug() {}, log() {}, warn() {}, error() {} } },
			);
			progress(
				"Loading small local AI (386 MB). No internet connection needed after setup…",
			);
			await engine.loadModelFromUrl("/ai-assets/smollm2.gguf", {
				n_ctx: 8192,
				n_threads: 1,
				n_gpu_layers: 0,
				progressCallback: ({ loaded, total }) =>
					progress(`Loading local AI: ${Math.round((loaded / total) * 100)}%`),
			});
		}
		const plan = slidePlan(data.brief);
		progress(
			`Writing ${plan.length} connected slides from your source material…`,
		);
		const result = await engine.createChatCompletion({
			messages: presentationMessages(data.brief, plan),
			max_tokens: 1800,
			temperature: 0,
			response_format: {
				type: "json_schema",
				json_schema: {
					name: "storyboard",
					schema: presentationSchema(data.brief, plan),
					strict: true,
				},
			},
		});
		if (result.choices[0]?.finish_reason === "length")
			throw new Error("AI response was truncated. Try a shorter brief.");
		self.postMessage({
			type: "result",
			spec: parseStoryboard(result.choices[0]?.message.content),
		});
	} catch (error) {
		await engine?.exit().catch(() => {});
		engine = null;
		self.postMessage({
			type: "error",
			message: `Local AI failed: ${error.message}. Your project is unchanged.`,
		});
	}
};
