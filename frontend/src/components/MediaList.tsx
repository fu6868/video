import {useMemo,useRef} from 'react';
import {useVirtualizer} from '@tanstack/react-virtual';
import {AlertTriangle,CheckCircle2,FileText,Subtitles} from 'lucide-react';
import {duration,type Media} from '../types';

type Props={items:Media[];selected:Set<string>;onToggle:(id:string)=>void;onToggleAll:(ids:string[],checked:boolean)=>void};
export default function MediaList({items,selected,onToggle,onToggleAll}:Props){
 const parent=useRef<HTMLDivElement>(null);const virtualizer=useVirtualizer({count:items.length,getScrollElement:()=>parent.current,estimateSize:()=>68,overscan:8});
 const all=useMemo(()=>items.length>0&&items.every(x=>selected.has(x.id)),[items,selected]);
 return <div className="media-table"><div className="media-head"><label><input type="checkbox" checked={all} onChange={e=>onToggleAll(items.map(x=>x.id),e.target.checked)}/></label><span>文件</span><span>时长</span><span>已有结果</span><span>状态</span></div><div className="media-scroll" ref={parent}><div style={{height:virtualizer.getTotalSize(),position:'relative'}}>{virtualizer.getVirtualItems().map(v=>{const m=items[v.index];return <div className="media-row" key={m.id} style={{position:'absolute',top:0,left:0,width:'100%',height:v.size,transform:`translateY(${v.start}px)`}}><label><input type="checkbox" checked={selected.has(m.id)} disabled={!!m.error} onChange={()=>onToggle(m.id)}/></label><div className="file-cell"><strong title={m.name}>{m.name}</strong><small title={m.parent}>{m.parent}</small></div><span className="mono">{duration(m.duration)}</span><span className="existing">{m.existing?.srt?.valid&&<span title="已有有效 SRT"><Subtitles size={15}/>SRT</span>}{m.existing?.txt?.valid&&<span title="已有有效 TXT"><FileText size={15}/>TXT</span>}{!m.existing?.srt?.valid&&!m.existing?.txt?.valid&&<em>—</em>}</span><span className={m.error?'state bad':'state good'} title={m.error||'可处理'}>{m.error?<><AlertTriangle size={15}/>{m.error}</>:<><CheckCircle2 size={15}/>可处理</>}</span></div>})}</div></div></div>
}
