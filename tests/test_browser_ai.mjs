import {directSequence} from '../studio/sequence-director.mjs';
import {composeScene,editorialMessages} from '../studio/composition-design.mjs';
import { test } from "node:test";
import assert from "node:assert/strict";
import {
	slidePlan,
	presentationSchema,
	parseStoryboard,
} from "../studio/ai-protocol.mjs";
const brief = {
	title: "Clear forms",
	description:
		"Use labels so each form control is understandable. Test the form without a mouse.",
	points: ["Use labels", "Test with a keyboard"],
	structure: "explainer",
};
test("canvas generation preserves every supplied point and direct editability", () => {
	const plan = slidePlan(brief),
		schema = presentationSchema(brief, plan);
	assert.equal(plan.length, 4);
	assert.equal(
		schema.properties.timeline.items[1].properties.elements.items[0].properties
			.text.const,
		"Use labels",
	);
	assert.equal(
		schema.properties.timeline.items[2].properties.elements.items[0].properties
			.text.const,
		"Test with a keyboard",
	);
	assert.equal(
		schema.properties.timeline.items[0].properties.type.const,
		"composition",
	);
	assert.equal(
		schema.properties.timeline.items[0].properties.motion_version.const,
		1,
	);
});
test("still generation has no animation contract and portrait sizing is smaller", () => {
	const still = presentationSchema(
		{ ...brief, motion: false, resolution: { width: 1080, height: 1920 } },
		slidePlan(brief),
	);
	const first = still.properties.timeline.items[0];
	assert.equal(first.properties.motion_version, undefined);
	assert.equal(
		first.properties.elements.items[0].properties.animation,
		undefined,
	);
	assert.equal(
		first.properties.elements.items[0].properties.font_size.const,
		0.05,
	);
});
test("long source is grouped without losing sentences", () => {
	const description = Array.from({ length: 10 }, (_, i) => `Fact ${i}.`).join(
			" ",
		),
		plan = slidePlan({ ...brief, points: [], description });
	assert.equal(plan.length, 8);
	assert.equal(
		plan
			.slice(1, -1)
			.flatMap((s) => s.topics)
			.join(" "),
		description,
	);
});
test("malformed and legacy outputs do not apply", () => {
	for (const value of [
		"null",
		"{}",
		'{"timeline":[{"type":"title"}]}',
		"JSON: {}",
	])
		assert.throws(() => parseStoryboard(value));
	assert.throws(() => slidePlan({ ...brief, structure: "unknown" }));
});

test('final generated scene does not require a forbidden transition',()=>{const schema=presentationSchema(brief,slidePlan(brief)),last=schema.properties.timeline.items.at(-1);assert.equal(last.properties.transition,undefined);assert(!last.required.includes('transition'));assert(schema.properties.timeline.items[0].required.includes('transition'));});

import {parseChartData,visualOptions,applyVisualDesign,validateChartData} from '../studio/ai-visuals.mjs';
test('explicit numeric data is preserved; unknown and invalid chart input rejected',()=>{
 const data=parseChartData('Week 1: 12\nWeek 2: 18');assert.deepEqual(data,{labels:['Week 1','Week 2'],values:[12,18]});
 assert.throws(()=>parseChartData('A: invalid\nB: 2'));
 assert(!visualOptions(brief,{kind:'body'}).includes('pie'));
 assert(!visualOptions({...brief,chartData:{labels:['A','B'],values:[-1,2]}},{kind:'body'}).includes('pie'));
 const scene={name:'Data',duration:7,elements:[{type:'text'},{type:'text'}]};applyVisualDesign(scene,'line',{...brief,chartData:data},1);assert.deepEqual(scene.elements[0].values,[12,18]);assert.equal(scene.elements[0].chart_type,'line');
});

test('description chart intent requires chart on first eligible scene; worker contract rejects partial data',()=>{
 const data={labels:['A','B'],values:[1,2]};const options=visualOptions({...brief,description:'Show a line chart of weekly totals.',chartData:data},{kind:'body',topics:['Weekly totals']});assert(options.includes('line'));assert(!options.includes('text'));assert.throws(()=>validateChartData({labels:['A'],values:[1]}));assert.throws(()=>validateChartData({labels:['A','B'],values:[1,NaN]}));validateChartData(data);
});

import {applyMotionPreset,applyArtDirection} from '../studio/design-presets.mjs';
test('coordinated motion preserves geometry and finite tracks',()=>{const scene={duration:4,elements:[{id:'a',x:.1,y:.2},{id:'b',x:.3,y:.4}]};applyMotionPreset(scene,'rise');assert.equal(scene.elements[0].x,.1);assert.equal(scene.elements[1].animation.start,.12);assert.equal(scene.elements[1].animation.direction,'down');applyMotionPreset(scene,'none');assert.equal(scene.elements[0].animation,undefined);});
test('art direction adds editable icons and layout hierarchy',()=>{const scene={background:{color:'#191925',accent:'#bba5ff'},elements:[{type:'text',color:'#ffffff'},{type:'text',color:'#bba5ff'}]};applyArtDirection(scene,'split','teal','target',2);assert.equal(scene.elements[0].type,'icon');assert.equal(scene.elements[0].icon,'target');assert.equal(scene.elements[1].w,.4);assert.equal(scene.background.accent,'#72ddd0');assert.throws(()=>applyArtDirection(scene,'unsafe','teal','target',2));});

test('story preset gives text words and chart wipe without overlapping exit',()=>{const scene={duration:1,elements:[{type:'text'},{type:'chart'},{type:'shape'}]};applyMotionPreset(scene,'story');assert.equal(scene.elements[0].animation.effect,'characters');assert.equal(scene.elements[1].animation.effect,'chart-draw');for(const item of scene.elements)assert(item.animation.start+item.animation.duration<=item.exit_animation.start+1e-9);});

test('after one chart later text design uses the exact offered options',()=>{const data={labels:['A','B'],values:[1,2]},b={...brief,description:'Compare data with a graph.',chartData:data},scene={name:'Later',duration:7,elements:[{type:'text'},{type:'text'}]},allowed=visualOptions({...b,chartData:null},{kind:'body'});assert(allowed.includes('card'));applyVisualDesign(scene,'card',b,2,allowed);assert.equal(scene.elements[0].shape,'rounded');});

test('composition keeps source and verified values through portrait photo and chart directions',()=>{const scene={background:{},elements:[{id:'t',type:'text',text:'Known fact',color:'#fff'},{id:'b',type:'text',text:'Explanation',color:'#fff'}]},asset={src:'data:image/png;base64,eA==',alt:'Supplied art'};composeScene(scene,{style:'editorial',layout:'split',resolution:{width:1080,height:1920},asset});assert.equal(scene.elements.find(i=>i.type==='image').src,asset.src);assert.equal(scene.elements.find(i=>i.id==='t').font_family,'serif');for(const i of scene.elements){assert(i.x+i.w<=1);assert(i.y+i.h<=1);}assert.equal(scene.elements.find(i=>i.id==='t').text,'Known fact');});
test('editorial prompt treats source as data and transmits exact offered designs',()=>{const m=editorialMessages({...brief,designStyle:'technical'},{kind:'body',topics:['Data']},['Do not invent facts'],['bar','line'],1,'hero');assert(m[0].content.includes('untrusted data'));assert.deepEqual(JSON.parse(m[1].content).allowedVisuals,['bar','line']);});

test('motion characters coordinate finite distinct timing and intensity',()=>{const make=()=>({duration:1,elements:[{id:'a',type:'text'},{id:'b',type:'chart'},{id:'c',type:'shape'}]});const calm=make(),fast=make();applyMotionPreset(calm,'calm');applyMotionPreset(fast,'energetic');assert(calm.elements[0].animation.intensity<fast.elements[0].animation.intensity);assert(calm.elements[0].animation.duration>=fast.elements[0].animation.duration);for(const scene of [calm,fast])for(const item of scene.elements)assert(item.animation.start+item.animation.duration<=item.exit_animation.start+1e-9);assert.equal(fast.elements[1].animation.effect,'chart-draw');});

test('director creates a held reading sequence and rejects absent visual targets',()=>{const scene={duration:6,elements:[{id:'heading',type:'text',y:.1,h:.3},{id:'body',type:'text',y:.6,h:.2}]};applyMotionPreset(scene,'balanced');directSequence(scene,{shot:'spotlight'});const body=scene.elements[1];assert.equal(body.keyframes[0].opacity,0);assert.equal(body.keyframes.at(-1).opacity,1);assert(body.animation.start>2);assert(scene.elements[0].keyframes.some(k=>k.y<0));assert.throws(()=>directSequence(scene,{shot:'visual-first'}),/needs an image/);});
