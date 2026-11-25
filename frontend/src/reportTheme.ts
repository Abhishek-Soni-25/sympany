// Sympany report format, shared by every downloaded report: a letterhead with the Sympany logo
// and claim on white, a berry band under it (the berry frame of the Sympany corporate design),
// bold black headings with a short berry rule, and a confidential footer. Self-contained so a
// saved file prints offline.
import { BRAND_LOGO } from "./brandLogo";
import { BRAND_NAME } from "./brand";

export const SY_BERRY = "#891350";
export const SY_BERRY_DEEP = "#6B1040";
export const SY_LAVENDER = "#6E5FA6";
export const SY_SAND = "#EAD6C1";
export const SY_RED = "#C8372D";
export const SY_GREEN = "#2E7D4F";
export const SY_AMBER = "#A35200";

const esc = (s: unknown) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));

export const REPORT_CSS = `
 @page{size:A4;margin:14mm 12mm 16mm;}
 *{box-sizing:border-box;}
 body{font-family:National2,"Schibsted Grotesk","Segoe UI",Arial,sans-serif;color:#000;max-width:1000px;margin:0 auto;padding:0 28px 40px;
   font-size:13.5px;line-height:1.5;-webkit-print-color-adjust:exact;print-color-adjust:exact;}
 .lh{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:22px 0 16px;}
 .lh img{height:58px;display:block;}
 .lh-meta{text-align:right;font-size:12px;color:#5E5559;line-height:1.45;}
 .lh-meta b{display:block;color:#000;font-size:13px;font-weight:700;}
 .twin{height:8px;background:${SY_BERRY};}
 .title{padding:26px 0 6px;}
 .title h1{margin:0;font-size:28px;line-height:1.15;font-weight:700;color:#000;}
 .title .gen{margin-top:6px;color:#5E5559;font-size:12.5px;}
 .scope{margin:14px 0 8px;background:#FBF7F3;border-left:3px solid ${SY_BERRY};padding:10px 14px;font-size:12.5px;color:#2E2729;line-height:1.55;}
 h2{color:#000;font-size:19px;font-weight:700;margin:34px 0 10px;padding-bottom:8px;break-after:avoid;
   background:linear-gradient(${SY_BERRY},${SY_BERRY}) left bottom/44px 3px no-repeat,linear-gradient(#E8DFD6,#E8DFD6) left bottom/100% 1px no-repeat;}
 h3{font-size:14px;font-weight:700;color:#000;margin:22px 0 8px;break-after:avoid;}
 p{max-width:78ch;}
 .cards,.kpis{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0;}
 .card,.kpi{border:1px solid #E8DFD6;border-left:3px solid ${SY_LAVENDER};border-radius:6px;padding:12px 16px;min-width:140px;flex:1;break-inside:avoid;}
 .card .l,.kpi .l{font-size:12px;color:#5E5559;}
 .card .v,.kpi .v{font-size:24px;font-weight:700;margin:3px 0;color:#000;}
 .kpi.red{border-left-color:${SY_RED};} .kpi.amber{border-left-color:${SY_AMBER};}
 table{width:100%;border-collapse:collapse;margin-top:8px;font-size:12.5px;}
 th{background:#F7EFE6;color:#000;text-align:left;padding:8px 9px;font-size:12px;font-weight:700;border-bottom:2px solid ${SY_BERRY};}
 td{padding:8px 9px;border-bottom:1px solid #EEE6DD;vertical-align:top;}
 tr{break-inside:avoid;}
 tbody tr:nth-child(even) td{background:#FDFBF9;}
 .bar{height:9px;background:#F2ECE6;border-radius:2px;overflow:hidden;}
 .bar span{display:block;height:100%;background:${SY_LAVENDER};}
 .wc{line-height:1.9;} .wc span{margin-right:10px;color:${SY_LAVENDER};}
 a{color:${SY_BERRY};}
 .p-high td:first-child{color:${SY_RED};font-weight:700;} .p-medium td:first-child{color:${SY_AMBER};font-weight:700;}
 .s-negative{color:${SY_RED};font-weight:700;} .s-positive{color:${SY_GREEN};font-weight:700;}
 .foot{margin-top:44px;padding-top:10px;border-top:1px solid #E8DFD6;display:flex;justify-content:space-between;gap:16px;font-size:11px;color:#7A7075;}
 .foot b{color:${SY_BERRY};font-weight:700;}
 .btn{background:${SY_BERRY};color:#fff;border:0;padding:11px 20px;border-radius:999px;font:700 13px/1 inherit;cursor:pointer;margin:16px 0 0;}
 .btn:hover{background:${SY_BERRY_DEEP};}
 @media (max-width:640px){body{padding:0 16px 32px;} .lh{flex-wrap:wrap;} .lh img{height:44px;} .lh-meta{text-align:left;} .title h1{font-size:22px;} table{display:block;overflow-x:auto;}}
 @media print{.noprint{display:none;} body{padding:0;}}
`;

/** Letterhead, twin rule and title block. `scope` is what the report covers (the filters). */
export const letterhead = (title: string, scope: string, generated = new Date()) => `
<button class="btn noprint" onclick="window.print()">Save as PDF or print</button>
<div class="lh"><img src="${BRAND_LOGO}" alt="${esc(BRAND_NAME)}"/>
  <div class="lh-meta"><b>Social media listening</b>Confidential. For internal use at Sympany.</div></div>
<div class="twin"></div>
<div class="title"><h1>${esc(title)}</h1>
  <div class="gen">Generated ${esc(generated.toLocaleString("en-CH", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }))}</div></div>
<div class="scope">${esc(scope)}</div>`;

export const reportFooter = (detail: string) => `
<div class="foot"><span><b>${esc(BRAND_NAME)}</b> · Social media listening and reputation risk</span><span>${esc(detail)}</span></div>`;
