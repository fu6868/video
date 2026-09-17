import {useEffect,useMemo,useRef,useState} from 'react';
import {useVirtualizer} from '@tanstack/react-virtual';
import {ArrowLeft,Check,Folder,HardDrive,Search,X,FileVideo2} from 'lucide-react';
import {api,type BrowseItem,type BrowseResponse} from '../types';

type Props={open:boolean;onClose:()=>void;onConfirm:(paths:string[])=>Promise<void>};
export default function FilePicker({open,onClose,onConfirm}:Props){
  const [roots,setRoots]=useState<string[]>([]);const [current,setCurrent]=useState('');const [parent,setParent]=useState<string|null>(null);
  const [items,setItems]=useState<BrowseItem[]>([]);const [selected,setSelected]=useState<string[]>([]);const [typed,setTyped]=useState('');const [filter,setFilter]=useState('');const [busy,setBusy]=useState(false);const [error,setError]=useState('');
  const listRef=useRef<HTMLDivElement>(null);
  async function load(path:string){
    setBusy(true);setError('');
    try{
      const first=await api<BrowseResponse>('/fs/list',{path,offset:0,limit:500});
      const all=[...first.items];
      for(let offset=500;offset<first.total;offset+=500){const page=await api<BrowseResponse>('/fs/list',{path:first.path,offset,limit:500});all.push(...page.items)}
      setCurrent(first.path);setParent(first.parent);setItems(all);listRef.current?.scrollTo({top:0});
    }catch(e){setError(e instanceof Error?e.message:String(e))}finally{setBusy(false)}
  }
  useEffect(()=>{if(!open)return;void api<{roots:string[]}>('/fs/roots').then(r=>setRoots(r.roots)).catch(e=>setError(String(e)));const onKey=(e:KeyboardEvent)=>{if(e.key==='Escape')onClose()};window.addEventListener('keydown',onKey);return()=>window.removeEventListener('keydown',onKey)},[open,onClose]);
  const shown=useMemo(()=>items.filter(x=>!filter||x.name.toLocaleLowerCase().includes(filter.toLocaleLowerCase())),[items,filter]);
  const virtualizer=useVirtualizer({count:shown.length,getScrollElement:()=>listRef.current,estimateSize:()=>48,overscan:10});
  function toggle(path:string){setSelected(v=>v.includes(path)?v.filter(x=>x!==path):[...v,path])}
  async function addTyped(){const p=typed.trim();if(!p)return;setError('');if(!selected.includes(p))setSelected(v=>[...v,p]);setTyped('');try{await load(p)}catch{/* registration performs the authoritative validation */}}
  if(!open)return null;
  return <div className="modal-backdrop" role="presentation" onMouseDown={e=>{if(e.target===e.currentTarget)onClose()}}><div className="modal file-picker" role="dialog" aria-modal="true" aria-label="选择本地视频或文件夹">
    <div className="modal-head"><div><h2>添加本地来源</h2><p>只登记路径，不移动或复制视频。按 Esc 可关闭。</p></div><button className="icon-btn" onClick={onClose} aria-label="关闭"><X/></button></div>
    <div className="drive-row">{roots.map(r=><button key={r} className={current.toLocaleLowerCase().startsWith(r.toLocaleLowerCase())?'chip active':'chip'} onClick={()=>void load(r)}><HardDrive size={16}/>{r}</button>)}</div>
    <div className="path-row"><button className="icon-btn" disabled={!parent||busy} onClick={()=>parent&&void load(parent)} aria-label="返回上级"><ArrowLeft/></button><div className="path-box" title={current}>{current||'请选择磁盘'}</div><label className="search-box"><Search size={16}/><input value={filter} onChange={e=>setFilter(e.target.value)} placeholder="筛选当前目录"/></label></div>
    <div className="browser-list" aria-busy={busy} ref={listRef}><div style={{height:virtualizer.getTotalSize(),position:'relative'}}>{virtualizer.getVirtualItems().map(v=>{const item=shown[v.index];return <div className="browser-item" key={item.path} style={{position:'absolute',top:0,left:0,width:'100%',height:v.size,transform:`translateY(${v.start}px)`}}><button className="browser-open" onClick={()=>item.kind==='directory'?void load(item.path):toggle(item.path)} title={item.path}>{item.kind==='directory'?<Folder/>:<FileVideo2/>}<span>{item.name}</span></button><label className="pick-check"><input type="checkbox" checked={selected.includes(item.path)} onChange={()=>toggle(item.path)}/><span>选择</span></label></div>})}</div>{!busy&&current&&shown.length===0&&<div className="empty overlay">当前目录没有可浏览的视频或子目录</div>}</div>
    <div className="picker-tools"><button className="secondary" disabled={!current} onClick={()=>current&&toggle(current)}>{selected.includes(current)?<><Check size={16}/>已选择当前文件夹</>:<><Folder size={16}/>选择当前文件夹</>}</button><div className="paste-path"><input value={typed} onChange={e=>setTyped(e.target.value)} placeholder="粘贴绝对路径，例如 S:\\b站下载" onKeyDown={e=>{if(e.key==='Enter')void addTyped()}}/><button className="secondary" onClick={()=>void addTyped()}>添加路径</button></div></div>
    {error&&<div className="error" role="alert">{error}</div>}
    <div className="selection"><strong>已选择 {selected.length} 项</strong><div>{selected.map(p=><span className="selected-path" key={p} title={p}>{p}<button onClick={()=>toggle(p)} aria-label={'移除 '+p}><X size={13}/></button></span>)}</div></div>
    <div className="modal-actions"><button className="secondary" onClick={onClose}>取消</button><button className="primary" disabled={!selected.length||busy} onClick={()=>{setBusy(true);void onConfirm(selected).then(()=>{setSelected([]);onClose()}).catch(e=>setError(e instanceof Error?e.message:String(e))).finally(()=>setBusy(false))}}>登记并扫描</button></div>
  </div></div>
}
