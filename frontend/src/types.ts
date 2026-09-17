export type ExistingState={exists:boolean;valid:boolean;error?:string};
export type Media={id:string;path:string;name:string;parent:string;root:string;duration:number|null;audio?:boolean;error?:string;existing:Record<'srt'|'txt',ExistingState>};
export type Job={id:string;media:Media;media_id:string;batch_id:string;status:string;stage?:string;processed:number;error?:string;available:string[];device?:string;language?:string;fallback?:string;started_at?:number;finished_at?:number};
export type ExportItem={job_id:string;artifact_id?:string;name:string;target:string;entry:string;status:string;reason?:string};
export type Export={id:string;batch_id:string;mode:'zip'|'distribute';artifact_kind:'srt'|'txt';status:string;processed:number;total:number;items:ExportItem[];error?:string;download_path?:string};
export type Batch={id:string;status:string;created_at:number;jobs:Job[];exports:Export[];settings:{model:'small'|'medium';language:string;formats:('srt'|'txt')[]}};
export type HistoryBatch={id:string;status:string;created_at:number;total:number;success:number;failed:number;settings?:Batch['settings']};
export type Scan={id:string;status:string;found:number;errors:{path:string;error:string}[];current_directory:string;media_ids:string[]};
export type System={online:boolean;models:Record<string,{available:boolean;path?:string;error?:string}>;device:string;fallback?:string;worker_alive:boolean;current_job?:Job;environment?:Record<string,unknown>};
export type Artifact={id:string;job_id:string;kind:'srt'|'txt';text:string;origin:string;segments:{start:number;end:number;text:string}[]};
export type BrowseItem={name:string;path:string;kind:'directory'|'video'};
export type BrowseResponse={path:string;parent:string|null;items:BrowseItem[];total:number};
export type Source={id:string;path:string;canonical:string;kind:'directory'|'video';order:number};
export const statusText:Record<string,string>={queued:'排队中',preparing:'加载模型',transcribing:'正在转写',finalizing:'整理结果',completed:'已完成',reused:'已复用',no_speech:'未检测到语音',failed:'失败',interrupted:'已中断',cancelled:'已取消',running:'进行中',pausing:'本视频完成后暂停',paused:'已暂停',partial_failed:'部分失败',preflight:'待确认',ready:'可导出',exists:'已存在 · 跳过',conflict:'命名冲突',error:'来源异常',skipped:'已跳过'};
export function duration(n?:number|null){if(n==null)return '未知时长';const s=Math.max(0,Math.floor(n));const h=Math.floor(s/3600);return `${h?`${h}:`:''}${String(Math.floor(s/60)%60).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`}
export function formatDate(seconds?:number){if(!seconds)return '—';return new Date(seconds*1000).toLocaleString()}
export async function api<T=any>(url:string,body?:unknown,method?:string):Promise<T>{const r=await fetch('/api'+url,{method:method||(body?'POST':'GET'),headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined,credentials:'same-origin'});if(!r.ok){const d=await r.json().catch(()=>({detail:r.statusText}));throw Error(typeof d.detail==='string'?d.detail:JSON.stringify(d.detail))}if(r.status===204)return undefined as T;return r.json()}
